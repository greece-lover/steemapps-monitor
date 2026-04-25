# 2026-04-25 — Phase 6 Etappe 8 (Community Measurement Points)

Erweiterung des API Monitors um verteilte Mess-Beiträge: ein offener
Ingest-Endpoint nimmt authentifizierte Messungen von Freiwilligen
entgegen, ein leichtgewichtiges Skript erlaubt Witnesses und
Node-Betreibern, in ein paar Befehlen mitzumachen, das Dashboard
attribuiert jede Quelle mit Steem-Handle.

Etappe folgt direkt nach Etappe 7 (Deployment auf den Produktions-Server, Commit
`0466578`). Die Live-Seite blieb während der gesamten Etappe unberührt
— sämtliche Arbeit lokal in `C:\tmp\steemapps`, Cutover in einem
folgenden Schritt.

## Plan-Korrekturen (vor Code-Beginn)

Drei Inkonsistenzen aus der ursprünglichen Spec wurden mit dem Auftrag­
geber geklärt und korrigiert, bevor Code geschrieben wurde:

| Spec-Punkt | Original | Korrigiert | Begründung |
|---|---|---|---|
| Rate-Limit pro API-Key | 120/h | **700/h, Burst 100** | Skript erzeugt 600/h (10 Nodes × 60 s); 120/h hätte sofort 429 geworfen |
| Timestamp-Toleranz | 5 min nach hinten | **−15 min / +60 s** | 5-Min-Batch + Netz + NTP-Drift hätten ältere Zeilen regelmäßig abgelehnt |
| `UNIQUE`-Constraint | nur App-Logik | **DB-Schema** | Doppel-Registrierung auf Engine-Ebene verhindern |

Die Korrekturen sind in der Spec-Antwort dokumentiert und in den
ausgelieferten Code direkt eingebaut.

## Was im Repo neu ist

### Backend (Python)

| Datei | Zweck |
|---|---|
| `participants.py` (neu) | Schlüssel-Generierung, bcrypt-Hashing + SHA-256-Lookup-Index, CRUD |
| `ingest.py` (neu) | Token-Bucket-Rate-Limiter, Validierung, Reject-Reasons |
| `database.py` (geändert) | Neue Tabelle `participants` mit `UNIQUE(steem_account)`; neuer Composite-Index `(source_location, timestamp)` |
| `config.py` (geändert) | `ADMIN_TOKEN`-ENV-Variable, `PRIMARY_SOURCE`-Dict |
| `api.py` (geändert) | Sechs neue Routes (siehe unten), Pydantic-Modelle auf Modul-Ebene |
| `requirements.txt` (geändert) | `bcrypt>=4.2,<5` |

Sechs neue Endpoints, alle unter `/api/v1/`:

- `POST /ingest` — X-API-Key, Batch-Body bis 200 Messungen, Rate-Limit 700/h
- `POST /admin/participants` — Bearer-Auth, gibt API-Key einmalig zurück
- `GET /admin/participants` — Liste aller Teilnehmer (ohne Keys)
- `PATCH /admin/participants/{id}` — `active` und/oder `note` ändern
- `DELETE /admin/participants/{id}` — Hard-delete (Mess-Historie bleibt)
- `GET /sources` — öffentlich, Primary + aktive Teilnehmer mit 24h-/7d-Counts
- `GET /nodes` — schlanke URL+Region-Liste für Skript-Bootstrap

### Participant-Skript (`participant/`)

| Datei | Zeilen | Zweck |
|---|---|---|
| `monitor.py` | 225 (177 Code) | asyncio: 60 s Poll, 5 min Flush, Retry, Buffer-Cap |
| `requirements.txt` | 1 | nur `httpx` |
| `Dockerfile` | 14 | python:3.12-slim, non-root |
| `docker-compose.yml` | 12 | Auto-Restart, Mem/CPU-Limit |
| `systemd-service.example` | 35 | gleiches Hardening wie Monitor-Unit |
| `.env.example` | 13 | kommentiert, nur `STEEMAPPS_API_KEY` zwingend |
| `README.md` | bilingual | DE + EN, Docker- und systemd-Pfad |

Drei-Befehle-Installation (Docker):

```bash
git clone https://github.com/greece-lover/steemapps-monitor.git
cd steemapps-monitor/participant
cp .env.example .env && nano .env       # API-Key eintragen
docker compose up -d --build
```

### Dashboard (`frontend/`)

