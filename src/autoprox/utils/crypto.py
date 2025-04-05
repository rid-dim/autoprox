import os
import json
import secrets
import string
import base64
import hashlib
from typing import Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from fastapi import HTTPException
from autonomi_client import Wallet, Network

# File to store encrypted private keys
KEYS_FILE = "autonomi_keys.json"

# Ensure keys directory exists
os.makedirs(os.path.dirname(os.path.abspath(KEYS_FILE)) if os.path.dirname(KEYS_FILE) else ".", exist_ok=True)

def generate_token(length: int = 20) -> str:
    """
    Generate a random token of specified length.
    
    Args:
        length: Length of the token
        
    Returns:
        Random token string
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def hash_token(token: str) -> str:
    """
    Create a SHA-256 hash of the token to use as the storage key.
    
    Args:
        token: The original token
        
    Returns:
        Hexadecimal digest of the hashed token
    """
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def encrypt_private_key(private_key: str, token: str) -> str:
    """
    Encrypt a private key using AES with the token as the key.
    
    Args:
        private_key: The private key to encrypt
        token: The token to use as encryption key
        
    Returns:
        Base64 encoded encrypted private key
    """
    # Use the token as the key (pad or truncate to 32 bytes for AES-256)
    key = token.encode('utf-8').ljust(32, b'\0')[:32]
    iv = os.urandom(16)  # 16 bytes for AES
    
    # Pad the data
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(private_key.encode('utf-8')) + padder.finalize()
    
    # Encrypt the data
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    
    # Combine IV and encrypted data and encode as base64
    return base64.b64encode(iv + encrypted_data).decode('utf-8')

def decrypt_private_key(encrypted_data: str, token: str) -> str:
    """
    Decrypt a private key using AES with the token as the key.
    
    Args:
        encrypted_data: Base64 encoded encrypted private key
        token: The token to use as decryption key
        
    Returns:
        Decrypted private key
    """
    try:
        # Use the token as the key (pad or truncate to 32 bytes for AES-256)
        key = token.encode('utf-8').ljust(32, b'\0')[:32]
        
        # Decode base64
        data = base64.b64decode(encrypted_data)
        
        # Extract IV and encrypted data
        iv = data[:16]
        encrypted_data = data[16:]
        
        # Decrypt the data
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(encrypted_data) + decryptor.finalize()
        
        # Unpad the data
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        unpadded_data = unpadder.update(padded_data) + unpadder.finalize()
        
        return unpadded_data.decode('utf-8')
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Failed to decrypt private key: {str(e)}"
        )

def save_encrypted_key(token: str, encrypted_key: str, wallet_address: str):
    """
    Save an encrypted private key with its token and wallet address.
    
    Args:
        token: Token used to encrypt the key
        encrypted_key: Encrypted private key
        wallet_address: Associated wallet address
    """
    data = {}
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r') as f:
                data = json.load(f)
        except:
            data = {}
    
    # Use token hash instead of raw token as the key
    token_hash = hash_token(token)
    
    # Store token_hash -> encrypted key mapping
    data[token_hash] = {
        "encrypted_key": encrypted_key,
        "wallet_address": wallet_address
    }
    
    with open(KEYS_FILE, 'w') as f:
        json.dump(data, f)

def get_encrypted_key(token: str) -> Tuple[str, str]:
    """
    Get an encrypted private key by its token.
    
    Args:
        token: Token associated with the encrypted key
        
    Returns:
        Tuple of (encrypted_key, wallet_address)
    """
    if not os.path.exists(KEYS_FILE):
        raise HTTPException(
            status_code=404,
            detail="No keys have been registered"
        )
    
    try:
        with open(KEYS_FILE, 'r') as f:
            data = json.load(f)
    except:
        raise HTTPException(
            status_code=500,
            detail="Failed to read keys file"
        )
    
    # Use token hash instead of raw token as the key
    token_hash = hash_token(token)
    
    if token_hash not in data:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )
    
    return data[token_hash]["encrypted_key"], data[token_hash]["wallet_address"]

def get_wallet_from_token(token: str) -> Wallet:
    """
    Get a wallet from a token.
    
    Args:
        token: Token associated with the encrypted key
        
    Returns:
        Wallet object
    """
    encrypted_key, _ = get_encrypted_key(token)
    private_key = decrypt_private_key(encrypted_key, token)
    
    network = Network(False)  # Mainnet
    return Wallet.new_from_private_key(network, private_key) 