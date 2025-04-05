import uvicorn
import argparse

def main() -> None:
    """Run the server."""
    parser = argparse.ArgumentParser(description="Run the Autonomi Network Proxy server")
    parser.add_argument("--host", type=str, default="localhost", help="Host to listen on")
    parser.add_argument("--port", type=int, default=17017, help="Port to listen on")
    
    args = parser.parse_args()
    
    uvicorn.run(
        "autoprox.main:app",
        host=args.host,
        port=args.port,
        reload=True
    )

if __name__ == "__main__":
    main() 