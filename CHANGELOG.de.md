# Changelog

Alle bemerkenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Das Format folgt [Keep a Changelog](https://keepachangelog.com/). Bis 1.0 werden semantische Meilensteine statt strikter SemVer-Versionen verwendet.

*English version: [CHANGELOG.md](CHANGELOG.md)*

## [Unveröffentlicht]

### Noch offen für Phase-3-Abschluss (VM-Deploy)

- Repo klonen, venv einrichten, systemd-Unit auf `/opt/steemapps-monitor/` aktivieren (Entwicklungs-VM war am Ende der Phase-3-Code-Session nicht erreichbar; folgt sobald die VM wieder hochgefahren ist)
- 30-Minuten-Laufzeit-Verifikation mit `curl http://127.0.0.1:8110/api/v1/status` und Zeilen-Zähler

## [Phase 3] — 2026-04-24

### Hinzugefügt

- `monitor.py` — asyncio-Entry-Point, ein Event-Loop treibt sowohl die Poll-Schleife (alle 60 s) als auch einen eingebetteten uvicorn-Server
- `database.py` — SQLite-Schema + WAL-Modus, Tabellen `measurements` und `nodes`, Indexe auf `timestamp`, `node_url` und `(node_url, timestamp)`; Insert/Read-Helfer sowie `get_latest_per_node`, `get_uptime_stats`
- `scoring.py` — reine Score-Berechnung entsprechend Methodik `mv1` (Latenz-Bänder, Block-Lag-Bänder, Error-Rate, No-Response-Boden); Score bei 0 gekappt
- `api.py` — FastAPI-Oberfläche mit `/api/v1/health`, `/api/v1/status`, `/api/v1/nodes/{url}/history`; menschenlesbare `reasons`-Liste pro Node
- `config.py` — zentrale Pfade, Intervalle, Node-Liste-Loader; `SOURCE_LOCATION` per env var für künftiges Multi-Location-Monitoring
- `logger.py` — stdout-Logging passend für systemd-Journal
- `nodes.json` — initiale vier Steem-API-Nodes (api.steemit.com, api.justyy.com, api.steem.fans, api.steemyy.com)
- `deploy/steemapps-monitor.service` — systemd-Unit mit Hardening (`ProtectSystem=strict`, `ReadWritePaths`, `RestrictAddressFamilies`, `MemoryDenyWriteExecute`)
- `deploy/README.md` — Install-, Update-, Log- und Shutdown-Kommandos
- `tests/` — 18 pytest-Tests (Scoring-Regeln gemäß Methodik + Datenbank-Round-Trip); zusätzlich `tests/smoke_one_tick.py` für manuellen Live-Check gegen die echten Nodes
- `requirements.txt` und `requirements-dev.txt`
- `progress/2026-04-24-phase3.md` — Phase-3-Progress-Log

### Geändert

- `docs/API.md` — Phase-3-Endpoints mit Beispiel-JSON dokumentiert; die reichere Phase-4-Oberfläche bleibt separat gelistet für externe Konsumenten
- `docs/ARCHITECTURE.md` + `docs/ARCHITEKTUR.md` — Prozess-Tabelle aktualisiert (Phase 3: eine Unit statt zwei) und neuer Abschnitt „Module layout / Modul-Layout"

### Lokal verifiziert

- 18/18 pytest grün
- `smoke_one_tick.py`: alle vier Nodes geantwortet, Block 105471530 synchron, Latenz 394–629 ms

## [Phase 2] — 2026-04-24

### Hinzugefügt

- Projekt-Gerüst: `README.md`, `CHANGELOG.md`, `ROADMAP.md` (alle zweisprachig DE/EN)
- Dokumentations-Basis unter `docs/`: `ARCHITECTURE`/`ARCHITEKTUR`, `CONTRIBUTING`, `SECURITY`, `USER-GUIDE` (alle zweisprachig), `DEPLOYMENT`, `KI_TRANSPARENZ`, `MEASUREMENT-METHODOLOGY`/`MESSMETHODIK`, `API`
- `LICENSE` (MIT)
- Python-orientierte `.gitignore`
- SSH-Host-Alias `steemfork` in der SSH-Config des Autors für die Entwicklungs-VM
- Server-Arbeitsverzeichnis `/opt/steemapps-monitor/` auf der Entwicklungs-VM (Ubuntu 24.04, REDACTED-IP)
- `progress/2026-04-24-phase1-bestandsaufnahme.md` — Phase-1-Server-Audit
- `progress/2026-04-24-phase2.md` — Phase-2-Zeitstempel-Log
- Privates GitHub-Repository `greece-lover/steemapps-monitor`

### Bekannte Abweichungen vom Konzept

- **Hosting-Ziel:** Das Konzept nennt den IONOS-Server (REDACTED-IP) als Produktionsserver; die initiale Entwicklung läuft auf der lokalen Ubuntu-VM des Autors. Der IONOS-Deploy wird in eine spätere Phase verschoben und wird die dort laufende Alreco-Installation nicht berühren.

## [Phase 1] — 2026-04-24

### Hinzugefügt

- Server-Audit der Entwicklungs-VM `steemfork` (REDACTED-IP, Ubuntu 24.04)
- Bestätigung, dass vorhandene Workloads (`steem-fork`, `sqv-indexer`, `sqv-frontend`) nicht beeinträchtigt werden
- Netzwerk-Verifikation: alle vier initialen Steem-API-Nodes erreichbar mit Sub-Sekunden-Latenz
