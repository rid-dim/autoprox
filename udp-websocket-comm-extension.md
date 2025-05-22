# WebSocket-SRMUDP-Kommunikation

## Überblick
Diese Implementierung fügt dem FastAPI-Server eine WebSocket-Schnittstelle hinzu, die als Bridge zu einer sicheren und zuverlässigen UDP-Verbindung (SRMUDP) dient. Dies ermöglicht Peer-to-Peer-Kommunikation zwischen Clients hinter NATs/Firewalls mit zuverlässiger Paketauslieferung.

## Hauptkomponenten

1. **WebSocket-Endpunkt**: Ein Endpunkt im FastAPI-Server für WebSocket-Verbindungen
2. **SRMUDP-Bibliothek**: Verwendung der SRMUDP-Bibliothek für:
   - UDP-Hole-Punching-Mechanismus: NAT-Traversal-Verfahren
   - Verschlüsselung: Sichere Kommunikation
   - Zuverlässige Paketauslieferung: Sicherstellen, dass Pakete ankommen
   - Automatische Wiederverbindungsversuche: Robustheit gegen Verbindungsabbrüche
3. **Status-Monitoring**: Überwachung der Verbindungen und Benachrichtigung der Clients

## Implementierung

### 1. Dateien
- `src/autoprox/routes/websocket.py`: WebSocket-Route und Handler
- `src/autoprox/utils/srmudp_manager.py`: Verwaltung der SRMUDP-Verbindungen
- `src/autoprox/examples/srmudp_websocket_example.py`: Beispielimplementierung eines Clients

### 2. WebSocket-Endpunkt
- `/v0/ws/proxy` Endpunkt
- Parameter für Remote-Peer-Adresse, Port und Verschlüsselungsschlüssel

### 3. Verbindungsablauf
1. Client stellt WebSocket-Verbindung her mit Ziel-IP, Port und Schlüssel
2. Server initiiert SRMUDP-Verbindung zur Zieladresse
3. WebSocket-Client wird über den Verbindungsstatus informiert:
   - "CONNECTED": WebSocket-Verbindung aufgebaut
   - "UDP_WAITING": UDP-Verbindung wird aufgebaut
   - "UDP_ESTABLISHED": UDP-Verbindung aufgebaut
   - "RECONNECTING": Wiederverbindungsversuch nach Verbindungsabbruch

### 4. Datenfluss
1. Daten vom WebSocket-Client → Server → SRMUDP → Remote-Peer
2. Daten vom Remote-Peer → SRMUDP → Server → WebSocket-Client

### 5. Verbindungsstabilität
- Automatische Wiederverbindungsversuche
- Timeout-Handling
- Zuverlässige Paketauslieferung durch SRMUDP

### 6. Funktionen der SRMUDP-Bibliothek
- NAT Traversal mit UDP Hole Punching
- Asymmetrische Schlüssel für die sichere Verbindungsaufnahme
- Zuverlässige Paketauslieferung
- Paketreihenfolge-Sicherstellung
- Verschlüsselung aller Daten

## Verwendung
Ein Beispiel-Client ist in `src/autoprox/examples/srmudp_websocket_example.py` implementiert. Dieser zeigt, wie man eine Verbindung zum WebSocket-Endpunkt herstellt und Daten sendet/empfängt.

### Client-Verwendungsbeispiel
```python
client = SRMUDPWebSocketClient(
    "ws://localhost:8000/v0/ws/proxy",
    "remote_host_ip",
    remote_port,
    "encryption_key"
)
await client.connect()
await client.send_text("Hello, world!")
```

## Sicherheitsüberlegungen
- Verschlüsselung der UDP-Daten durch SRMUDP
- Validierung der Eingabeparameter
- Die Verbindung ist nur so sicher wie der verwendete Verschlüsselungsschlüssel 