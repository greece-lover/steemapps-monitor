# Changelog

Alle bemerkenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Das Format folgt [Keep a Changelog](https://keepachangelog.com/). Bis 1.0 werden semantische Meilensteine statt strikter SemVer-Versionen verwendet.

*English version: [CHANGELOG.md](CHANGELOG.md)*

## [Unveröffentlicht]

### Geplant für Phase 3

- Python-Monitor-Kern (`monitor/main.py`), Poll-Schleife, JSON-RPC-Client gegen die Steem-Node-Schnittstelle
- SQLite-Schema für Minuten-Messwerte
- Gesundheits-Score nach [docs/MESSMETHODIK.md](docs/MESSMETHODIK.md)
- systemd-Service `steemapps-monitor.service`
- Initiale Node-Liste: api.steemit.com, api.justyy.com, api.steem.fans, api.steemyy.com

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
