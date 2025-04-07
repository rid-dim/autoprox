import asyncio
import aiohttp
import logging
import os

logger = logging.getLogger(__name__)

async def get_public_ip() -> str:
    """
    Ermittelt die öffentliche IP-Adresse des Servers asynchron.
    
    Returns:
        Öffentliche IP-Adresse als String
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.ipify.org') as response:
                return await response.text()
    except Exception as e:
        logger.error(f"Fehler bei der Ermittlung der öffentlichen IP: {e}")
        return "unknown"

async def get_public_connection_info(local_port: int = None) -> dict:
    """
    Gibt Informationen zur UDP-Verbindung asynchron zurück.
    
    Args:
        local_port: Der lokale Port, auf dem der UDP-Manager lauscht
    
    Returns:
        Dictionary mit öffentlicher IP und Port
    """
    try:
        # Verwende Umgebungsvariable, wenn kein Port übergeben wurde
        if local_port is None:
            local_port = int(os.environ.get('AUTOPROX_UDP_PORT', "unknown"))
        
        public_ip = await get_public_ip()
        return {
            "public_ip": public_ip,
            "port": local_port
        }
    except Exception as e:
        logger.error(f"Fehler bei der Ermittlung der Verbindungsinformationen: {e}")
        return {
            "public_ip": "unknown",
            "port": local_port or int(os.environ.get('AUTOPROX_UDP_PORT', "unknown"))
        } 