# Changelog

Alle bemerkenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Das Format folgt [Keep a Changelog](https://keepachangelog.com/). Bis 1.0 werden semantische Meilensteine statt strikter SemVer-Versionen verwendet.

*English version: [CHANGELOG.md](CHANGELOG.md)*

## [Unveröffentlicht]

## [Phase 6 Etappe 8] — 2026-04-25

### Neu

- `participants.py` — Verwaltung externer Mess-Beitragender: Schlüssel-Generierung (`sapk_…`-Prefix, 256-bit-Entropie), bcrypt-Hashing plus SHA-256-Lookup-Index für O(1)-Auth bei beliebig vielen Teilnehmern, CRUD-Helper über die neue `participants`-Tabelle
- `ingest.py` — eigenständige Validierungs- und Rate-Limit-Schicht: Token-Bucket pro Teilnehmer (700/h, Burst 100), Timestamp-Toleranz `−15 min … +60 s`, Plausibilitäts-Bounds für Latenz, Reject-Reason-Enum für API-Antworten
- `database.py`: neue Tabelle `participants` mit `UNIQUE`-Constraint auf `steem_account`, neuer Composite-Index `(source_location, timestamp)`
- `api.py`: sechs neue Endpoints — `POST /api/v1/ingest`, `POST/GET/PATCH/DELETE /api/v1/admin/participants[/{id}]`, `GET /api/v1/sources`, `GET /api/v1/nodes`. Admin-Auth fail-closed gegen `STEEMAPPS_ADMIN_TOKEN`-ENV; Konstantzeit-Vergleich via `secrets.compare_digest`
- `participant/` — Subverzeichnis mit dem Mess-Skript für Beitragende: `monitor.py` (177 Code-Zeilen, einzige Dependency httpx), `Dockerfile`, `docker-compose.yml`, `systemd-service.example`, `.env.example`, zweisprachiges README
- `frontend/sources.html` + `js/sources.js` — neue Dashboard-Seite mit Mess-Quellen-Tabelle (Steem-Handle verlinkt, Region, 24h-/7d-Counts)
- `common.js`: Attribution-Footer auf jeder Seite, der die Quellen aus `/api/v1/sources` lädt und im bestehenden `.footnote`-Block anzeigt
- Nav-Link "Sources" zu allen Dashboard-Seiten ergänzt
- `docs/PARTICIPATE.md` + `docs/TEILNEHMEN.md` — Teilnahme-Anleitung in beiden Sprachen mit Voraussetzungen, Installation, FAQ
- `docs/API.md`: vollständige Doku der sechs neuen Endpoints
- `scripts/dry_run_participant.py` — End-to-End-Dry-Run gegen In-Process-TestClient (Mock-Teilnehmer, drei Messungen, Verifikation in DB und in `/api/v1/sources`)
- `tests/test_api_etappe8.py` — 31 neue pytest-Tests: Ingest happy/sad paths, Auth-Verhalten, Rate-Limit-Trigger, Admin-CRUD, Sources-Endpoint, Pure-Module-Tests für `RateLimiter` und `validate_row`
- `requirements.txt`: `bcrypt>=4.2,<5` als neue Backend-Dependency

### Plan-Korrekturen vor Implementierung

- Rate-Limit von ursprünglich 120/h auf **700/h** angehoben — das Mess-Skript erzeugt 600 Messungen/h (10 Nodes × 60 s), 120/h hätte sofort 429 geworfen. Burst-Capacity 100 deckt zwei vollständige 5-Min-Batches plus Retry-Spielraum ab
- Timestamp-Toleranz von ursprünglich 5 min auf **−15 min / +60 s** erweitert — der 5-min-Batch des Skripts plus Netzwerk-Latenz plus NTP-Drift hätte sonst regelmäßig die ältesten Messungen abgelehnt
- `UNIQUE`-Constraint auf `steem_account` direkt im DB-Schema statt nur in der Anwendungs-Logik — Doppel-Registrierung wird damit auf Engine-Ebene verhindert

### Design-Entscheidungen

- API-Keys werden zweifach gehasht: bcrypt für die Spec-Anforderung plus SHA-256-Hex als Lookup-Index. Lookup ist damit O(1) per UNIQUE-Index, Verifikation läuft konstant-zeit per `bcrypt.checkpw`. Begründung im Schema-Kommentar in `database.py` und im Modul-Docstring von `participants.py`
- `verify_api_key` liefert für "Key unbekannt", "Key falsch" und "Key deaktiviert" die identische `None`-Antwort. Die API-Layer wandelt das in einen einzigen 401-Text um — sonst wäre Account-Enumeration per Probe trivial möglich
- Ingest schreibt mit `source_location = participant.display_label`, nicht mit dem Steem-Handle — Operator kann den Anzeige-Namen ändern, ohne dass historische Zeilen umetikettiert werden müssen
- Pydantic-Modelle wurden auf Modul-Ebene definiert, nachdem im ersten Wurf eine Definition innerhalb von `build_app()` von FastAPIs OpenAPI-Introspection nicht als Body-Parameter erkannt wurde (Symptom: jeder POST 422 mit "Field required: query.body")

### Lokal verifiziert

- 109/109 pytest grün (78 bestehend + 31 neu, keine Regressionen)
- `scripts/dry_run_participant.py` erfolgreich: Mock-Teilnehmer registriert, drei Messungen ingesticht, korrekt mit `display_label` in DB persistiert, in `/api/v1/sources` gezählt
- Participant-Skript: Syntax-Compile OK, 177 effektive Code-Zeilen (unter dem Spec-Limit von 200)

### Aufruf-Post-Entwurf

Liegt unter `progress/2026-04-25-phase6-etappe8.md`, Abschnitt "Aufruf-Post (Entwurf)". Vor Veröffentlichung vom Autor zu redigieren.

### Noch offen für Cutover auf den production-server

- `STEEMAPPS_ADMIN_TOKEN` in `/opt/steemapps-api-monitor/.env.local` setzen (file mode 600, Eigentümer `steemapps-monitor`)
- bcrypt im Server-venv nachinstallieren: `.venv/bin/pip install "bcrypt>=4.2,<5"`
- Frontend-Dateien (sources.html, sources.js, aktualisierte CSS, gepatchte HTML-Pages) nach `/var/www/api.steemapps.com/`
- Service-Restart, Smoke-Test gegen `/api/v1/sources` und `/api/v1/admin/participants` (letzteres mit korrektem Bearer-Token muss 200 mit leerer Liste liefern, ohne Token 401)
- Aufruf-Post nach Review veröffentlichen

### Noch offen für Phase-5-Produktions-Cutover

- `reporter/.env.local` auf der VM, Posting-Key manuell vom Autor eingetragen (nie per Chat übertragen)
- Erster Dry-Run auf der VM gegen die Live-Mess-DB
- Erster `STEEMAPPS_REPORTER_MODE=prod`-Broadcast manuell über `systemctl start steemapps-reporter.service` ausgelöst
- Timer aktivieren, sobald der erste echte Post auf steemit.com verifiziert ist

## [Phase 5] — 2026-04-24

### Neu

- `reporter/` — neues Python-Paket: `config.py` (ENV-Laden, `.env.local`-Reader, `ReporterConfig`-Dataclass), `query.py` (read-only SQL über das UTC-Tagesfenster), `aggregation.py` (reine Per-Node-/Global-/Wochen-Aggregation, `custom_json`-Payload-Builder), `template.py` (zweisprachiger DE/EN-Post-Renderer), `broadcast.py` (beem-Lazy-Import-Wrapper mit 3×60s-Retry und Permanent-/Transient-Fehler-Klassifikation), `daily_report.py` (CLI-Entry + `--seed-synthetic`-Dev-Helfer)
- `reporter/.env.example` — kommentierte ENV-Vorlage; `.env.local` ist die Live-Kopie auf der VM, immer `chmod 600` und im Besitz von `steemapps-reporter`
- `requirements-reporter.txt` — `beem>=0.24.26,<0.30`, getrennt von `requirements.txt`, damit der Monitor-Service-Footprint unverändert bleibt
- `deploy/steemapps-reporter.service` — oneshot-systemd-Unit, läuft als `steemapps-reporter` mit `EnvironmentFile=` auf `.env.local`; identische Hardening-Basis wie die Monitor-Unit plus `ReadOnlyPaths=` für die Mess-DB
- `deploy/steemapps-reporter.timer` — täglicher Trigger um 02:30 UTC mit `Persistent=true`, damit ein verpasster Run beim nächsten Boot nachgeholt wird
- `deploy/README.md` — Install-, Dry-Run- und Manual-Trigger-Anleitung für den Reporter
- `docs/DAILY-REPORT.md` + `docs/TAGES-REPORT.md` — Methodik, Zeitplan, `custom_json`-Schema, Fehlerbehandlungs-Semantik, manuelle Ausführungs-Rezepte
- `tests/test_aggregation.py` (9 Tests), `tests/test_template.py` (9 Tests), `tests/test_broadcast.py` (7 Tests) — neue Abdeckung für die Reporter-Schicht
- `progress/2026-04-24-phase5.md` — Phase-5-Progress-Log mit Dry-Run-Sample

### Design-Entscheidungen

- Dedizierter `@steem-api-health`-Reporter-Account statt `@greece-lover` — Trennung der Witness-Identität von der Automations-Ausgabe; eine kompromittierte VM offenbart den Witness-Key nicht
- Zweistufiger Broadcast: `custom_json` zuerst (Rohaggregation), dann `comment` (lesbarer Post), damit der Post-Body auf den On-Chain-Tx-Hash verweisen kann
- beem wird lazy innerhalb von `_build_steem()` importiert — Dev-Modus und Test-Suite laufen ohne beem-Installation
- Footer-Wortlaut (englischer und deutscher Witness-Vote-Absatz) durch Test gepinnt; eine Edit, die den Text verändert, bricht die Suite

### Lokal verifiziert

- 54/54 pytest grün (29 bestehend + 25 neu)
- Dry-Run gegen einen 14-Tage deterministischen Synthetik-Seed erzeugt einen zweisprachigen Post und eine 2 905-Byte-`custom_json`-Payload; Probe im Phase-5-Progress-Log dokumentiert

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
