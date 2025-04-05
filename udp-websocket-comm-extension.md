# WebSocket-UDP-Kommunikation Erweiterungsplan

## Überblick
Diese Erweiterung fügt dem FastAPI-Server eine WebSocket-Schnittstelle hinzu, die als Bridge zu einer verschlüsselten UDP-Hole-Punching-Verbindung dient. Dies ermöglicht Peer-to-Peer-Kommunikation zwischen Clients hinter NATs/Firewalls.

## Hauptkomponenten

1. **WebSocket-Endpunkt**: Ein neuer Endpunkt im FastAPI-Server für WebSocket-Verbindungen
2. **UDP-Hole-Punching-Mechanismus**: Implementierung des NAT-Traversal-Verfahrens
3. **Verschlüsselung**: AES-Verschlüsselung für die UDP-Kommunikation
4. **Status-Monitoring und Heartbeating**: Überwachung der Verbindungen und Benachrichtigung der Clients

## Detaillierte Implementierung

### 1. Neue Dateien erstellen
- `src/autoprox/routes/websocket.py`: WebSocket-Route und Handler
- `src/autoprox/utils/udp_manager.py`: UDP-Verbindungsverwaltung und Hole-Punching
- `src/autoprox/utils/encryption.py`: Erweiterung der bestehenden Krypto-Funktionen für UDP-Daten

### 2. WebSocket-Endpunkt
- Implementierung eines `/v0/ws/proxy` Endpunkts
- Authentifizierung über Token (ähnlich wie bei bestehenden Auth-Routen)
- Parameter für Remote-Peer-Adresse, Port und Verschlüsselungsschlüssel

### 3. Verbindungsablauf
1. Client stellt WebSocket-Verbindung her mit Ziel-IP, Port und Schlüssel
2. Server initiiert UDP-Hole-Punching zur Zieladresse
3. Server sendet kontinuierlich Heartbeat-Pakete zum UDP-Ziel
4. WebSocket-Client wird über den Verbindungsstatus informiert:
   - "CONNECTED": WebSocket-Verbindung aufgebaut
   - "UDP_WAITING": UDP-Verbindung wird aufgebaut, kein Heartbeat von Gegenstelle
   - "UDP_ESTABLISHED": UDP-Verbindung aufgebaut, Heartbeat von Gegenstelle empfangen

### 4. Datenfluss
1. Daten vom WebSocket-Client → Server → Verschlüsseln → UDP-Kanal → Remote-Peer
2. Daten vom Remote-Peer → UDP-Kanal → Server → Entschlüsseln → WebSocket-Client

### 5. IPv6-Betrachtungen
- IPv6 erleichtert in der Theorie Hole-Punching, da globale Adressen häufiger direkt erreichbar sind
- Dennoch müssen wir dual-stack Unterstützung implementieren (IPv4 und IPv6)
- Adressierung: Bei IPv6 vollständige Adressierung verwenden (keine NAT-Übersetzung)
- Firewall-Regeln können trotzdem Probleme verursachen
- Fallback-Mechanismus implementieren, wenn IPv6 nicht funktioniert

### 6. Erweiterungen an der bestehenden Codebasis
- Hinzufügen der neuen Route in `src/autoprox/main.py`
- Erweiterung der Krypto-Utilities für die UDP-Verschlüsselung
- Implementierung einer asynchronen UDP-Socket-Verwaltung

### 7. Sicherheitsüberlegungen
- Authentifizierung über Token wie in bestehenden Routen
- Verschlüsselung der UDP-Daten mit AES
- Rate-Limiting für Verbindungen
- Validierung der Eingabeparameter

## Nächste Schritte
1. Erstellen der grundlegenden WebSocket-Route
2. Implementieren des UDP-Managers
3. Integration der Verschlüsselung
4. Implementieren des Heartbeat-Mechanismus
5. Testen mit verschiedenen Netzwerkkonfigurationen
6. Dokumentation der API und Verwendung 