import asyncio
import logging
import socket
import threading
import queue
import time
import traceback
from enum import Enum
from typing import Optional, Dict, Any, Union, Tuple, List
import ipaddress
from datetime import datetime

# Import srmudp
from srmudp import SecureReliableSocket

# Configure logging
logger = logging.getLogger(__name__)

class ConnectionStatus(Enum):
    """Connection status enum"""
    CONNECTED = "CONNECTED"       # WebSocket connection established
    UDP_WAITING = "UDP_WAITING"   # Waiting for UDP connection
    UDP_ESTABLISHED = "UDP_ESTABLISHED"  # UDP connection established
    RECONNECTING = "RECONNECTING" # Attempting to reconnect
    ERROR = "ERROR"               # Error state

class SRMUDPManager:
    """
    Manages a Secure Reliable UDP connection with hole-punching capabilities.
    Uses the srmudp library to provide reliable UDP communication.
    """
    
    def __init__(
        self, 
        remote_host: str, 
        remote_port: int, 
        encryption_key: str,
        local_port: int = 0,  # Use 0 for random port assignment
        max_reconnect_attempts: int = 5,
        reconnect_delay: float = 5.0
    ):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.encryption_key = encryption_key
        self.local_port = local_port
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.reconnect_attempts = 0
        
        # Connection state
        self._status = ConnectionStatus.CONNECTED  # Start with WebSocket connected
        self._running = False
        self._socket = None
        self._tasks = []
        
        # Determine if IPv6 is being used
        try:
            self.is_ipv6 = bool(ipaddress.IPv6Address(remote_host))
        except ValueError:
            self.is_ipv6 = False
        
        # Timestamp of last error message
        self._last_error_timestamp = 0
        
        # Queues for message passing between threads
        self._send_queue = asyncio.Queue()
        self._recv_queue = asyncio.Queue()
        
        # Background thread for the srmudp socket (which is blocking)
        self._socket_thread = None
        self._socket_thread_stop = threading.Event()
        self._reconnect_event = threading.Event()
        self._socket_lock = threading.Lock()
    
    async def start(self):
        """Start the SRMUDP manager and establish connection"""
        if self._running:
            return
        
        self._running = True
        self._status = ConnectionStatus.UDP_WAITING
        
        # Reset reconnect attempts counter
        self.reconnect_attempts = 0
        
        # Create and start the socket thread
        self._socket_thread = threading.Thread(
            target=self._socket_thread_func,
            name="SRMUDPSocketThread",
            daemon=True
        )
        self._socket_thread.start()
        
        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._connection_monitor()),
        ]
        
        logger.info(f"SRMUDP manager started, connecting to {self.remote_host}:{self.remote_port}")
    
    def _socket_thread_func(self):
        """Background thread function that manages the SRMUDP socket"""
        while not self._socket_thread_stop.is_set():
            try:
                # Create the socket with appropriate family
                family = socket.AF_INET6 if self.is_ipv6 else socket.AF_INET
                
                with self._socket_lock:
                    if self._socket is not None and not self._socket.is_closed:
                        try:
                            self._socket.close()
                        except Exception as e:
                            logger.error(f"Error closing previous socket: {e}")
                    
                    self._socket = SecureReliableSocket(port=self.local_port, family=family)
                
                logger.info(f"SRMUDP socket created on port {self._socket.port}")
                
                # Get the local address
                local_address = self._socket.getsockname()
                logger.info(f"Local address: {local_address}")
                
                # Connect to the remote peer
                try:
                    remote_address = f"{self.remote_host}:{self.remote_port}"
                    logger.info(f"Connecting to {remote_address}...")
                    
                    # Connect to the remote peer
                    self._socket.connect(remote_address)
                    logger.info("SRMUDP connection established!")
                    
                    # Reset reconnect attempts on successful connection
                    self.reconnect_attempts = 0
                    
                    # Set the status to established
                    self._status = ConnectionStatus.UDP_ESTABLISHED
                    
                    # Clear reconnect event
                    self._reconnect_event.clear()
                    
                    # Main communication loop
                    while not self._socket_thread_stop.is_set() and not self._socket.is_closed and not self._reconnect_event.is_set():
                        # Check for outgoing messages
                        try:
                            # Non-blocking get from the send queue
                            while True:
                                try:
                                    data = self._send_queue.get_nowait()
                                    self._socket.send(data)
                                    logger.debug(f"Sent {len(data)} bytes")
                                except asyncio.QueueEmpty:
                                    break
                        except Exception as e:
                            logger.error(f"Error sending data: {e}")
                            if not self._socket_thread_stop.is_set():
                                # Trigger reconnect if we're still running
                                self._reconnect_event.set()
                                break
                        
                        # Check for incoming messages
                        try:
                            result = self._socket.receive(timeout=0.1)  # Short timeout for responsive handling
                            if result:
                                sender, data, _ = result
                                # Put the received data in the receive queue
                                asyncio.run_coroutine_threadsafe(
                                    self._recv_queue.put(data),
                                    asyncio.get_event_loop()
                                )
                                logger.debug(f"Received {len(data)} bytes from {sender}")
                        except Exception as e:
                            if not self._socket_thread_stop.is_set() and not self._reconnect_event.is_set():
                                if "timed out" not in str(e).lower():  # Ignore timeout exceptions
                                    logger.error(f"Error receiving data: {e}")
                                    # Trigger reconnect for serious errors
                                    if "connection refused" in str(e).lower() or "broken pipe" in str(e).lower():
                                        self._reconnect_event.set()
                                        break
                        
                        # Small sleep to avoid busy-wait
                        time.sleep(0.01)
                    
                except Exception as e:
                    logger.error(f"Error in SRMUDP connection: {e}")
                    logger.debug(traceback.format_exc())
                    self._status = ConnectionStatus.ERROR
                    
                    # Try to reconnect if we haven't exceeded max attempts
                    if self.reconnect_attempts < self.max_reconnect_attempts and not self._socket_thread_stop.is_set():
                        self.reconnect_attempts += 1
                        self._status = ConnectionStatus.RECONNECTING
                        logger.info(f"Connection failed. Reconnect attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} in {self.reconnect_delay} seconds...")
                        # Wait before reconnecting
                        time.sleep(self.reconnect_delay)
                        continue
                    else:
                        self._status = ConnectionStatus.ERROR
                        break
            
            except Exception as e:
                logger.error(f"Error initializing SRMUDP socket: {e}")
                logger.debug(traceback.format_exc())
                self._status = ConnectionStatus.ERROR
                
                # Try to reconnect if we haven't exceeded max attempts
                if self.reconnect_attempts < self.max_reconnect_attempts and not self._socket_thread_stop.is_set():
                    self.reconnect_attempts += 1
                    self._status = ConnectionStatus.RECONNECTING
                    logger.info(f"Socket initialization failed. Reconnect attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} in {self.reconnect_delay} seconds...")
                    # Wait before reconnecting
                    time.sleep(self.reconnect_delay)
                else:
                    break
            
            # Check if reconnect was triggered
            if self._reconnect_event.is_set() and not self._socket_thread_stop.is_set():
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    self.reconnect_attempts += 1
                    self._status = ConnectionStatus.RECONNECTING
                    logger.info(f"Connection lost. Reconnect attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} in {self.reconnect_delay} seconds...")
                    # Wait before reconnecting
                    time.sleep(self.reconnect_delay)
                    # Clear reconnect event
                    self._reconnect_event.clear()
                else:
                    logger.error(f"Max reconnect attempts ({self.max_reconnect_attempts}) reached. Giving up.")
                    self._status = ConnectionStatus.ERROR
                    break
        
        # Final cleanup
        with self._socket_lock:
            if self._socket and not self._socket.is_closed:
                try:
                    self._socket.close()
                except Exception as e:
                    logger.error(f"Error closing SRMUDP socket: {e}")
            self._socket = None
        
        logger.info("SRMUDP socket thread terminated")
    
    async def stop(self):
        """Stop the SRMUDP manager and close connections"""
        if not self._running:
            return
        
        self._running = False
        
        # Signal the socket thread to stop
        self._socket_thread_stop.set()
        self._reconnect_event.set()  # Also set reconnect event to avoid waiting there
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Wait for socket thread to complete (with timeout)
        if self._socket_thread and self._socket_thread.is_alive():
            self._socket_thread.join(timeout=2.0)
        
        logger.info("SRMUDP manager stopped")
    
    def reset_connection(self):
        """
        Reset the connection by signaling the socket thread to reconnect.
        This can be called externally to force a reconnection.
        """
        if self._running and not self._reconnect_event.is_set():
            logger.info("External reconnect request received")
            self._status = ConnectionStatus.RECONNECTING
            self._reconnect_event.set()
    
    async def send(self, data: bytes):
        """
        Send data to the remote peer.
        Places the data in the send queue to be processed by the socket thread.
        """
        if not self._running:
            raise RuntimeError("SRMUDP manager is not running")
        
        await self._send_queue.put(data)
    
    async def receive(self) -> Optional[bytes]:
        """
        Receive data from the remote peer.
        Gets data from the receive queue if available.
        """
        if not self._running:
            return None
        
        try:
            # Try to get data with a short timeout
            return await asyncio.wait_for(self._recv_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Error receiving data: {e}")
            return None
    
    def get_status(self) -> ConnectionStatus:
        """Get the current connection status"""
        return self._status
    
    async def _connection_monitor(self):
        """Monitor the connection status and trigger reconnects if needed"""
        while self._running:
            try:
                with self._socket_lock:
                    socket_closed = self._socket is None or self._socket.is_closed
                
                # Check if the socket is established
                if self._socket and self._socket.established:
                    if self._status != ConnectionStatus.UDP_ESTABLISHED:
                        self._status = ConnectionStatus.UDP_ESTABLISHED
                        logger.info("SRMUDP connection established")
                # Check if the socket is closed and we need to reconnect
                elif socket_closed and self._status != ConnectionStatus.ERROR and not self._reconnect_event.is_set():
                    if self.reconnect_attempts < self.max_reconnect_attempts:
                        logger.info("Connection monitor detected closed socket, triggering reconnect")
                        self._status = ConnectionStatus.RECONNECTING
                        self._reconnect_event.set()
                # Check if we're in an error state
                elif self._status == ConnectionStatus.ERROR:
                    logger.warning("SRMUDP connection in ERROR state")
                
                await asyncio.sleep(1.0)  # Check every second
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in connection monitor: {e}")
                await asyncio.sleep(1.0)
    
    @staticmethod
    async def get_public_ip() -> str:
        """Get the public IP address using an external service"""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.ipify.org') as response:
                    if response.status == 200:
                        return await response.text()
        except Exception as e:
            logger.error(f"Error getting public IP: {e}")
        
        return "127.0.0.1"  # Fallback to localhost
    
    def get_public_connection_info(self) -> Dict[str, Union[str, int]]:
        """Get the public connection information"""
        with self._socket_lock:
            if self._socket:
                # Get the local address from the socket
                local_address = self._socket.getsockname()
                return {
                    "address": local_address.split(":")[0],
                    "port": int(local_address.split(":")[1])
                }
            else:
                return {
                    "address": "0.0.0.0",
                    "port": self.local_port
                } 