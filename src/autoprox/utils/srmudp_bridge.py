import asyncio
import logging
import json
import socket
import struct
import random
from typing import Optional, Callable, Any, Tuple
from srmudp import SecureReliableSocket, Packet

logger = logging.getLogger(__name__)

# STUN constants
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020

# Common public STUN servers
STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302), 
    ("stun2.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("stun.nextcloud.com", 3478),
    ("stun.stunprotocol.org", 3478),
]

class SRMUDPBridge:
    """
    Simple bridge between WebSocket and SRMUDP communication.
    Handles bidirectional message forwarding with hook functions.
    """
    
    def __init__(self, local_port: int = 0):
        self.local_port = local_port
        self.socket: Optional[SecureReliableSocket] = None
        self.is_connected = False
        self.is_running = False
        self.message_hook: Optional[Callable] = None
        self.websocket_send_hook: Optional[Callable] = None
        
    async def start(self, remote_address: str) -> bool:
        """
        Start SRMUDP connection to remote address.
        
        Args:
            remote_address: Address in format "host:port"
            
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Create socket
            self.socket = SecureReliableSocket(self.local_port)
            
            # Set message hook for incoming messages
            self.socket.message_hook_fnc = self._handle_incoming_message
            
            # Connect to remote
            logger.info(f"Connecting to {remote_address}")
            await asyncio.get_event_loop().run_in_executor(
                None, self.socket.connect, remote_address
            )
            
            self.is_connected = True
            self.is_running = True
            logger.info(f"Connected to {remote_address}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to {remote_address}: {e}")
            return False
    
    def _handle_incoming_message(self, packet: Packet, sender_address, sock: SecureReliableSocket):
        """
        Hook function called when SRMUDP receives a message.
        Forwards the message directly to WebSocket if hook is set.
        """
        try:
            data = packet.data
            sender_str = f"{sender_address[0]}:{sender_address[1]}"
            
            logger.debug(f"Received SRMUDP message from {sender_str}: {len(data)} bytes")
            
            # Call WebSocket send hook if available
            if self.websocket_send_hook:
                asyncio.create_task(self.websocket_send_hook(data))
                
        except Exception as e:
            logger.error(f"Error handling incoming SRMUDP message: {e}")
    
    async def send_to_peer(self, data: bytes) -> bool:
        """
        Send data to the connected SRMUDP peer.
        
        Args:
            data: Data to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.socket or not self.is_connected:
            logger.error("Cannot send: not connected")
            return False
            
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self.socket.send, data
            )
            logger.debug(f"Sent {len(data)} bytes to SRMUDP peer")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send data to SRMUDP peer: {e}")
            return False
    
    def set_websocket_hook(self, hook: Callable):
        """Set the hook function for sending messages to WebSocket."""
        self.websocket_send_hook = hook
    
    async def discover_public_address_via_stun(self, timeout: float = 5.0) -> Optional[Tuple[str, int]]:
        """
        Discover the public address using STUN servers via the existing SRMUDP socket.
        This ensures we get the exact address that would be used for hole-punching.
        
        Args:
            timeout: Timeout for STUN requests
            
        Returns:
            Tuple of (public_ip, public_port) or None if discovery fails
        """
        if not self.socket:
            logger.error("Cannot discover STUN address: no SRMUDP socket available")
            return None
        
        # Access the underlying UDP socket from SRMUDP
        try:
            # The SRMUDP socket has a receiver_socket attribute which is the actual UDP socket
            udp_socket = self.socket.receiver_socket
            local_addr = self.socket.getsockname()
            
            logger.info(f"Using SRMUDP UDP socket for STUN discovery, bound to {local_addr}")
            
            # Try STUN servers
            for stun_host, stun_port in STUN_SERVERS:
                try:
                    result = await self._query_stun_server_with_socket(udp_socket, stun_host, stun_port, timeout)
                    if result:
                        logger.info(f"Discovered public address via {stun_host} using SRMUDP socket: {result[0]}:{result[1]}")
                        return result
                except Exception as e:
                    logger.debug(f"Failed to query STUN server {stun_host}:{stun_port} with SRMUDP socket: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error accessing SRMUDP UDP socket: {e}")
        
        logger.error("Failed to discover public address via any STUN server using SRMUDP socket")
        return None
    
    async def discover_public_address_safe(self, timeout: float = 5.0) -> Optional[Tuple[str, int]]:
        """
        Safely discover the public address using STUN via the active SRMUDP connection.
        
        This method attempts to perform STUN discovery while the socket is active,
        but with safety measures to avoid interfering with ongoing SRMUDP communication.
        
        Args:
            timeout: Timeout for STUN requests
            
        Returns:
            Tuple of (public_ip, public_port) or None if discovery fails
        """
        if not self.socket or not self.is_connected:
            logger.warning("Cannot perform safe STUN discovery: no active SRMUDP connection")
            return None
        
        logger.info("Attempting safe STUN discovery on active SRMUDP connection")
        
        try:
            # Brief pause to let any ongoing SRMUDP traffic settle
            await asyncio.sleep(0.1)
            
            # Perform STUN discovery with a shorter timeout to minimize interference
            result = await self.discover_public_address_via_stun(timeout=min(timeout, 3.0))
            
            if result:
                logger.info(f"Safe STUN discovery successful: {result[0]}:{result[1]}")
            else:
                logger.warning("Safe STUN discovery failed")
            
            return result
            
        except Exception as e:
            logger.error(f"Error during safe STUN discovery: {e}")
            return None
    
    async def _query_stun_server_with_socket(self, udp_socket, host: str, port: int, timeout: float) -> Optional[Tuple[str, int]]:
        """
        Query a STUN server using the provided UDP socket.
        This uses the actual SRMUDP socket for the STUN request.
        """
        transaction_id = random.getrandbits(96).to_bytes(12, 'big')
        request = self._create_stun_request(transaction_id)
        
        # Store the original timeout
        original_timeout = udp_socket.gettimeout()
        
        try:
            # Set timeout for this operation
            udp_socket.settimeout(timeout)
            
            # Send STUN request using the existing SRMUDP socket
            await asyncio.get_event_loop().run_in_executor(
                None, udp_socket.sendto, request, (host, port)
            )
            
            # Receive response
            data, addr = await asyncio.get_event_loop().run_in_executor(
                None, udp_socket.recvfrom, 1024
            )
            
            # Parse response
            return self._parse_stun_response(data, transaction_id)
            
        finally:
            # Restore original timeout
            udp_socket.settimeout(original_timeout)
    
    def _create_stun_request(self, transaction_id: bytes) -> bytes:
        """Create a STUN binding request packet."""
        magic_cookie = 0x2112A442
        message_length = 0
        
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
        
        message_type, message_length, magic_cookie, transaction_id = struct.unpack('!HHI12s', data[:20])
        
        if message_type != STUN_BINDING_RESPONSE or transaction_id != expected_transaction_id:
            return None
        
        offset = 20
        while offset < len(data):
            if offset + 4 > len(data):
                break
            
            attr_type, attr_length = struct.unpack('!HH', data[offset:offset+4])
            offset += 4
            
            if offset + attr_length > len(data):
                break
            
            attr_data = data[offset:offset+attr_length]
            
            if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS:
                return self._parse_xor_mapped_address(attr_data, magic_cookie, transaction_id)
            elif attr_type == STUN_ATTR_MAPPED_ADDRESS:
                return self._parse_mapped_address(attr_data)
            
            offset += attr_length
            while offset % 4 != 0:
                offset += 1
        
        return None
    
    def _parse_mapped_address(self, data: bytes) -> Optional[Tuple[str, int]]:
        """Parse MAPPED-ADDRESS attribute."""
        if len(data) < 8:
            return None
        
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
        
        reserved, family, xor_port = struct.unpack('!BBH', data[:4])
        
        if family == 1:  # IPv4
            if len(data) < 8:
                return None
            
            port = xor_port ^ (magic_cookie >> 16)
            
            xor_ip_bytes = data[4:8]
            magic_bytes = struct.pack('!I', magic_cookie)
            ip_bytes = bytes(a ^ b for a, b in zip(xor_ip_bytes, magic_bytes))
            ip_address = socket.inet_ntop(socket.AF_INET, ip_bytes)
            
            return (ip_address, port)
        
        return None
    
    async def stop(self):
        """Stop the SRMUDP connection."""
        self.is_running = False
        self.is_connected = False
        
        if self.socket:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.socket.close
                )
                logger.info("SRMUDP socket closed")
            except Exception as e:
                logger.error(f"Error closing SRMUDP socket: {e}")
            finally:
                self.socket = None
    
    def get_local_address(self) -> Optional[str]:
        """Get the local socket address."""
        if self.socket:
            try:
                return self.socket.getsockname()
            except:
                pass
        return None
    
    def get_peer_address(self) -> Optional[str]:
        """Get the peer socket address."""
        if self.socket and self.is_connected:
            try:
                return self.socket.getpeername()
            except:
                pass
        return None 