# WebSocket-SRMUDP-Proxy

Diese Implementierung fügt dem Autonomi Proxy Server eine WebSocket-Schnittstelle hinzu, die als Bridge zu einer sicheren und zuverlässigen UDP-Verbindung dient. Dies ermöglicht Peer-to-Peer-Kommunikation zwischen Clients, auch wenn diese hinter NATs oder Firewalls sind, mit garantierter Zustellung von Nachrichten.

## Funktionsweise

1. Ein Client verbindet sich über WebSocket mit dem Autonomi Proxy Server
2. Der Server erstellt eine SRMUDP-Verbindung zur angegebenen Zieladresse
3. Die sichere und zuverlässige UDP-Verbindung wird durch die SRMUDP-Bibliothek verwaltet
4. Die Kommunikation zwischen WebSocket-Client und UDP-Peer wird vom Server vermittelt
5. Der Client wird über den Verbindungsstatus informiert
6. Bei Verbindungsabbrüchen werden automatisch Wiederverbindungsversuche durchgeführt

## WebSocket-Endpunkt

```
ws://<host>:<port>/v0/ws/proxy?remote_host=<ip>&remote_port=<port>&encryption_key=<key>
```

### Parameter

- `remote_host`: Die IP-Adresse des entfernten Peers (IPv4 oder IPv6)
- `remote_port`: Der UDP-Port des entfernten Peers
- `encryption_key`: Ein Schlüssel zur Verschlüsselung der SRMUDP-Kommunikation
- `client_id`: (Optional) Eine eindeutige Client-ID für mehrere Verbindungen

## Status-Nachrichten

Der WebSocket-Client erhält regelmäßig Status-Updates:

- `CONNECTED`: WebSocket-Verbindung hergestellt, aber UDP noch nicht
- `UDP_WAITING`: UDP-Verbindung im Aufbau
- `UDP_ESTABLISHED`: UDP-Verbindung hergestellt
- `RECONNECTING`: Verbindung verloren, Wiederverbindungsversuch
- `ERROR`: Fehler in der Verbindung

## Datenformat

### Nachrichten vom Client zum Server

#### Text-Daten
```json
{
  "type": "data",
  "format": "text",
  "data": "Nachrichteninhalt"
}
```

#### Binär-Daten
```json
{
  "type": "data",
  "format": "binary",
  "data": "Base64-kodierte Daten"
}
```

### Nachrichten vom Server zum Client

#### Daten (Text)
```json
{
  "type": "data",
  "format": "text",
  "data": "Empfangene Nachricht"
}
```

#### Daten (Binär)
```json
{
  "type": "data",
  "format": "binary",
  "data": "Base64-kodierte Daten"
}
```

#### Status
```json
{
  "type": "status",
  "status": "UDP_ESTABLISHED",
  "connection_id": "Verbindungs-ID",
  "message": "UDP connection established with remote peer"
}
```

#### Fehler
```json
{
  "type": "error",
  "connection_id": "Verbindungs-ID",
  "message": "Fehlermeldung"
}
```

## Vorteile gegenüber regulärem UDP

- **Zuverlässige Zustellung**: Garantiert, dass Pakete ankommen oder ein Fehler gemeldet wird
- **Sichere Verschlüsselung**: Verschlüsselung durch die SRMUDP-Bibliothek
- **Automatische Wiederverbindung**: Bei Verbindungsabbrüchen werden automatisch Wiederverbindungsversuche durchgeführt
- **NAT Traversal**: Hole-Punching-Technologie für Verbindungen durch NATs und Firewalls

## Beispiel-Client

Ein Beispiel-Client ist in `src/autoprox/examples/srmudp_websocket_example.py` enthalten:

```bash
python -m src.autoprox.examples.srmudp_websocket_example --ws-url "ws://localhost:8000/v0/ws/proxy" --remote-host PEER_IP --remote-port PEER_PORT --encryption-key SECRET_KEY
```

Python-Bibliotheksverwendung:

```python
client = SRMUDPWebSocketClient(
    "ws://localhost:8000/v0/ws/proxy",
    "remote_host_ip",
    remote_port,
    "encryption_key"
)
await client.connect()
await client.send_text("Hello, world!")
await client.send_binary(b"Binary data")
```

## Sicherheitsüberlegungen

- Die UDP-Kommunikation wird durch die SRMUDP-Bibliothek verschlüsselt
- Verbindungen werden auf Grundlage des Verschlüsselungsschlüssels etabliert
- Nur Nachrichten von der erwarteten Gegenstelle werden akzeptiert 