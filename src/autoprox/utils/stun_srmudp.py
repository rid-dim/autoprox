import asyncio
import logging
import os
from typing import Optional, Tuple
from srmudp import SecureReliableSocket
from .srmudp_bridge import SRMUDPBridge

logger = logging.getLogger(__name__)

async def discover_srmudp_public_address() -> Optional[Tuple[str, int]]:
    """
    Discover the public address that would be used by SRMUDP connections.
    
    This function creates a temporary SRMUDP socket using the server's preferred port,
    performs STUN discovery through it, and then closes it. This ensures we get
    the exact public address that SRMUDP hole-punching would see.
    
    Returns:
        Tuple of (public_ip, public_port) or None if discovery fails
    """
    preferred_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
    
    # Create a temporary SRMUDP bridge just for STUN discovery
    bridge = SRMUDPBridge(local_port=preferred_port)
    
    try:
        # Create the SRMUDP socket but don't connect to anything
        bridge.socket = SecureReliableSocket(preferred_port)
        
        # Get the actual bound port
        local_addr = bridge.get_local_address()
        if local_addr and ':' in local_addr:
            actual_port = int(local_addr.split(':')[1])
            logger.info(f"Created temporary SRMUDP socket on port {actual_port} for STUN discovery")
        
        # Perform STUN discovery using this socket
        result = await bridge.discover_public_address_via_stun()
        
        if result:
            logger.info(f"SRMUDP STUN discovery successful: {result[0]}:{result[1]}")
            return result
        else:
            logger.error("SRMUDP STUN discovery failed")
            return None
            
    except Exception as e:
        logger.error(f"Error during SRMUDP STUN discovery: {e}")
        return None
    finally:
        # Always clean up the temporary socket
        if bridge.socket:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, bridge.socket.close
                )
                logger.debug("Temporary SRMUDP socket closed")
            except Exception as e:
                logger.error(f"Error closing temporary SRMUDP socket: {e}")

async def discover_srmudp_public_address_with_port(local_port: int) -> Optional[Tuple[str, int]]:
    """
    Discover the public address using a specific local port with SRMUDP.
    
    Args:
        local_port: Specific local port to use
        
    Returns:
        Tuple of (public_ip, public_port) or None if discovery fails
    """
    bridge = SRMUDPBridge(local_port=local_port)
    
    try:
        # Create the SRMUDP socket but don't connect to anything
        bridge.socket = SecureReliableSocket(local_port)
        
        # Perform STUN discovery using this socket
        result = await bridge.discover_public_address_via_stun()
        
        if result:
            logger.info(f"SRMUDP STUN discovery on port {local_port} successful: {result[0]}:{result[1]}")
            return result
        else:
            logger.error(f"SRMUDP STUN discovery on port {local_port} failed")
            return None
            
    except Exception as e:
        logger.error(f"Error during SRMUDP STUN discovery on port {local_port}: {e}")
        return None
    finally:
        # Always clean up the temporary socket
        if bridge.socket:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, bridge.socket.close
                )
                logger.debug(f"Temporary SRMUDP socket on port {local_port} closed")
            except Exception as e:
                logger.error(f"Error closing temporary SRMUDP socket on port {local_port}: {e}") 