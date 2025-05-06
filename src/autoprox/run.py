import uvicorn
import argparse
import sys
import os

def print_server_info(host, port, udp_port):
    """
    Gibt Serverinformationen aus und protokolliert sie.
    
    Args:
        host: Hostname oder IP-Adresse
        port: HTTP-Port
        udp_port: UDP-Kommunikationsport
    """
    server_info = [
        "="*60,
        "AUTONOMI PROXY SERVER WIRD GESTARTET",
        f"HTTP Server: {host}:{port}",
        f"UDP Kommunikationsport: {udp_port}",
        f"API Dokumentation: http://{host}:{port}/v0/docs",
        f"WebSocket Endpunkt (traditionell): ws://{host}:{port}/v0/ws/proxy",
        f"WebSocket Endpunkt (SRMUDP): ws://{host}:{port}/v0/ws/srmudp/proxy",
        "="*60
    ]
    
    # Ausgabe nur auf stdout
    for line in server_info:
        print(line, flush=True)
    
    # Speichere in eine Logdatei
    log_dir = os.path.expanduser("~/.autoprox")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "server_info.log")
    
    with open(log_file, "w") as f:
        for line in server_info:
            f.write(line + "\n")
    
    print(f"Server-Informationen wurden in {log_file} gespeichert.", flush=True)

def main() -> None:
    """
    Hauptfunktion zum Starten des Autonomi Proxy Servers.
    Verarbeitet Kommandozeilenargumente und startet den Server.
    """
    parser = argparse.ArgumentParser(description="Run the Autonomi Network Proxy server")
    parser.add_argument("--host", type=str, default="localhost", help="Host to listen on")
    parser.add_argument("--port", type=int, default=17017, help="HTTP-Port to listen on")
    parser.add_argument("--udp-port", type=int, default=17171, help="UDP communication port")
    
    args = parser.parse_args()
    
    # Speichere den UDP-Port in einer Umgebungsvariable
    os.environ['AUTOPROX_UDP_PORT'] = str(args.udp_port)
    
    # Serverinformationen ausgeben
    print_server_info(args.host, args.port, args.udp_port)
    
    # Starte den Server
    uvicorn.run(
        "autoprox.main:app",
        host=args.host,
        port=args.port,
        reload=True
    )

if __name__ == "__main__":
    main() 