- `sources.html` (neu) + `js/sources.js` (neu) — Tabelle mit Mess-Quellen
- `css/main.css` (geändert) — Pills für Sources, Attribution-Block-Style
- `js/common.js` (geändert) — Attribution-Footer auf jeder Seite
- Nav-Link "Sources" zu allen 5 bestehenden Seiten ergänzt

### Doku

- `docs/PARTICIPATE.md` (EN) + `docs/TEILNEHMEN.md` (DE)
- `docs/API.md` — vollständige Doku der sechs neuen Endpoints
- `CHANGELOG.de.md` + `CHANGELOG.md` — Etappe-8-Sektion

### Tooling

- `scripts/dry_run_participant.py` — End-to-End-Smoke-Test, registriert
  Mock-Teilnehmer, sendet drei Messungen, prüft DB und `/sources`
- `tests/test_api_etappe8.py` — 31 neue pytest-Tests

## Tests

### Suite-Lauf

```
$ .venv/Scripts/python.exe -m pytest tests/ -q
........................................................................ [ 66%]
.....................................                                    [100%]
109 passed in 20.61s
```

Davon **31 neu** (test_api_etappe8.py), **78 vorhanden**, **0 Regressionen**.

### Test-Abdeckung Etappe 8

| Bereich | Tests |
|---|---|
| Ingest happy path / Source-Location-Persistenz | 2 |
| Ingest Authentifizierung (fehlend, falsch, deaktiviert, malformed) | 4 |
| Ingest Validierung (5 Reject-Reasons, Mixed Batch, Größe) | 8 |
| Ingest Rate-Limit-Trigger (Burst → 429) | 1 |
| Admin CRUD (POST/GET/PATCH/DELETE, 401, 503, 409, 404) | 8 |
| Sources (Primary first, aktive Teilnehmer, deaktivierte versteckt) | 3 |
| Pure-Module: RateLimiter Refill, validate_row Fehler-Pfade, normalise_timestamp | 5 |

### Dry-Run-Protokoll

```
$ .venv/Scripts/python.exe scripts/dry_run_participant.py
[1/5] Throwaway DB at C:\Temp\steemapps-dryrun-9si6kv3m\dryrun.sqlite
[2/5] Participant registered, API key = sapk_NeSs1UO…
[3/5] Built batch with 3 measurements
[4/5] Ingest response: accepted=3, rejected=0, remaining=97
[5/5] DB now contains 3 rows, all attributed to 'Mock (TEST)'.
      /sources reports 3 24h, 3 7d for mock-tester.

DRY RUN OK — ingest pipeline contract is intact end-to-end.
```

## Design-Entscheidungen

### bcrypt + SHA-256-Lookup-Index (nicht "nur" bcrypt)

Die Spec verlangt bcrypt-Hashing der API-Keys. Bcrypt allein erzwingt
aber `O(N × ~200 ms)` Lookup-Kosten pro Request bei N aktiven
Teilnehmern. Lösung: zwei Spalten — `api_key_lookup` (SHA-256 hex,
UNIQUE-Index, irreversibel weil 256-bit Eingangs-Entropie) und
`api_key_hash` (bcrypt). Lookup ist O(1) per UNIQUE-Index, danach
konstantzeit-Verifikation via `bcrypt.checkpw`. Spec-konform und
performant.

### Identische 401-Antwort für drei Fehlerklassen

`verify_api_key` gibt für "Key unbekannt", "Key falsch" und "Key
deaktiviert" dieselbe `None` zurück. Wer die Antwort unterscheiden
könnte, könnte aktive Steem-Accounts per Probe enumerieren. Die
identische Detail-Message "invalid or inactive api key" verhindert
das.

### `source_location = display_label`, nicht Steem-Handle

Beim Insert in `measurements` wird `source_location` auf den
`display_label` gesetzt, nicht auf `steem_account`. Vorteil: der
Operator kann den Anzeigenamen ändern, ohne die historische
Attribution zu zerstören. Der Lookup zwischen Steem-Account und
Label läuft zur Anzeige-Zeit über die `participants`-Tabelle.

### Pydantic-Modelle auf Modul-Ebene

