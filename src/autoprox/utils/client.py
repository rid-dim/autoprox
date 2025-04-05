from autonomi_client import Client
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Store the client instance
client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI that initializes and cleans up the Autonomi client.
    """
    # Initialize the client on startup
    global client
    client = await Client.init()
    yield
    # Clean up on shutdown
    client = None

async def get_client() -> Client:
    """
    Returns the initialized Autonomi Client instance.
    """
    global client
    if client is None:
        client = await Client.init()
    return client 