# Messungen beitragen (Deutsch)

Der Steem-API-Monitor unter <https://api.steemapps.com/> misst alle
öffentlichen Nodes von einer einzigen VM in Deutschland. Das reicht, um
Total-Ausfälle zu erkennen, aber nicht, um zu sehen, ob ein Node für
Nutzer in den USA oder Asien schnell ist. Community-Beiträge füllen diese
Lücke: ein kleines Skript auf einem freiwilligen Server liefert die
Perspektive aus seiner Region.

Die englische Fassung dieses Dokuments liegt unter [PARTICIPATE.md](PARTICIPATE.md).

## Für wen das gedacht ist

Alle Betreiber mit einem kleinen VPS und ausgehendem HTTPS — typischerweise
Witnesses, dApp-Betreiber, Node-Runner. Besonders gesucht sind Beiträge
aus:

- **Nordamerika** (US East / US West)
- **Asien** (Singapur, Tokyo, Seoul)
- **Süd-Amerika**
- **Afrika**
- **Australien / Ozeanien**

Du musst selbst keinen Steem-Node betreiben. Das Skript macht nur
ausgehende JSON-RPC-Calls zu den öffentlichen Nodes.

## Ablauf

1. **API-Key holen.**
   Öffne <https://api.steemapps.com/join.html> und gib ein:
   - Deinen Steem-Account-Namen
   - Ein kurzes Server-Label (z. B. `Hetzner FSN1`)
   - Die geografische Region des Servers

   Das Formular prüft, ob der Account auf der Steem-Chain existiert,
   und stellt direkt einen API-Key aus. Format: `sapk_…`. Er wird nur
   auf dem Host gespeichert, der das Skript ausführt — er lässt sich
   nicht ein zweites Mal abrufen. Bei Verlust beim Operator einen
   neuen Key anfragen.

2. **Skript installieren.**
   Der Participant-Code liegt unter
   <https://github.com/greece-lover/steemapps-monitor/tree/main/participant>.
   Drei Befehle für die Docker-Installation:

   ```bash
   git clone https://github.com/greece-lover/steemapps-monitor.git
   cd steemapps-monitor/participant
   cp .env.example .env && nano .env       # STEEMAPPS_API_KEY eintragen
   docker compose up -d --build
   ```

   Ein systemd-Rezept ist beigefügt für Hosts ohne Docker — siehe das
   [README im participant/-Verzeichnis](../participant/README.md).

3. **Verifizieren.**
   Nach 5–10 Minuten siehst du Flush-Log-Zeilen vom Skript und einen
   `24h`-Count > 0 für deinen Steem-Handle auf
   <https://api.steemapps.com/sources.html>.

## Was das Skript tut

Einmal pro Minute schickt es eine JSON-RPC-Anfrage
`condenser_api.get_dynamic_global_properties` an jeden der 10 vom
zentralen Dashboard überwachten Nodes. Latenz, Head-Block-Höhe und
Fehler werden im RAM gepuffert. Alle fünf Minuten wandert der Buffer
per HTTPS an `https://api.steemapps.com/api/v1/ingest`,
authentifiziert über den `X-API-Key`-Header.

Der Buffer liegt nur im RAM. Ein Neustart verliert maximal fünf Minuten
Daten — bewusste Entscheidung gegen einen Schreibpfad, der gepflegt
werden müsste.

## Ressourcenbedarf

| Ressource | Typisch |
|---|---|
| RAM | < 30 MB |
| CPU | < 1 % einer Kern-Auslastung |
| Ausgehende Bandbreite | ca. 5 MB / Tag |
| Eingehende Bandbreite | nicht nötig |

Eine 1 GB / 1 vCPU-Maschine reicht völlig.

## Vertrauensgrenze und Datenverwendung

- Deine Messungen landen in derselben SQLite-DB wie die des zentralen
  Monitors, markiert mit deinem `display_label`.
- Sie speisen die regionalen Latenz-Vergleiche im Dashboard.
- Sie werden nicht weiterverkauft. Das Dashboard ist read-only und
  öffentlich.
- Teilnahme jederzeit beendbar; ein neuer Key setzt Attribution und
  Counts zurück.

## Spielregeln

- Maximal eine Instanz pro Steem-Account.
- Keine Manipulation der Messwerte. Das Dashboard prüft Plausibilität
  (Latenz-Bereich, Timestamp-Fenster, Success-/Latenz-Konsistenz);
  auffällige Teilnehmer werden deaktiviert.
- `.env` privat halten. Bei Verdacht auf Leakage neuen Key beantragen,
  Rotation innerhalb weniger Stunden.

## FAQ

**Braucht das Skript einen offenen Port?**
Nein. Nur ausgehendes HTTPS zu `api.steemapps.com` und JSON-RPC zu den
zehn überwachten Nodes.

**Was passiert, wenn der Server `api.steemapps.com` nicht erreicht?**
Buffer bleibt im RAM, Retry beim nächsten Flush. Nach sehr langen
Ausfällen werden die ältesten Zeilen über ~1000 verworfen, damit der
Buffer nicht überläuft.

**Muss ich das Skript anpassen, wenn die Node-Liste sich ändert?**
Nein. Das Skript holt die aktuelle Liste beim Start von
`/api/v1/nodes`. Änderungen propagieren sich beim nächsten Neustart.

**Aktualisiert sich das Skript selbst?**
Nein. Repo aktualisieren, Container neu bauen oder Service neu starten.

**Kann ich sehen, was gesendet wird?**
Ja. `monitor.py` ist eine einzige Python-Datei mit ca. 200 Zeilen — in
unter fünf Minuten lesbar. Das Wire-Format ist in [docs/API.md](API.md)
unter `POST /api/v1/ingest` dokumentiert.

**Build schlägt mit "No matching distribution found" fehl?**
Auf Ubuntu mit `systemd-resolved` (Default seit 18.04) zeigt
`/etc/resolv.conf` auf `127.0.0.53`, was im Docker-Build-Sandbox nicht
erreichbar ist. Lege eine `docker-compose.override.yml` neben
`docker-compose.yml` an:

```yaml
services:
  participant:
    build:
      context: .
      network: host
    dns:
      - 1.1.1.1
      - 8.8.8.8
```

Alternativ system-weit: `/etc/docker/daemon.json` mit
`{"dns": ["1.1.1.1", "8.8.8.8"]}`, dann
`sudo systemctl restart docker`.

## Kontakt

- Steem: `@greece-lover`
- Sonst dieselben Kanäle wie SteemApps-Support
