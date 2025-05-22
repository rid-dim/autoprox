import asyncio
import json
import logging
import base64
import os
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field
from ..utils.srmudp_bridge import SRMUDPBridge

logger = logging.getLogger(__name__)

# Create router for websocket endpoints
router = APIRouter(prefix="/v0", tags=["websocket"])

# Store active bridges by connection ID
active_bridges: Dict[str, SRMUDPBridge] = {}

class WebSocketInfo(BaseModel):
    """Model for WebSocket information response"""
    websocket_url: str = Field(..., description="URL of the WebSocket endpoint")
    parameters: Dict[str, str] = Field(..., description="Required parameters")
    description: str = Field(..., description="Service description")

@router.get("/ws/info", response_model=WebSocketInfo)
async def get_websocket_info():
    """
    Returns information about the WebSocket-SRMUDP bridge endpoint.
    """
    default_srmudp_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
    port_description = f"Local port to bind to (optional, default: server preference {default_srmudp_port}, 0 for random)"
    
    return {
        "websocket_url": "/v0/ws/bridge",
        "parameters": {
            "remote_address": "Target address in format 'host:port' (required)",
            "local_port": port_description
        },
        "description": "WebSocket to SRMUDP bridge - forwards all non-heartbeat messages bidirectionally"
    }

@router.websocket("/ws/bridge")
async def websocket_srmudp_bridge(
    websocket: WebSocket,
    remote_address: str = Query(..., description="Remote address in format 'host:port'"),
    local_port: Optional[int] = Query(None, description="Local port to bind to (None for server default, 0 for random)")
):
    """
    WebSocket to SRMUDP bridge.
    
    Establishes a bidirectional bridge between WebSocket and SRMUDP.
    All messages received via WebSocket (except heartbeat) are forwarded to SRMUDP.
    All messages received via SRMUDP are forwarded to WebSocket.
    """
    await websocket.accept()
    
    # Use server default SRMUDP port if none specified
    if local_port is None:
        local_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
    
    # Create connection ID for logging
    connection_id = f"{remote_address}_{local_port}"
    
    # Create SRMUDP bridge
    bridge = SRMUDPBridge(local_port=local_port)
    active_bridges[connection_id] = bridge
    
    # Set up WebSocket send hook
    async def websocket_send_hook(data: bytes):
        """Hook function to send data from SRMUDP to WebSocket"""
        try:
            # Try to decode as UTF-8 text
            try:
                text_data = data.decode('utf-8')
                await websocket.send_json({
                    "type": "message", 
                    "format": "text",
                    "data": text_data
                })
                logger.debug(f"Sent text message to WebSocket: {len(text_data)} chars")
            except UnicodeDecodeError:
                # Send as base64 encoded binary
                binary_data = base64.b64encode(data).decode('ascii')
                await websocket.send_json({
                    "type": "message",
                    "format": "binary", 
                    "data": binary_data
                })
                logger.debug(f"Sent binary message to WebSocket: {len(data)} bytes")
                
        except Exception as e:
            logger.error(f"Error sending to WebSocket: {e}")
    
    # Set the hook
    bridge.set_websocket_hook(websocket_send_hook)
    
    try:
        # Start SRMUDP connection
        logger.info(f"Starting bridge to {remote_address}")
        success = await bridge.start(remote_address)
        
        if not success:
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to connect to {remote_address}"
            })
            return
        
        # Send connection success
        await websocket.send_json({
            "type": "status",
            "status": "connected",
            "local_address": bridge.get_local_address(),
            "peer_address": bridge.get_peer_address()
        })
        
        # Handle WebSocket messages
        while bridge.is_running:
            try:
                # Receive message from WebSocket
                message = await websocket.receive_text()
                
                # Skip heartbeat messages
                if _is_heartbeat_message(message):
                    logger.debug("Skipping heartbeat message")
                    continue
                
                # Try to parse as JSON
                try:
                    message_data = json.loads(message)
                    
                    # Handle different message types
                    if message_data.get("type") == "message":
                        # Forward regular messages to SRMUDP peer
                        format_type = message_data.get("format", "text")
                        data = message_data.get("data", "")
                        
                        # Convert data to bytes based on format
                        if format_type == "binary":
                            try:
                                # Decode base64 for binary data
                                binary_data = base64.b64decode(data)
                                await bridge.send_to_peer(binary_data)
                            except Exception as e:
                                logger.error(f"Failed to decode binary data: {e}")
                                await websocket.send_text(json.dumps({
                                    "type": "error",
                                    "error": f"Invalid binary data format: {str(e)}"
                                }))
                        else:
                            # Send as text (UTF-8 encoded)
                            await bridge.send_to_peer(data.encode('utf-8'))
                    
                    elif message_data.get("type") == "discover_public_address":
                        # Perform STUN discovery on the active connection
                        logger.info(f"WebSocket {connection_id} requested public address discovery")
                        
                        try:
                            public_address = await bridge.discover_public_address_safe()
                            
                            if public_address:
                                public_ip, public_port = public_address
                                await websocket.send_text(json.dumps({
                                    "type": "public_address_discovered",
                                    "public_ip": public_ip,
                                    "public_port": public_port,
                                    "local_address": bridge.get_local_address(),
                                    "peer_address": bridge.get_peer_address(),
                                    "discovery_method": "STUN via active SRMUDP connection"
                                }))
                            else:
                                await websocket.send_text(json.dumps({
                                    "type": "public_address_discovery_failed",
                                    "error": "Failed to discover public address via STUN",
                                    "local_address": bridge.get_local_address(),
                                    "peer_address": bridge.get_peer_address()
                                }))
                                
                        except Exception as e:
                            logger.error(f"Error during public address discovery: {e}")
                            await websocket.send_text(json.dumps({
                                "type": "error",
                                "error": f"Public address discovery failed: {str(e)}"
                            }))
                    
                    else:
                        # Unknown message type
                        await websocket.send_text(json.dumps({
                            "type": "error", 
                            "error": f"Unknown message type: {message_data.get('type')}"
                        }))
                    
                except json.JSONDecodeError:
                    # Treat as plain text
                    text_bytes = message.encode('utf-8')
                    await bridge.send_to_peer(text_bytes)
                    logger.debug(f"Forwarded plain text to SRMUDP peer")
                    
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for {connection_id}")
                break
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                break
                
    except Exception as e:
        logger.error(f"Error in WebSocket bridge: {e}")
        try:
            await websocket.send_json({
                "type": "error", 
                "message": str(e)
            })
        except:
            pass
    finally:
        # Clean up
        if connection_id in active_bridges:
            del active_bridges[connection_id]
        await bridge.stop()
        logger.info(f"Bridge {connection_id} closed")

