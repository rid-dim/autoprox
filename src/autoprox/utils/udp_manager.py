import asyncio
import socket
import time
import logging
import ipaddress
import secrets
import struct
import zlib
from enum import Enum
from typing import Optional, Tuple, Union, Dict, Any, List, Set
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
# Maximum UDP packet size (bytes) - safe limit to avoid fragmentation
MAX_UDP_PACKET_SIZE = 1400  # Conservative estimate for most networks
# Encrypted data is typically 30-40% larger than raw data due to IV, padding, and encoding
ENCRYPTION_OVERHEAD_FACTOR = 1.4  # 40% overhead for encryption
# Fragment message prefix
FRAGMENT_PREFIX = b"FRAGMENT:"
# Fragment header size (bytes): 4 (msg_id) + 4 (total_fragments) + 4 (fragment_index) + 4 (payload_size)
FRAGMENT_HEADER_SIZE = 16
# Adjusted maximum fragment payload to account for encryption overhead
MAX_FRAGMENT_PAYLOAD_SIZE = int((MAX_UDP_PACKET_SIZE - len(FRAGMENT_PREFIX) - FRAGMENT_HEADER_SIZE) / ENCRYPTION_OVERHEAD_FACTOR)

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
        local_port: int = int(os.environ.get('AUTOPROX_UDP_PORT', 17171))  # Use environment variable or default
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
        
        # Communication queues - separate queue for heartbeats to prioritize them
        self._regular_send_queue = asyncio.Queue()
        self._heartbeat_send_queue = asyncio.Queue()  # New dedicated queue for heartbeats
        self._receive_queue = asyncio.Queue()
        
        # Determine if IPv6 is being used
        try:
            self.is_ipv6 = bool(ipaddress.IPv6Address(remote_host))
        except ValueError:
            self.is_ipv6 = False
        
        # Timestamp of last error message
        self._last_error_timestamp = 0
        
        # Fragment handling
        self._next_message_id = 0
        self._fragment_buffer = {}  # Store received fragments: {msg_id: {fragment_index: data, ...}, ...}
        self._completed_messages = {}  # Store completed messages: {msg_id: (completed, total_fragments)}
        self._fragment_cleanup_task = None
        
        # Heartbeat tracking
        self._last_heartbeat_sent = 0
    
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
            asyncio.create_task(self._connection_monitor()),
            asyncio.create_task(self._fragment_cleanup_loop())
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
        """
        Send data to the remote peer.
        Large messages will be automatically fragmented.
        """
        if not self._running:
            raise RuntimeError("UDP manager is not running")
        
        # Konservativere Schätzung der maximalen Datengröße aufgrund von Verschlüsselungs-Overhead
        if len(data) <= MAX_FRAGMENT_PAYLOAD_SIZE:
            # Small message, send directly
            await self._regular_send_queue.put(data)
        else:
            # Large message, needs fragmentation
            await self._send_fragmented(data)
    
    async def _send_fragmented(self, data: bytes):
        """
        Fragment and send a large message.
        
        Format:
        FRAGMENT_PREFIX + msg_id(4) + total_fragments(4) + fragment_index(4) + payload_size(4) + payload
        """
        # Generate message ID and increment counter
        msg_id = self._next_message_id
        self._next_message_id = (self._next_message_id + 1) % 0xFFFFFFFF
        
        # Calculate total fragments needed
        total_fragments = (len(data) + MAX_FRAGMENT_PAYLOAD_SIZE - 1) // MAX_FRAGMENT_PAYLOAD_SIZE
        
        # Split data into fragments
        for i in range(total_fragments):
            start_pos = i * MAX_FRAGMENT_PAYLOAD_SIZE
            end_pos = min(start_pos + MAX_FRAGMENT_PAYLOAD_SIZE, len(data))
            payload = data[start_pos:end_pos]
            payload_size = len(payload)
            
            # Create header
            header = struct.pack("!IIII", msg_id, total_fragments, i, payload_size)
            
            # Create fragment
            fragment = FRAGMENT_PREFIX + header + payload
            
            # Send fragment
            await self._regular_send_queue.put(fragment)
            
        logger.debug(f"Fragmented message {msg_id} into {total_fragments} parts")
    
    async def receive(self) -> Optional[bytes]:
        """
        Receive data from the remote peer.
        Fragmented messages will be reassembled automatically.
        """
        if not self._running:
            return None
        
        return await self._receive_queue.get()
    
    def get_status(self) -> ConnectionStatus:
        """Get the current connection status"""
        return self._status
    
    async def _process_fragments(self, fragment: bytes) -> Optional[bytes]:
        """
        Process a received fragment and reassemble complete messages.
        Returns the reassembled message if complete, None otherwise.
        """
        # Strip prefix
        fragment_data = fragment[len(FRAGMENT_PREFIX):]
        
        # Parse header
        if len(fragment_data) < FRAGMENT_HEADER_SIZE:
            logger.warning(f"Received fragment with invalid header size: {len(fragment_data)}")
            return None
        
        header = fragment_data[:FRAGMENT_HEADER_SIZE]
        payload = fragment_data[FRAGMENT_HEADER_SIZE:]
        
        try:
            msg_id, total_fragments, fragment_index, payload_size = struct.unpack("!IIII", header)
        except struct.error:
            logger.warning("Failed to unpack fragment header")
            return None
        
        # Validate payload size
        if len(payload) != payload_size:
            logger.warning(f"Fragment payload size mismatch: expected {payload_size}, got {len(payload)}")
            return None
        
        # Check if message is already completed
        if msg_id in self._completed_messages:
            # We already processed this message, ignore this fragment
            return None
        
        # Store fragment
        if msg_id not in self._fragment_buffer:
            self._fragment_buffer[msg_id] = {}
        
        self._fragment_buffer[msg_id][fragment_index] = payload
        
        # Check if we have all fragments
        if len(self._fragment_buffer[msg_id]) == total_fragments:
            # Reassemble message
            reassembled = bytearray()
            for i in range(total_fragments):
                if i not in self._fragment_buffer[msg_id]:
                    logger.warning(f"Missing fragment {i} for message {msg_id}")
                    return None
                reassembled.extend(self._fragment_buffer[msg_id][i])
            
            # Mark message as completed
            self._completed_messages[msg_id] = (time.time(), total_fragments)
            
            # Clean up fragments
            del self._fragment_buffer[msg_id]
            
            logger.debug(f"Reassembled message {msg_id} from {total_fragments} fragments")
            return bytes(reassembled)
        
        return None
    
    async def _fragment_cleanup_loop(self):
        """
        Periodically clean up old completed messages and partial fragments.
        """
        while self._running:
            try:
                current_time = time.time()
                
                # Clean up completed messages older than 60 seconds
                for msg_id in list(self._completed_messages.keys()):
                    timestamp, _ = self._completed_messages[msg_id]
                    if current_time - timestamp > 60:
                        del self._completed_messages[msg_id]
                
                # Clean up incomplete fragments older than 30 seconds
                # This is a basic timeout mechanism to prevent memory leaks
                for msg_id in list(self._fragment_buffer.keys()):
                    # Check if any fragments exist for over 30 seconds
                    # This is a simple implementation; could be improved with per-fragment timestamps
                    if msg_id not in self._completed_messages and len(self._fragment_buffer[msg_id]) > 0:
                        del self._fragment_buffer[msg_id]
                        logger.debug(f"Cleaned up incomplete fragments for message {msg_id}")
                
                await asyncio.sleep(10)  # Run cleanup every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in fragment cleanup loop: {e}")
                await asyncio.sleep(10)
    
    async def _udp_receive_loop(self):
        """Background task for receiving UDP packets"""
        loop = asyncio.get_event_loop()
        
        # Puffer für verschlüsselte Notfall-Fragmente
        encrypted_fragments = {}
        last_fragment_time = {}
        
        while self._running:
            try:
                # Wait for data using asyncio
                data, addr = await loop.sock_recvfrom(self._socket, 4096)
                
                # Verify the sender is our expected peer
                peer_addr = (self.remote_host, self.remote_port)
                if addr[0] != self.remote_host or addr[1] != self.remote_port:
                    logger.warning(f"Received data from unexpected address: {addr}, expected: {peer_addr}")
                    continue
                
                # Spezieller Fall: Wenn wir mehrere UDP-Pakete mit fast gleicher Größe erhalten,
                # könnten das unsere notfall-fragmentierten verschlüsselten Daten sein
                addr_key = f"{addr[0]}:{addr[1]}"
                current_time = time.time()
                
                # Wenn das Paket etwa die maximale Größe hat, behandle es als potenzielles Fragment
                if abs(len(data) - (MAX_UDP_PACKET_SIZE - 20)) < 50:
                    if addr_key not in encrypted_fragments:
                        encrypted_fragments[addr_key] = []
                        last_fragment_time[addr_key] = current_time
                    
                    # Sammle Fragmente
                    encrypted_fragments[addr_key].append(data)
                    last_fragment_time[addr_key] = current_time
                    
                    # Wenn eine Pause von mehr als 0.1 Sekunden zwischen Paketen liegt, 
                    # versuche die gesammelten Fragmente zu verarbeiten
                    await asyncio.sleep(0.1)
                    if current_time - last_fragment_time[addr_key] >= 0.1 and encrypted_fragments[addr_key]:
                        # Versuche die gesammelten Fragmente zusammenzusetzen und zu entschlüsseln
                        try:
                            combined_data = b''.join(encrypted_fragments[addr_key])
                            decrypted_data = decrypt_data(self.encryption_key, combined_data)
                            
                            # Leere den Puffer
                            encrypted_fragments[addr_key] = []
                            
                            # Verarbeite die entschlüsselten Daten wie gehabt
                            if decrypted_data.startswith(HEARTBEAT_PREFIX):
                                logger.debug("Received heartbeat from remote peer")
                                self._last_heartbeat_received = time.time()
                                
                                if self._status == ConnectionStatus.UDP_WAITING:
                                    self._status = ConnectionStatus.UDP_ESTABLISHED
                                    logger.info("UDP connection established with remote peer")
                            elif decrypted_data.startswith(FRAGMENT_PREFIX):
                                reassembled = await self._process_fragments(decrypted_data)
                                if reassembled:
                                    await self._receive_queue.put(reassembled)
                            else:
                                await self._receive_queue.put(decrypted_data)
                            
                            continue
                        except Exception as e:
                            # Wenn die Entschlüsselung fehlschlägt, verarbeite die Daten einzeln
                            logger.debug(f"Failed to combine fragments: {e}")
                            encrypted_fragments[addr_key] = []
                
                # Normal processing for individual packets
                try:
                    decrypted_data = decrypt_data(self.encryption_key, data)
                    
                    # Check if it's a heartbeat
                    if decrypted_data.startswith(HEARTBEAT_PREFIX):
                        logger.debug("Received heartbeat from remote peer")
                        self._last_heartbeat_received = time.time()
                        
                        # Update connection status if needed
                        if self._status == ConnectionStatus.UDP_WAITING:
                            self._status = ConnectionStatus.UDP_ESTABLISHED
                            logger.info("UDP connection established with remote peer")
                    
                    # Check if it's a fragment
                    elif decrypted_data.startswith(FRAGMENT_PREFIX):
                        # Process fragment
                        reassembled = await self._process_fragments(decrypted_data)
                        if reassembled:
                            # Have a complete message, put it in the receive queue
                            await self._receive_queue.put(reassembled)
                    
                    else:
                        # Regular data, put in receive queue
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
        """Background task for sending UDP packets with priority for heartbeats"""
        while self._running:
            try:
                # First check if there are any heartbeats to send (prioritized)
                # We use try_get to not block if there are no heartbeats
                heartbeat_data = None
                
                try:
                    # Try to get a heartbeat message first (non-blocking)
                    heartbeat_data = self._heartbeat_send_queue.get_nowait()
                except asyncio.QueueEmpty:
                    # No heartbeat message in queue, that's okay
                    pass
                
                # If we have a heartbeat, send it immediately
                if heartbeat_data:
                    await self._send_packet(heartbeat_data)
                    self._heartbeat_send_queue.task_done()
                    continue
                
                # Otherwise, try to get a regular message
                # This will block until a message is available
                data = await self._regular_send_queue.get()
                await self._send_packet(data)
                self._regular_send_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in UDP send loop: {e}")
                await asyncio.sleep(0.1)  # Avoid tight loop on error
    
    async def _send_packet(self, data: bytes):
        """Send a single packet, handling encryption and emergency fragmentation if needed"""
        try:
            # Encrypt the data
            encrypted_data = encrypt_data(self.encryption_key, data)
            
            # Check size before sending
            if len(encrypted_data) > MAX_UDP_PACKET_SIZE:
                logger.warning(f"Encrypted data too large: {len(encrypted_data)} bytes. Fragmenting large encrypted data.")
                
                # Notfall-Fragmentierung für verschlüsselte Daten, die das Limit überschreiten
                max_chunk_size = MAX_UDP_PACKET_SIZE - 20  # Kleiner Puffer für UDP-Header
                
                chunks = [encrypted_data[i:i+max_chunk_size] for i in range(0, len(encrypted_data), max_chunk_size)]
                logger.info(f"Emergency fragmenting encrypted data into {len(chunks)} chunks")
                
                for i, chunk in enumerate(chunks):
                    peer_addr = (self.remote_host, self.remote_port)
                    self._socket.sendto(chunk, peer_addr)
                    
                    # Every 10 chunks, check if we need to send a heartbeat
                    if i % 10 == 0 and i > 0:
                        # Check if it's time for another heartbeat
                        current_time = time.time()
                        if current_time - self._last_heartbeat_sent >= HEARTBEAT_INTERVAL:
                            # Send a heartbeat directly
                            await self._send_direct_heartbeat()
                    
                    # Smaller pause to improve throughput while still allowing other tasks to run
                    await asyncio.sleep(0.005)  # 5ms pause zwischen Fragmenten
                
                return
            
            # Send normal packet
            peer_addr = (self.remote_host, self.remote_port)
            self._socket.sendto(encrypted_data, peer_addr)
            logger.debug(f"Sent {len(encrypted_data)} bytes to {peer_addr}")
            
        except Exception as e:
            logger.error(f"Error sending packet: {e}")
            raise
    
    async def _send_direct_heartbeat(self):
        """Send a heartbeat directly, bypassing the queue system"""
        try:
            # Generate a heartbeat with random bytes
            random_bytes = secrets.token_bytes(8)
            heartbeat_msg = HEARTBEAT_PREFIX + random_bytes
            
            # Encrypt and send directly
            encrypted_data = encrypt_data(self.encryption_key, heartbeat_msg)
            peer_addr = (self.remote_host, self.remote_port)
            self._socket.sendto(encrypted_data, peer_addr)
            
            # Update last heartbeat timestamp
            self._last_heartbeat_sent = time.time()
            logger.debug(f"Sent direct heartbeat to remote peer")
            
        except Exception as e:
            logger.error(f"Error sending direct heartbeat: {e}")
    
    async def _heartbeat_loop(self):
        """Background task for sending heartbeats to keep the connection alive"""
        while self._running:
            try:
                # Generiere einen Zufallswert für den Heartbeat
                # 8 Bytes Zufallsdaten (64 Bit)
                random_bytes = secrets.token_bytes(8)
                
                # Erstelle die Heartbeat-Nachricht mit Zufallswert
                heartbeat_msg = HEARTBEAT_PREFIX + random_bytes
                
                # Sende den Heartbeat mit Zufallswert in die priorisierte Heartbeat-Queue
                await self._heartbeat_send_queue.put(heartbeat_msg)
                self._last_heartbeat_sent = time.time()
                logger.debug(f"Queued heartbeat to remote peer (with {len(random_bytes)} random bytes)")
                
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