Erster Wurf hatte `IngestRequest`/`IngestMeasurement` innerhalb von
`build_app()` definiert (parallel zum bestehenden `_detail_data`-
Pattern). FastAPIs OpenAPI-Introspection erkannte sie dann nicht als
Body-Modell, sondern als Query-String-Parameter — jeder POST 422'te
mit `"Field required: query.body"`. Lösung: Modelle nach Modul-Scope
verschoben. Im Code-Kommentar bei den Modell-Definitionen festgehalten.

### Rate-Limiter: pro Process, nicht pro Server

Token-Buckets liegen im RAM, gehen bei Restart verloren. Bewusst:
ein Restart erlaubt allen Teilnehmern einen frischen Burst, was
maximal `RATE_LIMIT_BURST` zusätzliche Messungen pro Restart kostet.
Die Alternative (Bucket-State in SQLite) hätte für dieses Volumen
nichts gebracht außer Komplexität.

### Buffer im Skript: nur RAM, kein Disk-Spill

`monitor.py` puffert nur in einer `list[dict]`. Bei Restart verliert
der Teilnehmer maximal `FLUSH_INTERVAL_S` Sekunden Daten (default
300 s = 5 min). Bewusste Entscheidung gegen einen Schreibpfad mit
File-Cleanup, der die Audit-Fläche und Bug-Fläche verdoppelt hätte.
Der Buffer ist auf 1000 Zeilen gekappt, damit eine lange Server-
Outage den Container nicht zur OOM-Kill-Kandidatur macht.

## Aufruf-Post (Entwurf — vor Veröffentlichung vom Autor zu redigieren)

**Plattform:** Steem, Account `@greece-lover`
**Typ:** normaler Post mit Tags `steem`, `witness`, `monitoring`,
`api`, `community`

---

> **Verteilte Messungen für den Steem-API-Monitor — wer macht mit?**
>
> Seit ein paar Tagen läuft unter https://api.steemapps.com/ ein
> öffentlicher Monitor für die zehn aktiven Steem-API-Nodes:
> Latenz, Block-Höhe, Ausfälle, alles minutengenau aus den letzten
> 30 Tagen. Quellcode auf GitHub, Methodik in `MEASUREMENT-METHODOLOGY.md`
> dokumentiert.
>
> Eine Schwäche bleibt: alle Messungen kommen von einer einzigen VM
> in Deutschland. Damit sehen wir gut, wenn ein Node tot ist — aber
> nicht, ob er für jemanden in den USA, Asien oder Süd-Amerika
> schnell ist. Genau dafür gibt es jetzt einen Mitmach-Pfad.
>
> **Was du brauchst:**
> - einen kleinen VPS (1 GB RAM reicht, das Skript braucht unter 30 MB)
> - einen Steem-Account
> - ausgehendes HTTPS — keinen offenen Port
>
> **Was passiert:**
> Ein 200-Zeilen-Python-Skript misst alle 60 Sekunden die zehn
> öffentlichen Nodes von deinem Server aus und schickt das Ergebnis
> alle fünf Minuten gebündelt an api.steemapps.com. Auf der neuen
> Sources-Seite des Dashboards taucht dein Steem-Handle auf,
> verlinkt auf dein Profil. Deine Messungen fließen in die regionalen
> Latenz-Vergleiche ein.
>
> **Installation per Docker (drei Befehle):**
> ```bash
> git clone https://github.com/greece-lover/steemapps-monitor.git
> cd steemapps-monitor/participant
> docker compose up -d --build
> ```
> (Davor `cp .env.example .env` und API-Key eintragen.)
>
> Eine systemd-Variante ist im Repo enthalten, falls du keinen Docker
> möchtest.
>
> **Besonders gesucht:** Beiträge aus Nordamerika, Asien (Tokyo,
> Singapur, Seoul), Süd-Amerika, Afrika und Australien.
>
> **API-Key bekommst du**, indem du mir per Steem-DM oder Memo
> deinen Account-Namen, ein kurzes Server-Label und die Region
> schickst. Der Key wird einmalig im Klartext zurückgegeben und
> ist danach nur noch als bcrypt-Hash in der DB.
>
> Volle Anleitung: PARTICIPATE.md (EN) und TEILNEHMEN.md (DE) im
> Repo. Das Skript ist eine einzige auditierbare Datei.
>
> Witness-Vote für `@greece-lover`, falls dir das Projekt
> insgesamt etwas wert ist — ich finanziere die Produktions-Infrastruktur
> aus den Witness-Earnings.

---

