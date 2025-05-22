import logging
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from ..utils.stun_client import get_public_ip, get_public_address, get_public_address_for_srmudp
from ..utils.stun_srmudp import discover_srmudp_public_address, discover_srmudp_public_address_with_port
from ..routes.websocket import active_bridges

logger = logging.getLogger(__name__)

# Create router for network endpoints  
router = APIRouter(prefix="/v0", tags=["network"])

class PublicIPInfo(BaseModel):
    """Model for public IP information response"""
    public_ip: str = Field(..., description="Public IP address discovered via STUN")
    discovery_method: str = Field(..., description="Method used to discover the IP")
    success: bool = Field(..., description="Whether discovery was successful")

class PublicAddressInfo(BaseModel):
    """Model for public address information response"""
    public_ip: str = Field(..., description="Public IP address discovered via STUN")
    public_port: int = Field(..., description="Public port discovered via STUN")
    local_port: int = Field(..., description="Local port that was bound")
    discovery_method: str = Field(..., description="Method used to discover the address")
    success: bool = Field(..., description="Whether discovery was successful")

@router.get("/network/public-ip", response_model=PublicIPInfo)
async def get_public_ip_info():
    """
    Discover and return the public IP address using STUN servers.
    
    This endpoint queries public STUN servers to discover the external/public 
    IP address as seen by the internet. This is useful for NAT traversal
    and determining the address that SRMUDP peers will see.
    """
    try:
        public_ip = await get_public_ip()
        
        if public_ip:
            return {
                "public_ip": public_ip,
                "discovery_method": "STUN",
                "success": True
            }
        else:
            raise HTTPException(
                status_code=503,
                detail="Failed to discover public IP address via STUN servers"
            )
            
    except Exception as e:
        logger.error(f"Error discovering public IP: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error while discovering public IP: {str(e)}"
        )

@router.get("/network/public-address", response_model=PublicAddressInfo)
async def get_public_address_info(
    local_port: Optional[int] = Query(None, description="Local port to bind to (None=server preference, 0=random)")
):
    """
    Discover and return the public IP address and port using STUN servers.
    
    This endpoint queries public STUN servers to discover the external/public 
    IP address and port as seen by the internet. The port information can be
    useful for understanding NAT behavior.
    
    If no local_port is specified, uses the server's preferred SRMUDP port.
    """
    try:
        # Use server default if no port specified
        if local_port is None:
            local_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
        
        result = await get_public_address(local_port)
        
        if result:
            public_ip, public_port = result
            return {
                "public_ip": public_ip,
                "public_port": public_port,
                "local_port": local_port,
                "discovery_method": "STUN",
                "success": True
            }
        else:
            raise HTTPException(
                status_code=503,
                detail="Failed to discover public address via STUN servers"
            )
            
    except Exception as e:
        logger.error(f"Error discovering public address: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error while discovering public address: {str(e)}"
        )

@router.get("/network/srmudp-address", response_model=PublicAddressInfo)
async def get_srmudp_public_address():
    """
    Discover the public address that would be used by SRMUDP connections.
    
    This endpoint creates a temporary SRMUDP socket using the server's preferred port
    and performs STUN discovery through it. This ensures we get the exact public 
    address that SRMUDP hole-punching would see, avoiding port conflicts.
    
    Note: This will fail if there's already an active WebSocket bridge using the same port.
    """
    local_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
    
    # Check if there's already an active bridge using this port
    conflicting_bridges = []
    for connection_id, bridge in active_bridges.items():
        if bridge.local_port == local_port and bridge.is_running:
            conflicting_bridges.append(connection_id)
    
    if conflicting_bridges:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot perform STUN discovery: port {local_port} is in use by active WebSocket bridges: {conflicting_bridges}"
        )
    
    try:
        result = await discover_srmudp_public_address()
        
        if result:
            public_ip, public_port = result
            return {
                "public_ip": public_ip,
                "public_port": public_port,
                "local_port": local_port,
                "discovery_method": "STUN via SRMUDP socket",
                "success": True
            }
        else:
            raise HTTPException(
                status_code=503,
                detail="Failed to discover SRMUDP public address via STUN servers"
            )
            
    except Exception as e:
        logger.error(f"Error discovering SRMUDP public address: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error while discovering SRMUDP public address: {str(e)}"
        )

@router.get("/network/srmudp-address-test", response_model=PublicAddressInfo)
async def test_srmudp_public_address(
    test_port: int = Query(..., description="Port to test SRMUDP STUN discovery with")
):
    """
    Test SRMUDP STUN discovery with a specific port.
    
    This endpoint creates a temporary SRMUDP socket on the specified port
    and performs STUN discovery. Useful for testing hole-punching behavior
    with different ports.
    
    Note: This will fail if the specified port is already in use by a WebSocket bridge.
    """
    # Check if there's already an active bridge using this port
    conflicting_bridges = []
    for connection_id, bridge in active_bridges.items():
        if bridge.local_port == test_port and bridge.is_running:
            conflicting_bridges.append(connection_id)
    
    if conflicting_bridges:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot test port {test_port}: already in use by active WebSocket bridges: {conflicting_bridges}"
        )
    
    try:
        result = await discover_srmudp_public_address_with_port(test_port)
        
        if result:
            public_ip, public_port = result
            return {
                "public_ip": public_ip,
                "public_port": public_port,
                "local_port": test_port,
                "discovery_method": f"STUN via SRMUDP socket (test port {test_port})",
                "success": True
            }
        else:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to discover public address via SRMUDP on port {test_port}"
            )
            
    except Exception as e:
        logger.error(f"Error testing SRMUDP public address on port {test_port}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error while testing SRMUDP on port {test_port}: {str(e)}"
        )

@router.get("/network/stun-servers")
async def get_stun_servers():
    """
    Get the list of STUN servers used for public IP discovery.
    
    Returns information about the STUN servers that are queried
    to discover the public IP address.
    """
    from ..utils.stun_client import STUN_SERVERS
    
    return {
        "stun_servers": [
            {"host": host, "port": port} 
            for host, port in STUN_SERVERS
        ],
        "description": "Public STUN servers used for IP discovery",
        "usage": "These servers are queried in order until one responds successfully"
    }

@router.get("/network/active-ports")
async def get_active_srmudp_ports():
    """
    Get information about SRMUDP ports currently in use by active WebSocket bridges.
    
    This is useful to check which ports are occupied before attempting STUN discovery
    or creating new WebSocket bridges.
    
    Returns:
        Information about active bridges and their port usage
    """
    from ..routes.websocket import active_bridges
    
    active_ports = {}
    
    for connection_id, bridge in active_bridges.items():
        if bridge.is_running and bridge.socket:
            local_addr = bridge.get_local_address()
            peer_addr = bridge.get_peer_address()
            
            port_info = {
                "connection_id": connection_id,
                "local_port": bridge.local_port,
                "local_address": local_addr,
                "peer_address": peer_addr,
                "is_connected": bridge.is_connected,
                "status": "active"
            }
            
            active_ports[bridge.local_port] = port_info
    
    server_preferred_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
    
    return {
        "active_bridges": active_ports,
        "server_preferred_port": server_preferred_port,
        "port_conflicts": {
            "stun_discovery_blocked": server_preferred_port in active_ports,
            "conflicting_port": server_preferred_port if server_preferred_port in active_ports else None
        },
        "available_actions": {
            "can_use_stun_discovery": server_preferred_port not in active_ports,
            "can_test_specific_ports": [port for port in range(12345, 12355) if port not in active_ports][:5]  # Show 5 example ports
        }
    } 