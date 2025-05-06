from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import data, auth, health, websocket, srmudp_websocket
from .utils.client import lifespan

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

    # Allow all CORS origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Erlaubt alle Ursprünge
        allow_credentials=True,
        allow_methods=["*"],  # Erlaubt alle Methoden
        allow_headers=["*"],  # Erlaubt alle Header
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
    app.include_router(srmudp_websocket.router)
    
    return app

# Create the application instance
app = create_app() 