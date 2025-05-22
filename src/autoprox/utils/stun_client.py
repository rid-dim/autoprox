import socket
import struct
import random
import asyncio
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Common public STUN servers
STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302), 
    ("stun2.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("stun.nextcloud.com", 3478),
    ("stun.stunprotocol.org", 3478),
]

# STUN message types
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101

# STUN attributes
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020

class STUNClient:
    """Simple STUN client for discovering public IP address and port."""
    
    def __init__(self, timeout: float = 5.0, local_port: int = 0):
        self.timeout = timeout
        self.local_port = local_port
    
    async def discover_public_address(self, use_local_port: Optional[int] = None) -> Optional[Tuple[str, int]]:
        """
        Discover the public IP address and port using STUN servers.
        
        Args:
            use_local_port: Specific local port to bind to (overrides instance setting)
        
        Returns:
            Tuple of (ip_address, port) or None if discovery fails
        """
        bind_port = use_local_port if use_local_port is not None else self.local_port
        
        for stun_host, stun_port in STUN_SERVERS:
            try:
                result = await self._query_stun_server(stun_host, stun_port, bind_port)
                if result:
                    logger.info(f"Discovered public address via {stun_host} (local port {bind_port}): {result[0]}:{result[1]}")
                    return result
            except Exception as e:
                logger.debug(f"Failed to query STUN server {stun_host}:{stun_port}: {e}")
                continue
        
        logger.error("Failed to discover public address via any STUN server")
        return None
    
    async def _query_stun_server(self, host: str, port: int, local_port: int = 0) -> Optional[Tuple[str, int]]:
        """
        Query a specific STUN server.
        
        Args:
            host: STUN server hostname
            port: STUN server port
            local_port: Local port to bind to (0 for random)
            
        Returns:
            Tuple of (ip_address, port) or None if query fails
        """
        # Create STUN binding request
        transaction_id = random.getrandbits(96).to_bytes(12, 'big')
        request = self._create_stun_request(transaction_id)
        
        # Create socket and bind to specific port if requested
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        
        try:
            # Bind to specific local port if specified
            if local_port > 0:
                sock.bind(('', local_port))
                logger.debug(f"Bound STUN socket to local port {local_port}")
            
            # Send request
            await asyncio.get_event_loop().run_in_executor(
                None, sock.sendto, request, (host, port)
            )
            
            # Receive response
            data, addr = await asyncio.get_event_loop().run_in_executor(
                None, sock.recvfrom, 1024
            )
            
            # Parse response
            return self._parse_stun_response(data, transaction_id)
            
        finally:
            sock.close()
    
    def _create_stun_request(self, transaction_id: bytes) -> bytes:
        """Create a STUN binding request packet."""
        # STUN header: message type (2) + message length (2) + magic cookie (4) + transaction ID (12)
        magic_cookie = 0x2112A442
        message_length = 0  # No attributes
        
        header = struct.pack(
            '!HHI12s',
            STUN_BINDING_REQUEST,
            message_length, 
            magic_cookie,
            transaction_id
        )
        
        return header
    
    def _parse_stun_response(self, data: bytes, expected_transaction_id: bytes) -> Optional[Tuple[str, int]]:
        """Parse STUN response packet."""
        if len(data) < 20:
            return None
        
        # Parse header
        message_type, message_length, magic_cookie, transaction_id = struct.unpack('!HHI12s', data[:20])
        
        # Verify this is a binding response with correct transaction ID
        if message_type != STUN_BINDING_RESPONSE or transaction_id != expected_transaction_id:
            return None
        
        # Parse attributes
        offset = 20
        while offset < len(data):
            if offset + 4 > len(data):
                break
            
            attr_type, attr_length = struct.unpack('!HH', data[offset:offset+4])
            offset += 4
            
            if offset + attr_length > len(data):
                break
            
            attr_data = data[offset:offset+attr_length]
            
            # Handle XOR-MAPPED-ADDRESS (preferred) or MAPPED-ADDRESS
            if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS:
                return self._parse_xor_mapped_address(attr_data, magic_cookie, transaction_id)
            elif attr_type == STUN_ATTR_MAPPED_ADDRESS:
                return self._parse_mapped_address(attr_data)
            
            # Align to 4-byte boundary
            offset += attr_length
            while offset % 4 != 0:
                offset += 1
        
        return None
    
    def _parse_mapped_address(self, data: bytes) -> Optional[Tuple[str, int]]:
        """Parse MAPPED-ADDRESS attribute."""
        if len(data) < 8:
            return None
        
        # Format: reserved (1) + family (1) + port (2) + address (4 for IPv4)
        reserved, family, port = struct.unpack('!BBH', data[:4])
        
        if family == 1:  # IPv4
            if len(data) < 8:
                return None
            ip_bytes = data[4:8]
            ip_address = socket.inet_ntop(socket.AF_INET, ip_bytes)
            return (ip_address, port)
        
        return None
    
    def _parse_xor_mapped_address(self, data: bytes, magic_cookie: int, transaction_id: bytes) -> Optional[Tuple[str, int]]:
        """Parse XOR-MAPPED-ADDRESS attribute."""
        if len(data) < 8:
            return None
        
        # Format: reserved (1) + family (1) + port (2) + address (4 for IPv4)
        reserved, family, xor_port = struct.unpack('!BBH', data[:4])
        
        if family == 1:  # IPv4
            if len(data) < 8:
                return None
            
            # XOR the port with the most significant 16 bits of magic cookie
            port = xor_port ^ (magic_cookie >> 16)
            
            # XOR the address with magic cookie
            xor_ip_bytes = data[4:8]
            magic_bytes = struct.pack('!I', magic_cookie)
            ip_bytes = bytes(a ^ b for a, b in zip(xor_ip_bytes, magic_bytes))
            ip_address = socket.inet_ntop(socket.AF_INET, ip_bytes)
            
            return (ip_address, port)
        
        return None

# Global instance
_stun_client = STUNClient()

async def get_public_ip(local_port: int = 0) -> Optional[str]:
    """
    Get the public IP address using STUN.
    
    Args:
        local_port: Local port to bind to (0 for random)
    
    Returns:
        Public IP address as string or None if discovery fails
    """
    result = await _stun_client.discover_public_address(local_port)
    return result[0] if result else None

async def get_public_address(local_port: int = 0) -> Optional[Tuple[str, int]]:
    """
    Get the public IP address and port using STUN.
    
    Args:
        local_port: Local port to bind to (0 for random)
    
    Returns:
        Tuple of (ip_address, port) or None if discovery fails
    """
    return await _stun_client.discover_public_address(local_port)

async def get_public_address_for_srmudp() -> Optional[Tuple[str, int]]:
    """
    Get the public IP address and port using the server's preferred SRMUDP port.
    This ensures the discovered address matches what SRMUDP would use for hole-punching.
    
    Returns:
        Tuple of (ip_address, port) or None if discovery fails
    """
    import os
    preferred_port = int(os.environ.get('AUTOPROX_SRMUDP_PORT', 0))
    return await get_public_address(preferred_port) 