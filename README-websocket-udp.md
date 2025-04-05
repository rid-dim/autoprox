# WebSocket-UDP-Proxy Erweiterung

Diese Erweiterung fügt dem Autonomi Proxy Server eine WebSocket-Schnittstelle hinzu, die als Bridge zu einer verschlüsselten UDP-Hole-Punching-Verbindung dient. Dies ermöglicht Peer-to-Peer-Kommunikation zwischen Clients, auch wenn diese hinter NATs oder Firewalls sind.

## Funktionsweise

1. Ein Client verbindet sich über WebSocket mit dem Autonomi Proxy Server
2. Der Server erstellt eine UDP-Verbindung zur angegebenen Zieladresse
3. Der Server sendet kontinuierlich verschlüsselte Heartbeat-Pakete zum UDP-Ziel
4. Die Kommunikation zwischen WebSocket-Client und UDP-Peer wird vom Server vermittelt
5. Der Client wird über den Verbindungsstatus informiert

## WebSocket-Endpunkt

```
ws://<host>:<port>/v0/ws/proxy?token=<token>&remote_host=<ip>&remote_port=<port>&encryption_key=<key>
```

### Parameter

- `token`: Ein gültiger Authentifizierungstoken (erstellt über `/v0/token`)
- `remote_host`: Die IP-Adresse des entfernten Peers (IPv4 oder IPv6)
- `remote_port`: Der UDP-Port des entfernten Peers
- `encryption_key`: Ein Schlüssel zur Verschlüsselung der UDP-Kommunikation

## Status-Nachrichten

Der WebSocket-Client erhält regelmäßig Status-Updates:

- `CONNECTED`: WebSocket-Verbindung hergestellt, aber UDP noch nicht
- `UDP_WAITING`: UDP-Verbindung im Aufbau, kein Heartbeat von der Gegenstelle
- `UDP_ESTABLISHED`: UDP-Verbindung hergestellt, Heartbeat von der Gegenstelle empfangen
- `ERROR`: Fehler in der Verbindung

## Datenformat

### Nachrichten vom Client zum Server

```json
{
  "type": "data",
  "data": "Nachrichteninhalt"
}
```

### Nachrichten vom Server zum Client

#### Daten

```json
{
  "type": "data",
  "data": "Empfangene Nachricht"
}
```

#### Status

```json
{
  "type": "status",
  "status": "UDP_ESTABLISHED",
  "message": "UDP connection established with remote peer"
}
```

#### Fehler

```json
{
  "type": "error",
  "message": "Fehlermeldung"
}
```

## IPv6-Unterstützung

Die Implementierung unterstützt sowohl IPv4 als auch IPv6:

- Erkennt automatisch den IP-Typ und wählt den richtigen Socket-Typ
- Verwendet duale Socket-Konfiguration für IPv6, falls verfügbar
- Bindet an `::` für IPv6 und `0.0.0.0` für IPv4

## Beispiel-Client

Ein Beispiel-Client ist in `examples/websocket_udp_client.py` enthalten:

```bash
python examples/websocket_udp_client.py --host localhost --port 17017 --token YOUR_TOKEN --remote-host PEER_IP --remote-port PEER_PORT --key SECRET_KEY
```

## Sicherheitsüberlegungen

- Die UDP-Kommunikation wird mit AES-256 verschlüsselt
- Der Authentifizierungstoken schützt den WebSocket-Zugang
- Nur Nachrichten von der erwarteten Gegenstelle werden akzeptiert 