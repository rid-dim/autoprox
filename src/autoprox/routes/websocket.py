from typing import Annotated, Dict, Optional, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Header, Query, Depends
from pydantic import BaseModel, Field
import json
import asyncio
from ..utils.udp_manager import UDPManager, ConnectionStatus
import os
from ..utils.network import get_public_connection_info

# Create a router for websocket endpoints
router = APIRouter(prefix="/v0", tags=["websocket"])

# Dictionary to store active UDP connections by token
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
    
    # Ermittle die öffentliche IP per get_public_connection_info
    connection_info = await get_public_connection_info()
    
    # Erstelle die UDP-Verbindungs-URL
    udp_connection_url = f"udp://{connection_info['public_ip']}:{connection_info['port']}"
    
    return {
        "websocket_url": "/v0/ws/proxy",
        "parameters": {
            "remote_host": "Target IP address (required)",
            "remote_port": "Target port (required)",
            "encryption_key": "Encryption key (required)"
        },
        "udp_connection_info": udp_connection_url,
        "documentation": "See README-websocket-udp.md for details"
    }

@router.websocket("/ws/proxy")
async def websocket_proxy(
    websocket: WebSocket,
    remote_host: str = Query(..., description="Remote host IP address"),
    remote_port: int = Query(..., description="Remote host port"),
    encryption_key: str = Query(..., description="Encryption key for UDP communication")
):
    """
    WebSocket endpoint that acts as a proxy to a UDP hole-punching connection.
    
    The client connects to this WebSocket and specifies a remote host to connect to via UDP.
    The server will establish a UDP connection to the remote host and proxy data between the WebSocket and UDP.
    
    The UDP connection uses hole-punching to establish a connection through NATs.
    All UDP data is encrypted using the provided encryption key.
    """
    await websocket.accept()
    
    # Create UDP manager for this connection
    udp_manager = UDPManager(
        remote_host=remote_host,
        remote_port=remote_port,
        encryption_key=encryption_key
    )
    
    # Store the connection
    connection_id = f"{remote_host}_{remote_port}"
    active_connections[connection_id] = udp_manager
    
    try:
        # Send initial status - WebSocket connected
        await websocket.send_json({
            "type": "status",
            "status": "CONNECTED",
            "message": "WebSocket connection established"
        })
        
        # Start UDP connection
        await udp_manager.start()
        
        # Start background tasks
        udp_to_ws_task = asyncio.create_task(forward_udp_to_websocket(websocket, udp_manager))
        ws_to_udp_task = asyncio.create_task(forward_websocket_to_udp(websocket, udp_manager))
        status_update_task = asyncio.create_task(send_status_updates(websocket, udp_manager))
        
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
            # Send the data received from UDP to the WebSocket
            await websocket.send_json({
                "type": "data",
                "data": data.decode('utf-8', errors='replace')  # Assume UTF-8 text data
            })

async def forward_websocket_to_udp(websocket: WebSocket, udp_manager: UDPManager):
    """Forward data received from WebSocket to UDP"""
    while True:
        message = await websocket.receive_text()
        try:
            # Parse the message to handle both text and commands
            data = json.loads(message)
            
            if data.get("type") == "data":
                # Send data to UDP
                await udp_manager.send(data.get("data").encode('utf-8'))
            elif data.get("type") == "command":
                # Handle commands (future extension)
                pass
        except json.JSONDecodeError:
            # If not JSON, treat as raw data
            await udp_manager.send(message.encode('utf-8'))

async def send_status_updates(websocket: WebSocket, udp_manager: UDPManager):
    """Send periodic status updates to the WebSocket client"""
    last_status = None
    
    while True:
        current_status = udp_manager.get_status()
        
        # Only send updates when status changes
        if current_status != last_status:
            status_message = {
                "type": "status",
                "status": current_status.value,
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