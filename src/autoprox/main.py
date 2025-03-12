from typing import Annotated
from fastapi import FastAPI, Path, HTTPException, Depends, Response
from autonomi_client import Client
from contextlib import asynccontextmanager
import mimetypes

# Store the client instance
client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initializes the Autonomi client during app startup and keeps it available
    throughout the application lifecycle.
    """
    # Initialize client on startup
    global client
    client = await Client.init()
    
    yield
    
    # Clean up resources if needed
    # client.close() # Uncomment if client needs to be closed

# Create FastAPI app with metadata for OpenAPI
app = FastAPI(
    title="Autonomi Network Proxy",
    description="A simple HTTP proxy for the Autonomi Network",
    version="0.1.0",
    docs_url="/v0/docs",
    openapi_url="/v0/openapi.json",
    lifespan=lifespan,
)

async def get_client() -> Client:
    """
    Returns the initialized Autonomi client.
    """
    if client is None:
        raise RuntimeError("Client not initialized. Server may still be starting.")
    return client

@app.get("/v0/data/get/public/{data_address}/{filename}")
async def get_public_data(
    data_address: Annotated[
        str,
        Path(
            description="The immutable data address to fetch",
            min_length=64,
            max_length=64,
            pattern="^[a-fA-F0-9]+$"
        )
    ],
    filename: Annotated[
        str,
        Path(
            description="The filename to serve the data as"
        )
    ]
):
    """
    Fetches public data from the Autonomi Network.
    The filename parameter is used to serve the data with the correct content type.
    """
    try:
        c = await get_client()
        data = await c.data_get_public(data_address)
        
        # Detect the content type based on the filename
        content_type, _ = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = "application/octet-stream"
            
        # Return the binary data with the correct content type
        return Response(content=data, media_type=content_type)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Failed to fetch data: {str(e)}"
        ) 