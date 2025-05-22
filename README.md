# WebSocket-SRMUDP Bridge

A simple bridge server that connects WebSocket clients to SRMUDP (Secure Reliable Message UDP) peers. This allows web applications to communicate with SRMUDP-based systems through a WebSocket interface.

## Features

- **WebSocket to SRMUDP Bridge**: Direct bidirectional communication bridge
- **Simple Hook System**: Incoming SRMUDP messages are forwarded directly to WebSocket via hook functions
- **Multiple Formats**: Supports both text and binary message formats
- **Heartbeat Filtering**: Automatically filters out common heartbeat/ping messages
- **Public IP Discovery**: Built-in STUN client for discovering external IP addresses
- **NAT Traversal Support**: Essential information for SRMUDP hole-punching
- **Easy Integration**: Simple WebSocket API that any web application can use

## Installation

### Using Poetry (recommended)

```bash
poetry install
```

### Using pip

```bash
pip install -e .
```

## Usage

### Starting the Server

```bash
# Start with default settings (localhost:8000)
autoprox

# Start with custom host and port
autoprox --host 0.0.0.0 --port 8080

# Start with preferred SRMUDP port
autoprox --srmudp-port 12345

# Start with all custom settings
autoprox --host 0.0.0.0 --port 8080 --srmudp-port 12345

# Start with auto-reload for development
autoprox --reload
```

#### Command Line Options

- `--host HOST`: Host to listen on (default: localhost)
- `--port PORT`: HTTP port for the web server (default: 8000)  
- `--srmudp-port PORT`: Preferred SRMUDP bind port (default: 0 for random)
- `--reload`: Enable auto-reload for development

### WebSocket API

Connect to the WebSocket bridge endpoint:

```
ws://localhost:8000/v0/ws/bridge?remote_address=TARGET_HOST:TARGET_PORT&local_port=0
```

#### Parameters

- `remote_address`: Target SRMUDP address in format `host:port` (required)
- `local_port`: Local port to bind to (optional)
  - `None`: Use server preference (set via `--srmudp-port`)
  - `0`: Random port
  - `>0`: Specific port number

#### Message Format

**Sending to SRMUDP:**
```json
{
    "type": "message",
    "format": "text",  // or "binary"
    "data": "Your message here"
}
```

**Receiving from SRMUDP:**
```json
{
    "type": "message",
    "format": "text",  // or "binary"  
    "data": "Message from SRMUDP peer"
}
```

**Status Messages:**
```json
{
    "type": "status",
    "status": "connected",
    "local_address": "127.0.0.1:12345",
    "peer_address": "127.0.0.1:54321"
}
```

### Example

See `examples/websocket_bridge_example.py` for a complete working example.

```python
import asyncio
import json
import websockets

async def bridge_client():
    url = "ws://localhost:8000/v0/ws/bridge?remote_address=127.0.0.1:12345"
    
    async with websockets.connect(url) as websocket:
        # Send a message
        await websocket.send(json.dumps({
            "type": "message",
            "format": "text",
            "data": "Hello SRMUDP!"
        }))
        
        # Receive response
        response = await websocket.recv()
        data = json.loads(response)
        print(f"Received: {data}")

asyncio.run(bridge_client())
```

## API Documentation

When the server is running, visit:
- API Docs: http://localhost:8000/v0/docs
- Bridge Info: http://localhost:8000/v0/ws/info
- Active Bridges: http://localhost:8000/v0/ws/bridges
- Server Config: http://localhost:8000/v0/ws/server-config

### Network Discovery Endpoints

- **Public IP**: `GET /v0/network/public-ip` - Discover your public IP via STUN
- **Public Address**: `GET /v0/network/public-address` - Discover your public IP and port via STUN  
- **SRMUDP Address**: `GET /v0/network/srmudp-address` - Discover public address using actual SRMUDP socket
- **SRMUDP Test**: `GET /v0/network/srmudp-address-test?test_port=12345` - Test STUN with specific port
- **Active Ports**: `GET /v0/network/active-ports` - Show which ports are in use by WebSocket bridges
- **STUN Servers**: `GET /v0/network/stun-servers` - List available STUN servers

The **SRMUDP Address** endpoint is the most accurate for hole-punching as it uses the actual SRMUDP UDP socket.

**Important**: The SRMUDP Address and Test endpoints will return a `409 Conflict` error if there's already an active WebSocket bridge using the same port, preventing socket conflicts.

Example:
```bash
curl http://localhost:8000/v0/network/public-ip
# Returns: {"public_ip": "78.51.80.235", "discovery_method": "STUN", "success": true}

curl http://localhost:8000/v0/network/srmudp-address  
# Returns: {"public_ip": "78.51.80.235", "public_port": 12345, "local_port": 12345, "discovery_method": "STUN via SRMUDP socket", "success": true}

curl http://localhost:8000/v0/network/active-ports
# Returns information about active WebSocket bridges and port conflicts
```

### WebSocket Commands

The WebSocket API supports several message types:

**Send Message:**
```json
{
    "type": "message",
    "format": "text",  // or "binary"
    "data": "Your message here"
}
```

**Discover Public Address (on active connection):**
```json
{
    "type": "discover_public_address"
}
```

**Responses:**
```json
{
    "type": "public_address_discovered",
    "public_ip": "78.51.80.235",
    "public_port": 12345,
    "local_address": ["127.0.0.1", 12345],
    "peer_address": ["127.0.0.1", 54321],
    "discovery_method": "STUN via active SRMUDP connection"
}
```

## Architecture

The bridge works by:

1. **WebSocket Connection**: Client connects to `/v0/ws/bridge` endpoint
2. **SRMUDP Connection**: Server establishes SRMUDP connection to target address
3. **Hook Functions**: SRMUDP incoming messages are handled by a hook function that directly forwards to WebSocket
4. **Bidirectional Forwarding**: All WebSocket messages (except heartbeats) are forwarded to SRMUDP peer

## Dependencies

- FastAPI: Web framework and WebSocket support
- SRMUDP: Secure reliable UDP communication
- Uvicorn: ASGI server
- Pydantic: Data validation

## Development

### Running Tests

```bash
# Install development dependencies
poetry install --with dev

# Run the example
python examples/websocket_bridge_example.py
```

### Code Style

```bash
# Format code
black src/

# Lint code  
ruff src/

# Type checking
mypy src/
```

## License

MIT License. See LICENSE file for details.