Hinweise zum Post:
- `<200 Zeilen Python` ist sachlich korrekt (177 effektive Code-Zeilen)
- Kein Marketing-Sprech, kein "revolutionär", kein "world-class"
- Witness-Vote-Hinweis am Ende, nicht im Aufmacher
- Vor Veröffentlichung: Steem-Markdown-Preview, Vorschau-Bild?

## Cutover auf den Produktions-Server (durchgeführt 2026-04-25 04:05–04:09 UTC)

Direkt im Anschluss an den Repo-Commit. Ablauf identisch zur Etappe-7-
Vorlage (Pre-Flight → Backup → Transfer → bcrypt → Token → Restart →
Smoke → Tabu-Check), zusätzlich systemd-Unit-Patch (EnvironmentFile=).

### Was sich auf dem Server geändert hat

| Pfad | Änderung |
|---|---|
| `/opt/steemapps-api-monitor/api.py` | aktualisiert (sechs neue Routes) |
| `/opt/steemapps-api-monitor/config.py` | aktualisiert (ADMIN_TOKEN, PRIMARY_SOURCE) |
| `/opt/steemapps-api-monitor/database.py` | aktualisiert (participants-Tabelle + Index) |
| `/opt/steemapps-api-monitor/ingest.py` | **neu** |
| `/opt/steemapps-api-monitor/participants.py` | **neu** |
| `/opt/steemapps-api-monitor/requirements.txt` | bcrypt ergänzt |
| `/opt/steemapps-api-monitor/.venv/` | bcrypt 4.3.0 nachinstalliert |
| `/opt/steemapps-api-monitor/.env.local` | **neu**, mode 600, owner steemapps-monitor, enthält STEEMAPPS_ADMIN_TOKEN (32 Byte hex) |
| `/etc/systemd/system/steemapps-api-monitor.service` | `EnvironmentFile=-/opt/steemapps-api-monitor/.env.local` ergänzt (Dash-Prefix = optional) |
| `/var/www/api.steemapps.com/sources.html` | **neu** |
| `/var/www/api.steemapps.com/js/sources.js` | **neu** |
| `/var/www/api.steemapps.com/js/common.js` | aktualisiert (Attribution-Footer) |
| `/var/www/api.steemapps.com/css/main.css` | aktualisiert (Pills, Attribution-Block) |
| `/var/www/api.steemapps.com/{index,node,regions,stats,outages}.html` | aktualisiert (Sources-Nav-Link) |
| `/opt/steemapps-api-monitor/data/measurements.sqlite` | unverändert (Schema-Migration nur additive `participants`-Tabelle) |

### Backups

| Pfad | Inhalt | MD5 (sample) |
|---|---|---|
| `/opt/steemapps-api-monitor/data/measurements.sqlite.pre-etappe8.bak` | DB vor Cutover (1.282.048 B, 5.970 Zeilen) | `1499e046…` |
| `/opt/steemapps-api-monitor/{api,config,database}.py.pre-etappe8.bak` | Python-Files vor Etappe 8 | siehe Cutover-Log |
| `/opt/steemapps-api-monitor/requirements.txt.pre-etappe8.bak` | Vor bcrypt-Ergänzung | `fa31677c…` |
| `/etc/systemd/system/steemapps-api-monitor.service.pre-etappe8.bak` | Vor EnvironmentFile=-Patch | `348b3440…` |
| `<server>:<backup-path>/etappe8-www-pre.tar.gz` | Komplett-tar des `/var/www/api.steemapps.com/` (201.916 B) | `9e838674…` |

### Restart-Metriken

- **Downtime: 226 ms** (`systemctl restart` Wall-Time, gemessen mit `date +%s%N`)
- Kein Tick verpasst — Pre-Restart 5.990 Zeilen → Post-Restart 6.000 Zeilen (+10 in einem Tick) → 5 Min später 6.010
- PID 302121 → 659942
- `participants`-Tabelle bei erstem `initialise()`-Call angelegt (CREATE TABLE IF NOT EXISTS, idempotent)
- NRestarts=0 seit Boot — kein Crash-Loop

### Smoke-Test (auf dem Server, gegen Loopback)

