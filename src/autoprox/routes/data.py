from typing import Annotated, AsyncGenerator
from fastapi import APIRouter, Path, HTTPException, Header, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import mimetypes
import asyncio
import base64
from autonomi_client import PaymentOption

from ..utils.client import get_client
from ..utils.crypto import get_wallet_from_token

router = APIRouter(prefix="/v0/data", tags=["data"])

class DataPutRequest(BaseModel):
    data: str = Field(..., description="Base64 encoded data to upload")

class DataPutResponse(BaseModel):
    address: str = Field(..., description="Data address where the content was stored")
    price: float = Field(..., description="Price paid for storage in tokens")

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

@router.get("/get/public/{data_address}/{filename}")
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
        
        # Try to determine the content type from the filename
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

@router.put("/put/public", response_model=DataPutResponse)
async def put_public_data(
    request: DataPutRequest = Body(...),
    token: str = Header(alias="autonomi-write-token", description="Authorization token for write operations")
):
    """
    Uploads data to the Autonomi Network.
    
    Requires a valid write token in the 'autonomi-write-token' header.
    
    Returns the data address and price paid for storage.
    """
    try:
        # Get wallet from token
        wallet = get_wallet_from_token(token)
        
        # Create a payment option
        payment_option = PaymentOption.wallet(wallet)
        
        # Decode the base64 data
        try:
            binary_data = base64.b64decode(request.data)
        except:
            raise HTTPException(
                status_code=400,
                detail="Invalid base64 encoded data"
            )
        
        # Upload the data
        c = await get_client()
        price, address = await c.data_put_public(binary_data, payment_option)
        
        return {
            "address": address,
            "price": price
        }
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload data: {str(e)}"
        ) 