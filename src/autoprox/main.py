from fastapi import FastAPI
from .routes import data, auth, health, websocket
from .utils.client import lifespan
import uvicorn
import argparse
import sys
from typing import Optional, List

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Autonomi Network Proxy",
        description="A simple HTTP proxy for the Autonomi Network",
        version="0.1.0",
        docs_url="/v0/docs",
        openapi_url="/v0/openapi.json",
        lifespan=lifespan
    )

    @app.get("/ant-proxy-id")
    async def get_proxy_id() -> str:
        """
        Returns the ID of this proxy server instance.
        This route is globally available (not under version prefixes).
        """
        return "autoprox-0"

    # Include all routers
    app.include_router(data.router)
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(websocket.router)
    
    return app

# Create the application instance
app = create_app()

def main(args: Optional[List[str]] = None) -> int:
    """
    Run the server.
    
    Args:
        args: Command line arguments (if None, sys.argv[1:] will be used)
    
    Returns:
        Exit code (0 for success)
    """
    parser = argparse.ArgumentParser(description="Run the Autonomi Network Proxy server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to listen on")
    parser.add_argument("--port", type=int, default=17017, help="Port to listen on")
    
    parsed_args = parser.parse_args(args)
    
    print(f"Starting Autonomi Network Proxy on {parsed_args.host}:{parsed_args.port}")
    print(f"API documentation will be available at: http://{parsed_args.host}:{parsed_args.port}/v0/docs")
    print(f"WebSocket endpoint will be available at: ws://{parsed_args.host}:{parsed_args.port}/v0/ws/proxy")
    
    uvicorn.run(
        "autoprox.main:app",
        host=parsed_args.host,
        port=parsed_args.port,
        reload=True
    )
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 