| Schritt | Erwartung | Tatsächlich |
|---|---|---|
| `curl /api/v1/admin/participants` ohne Bearer | 401 | 401 |
| `curl /api/v1/admin/participants` mit korrektem Bearer | 200 + leere Liste | `{"participants":[]}` |
| `POST /admin/participants` `smoke-test-mock` | 201 + plain api_key | 201, key prefix `sapk_3U-…` |
| `POST /ingest` mit Mock-Key, 3 Messungen | accepted=3 | `{"accepted":3,"rejected":[],"rate_limit_remaining":97}` |
| `GET /sources` | Mock + Primary | beide gelistet, Mock mit 24h=3 |
| `POST /ingest` mit `sapk_definitely-fake` | 401 | 401 |
| `DELETE /admin/participants/1` | 200 | `{"deleted":true,"id":1}` |
| Mock-Mess-Zeilen entfernt aus DB | 3 entfernt | 3 entfernt |
| `GET /sources` final | nur Primary | `sources count: 1` |

### External Smoke (von Entwickler-Workstation gegen `api.steemapps.com`)

| URL | HTTP |
|---|---|
| `GET https://api.steemapps.com/api/v1/sources` | 200 (Primary, 6010 Messungen) |
| `GET https://api.steemapps.com/api/v1/nodes` | 200 (10 Nodes) |
| `POST https://api.steemapps.com/api/v1/ingest` mit leerem Body | 422 (Pydantic-Validation, korrekt) |
| `GET https://api.steemapps.com/sources.html` | 200 (2.726 B) |
| `GET https://api.steemapps.com/api/v1/status` | 200 |
| `GET https://api.steemapps.com/api/v1/regions` | 200 |
| `GET https://api.steemapps.com/api/v1/outages` | 200 |

### Browser-Test (claude-in-chrome, gegen Live-Site)

- `https://api.steemapps.com/sources.html`: Tabelle mit Primary-Eintrag (greece-lover, "central monitor"-Pill, "Welako VM (DE)", eu-central, 6010/6010), Attribution-Footer mit verlinktem `@greece-lover (eu-central)`, keine Console-Errors
- `https://api.steemapps.com/index.html`: Nav um "Sources"-Link erweitert, Overview rendert weiter normal mit allen 10 Node-Cards, keine Console-Errors

### Tabu-Verifikation

| Bereich | Vorher | Nachher | Diff |
|---|---|---|---|
| Docker-Container (mailcow+neonblocks+steemauth) | 24 | 24 | identisch |
| Nginx sites-enabled | 12 | 12 | identisch |
| `nginx -t` | OK | OK | — |
| `https://steemapps.com/` | HTTP 200 | HTTP 200 | — |
| `https://welako.app/` | HTTP 200 | HTTP 200 | — |
| `https://neonblocks.steemapps.com/` | HTTP 200 | HTTP 200 | — |

Mailcow-`netfilter`-Container war bei Post-Check 4 Min alt — periodischer Restart, **nicht** durch unseren Deploy verursacht (kein Touch von /opt/mailcow*).

### Live-URLs nach Cutover

- `https://api.steemapps.com/sources.html` — neue Sources-Seite
- `https://api.steemapps.com/api/v1/sources` — JSON-API für Mess-Quellen
- `https://api.steemapps.com/api/v1/nodes` — Node-Liste für Participant-Bootstrap
- `https://api.steemapps.com/api/v1/ingest` — Ingest-Endpoint (POST, X-API-Key)
- `https://api.steemapps.com/api/v1/admin/participants` — Admin-CRUD (Bearer-Auth)

### Admin-Token

Generiert auf dem Server mit `openssl rand -hex 32`, geschrieben in
`/opt/steemapps-api-monitor/.env.local`. Datei ist mode 600, Eigentümer
`steemapps-monitor`. Wert wurde **nicht** über den Chat übertragen.
Abrufbar per:

```bash
ssh root@REDACTED-IP 'cat /opt/steemapps-api-monitor/.env.local'
```

### Rollback-Pfad (falls je nötig)

