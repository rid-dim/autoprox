from typing import Annotated
from fastapi import FastAPI, Path, HTTPException, Response
from fastapi.responses import StreamingResponse
from autonomi_client import Client
from contextlib import asynccontextmanager
import mimetypes
import asyncio
from typing import AsyncGenerator

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

async def stream_data(data: bytes, chunk_size: int = 8192) -> AsyncGenerator[bytes, None]:
    """
    Stream the data in chunks to avoid memory issues with large files.
    
    Args:
        data: The binary data to stream
        chunk_size: Size of each chunk in bytes
    """
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]
        # Small delay to prevent overwhelming the connection
        await asyncio.sleep(0.001)

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
    ],
    timeout: Annotated[
        int,
        Path(
            description="Timeout in seconds for the data fetch operation",
            ge=1,
            le=300,  # Max 5 minutes
        )
    ] = 60,  # Default 1 minute
):
    """
    Fetches public data from the Autonomi Network.
    The filename parameter is used to serve the data with the correct content type.
    Supports streaming of large files and configurable timeout.
    """
    try:
        c = await get_client()
        
        # Create a timeout context
        async with asyncio.timeout(timeout):
            data = await c.data_get_public(data_address)
        
        # Detect the content type based on the filename
        content_type, _ = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = "application/octet-stream"
            
        # Prepare response headers
        headers = {
            "Cache-Control": "public, max-age=31536000"  # Cache for 1 year as it's immutable data
        }
        
        # Only set Content-Disposition to attachment for non-viewable files
        if not any(content_type.startswith(prefix) for prefix in ['image/', 'video/', 'audio/', 'text/', 'application/pdf']):
            headers["Content-Disposition"] = f"attachment; filename={filename}"
            
        # Return a streaming response
        return StreamingResponse(
            stream_data(data),
            media_type=content_type,
            headers=headers
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,  # Gateway Timeout
            detail=f"Data fetch operation timed out after {timeout} seconds"
        )
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Failed to fetch data: {str(e)}"
        ) 