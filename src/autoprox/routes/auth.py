from typing import Annotated
from fastapi import APIRouter, HTTPException, Body, Header
from pydantic import BaseModel, Field
from autonomi_client import Network, Wallet

from ..utils.crypto import (
    generate_token, 
    encrypt_private_key, 
    save_encrypted_key, 
    get_encrypted_key,
    decrypt_private_key
)

router = APIRouter(prefix="/v0", tags=["auth"])

class PrivateKeyRequest(BaseModel):
    private_key: str = Field(None, description="Private key (leave empty to generate a new one)")

class TokenResponse(BaseModel):
    token: str = Field(..., description="Access token for write operations")
    wallet_address: str = Field(..., description="Associated wallet address")

class AddressResponse(BaseModel):
    wallet_address: str = Field(..., description="Wallet address associated with the token")

class PrivateKeyResponse(BaseModel):
    private_key: str = Field(..., description="Private key associated with the token")

class TokenValidityResponse(BaseModel):
    valid: bool = Field(..., description="Whether the token is valid")
    wallet_address: str = Field(None, description="Associated wallet address if token is valid")

@router.get("/token", response_model=TokenResponse)
async def get_write_token(
    private_key: str = Header(None, alias="x-private-key", description="Optional private key to use")
):
    """
    Creates a write token for the Autonomi Network.
    
    If a private key is provided in the 'x-private-key' header, it will be used to create the token.
    Otherwise, a new private key will be generated.
    
    Returns a token that can be used to authenticate write operations
    and the associated wallet address.
    """
    try:
        # Generate a 20-character random token
        token = generate_token(20)
        
        # Use provided private key or generate a new one
        network = Network(False)  # Mainnet
        
        if not private_key:
            private_key = Wallet.random_private_key()
        wallet = Wallet.new_from_private_key(network, private_key)
        
        wallet_address = wallet.address()
        
        # Encrypt the private key using the token
        encrypted_key = encrypt_private_key(private_key, token)
        
        # Save the encrypted key
        save_encrypted_key(token, encrypted_key, wallet_address)
        
        return {
            "token": token,
            "wallet_address": wallet_address
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create write token: {str(e)}"
        )

@router.get("/token/address", response_model=AddressResponse)
async def get_wallet_address(
    token: str = Header(alias="autonomi-write-token", description="Authorization token")
):
    """
    Gets the wallet address associated with a token.
    
    Requires a valid write token in the 'autonomi-write-token' header.
    
    Returns the wallet address.
    """
    try:
        # Get the wallet address from the token
        _, wallet_address = get_encrypted_key(token)
        
        return {
            "wallet_address": wallet_address
        }
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get wallet address: {str(e)}"
        )

@router.get("/token/private-key", response_model=PrivateKeyResponse)
async def get_private_key(
    token: str = Header(alias="autonomi-write-token", description="Authorization token")
):
    """
    Gets the private key associated with a token.
    
    Requires a valid write token in the 'autonomi-write-token' header.
    
    Returns the private key.
    """
    try:
        # Get the encrypted key from the token
        encrypted_key, _ = get_encrypted_key(token)
        
        # Decrypt the private key
        private_key = decrypt_private_key(encrypted_key, token)
        
        return {
            "private_key": private_key
        }
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get private key: {str(e)}"
        )

@router.get("/token/validate", response_model=TokenValidityResponse)
async def validate_token(
    token: str = Header(alias="autonomi-write-token", description="Authorization token to validate")
):
    """
    Validates a token.
    
    Checks if the token exists and can be used to decrypt a private key.
    
    Returns whether the token is valid and the associated wallet address if it is.
    """
    try:
        # Try to get the wallet address from the token
        _, wallet_address = get_encrypted_key(token)
        
        # Try to decrypt the private key (this will verify the token is valid)
        encrypted_key, _ = get_encrypted_key(token)
        decrypt_private_key(encrypted_key, token)
        
        return {
            "valid": True,
            "wallet_address": wallet_address
        }
    except HTTPException:
        # Token is invalid
        return {
            "valid": False,
            "wallet_address": None
        }
    except Exception as e:
        # Something else went wrong
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate token: {str(e)}"
        ) 