```bash
ssh root@REDACTED-IP

# 1) Service stoppen
systemctl stop steemapps-api-monitor

# 2) Python-Code zurückspielen
sudo -u steemapps-monitor bash -c '
  cd /opt/steemapps-api-monitor
  for f in api config database requirements; do
    cp -v ${f}.{py,txt}.pre-etappe8.bak ${f}.${f##*.}
  done
  rm ingest.py participants.py
'

# 3) DB zurückspielen NUR bei Verdacht auf Datenkorruption
#    (Etappe 8 hat NUR additive participants-Tabelle angelegt;
#     bestehende Mess-Daten sind unverändert)
# sudo -u steemapps-monitor cp /opt/steemapps-api-monitor/data/measurements.sqlite{.pre-etappe8.bak,}

# 4) systemd-Unit zurückspielen
cp /etc/systemd/system/steemapps-api-monitor.service.pre-etappe8.bak \
   /etc/systemd/system/steemapps-api-monitor.service
systemctl daemon-reload

# 5) Frontend zurückspielen
rm -rf /var/www/api.steemapps.com.broken
mv /var/www/api.steemapps.com /var/www/api.steemapps.com.broken
mkdir /var/www/api.steemapps.com
tar -C /var/www/api.steemapps.com -xzf <server>:<backup-path>/etappe8-www-pre.tar.gz --strip-components=1
chown -R www-data:www-data /var/www/api.steemapps.com

# 6) bcrypt im venv lassen (schadet nicht) ODER:
# sudo -u steemapps-monitor /opt/steemapps-api-monitor/.venv/bin/pip uninstall -y bcrypt

# 7) Service starten
systemctl start steemapps-api-monitor
systemctl is-active steemapps-api-monitor
```

Tabu-Container und nginx-Sites bleiben in jeder Rollback-Variante
unberührt.

## Server-Stand (vor Cutover, jetzt obsolet — historisch)

**Etappe 7 war Stand auf dem production-server.** Cutover-Schritte (siehe oben für
das tatsächlich Durchgeführte):

```bash
# 1. Code-Transfer (tar | ssh) wie in Etappe 7
#    Neue Dateien: participants.py, ingest.py, scripts/dry_run_participant.py
#    Geänderte Dateien: api.py, database.py, config.py, requirements.txt

# 2. Dependency installieren
sudo -u steemapps-monitor /opt/steemapps-api-monitor/.venv/bin/pip install "bcrypt>=4.2,<5"

# 3. Admin-Token setzen
echo 'STEEMAPPS_ADMIN_TOKEN=<32-byte-zufalls-string>' \
  | sudo -u steemapps-monitor tee -a /opt/steemapps-api-monitor/.env.local
# .env.local muss EnvironmentFile= in der systemd-Unit referenzieren —
# wenn nicht, Unit anpassen.

# 4. Frontend nach /var/www/api.steemapps.com/
#    Neu: sources.html, js/sources.js
#    Geändert: index.html, node.html, regions.html, stats.html, outages.html,
#              css/main.css, js/common.js

# 5. Service-Restart
sudo systemctl restart steemapps-api-monitor

# 6. Smoke-Test
curl -s https://api.steemapps.com/api/v1/sources | jq .
curl -s -H "Authorization: Bearer <token>" \
     https://api.steemapps.com/api/v1/admin/participants | jq .
# Erwartung: erstes Kommando 200 mit nur Primary; zweites 200 mit leerer Liste
```

Tabu-Container (mailcow ×20, steemauth ×4, neonblocks ×3) bleiben
unberührt.

## Phase-6-Status nach Etappe 8

```
49e7e0b  Etappe 1  API-Endpoints + Outage-Detektion + Filter
5a2d3c2  Etappe 2  Detail-Ansicht pro Node mit Compare
3312916  Etappe 3  Stats-Übersichtsseite + Time-Comparison-Fix
281a1b4  Etappe 4  Regionale Karte mit Leaflet
9180598  Etappe 5  Ausfall-Log mit Filter und CSV/JSON-Export
2c03dc3  Etappe 6  Theme, Autorefresh, Mobile + 96×-Speedup
0466578  Etappe 7  Deployment + Nginx-proxy_pass-Fix
<tbd>    Etappe 8  Community Measurement Points + Ingest + Sources
```

## Mögliche nächste Schritte

- Cutover gemäß "Server-Stand"-Block oben
- Aufruf-Post nach Review veröffentlichen
- Sobald die ersten Teilnehmer aktiv sind: Per-Source-Latenz-Overlay
  in `node.html` (war im Spec-Umfang erwähnt, ist erst sinnvoll wenn
  Vergleichsdaten existieren)
- Auto-Refresh auch für `sources.html` an `SteemAPI.onAutoRefresh`
  binden — aktuell statischer Snapshot, was OK ist weil Counts sich
  langsam ändern
- Server-seitige Anomalie-Erkennung (z. B. Teilnehmer mit identischer
  Latenz über alle Nodes → vermutlich Mock-Daten) als Folge-Etappe,
  sobald genug echte Daten zur Baseline existieren
