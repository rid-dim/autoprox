from typing import Annotated, Dict, Optional, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Header, Query, Depends
from pydantic import BaseModel, Field
import json
import asyncio
import uuid
import logging
from ..utils.srmudp_manager import SRMUDPManager, ConnectionStatus
import os
import base64

# Logging konfigurieren
logger = logging.getLogger(__name__)

# Create a router for websocket endpoints
router = APIRouter(prefix="/v0", tags=["srmudp_websocket"])

# Dictionary to store active SRMUDP connections by connection ID
active_connections: Dict[str, SRMUDPManager] = {}

class WebSocketInfo(BaseModel):
    """Model for WebSocket information response"""
    websocket_url: str = Field(..., description="URL of the WebSocket endpoint")
    parameters: Dict[str, str] = Field(..., description="Required parameters for the WebSocket connection")
    udp_connection_info: str = Field(..., description="UDP connection information")
    documentation: str = Field(..., description="Reference to detailed documentation")

@router.get("/ws/srmudp/info", response_model=WebSocketInfo)
async def get_websocket_info():
    """
    Returns information about the WebSocket-SRMUDP proxy endpoint.
    This is a helper endpoint since WebSockets cannot be documented in Swagger.
    """
    # Get the UDP port from the environment variable
    udp_port = int(os.environ.get('AUTOPROX_UDP_PORT', 0))
    
    # Get the public IP
    public_ip = await SRMUDPManager.get_public_ip()
    
    # Create the UDP connection URL
    udp_connection_url = f"udp://{public_ip}:{udp_port}"
    
    # Protocol documentation
    protocol_docs = """
WebSocket Nachrichten vom Server:
- {"type": "status", "status": "STATUS_TEXT", "connection_id": "ID", "message": "TEXT"} - Statusänderungen
- {"type": "data", "data": "DATA"} - Daten vom UDP-Peer
- {"type": "error", "connection_id": "ID", "message": "TEXT"} - Fehlermeldungen

WebSocket Nachrichten vom Client:
- {"type": "data", "data": "DATA"} - Daten zum UDP-Peer senden
- {"type": "command", ...} - Künftige Befehlserweiterungen
    """
    
    return {
        "websocket_url": "/v0/ws/srmudp/proxy",
        "parameters": {
            "remote_host": "Target IP address (required)",
            "remote_port": "Target port (required)",
            "encryption_key": "Encryption key (required)",
            "client_id": "Optional client ID for multiple connections"
        },
        "udp_connection_info": udp_connection_url,
        "documentation": protocol_docs
    }

