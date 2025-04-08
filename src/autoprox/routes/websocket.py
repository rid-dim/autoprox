from typing import Annotated, Dict, Optional, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Header, Query, Depends
from pydantic import BaseModel, Field
import json
import asyncio
import uuid
import logging
from ..utils.udp_manager import UDPManager, ConnectionStatus, HEARTBEAT_PREFIX
import os
from ..utils.network import get_public_ip
import base64

# Logging konfigurieren
logger = logging.getLogger(__name__)

# Create a router for websocket endpoints
router = APIRouter(prefix="/v0", tags=["websocket"])

# Dictionary to store active UDP connections by connection ID
active_connections: Dict[str, UDPManager] = {}

class WebSocketInfo(BaseModel):
    """Model for WebSocket information response"""
    websocket_url: str = Field(..., description="URL of the WebSocket endpoint")
    parameters: Dict[str, str] = Field(..., description="Required parameters for the WebSocket connection")
    udp_connection_info: str = Field(..., description="UDP connection information")
    documentation: str = Field(..., description="Reference to detailed documentation")

@router.get("/ws/info", response_model=WebSocketInfo)
async def get_websocket_info():
    """
    Returns information about the WebSocket-UDP proxy endpoint.
    This is a helper endpoint since WebSockets cannot be documented in Swagger.
    """
    # Hole den UDP-Port aus der Umgebungsvariable
    udp_port = int(os.environ.get('AUTOPROX_UDP_PORT', 17171))
    
    # Ermittle die öffentliche IP
    public_ip = await get_public_ip()
    
    # Erstelle die UDP-Verbindungs-URL
    udp_connection_url = f"udp://{public_ip}:{udp_port}"
    
    # Protokolldokumentation
    protocol_docs = """
WebSocket Nachrichten vom Server:
- {"type": "status", "status": "STATUS_TEXT", "connection_id": "ID", "message": "TEXT"} - Statusänderungen
- {"type": "data", "data": "DATA"} - Daten vom UDP-Peer (Heartbeats werden gefiltert)
- {"type": "error", "connection_id": "ID", "message": "TEXT"} - Fehlermeldungen

WebSocket Nachrichten vom Client:
- {"type": "data", "data": "DATA"} - Daten zum UDP-Peer senden
- {"type": "command", ...} - Künftige Befehlserweiterungen
    """
    
    return {
        "websocket_url": "/v0/ws/proxy",
        "parameters": {
            "remote_host": "Target IP address (required)",
            "remote_port": "Target port (required)",
            "encryption_key": "Encryption key (required)",
            "client_id": "Optional client ID for multiple connections"
        },
        "udp_connection_info": udp_connection_url,
        "documentation": protocol_docs
    }

@router.get("/ws/connections", response_model=List[dict])
async def get_connections():
    """
    Zeigt aktive WebSocket-UDP-Verbindungen.
    Nur zu Debug- und Testzwecken.
    """
    connections = []
    for connection_id, manager in active_connections.items():
        connections.append({
            "connection_id": connection_id,
            "remote_host": manager.remote_host,
            "remote_port": manager.remote_port,
            "status": manager.get_status().value
        })
    return connections