def _is_heartbeat_message(message: str) -> bool:
    """
    Check if a message is a heartbeat/ping message.
    
    Args:
        message: The message to check
        
    Returns:
        True if it's a heartbeat message, False otherwise
    """
    try:
        data = json.loads(message)
        msg_type = data.get("type", "").lower()
        return msg_type in ["ping", "pong", "heartbeat", "keepalive"]
    except:
        # Check for common heartbeat strings
        lower_msg = message.lower().strip()
        return lower_msg in ["ping", "pong", "heartbeat", "keepalive"]

@router.get("/ws/bridges")
async def get_active_bridges():
    """
    Get information about active WebSocket-SRMUDP bridges.
    For debugging and monitoring.
    """
    bridges_info = []
    for connection_id, bridge in active_bridges.items():
        bridges_info.append({
            "connection_id": connection_id,
            "local_address": bridge.get_local_address(),
            "peer_address": bridge.get_peer_address(),
            "is_connected": bridge.is_connected,
            "is_running": bridge.is_running
        })
    return {
        "active_bridges": len(bridges_info),
        "bridges": bridges_info
    }

@router.get("/ws/server-config")
async def get_server_config():
    """
    Get the current server configuration.
    """
    default_srmudp_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
    
    return {
        "preferred_srmudp_port": default_srmudp_port,
        "port_behavior": "0 = random port, >0 = preferred port",
        "note": "Clients can override this with the local_port parameter"
    } 