@router.get("/ws/srmudp/connections", response_model=List[dict])
async def get_connections():
    """
    Zeigt aktive WebSocket-SRMUDP-Verbindungen.
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

@router.websocket("/ws/srmudp/proxy")
async def websocket_proxy(
    websocket: WebSocket,
    remote_host: str = Query(..., description="Remote host IP address"),
    remote_port: int = Query(..., description="Remote host port"),
    encryption_key: str = Query(..., description="Encryption key for SRMUDP communication"),
    client_id: Optional[str] = Query(None, description="Optional client ID for multiple connections")
):
    """
    WebSocket endpoint that acts as a proxy to a SRMUDP connection.
    
    The client connects to this WebSocket and specifies a remote host to connect to via SRMUDP.
    The server will establish a SRMUDP connection to the remote host and proxy data between the WebSocket and SRMUDP.
    
    The SRMUDP connection uses hole-punching to establish a connection through NATs.
    All data is encrypted using the SRMUDP library's built-in encryption.
    
    Multiple clients can connect to the same remote host with different encryption keys.
    """
    await websocket.accept()
    
    # Generiere eine eindeutige Verbindungs-ID
    # Wenn client_id angegeben wurde, füge sie zur Verbindungs-ID hinzu
    connection_id = f"{client_id or uuid.uuid4().hex}_{remote_host}_{remote_port}"
    
    # Create SRMUDP manager for this connection
    srmudp_manager = SRMUDPManager(
        remote_host=remote_host,
        remote_port=remote_port,
        encryption_key=encryption_key
    )
    
    # Store the connection
    active_connections[connection_id] = srmudp_manager
    
    try:
        # Send initial status - WebSocket connected
        await websocket.send_json({
            "type": "status",
            "status": "CONNECTED",
            "connection_id": connection_id,
            "message": "WebSocket connection established"
        })
        
        # Start SRMUDP connection
        await srmudp_manager.start()
        
        # Start background tasks
        udp_to_ws_task = asyncio.create_task(forward_udp_to_websocket(websocket, srmudp_manager))
        ws_to_udp_task = asyncio.create_task(forward_websocket_to_udp(websocket, srmudp_manager))
        status_update_task = asyncio.create_task(send_status_updates(websocket, srmudp_manager, connection_id))
        
        # Wait for any task to complete (usually when the WebSocket disconnects)
        await asyncio.wait(
            [udp_to_ws_task, ws_to_udp_task, status_update_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
    except WebSocketDisconnect:
        # WebSocket disconnected
        logger.info(f"WebSocket disconnected for connection {connection_id}")
    except Exception as e:
        # Try to send error message
        try:
            logger.error(f"Error in websocket connection: {str(e)}")
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
        await srmudp_manager.stop()
        logger.info(f"Connection {connection_id} closed")

async def forward_udp_to_websocket(websocket: WebSocket, srmudp_manager: SRMUDPManager):
    """Forward data received from SRMUDP to the WebSocket"""
    while True:
        try:
            data = await srmudp_manager.receive()
            if data:
                try:
                    # Versuche die Daten als UTF-8 zu dekodieren (für Text-Nachrichten)
                    text_data = data.decode('utf-8', errors='strict')
                    
                    # Sende als JSON, wenn es sich um Text handelt
                    await websocket.send_json({
                        "type": "data",
                        "format": "text",
                        "data": text_data
                    })
                    logger.debug(f"Sent text data to WebSocket: {len(text_data)} chars")
                except UnicodeDecodeError:
                    # Wenn es keine gültige UTF-8-Daten sind, sende als Base64-kodierte binäre Daten
                    binary_data = base64.b64encode(data).decode('ascii')
                    
                    await websocket.send_json({
                        "type": "data",
                        "format": "binary",
                        "data": binary_data
                    })
                    logger.debug(f"Sent binary data to WebSocket: {len(data)} bytes")
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
            break
        except asyncio.CancelledError:
            logger.info("UDP to WebSocket task cancelled")
            break
        except Exception as e:
            logger.error(f"Error forwarding UDP to WebSocket: {e}")
            await asyncio.sleep(0.1)  # Avoid tight loop on errors

async def forward_websocket_to_udp(websocket: WebSocket, srmudp_manager: SRMUDPManager):
    """Forward data received from WebSocket to SRMUDP"""
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
                    await srmudp_manager.send(binary_data)
                    logger.debug(f"Sent binary data to SRMUDP: {len(binary_data)} bytes")
                else:
                    # Text-Daten
                    text_data = data_content.encode('utf-8')
                    await srmudp_manager.send(text_data)
                    logger.debug(f"Sent text data to SRMUDP: {len(text_data)} bytes")
                    
            elif message.get("type") == "command":
                # Handle commands (future extension)
                logger.debug(f"Received command: {message}")
                pass
                
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected, stopping forward_websocket_to_udp loop.")
            break
        except asyncio.CancelledError:
            logger.info("WebSocket to UDP task cancelled")
            break
        except json.JSONDecodeError:
            # Falls keine gültige JSON-Nachricht, versuche als Roh-Text zu behandeln
            try:
                raw_message = await websocket.receive_text()
                await srmudp_manager.send(raw_message.encode('utf-8'))
                logger.debug(f"Sent raw text data to SRMUDP: {len(raw_message)} chars")
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected during raw message handling, stopping loop.")
                break
            except Exception as e:
                logger.error(f"Fehler beim Verarbeiten der WebSocket-Nachricht: {e}")
        except Exception as e:
            logger.error(f"Fehler in der WebSocket-zu-SRMUDP-Weiterleitung: {e}")
            await asyncio.sleep(0.1)  # Vermeide enge Schleife bei Fehlern

async def send_status_updates(websocket: WebSocket, srmudp_manager: SRMUDPManager, connection_id: str):
    """Send periodic status updates to the WebSocket client"""
    last_status = None
    
    while True:
        try:
            current_status = srmudp_manager.get_status()
            
            # Only send updates when status changes
            if current_status != last_status:
                status_message = {
                    "type": "status",
                    "status": current_status.value,
                    "connection_id": connection_id,
                    "message": get_status_message(current_status)
                }
                await websocket.send_json(status_message)
                logger.info(f"Status change for {connection_id}: {current_status.value}")
                last_status = current_status
            
            await asyncio.sleep(1)  # Check status every second
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected, stopping status updates.")
            break
        except asyncio.CancelledError:
            logger.info("Status update task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in status updates: {e}")
            await asyncio.sleep(1)

def get_status_message(status: ConnectionStatus) -> str:
    """Get a human-readable message for a connection status"""
    if status == ConnectionStatus.CONNECTED:
        return "WebSocket connection established, waiting for UDP"
    elif status == ConnectionStatus.UDP_WAITING:
        return "Attempting to establish UDP connection"
    elif status == ConnectionStatus.UDP_ESTABLISHED:
        return "UDP connection established with remote peer"
    elif status == ConnectionStatus.RECONNECTING:
        return "Connection lost, attempting to reconnect"
    elif status == ConnectionStatus.ERROR:
        return "Error in UDP connection"
    else:
        return "Unknown status" 