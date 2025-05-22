from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import health, websocket, network

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="WebSocket-SRMUDP Bridge",
        description="A bridge between WebSocket and SRMUDP communication with public IP discovery",
        version="0.2.0",
        docs_url="/v0/docs",
        openapi_url="/v0/openapi.json"
    )

    # Allow all CORS origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    @app.get("/bridge-id")
    async def get_bridge_id() -> str:
        """
        Returns the ID of this bridge server instance.
        """
        return "websocket-srmudp-bridge-v1"

    # Include routers
    app.include_router(health.router)
    app.include_router(websocket.router)
    app.include_router(network.router)
    
    return app

# Create the application instance
app = create_app() 