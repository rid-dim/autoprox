import os
from typing import Union, Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

def derive_key(encryption_key: Union[str, bytes], length: int = 32) -> bytes:
    """
    Derives a key of specified length from the provided encryption key.
    
    Args:
        encryption_key: The input key material (string or bytes)
        length: The desired key length in bytes (default: 32 for AES-256)
    
    Returns:
        A bytes object of the specified length
    """
    if isinstance(encryption_key, str):
        key_bytes = encryption_key.encode('utf-8')
    else:
        key_bytes = encryption_key
    
    # If the key is already the right length, use it directly
    if len(key_bytes) == length:
        return key_bytes
    
    # If the key is too long, truncate it
    if len(key_bytes) > length:
        return key_bytes[:length]
    
    # If the key is too short, pad it with zeros
    return key_bytes.ljust(length, b'\0')

def encrypt_data(key: Union[str, bytes], data: Union[str, bytes]) -> bytes:
    """
    Encrypts data using AES in CBC mode with PKCS7 padding.
    
    Args:
        key: The encryption key (string or bytes)
        data: The data to encrypt (string or bytes)
    
    Returns:
        The encrypted data with IV prefixed
    """
    # Ensure we have bytes
    if isinstance(key, str):
        key = key.encode('utf-8')
    if isinstance(data, str):
        data = data.encode('utf-8')
    
    # Derive a 32-byte key for AES-256
    key = derive_key(key, 32)
    
    # Generate a random 16-byte IV
    iv = os.urandom(16)
    
    # Create a cipher object
    cipher = Cipher(
        algorithms.AES(key),
        modes.CBC(iv),
        backend=default_backend()
    )
    
    # Pad the data to a multiple of the block size (16 bytes for AES)
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(data) + padder.finalize()
    
    # Encrypt the padded data
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    
    # Return the IV + ciphertext
    return iv + ciphertext

def decrypt_data(key: Union[str, bytes], ciphertext: bytes) -> bytes:
    """
    Decrypts data encrypted with AES in CBC mode and PKCS7 padding.
    
    Args:
        key: The encryption key (string or bytes)
        ciphertext: The encrypted data with IV prefixed
    
    Returns:
        The decrypted data
    """
    # Ensure we have bytes for the key
    if isinstance(key, str):
        key = key.encode('utf-8')
    
    # Derive a 32-byte key for AES-256
    key = derive_key(key, 32)
    
    # Extract the IV from the beginning of the ciphertext
    iv = ciphertext[:16]
    actual_ciphertext = ciphertext[16:]
    
    # Create a cipher object
    cipher = Cipher(
        algorithms.AES(key),
        modes.CBC(iv),
        backend=default_backend()
    )
    
    # Decrypt the ciphertext
    decryptor = cipher.decryptor()
    padded_plaintext = decryptor.update(actual_ciphertext) + decryptor.finalize()
    
    # Unpad the decrypted data
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
    
    return plaintext

# Make sure existing functions are available for import
# These should already be defined elsewhere in the codebase
__all__ = [
    'encrypt_data',
    'decrypt_data',
    'derive_key',
    # Include any existing crypto functions that should be available
] 