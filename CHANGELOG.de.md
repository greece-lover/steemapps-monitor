# Changelog

Alle bemerkenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Das Format folgt [Keep a Changelog](https://keepachangelog.com/). Bis 1.0 werden semantische Meilensteine statt strikter SemVer-Versionen verwendet.

*English version: [CHANGELOG.md](CHANGELOG.md)*

## [Unveröffentlicht]

### Neu

- Redaktionelle **Node-Kategorie** (orthogonal zum gemessenen Health-Status). Drei Werte: `live` (Default — kein UI-Badge), `testing` (gelbe Pille), `community` (blaue Pille). Optionales `description`-Feld pro Node, als Hover-Tooltip auf dem Badge.
- `nodes.json` akzeptiert die neuen optionalen Felder `category` und `description`. Validierung in `config.load_nodes()` — ungültige Kategorien lassen den Start fehlschlagen.
- DB-Schema: `nodes.category` (TEXT NOT NULL DEFAULT 'live') und `nodes.description` (TEXT). Bestehende DBs werden bei `initialise()` per `ALTER TABLE ADD COLUMN` idempotent migriert.
- `/api/v1/status` liefert pro Node jetzt `category` und `description` mit (am Ende des Objekts angefügt — keine Breaking-Reihenfolge).
- Übersichts-Seite: aufklappbare Legende, die beide Achsen erklärt (Health-Status / Node-Kategorie).
- Erster Testing-Node: `api3.justyy.com` (asia, „Justyy private fiber — under verification").

### Hinweise

- Der CSS-Selektor `.status-pill[data-status="degraded"]` matcht weiterhin nicht (API liefert `warning`/`critical`); nicht in dieser Änderung adressiert — separate Aufräum-Session.

## [Phase 6 Etappe 9] — 2026-04-25

### Neu

- `reporter/observations.py` — Beobachtungs-Engine mit acht Kategorien (`top_performer`, `laggard`, `latency_change`, `new_outage`, `consistent_leader`, `consistent_laggard`, `global_trend`, `biggest_outage`). Kategorien mit fehlenden Voraussetzungen (z. B. keine Vortags-Daten) werden leise übersprungen — keine Fake-Vergleiche im Post
- `reporter/image_generator.py` — Pillow-basierter PNG-Renderer für das tägliche Cover-Bild (1200×675, brand-konform: dunkler Verlauf, lime Akzent, "FASTEST"/"SLOWEST"-Tiles)
- `scripts/dry_run_daily_report.py` — End-to-End-Preview gegen 14 Tage Synthetik-Daten in einer tmp-DB
- `tests/test_observations.py` (18 Tests), `tests/test_image_generator.py` (3 Tests), `tests/test_aggregation_etappe9.py` (4 Tests)

### Geändert

- `reporter/template.py` — komplett auf Englisch umgestellt (keine deutsche Sektion mehr im Post). Neue Reihenfolge laut Spec: Cover-Bild → Executive Summary → Perspective-Notice → Observations → Detail-Tabelle → Biggest-Outage → W-o-W → Methodology → Participation-Block → Feedback → Resources → Footer
- `reporter/aggregation.py` — `NodeStats.source_count` zählt unique `source_location`-Werte pro Node-Window; im `custom_json`-Payload mit ausgegeben. Multi-Source-Latenz-Label `(avg of N sources)` schaltet sich automatisch ab N≥2 ein
- `reporter/config.py` — `image_dir`- und `image_url_base`-Felder (ENV-overridable). Defaults zeigen auf den Produktions-Webroot
- `reporter/daily_report.py` — Image-Generation **vor** dem Chain-Broadcast (Fail-fast bei Pillow-Problemen). Hookup für Observations und Multi-Source-Logik. Neuer `--image-only`-Flag für Cover-Preview ohne Broadcast
- `requirements-reporter.txt` — `Pillow>=10,<12`

### Plan-Korrekturen vor Commit (nach erstem Dry-Run-Review)

- Executive Summary von "Beobachtungen wiederholen" auf reine Headline-Zahlen reduziert (Uptime, Mess-Count, Median-Latenz). Spezifika nur noch in der Bullet-Liste
- Beobachtungs-Bullets von `↑/↓`-Pfeilen auf `**Label:**`-Bold-Prefix umgestellt — passt zum technischen Voice und vermeidet Unicode-Render-Risiko bei Steemit
- Perspective-Notice: das zu optimistische "first community contributors are now being onboarded" durch "Want to contribute measurements from your region? See the participation block below." ersetzt
- W-o-W-Format: exakte Null-Deltas erscheinen als `±0.00 pp` statt als `+-0.00 pp` (float-Arithmetik mit `-0.0` als Quelle)

### Lokal verifiziert

- 151/151 pytest grün (+33 vs Etappe 8, keine Regressionen)
- `scripts/dry_run_daily_report.py`: 14 Tage Synthetik → 9 Beobachtungen für den Vortag, sauberes Cover-PNG (38 KB), 5,5 KB Markdown-Body in korrekter Sektion-Reihenfolge

### Noch offen für Cutover auf den Produktions-Server

- Code-Transfer per `tar | ssh`
- `Pillow>=10,<12` ins Reporter-venv installieren
- `/var/www/api.steemapps.com/reports/`-Verzeichnis anlegen, www-data-Ownership
- `--image-only` Smoke-Test
- Voller Dry-Run gegen Live-DB mit dem heutigen Datum, Output zur Freigabe vorlegen
- Erster echter Broadcast manuell triggern (Posting-Key vom Autor selbst per SSH in `.env.local` eingetragen, nicht via Chat)
- Timer aktivieren, sobald der erste echte Post auf steemit.com verifiziert ist

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

Liegt in den internen Deployment-Notizen, Abschnitt "Aufruf-Post (Entwurf)". Vor Veröffentlichung vom Autor zu redigieren.

### Cutover auf Produktions-Server (live seit 2026-04-25 04:06 UTC)

- Service-Restart in **226 ms** Wall-Time, kein Tick verpasst (5.990 → 6.000 Zeilen +10 in einem Tick)
- `participants`-Tabelle automatisch beim Start angelegt (`CREATE TABLE IF NOT EXISTS`, idempotent)
- `bcrypt 4.3.0` im venv nachinstalliert
- `STEEMAPPS_ADMIN_TOKEN` in `<production-path>/.env.local` (mode 600, owner steemapps-monitor) — Wert separat per SSH abrufbar, nicht im Repo
- systemd-Unit um `EnvironmentFile=-<production-path>/.env.local` erweitert (Dash-Prefix = optional)
- Smoke-Test mit Mock-Teilnehmer (POST → ingest 3 Zeilen → in `/sources` sichtbar → DELETE) erfolgreich
- Tabu-Verifikation: 24 Container und 12 nginx-Sites identisch zum Pre-Flight-Stand, alle Schwesterdomains weiter HTTP 200
- Live unter `https://api.steemapps.com/sources.html` und `/api/v1/{ingest,sources,nodes,admin/participants}`
- Backup-Pfade unter `<production-path>/*.pre-etappe8.bak` und `<server>:<backup-path>/etappe8-www-pre.tar.gz`; Rollback-Rezept in den internen Deployment-Notizen

### Noch offen

- Aufruf-Post nach Review veröffentlichen (sobald Repo öffentlich)

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
- SSH-Host-Alias für die Entwicklungs-VM in der SSH-Config des Autors
- Server-Arbeitsverzeichnis `/opt/steemapps-monitor/` auf der lokalen Entwicklungs-VM (Ubuntu 24.04)
- Privates GitHub-Repository `greece-lover/steemapps-monitor`

### Bekannte Abweichungen vom Konzept

- **Hosting-Ziel:** Der Produktionsserver wird in eine spätere Phase verschoben; die initiale Entwicklung läuft auf der lokalen Ubuntu-VM des Autors.

## [Phase 1] — 2026-04-24

### Hinzugefügt

- Server-Audit der lokalen Entwicklungs-VM (Ubuntu 24.04)
- Bestätigung, dass vorhandene Workloads (`steem-fork`, `sqv-indexer`, `sqv-frontend`) nicht beeinträchtigt werden
- Netzwerk-Verifikation: alle vier initialen Steem-API-Nodes erreichbar mit Sub-Sekunden-Latenz