@router.websocket("/ws/proxy")
async def websocket_proxy(
    websocket: WebSocket,
    remote_host: str = Query(..., description="Remote host IP address"),
    remote_port: int = Query(..., description="Remote host port"),
    encryption_key: str = Query(..., description="Encryption key for UDP communication"),
    client_id: Optional[str] = Query(None, description="Optional client ID for multiple connections")
):
    """
    WebSocket endpoint that acts as a proxy to a UDP hole-punching connection.
    
    The client connects to this WebSocket and specifies a remote host to connect to via UDP.
    The server will establish a UDP connection to the remote host and proxy data between the WebSocket and UDP.
    
    The UDP connection uses hole-punching to establish a connection through NATs.
    All UDP data is encrypted using the provided encryption key.
    
    Multiple clients can connect to the same remote host with different encryption keys.
    """
    await websocket.accept()
    
    # Generiere eine eindeutige Verbindungs-ID
    # Wenn client_id angegeben wurde, füge sie zur Verbindungs-ID hinzu
    connection_id = f"{client_id or uuid.uuid4().hex}_{remote_host}_{remote_port}"
    
    # Create UDP manager for this connection
    udp_manager = UDPManager(
        remote_host=remote_host,
        remote_port=remote_port,
        encryption_key=encryption_key
    )
    
    # Store the connection
    active_connections[connection_id] = udp_manager
    
    try:
        # Send initial status - WebSocket connected
        await websocket.send_json({
            "type": "status",
            "status": "CONNECTED",
            "connection_id": connection_id,
            "message": "WebSocket connection established"
        })
        
        # Start UDP connection
        await udp_manager.start()
        
        # Start background tasks
        udp_to_ws_task = asyncio.create_task(forward_udp_to_websocket(websocket, udp_manager))
        ws_to_udp_task = asyncio.create_task(forward_websocket_to_udp(websocket, udp_manager))
        status_update_task = asyncio.create_task(send_status_updates(websocket, udp_manager, connection_id))
        
        # Wait for any task to complete (usually when the WebSocket disconnects)
        await asyncio.wait(
            [udp_to_ws_task, ws_to_udp_task, status_update_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
    except WebSocketDisconnect:
        # WebSocket disconnected
        pass
    except Exception as e:
        # Try to send error message
        try:
            await websocket.send_json({
                "type": "error",
                "connection_id": connection_id,
                "message": f"Error in websocket connection: {str(e)}"
            })
        except:
            pass
    finally:
        # Clean up
        if connection_id in active_connections:
            del active_connections[connection_id]
        await udp_manager.stop()

async def forward_udp_to_websocket(websocket: WebSocket, udp_manager: UDPManager):
    """Forward data received from UDP to the WebSocket"""
    while True:
        data = await udp_manager.receive()
        if data:
            # Ignoriere Heartbeat-Nachrichten - nicht an WebSocket senden
            if data.startswith(HEARTBEAT_PREFIX):
                continue
            
            try:
                # Versuche die Daten als UTF-8 zu dekodieren (für Text-Nachrichten)
                text_data = data.decode('utf-8', errors='strict')
                
                # Sende als JSON, wenn es sich um Text handelt
                await websocket.send_json({
                    "type": "data",
                    "format": "text",
                    "data": text_data
                })
            except UnicodeDecodeError:
                # Wenn es keine gültige UTF-8-Daten sind, sende als Base64-kodierte binäre Daten
                binary_data = base64.b64encode(data).decode('ascii')
                
                await websocket.send_json({
                    "type": "data",
                    "format": "binary",
                    "data": binary_data
                })

async def forward_websocket_to_udp(websocket: WebSocket, udp_manager: UDPManager):
    """Forward data received from WebSocket to UDP"""
    while True:
        try:
            # Verwende receive_json für strukturierte Nachrichten
            message = await websocket.receive_json()
            
            if message.get("type") == "data":
                data_format = message.get("format", "text")
                data_content = message.get("data", "")
                
                if data_format == "binary":
                    # Dekodiere Base64-Daten
                    binary_data = base64.b64decode(data_content)
                    await udp_manager.send(binary_data)
                else:
                    # Text-Daten
                    await udp_manager.send(data_content.encode('utf-8'))
                    
            elif message.get("type") == "command":
                # Handle commands (future extension)
                pass
                
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected, stopping forward_websocket_to_udp loop.")
            break
        except json.JSONDecodeError:
            # Falls keine gültige JSON-Nachricht, versuche als Roh-Text zu behandeln
            try:
                raw_message = await websocket.receive_text()
                await udp_manager.send(raw_message.encode('utf-8'))
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected during raw message handling, stopping loop.")
                break
            except Exception as e:
                logger.error(f"Fehler beim Verarbeiten der WebSocket-Nachricht: {e}")
        except Exception as e:
            logger.error(f"Fehler in der WebSocket-zu-UDP-Weiterleitung: {e}")
            await asyncio.sleep(0.1)  # Vermeide enge Schleife bei Fehlern

async def send_status_updates(websocket: WebSocket, udp_manager: UDPManager, connection_id: str):
    """Send periodic status updates to the WebSocket client"""
    last_status = None
    
    while True:
        current_status = udp_manager.get_status()
        
        # Only send updates when status changes
        if current_status != last_status:
            status_message = {
                "type": "status",
                "status": current_status.value,
                "connection_id": connection_id,
                "message": get_status_message(current_status)
            }
            await websocket.send_json(status_message)
            last_status = current_status
        
        await asyncio.sleep(1)  # Check status every second

def get_status_message(status: ConnectionStatus) -> str:
    """Get a human-readable message for a connection status"""
    if status == ConnectionStatus.CONNECTED:
        return "WebSocket connection established"
    elif status == ConnectionStatus.UDP_WAITING:
        return "Waiting for UDP connection to remote peer"
    elif status == ConnectionStatus.UDP_ESTABLISHED:
        return "UDP connection established with remote peer"
    elif status == ConnectionStatus.ERROR:
        return "Error in connection"
    return "Unknown status" 