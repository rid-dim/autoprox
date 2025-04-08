import asyncio
import socket
import time
import logging
import ipaddress
import secrets
import struct
from enum import Enum
from typing import Optional, Tuple, Union, Dict, Any, List
from ..utils.encryption import encrypt_data, decrypt_data
from datetime import datetime
import os
import aiohttp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define connection status enum
class ConnectionStatus(Enum):
    CONNECTED = "CONNECTED"  # WebSocket connection established
    UDP_WAITING = "UDP_WAITING"  # Waiting for UDP connection
    UDP_ESTABLISHED = "UDP_ESTABLISHED"  # UDP connection established
    ERROR = "ERROR"  # Error state

# Heartbeat message prefix
HEARTBEAT_PREFIX = b"HEARTBEAT:"  # Prefix für Heartbeat-Nachrichten
# How often to send heartbeats
HEARTBEAT_INTERVAL = 1.0  # seconds
# How long to wait before considering connection lost
HEARTBEAT_TIMEOUT = 5.0  # seconds

class UDPManager:
    """
    Manages a UDP connection with hole-punching capabilities.
    Handles encryption of all data and maintains connection status.
    """
    
    def __init__(
        self, 
        remote_host: str, 
        remote_port: int, 
        encryption_key: str,
        local_port: int = int(os.environ.get('AUTOPROX_UDP_PORT'))  # Use environment variable
    ):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.encryption_key = encryption_key.encode('utf-8')
        self.local_port = local_port
        
        # Connection state
        self._status = ConnectionStatus.CONNECTED  # Start with WebSocket connected
        self._socket = None
        self._running = False
        self._last_heartbeat_received = 0
        self._tasks = []
        
        # Communication queues
        self._send_queue = asyncio.Queue()
        self._receive_queue = asyncio.Queue()
        
        # Determine if IPv6 is being used
        try:
            self.is_ipv6 = bool(ipaddress.IPv6Address(remote_host))
        except ValueError:
            self.is_ipv6 = False
        
        # Timestamp of last error message
        self._last_error_timestamp = 0
    
    async def start(self):
        """Start the UDP manager and establish connection"""
        if self._running:
            return
        
        self._running = True
        self._status = ConnectionStatus.UDP_WAITING
        
        # Create the appropriate socket type based on IP version
        socket_family = socket.AF_INET6 if self.is_ipv6 else socket.AF_INET
        self._socket = socket.socket(socket_family, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # For IPv6, make sure we can handle both v4 and v6 (if supported)
        if self.is_ipv6 and hasattr(socket, 'IPV6_V6ONLY'):
            self._socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        
        # Bind to the local port
        bind_addr = ('::', self.local_port) if self.is_ipv6 else ('0.0.0.0', self.local_port)
        self._socket.bind(bind_addr)
        
        # Make the socket non-blocking
        self._socket.setblocking(False)
        
        # Get the actual port we're bound to (if we used 0)
        _, self.local_port = self._socket.getsockname()[:2]
        
        logger.info(f"UDP socket bound to {'::'if self.is_ipv6 else '0.0.0.0'}:{self.local_port}")
        logger.info(f"Attempting to connect to remote peer at {self.remote_host}:{self.remote_port}")
        
        # Start the background tasks
        self._tasks = [
            asyncio.create_task(self._udp_receive_loop()),
            asyncio.create_task(self._udp_send_loop()),
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._connection_monitor())
        ]
    
    async def stop(self):
        """Stop the UDP manager and close connections"""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Close the socket
        if self._socket:
            self._socket.close()
            self._socket = None
        
        logger.info("UDP manager stopped")
    
    async def send(self, data: bytes):
        """Send data to the remote peer"""
        if not self._running:
            raise RuntimeError("UDP manager is not running")
        
        await self._send_queue.put(data)
    
    async def receive(self) -> Optional[bytes]:
        """Receive data from the remote peer"""
        if not self._running:
            return None
        
        return await self._receive_queue.get()
    
    def get_status(self) -> ConnectionStatus:
        """Get the current connection status"""
        return self._status
    
    async def _udp_receive_loop(self):
        """Background task for receiving UDP packets"""
        loop = asyncio.get_event_loop()
        
        while self._running:
            try:
                # Wait for data using asyncio
                data, addr = await loop.sock_recvfrom(self._socket, 4096)
                
                # Verify the sender is our expected peer
                peer_addr = (self.remote_host, self.remote_port)
                if addr[0] != self.remote_host or addr[1] != self.remote_port:
                    logger.warning(f"Received data from unexpected address: {addr}, expected: {peer_addr}")
                    continue
                
                # Decrypt the data
                try:
                    decrypted_data = decrypt_data(self.encryption_key, data)
                    
                    # Check if it's a heartbeat (now with prefix)
                    if decrypted_data.startswith(HEARTBEAT_PREFIX):
                        logger.debug("Received heartbeat from remote peer")
                        self._last_heartbeat_received = time.time()
                        
                        # Update connection status if needed
                        if self._status == ConnectionStatus.UDP_WAITING:
                            self._status = ConnectionStatus.UDP_ESTABLISHED
                            logger.info("UDP connection established with remote peer")
                    else:
                        # Put regular data in the receive queue
                        await self._receive_queue.put(decrypted_data)
                except Exception as e:
                    logger.error(f"Error decrypting received data: {e}")
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                current_time = time.time()
                if current_time - self._last_error_timestamp >= 5:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    logger.error(f"{timestamp} - Error in UDP receive loop: {e}")
                    self._last_error_timestamp = current_time
                await asyncio.sleep(0.1)  # Avoid tight loop on error
    
    async def _udp_send_loop(self):
        """Background task for sending UDP packets"""
        while self._running:
            try:
                # Get data from the send queue
                data = await self._send_queue.get()
                
                # Encrypt the data
                encrypted_data = encrypt_data(self.encryption_key, data)
                
                # Send it
                peer_addr = (self.remote_host, self.remote_port)
                self._socket.sendto(encrypted_data, peer_addr)
                logger.debug(f"Sent {len(encrypted_data)} bytes to {peer_addr}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in UDP send loop: {e}")
                await asyncio.sleep(0.1)  # Avoid tight loop on error
    
    async def _heartbeat_loop(self):
        """Background task for sending heartbeats to keep the connection alive"""
        while self._running:
            try:
                # Generiere einen Zufallswert für den Heartbeat
                # 8 Bytes Zufallsdaten (64 Bit)
                random_bytes = secrets.token_bytes(8)
                
                # Erstelle die Heartbeat-Nachricht mit Zufallswert
                heartbeat_msg = HEARTBEAT_PREFIX + random_bytes
                
                # Sende den Heartbeat mit Zufallswert
                await self._send_queue.put(heartbeat_msg)
                logger.debug(f"Sent heartbeat to remote peer (with {len(random_bytes)} random bytes)")
                
                # Wait for the next heartbeat interval
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(1)  # Longer sleep on error
    
    async def _connection_monitor(self):
        """Background task for monitoring the connection status"""
        while self._running:
            try:
                # Check if we've received a heartbeat recently
                current_time = time.time()
                time_since_last_heartbeat = current_time - self._last_heartbeat_received
                
                # If we have an established connection but haven't received a heartbeat recently,
                # mark the connection as waiting again
                if (self._status == ConnectionStatus.UDP_ESTABLISHED and 
                    self._last_heartbeat_received > 0 and
                    time_since_last_heartbeat > HEARTBEAT_TIMEOUT):
                    logger.warning("Heartbeat timeout, connection lost")
                    self._status = ConnectionStatus.UDP_WAITING
                
                await asyncio.sleep(1)  # Check once per second
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in connection monitor: {e}")
                await asyncio.sleep(1)  # Longer sleep on error

    async def get_public_ip() -> str:
        """
        Ermittelt die öffentliche IP-Adresse des Servers.
        
        Returns:
            Öffentliche IP-Adresse als String
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.ipify.org') as response:
                    return await response.text()
        except Exception as e:
            logger.error(f"Fehler bei der Ermittlung der öffentlichen IP: {e}")
            return "unknown"

    def get_public_connection_info(self) -> Dict[str, Union[str, int]]:
        """
        Gibt Informationen zur UDP-Verbindung zurück.
        
        Returns:
            Dictionary mit öffentlicher IP und Port
        """
        return {
            "public_ip": asyncio.run(self.get_public_ip()),
            "port": self.local_port
        } 