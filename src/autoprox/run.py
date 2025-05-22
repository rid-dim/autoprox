import uvicorn
import argparse
import sys
import os

def print_server_info(host, port, srmudp_port):
    """
    Print server information.
    
    Args:
        host: Hostname or IP address
        port: HTTP port
        srmudp_port: Preferred SRMUDP bind port
    """
    server_info = [
        "="*60,
        "WEBSOCKET-SRMUDP BRIDGE SERVER STARTING",
        f"HTTP Server: {host}:{port}",
        f"Preferred SRMUDP Port: {srmudp_port} (0 = random)",
        f"API Documentation: http://{host}:{port}/v0/docs",
        f"WebSocket Bridge Endpoint: ws://{host}:{port}/v0/ws/bridge",
        f"Example: ws://{host}:{port}/v0/ws/bridge?remote_address=127.0.0.1:12345&local_port={srmudp_port}",
        "="*60
    ]
    
    # Output to stdout
    for line in server_info:
        print(line, flush=True)
    
    # Save to log file
    log_dir = os.path.expanduser("~/.autoprox")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "server_info.log")
    
    with open(log_file, "w") as f:
        for line in server_info:
            f.write(line + "\n")
    
    print(f"Server information saved to {log_file}.", flush=True)

def main() -> None:
    """
    Main function to start the WebSocket-SRMUDP Bridge server.
    Processes command line arguments and starts the server.
    """
    parser = argparse.ArgumentParser(description="Run the WebSocket-SRMUDP Bridge server")
    parser.add_argument("--host", type=str, default="localhost", help="Host to listen on")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port to listen on")
    parser.add_argument("--srmudp-port", type=int, default=0, help="Preferred SRMUDP bind port (0 for random)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    args = parser.parse_args()
    
    # Store the SRMUDP port in environment variable for access by the application
    os.environ['AUTOPROX_SRMUDP_PORT'] = str(args.srmudp_port)
    
    # Print server information
    print_server_info(args.host, args.port, args.srmudp_port)
    
    # Start the server
    uvicorn.run(
        "autoprox.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )

if __name__ == "__main__":
    main() 