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

## Server-Stand (Welako, außerhalb dieses Commits)

**Etappe 7 ist Stand auf dem production-server.** Diese Etappe enthält
keine Server-Änderungen — der Cutover ist eine separate Aktion mit
folgenden Schritten:

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
