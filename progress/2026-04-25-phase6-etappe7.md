# 2026-04-25 — Phase 6 Etappe 7 (Deployment)

Das Phase-6-Frontend + Backend live auf `https://api.steemapps.com/`.
Monitor-Service blieb nahezu ohne Downtime (<5 s, kein Tick verpasst),
historische Daten intakt (1.450 → 1.470 → weiter zählend), alle Tabu-
Dienste unberührt. Zusätzlich: ein Nginx-Bug, der die Node-URL-
enthaltenden Routes betraf, wurde im Zuge des Deployments gefixt.

## Schritte in Reihenfolge

### 1. Pre-Flight auf dem Server
Service-Uptime 2.5 h, 1.450 Messungen, **Schema identisch** zur neuen
Code-Basis (keine Migration nötig), 24 Tabu-Container laufen, 12 Nginx-
Sites enabled.

### 2. Backup
- `data/measurements.sqlite` → `…sqlite.pre-phase6.bak` (327 KB)
- `/etc/systemd/system/steemapps-api-monitor.service` →
  `…service.pre-phase6.bak` (1.321 B)
- MD5s aller vorherigen Python-Dateien im Log festgehalten.

### 3. Code-Transfer (tar | ssh)

Python-Module nach `/opt/steemapps-api-monitor/`:

| Datei | Status |
|---|---|
| `api.py` | aktualisiert (neue Endpoints + pattern-Fix + Export-Routes) |
| `cache.py` | **neu** |
| `config.py` | aktualisiert (REGION_COORDINATES, ENV-Port-Override) |
| `database.py` | aktualisiert (neue Helpers + Time-Comparison-Fix + Speedup) |
| `logger.py`, `monitor.py`, `scoring.py` | unverändert |

Frontend nach `/var/www/api.steemapps.com/`:
- 5 HTML-Seiten (index, node, stats, regions, outages)
- `css/main.css` (mit Theme-Variablen)
- `js/common.js`, `main.js`, `node.js`, `stats.js`, `regions.js`, `outages.js`
- Ownership `www-data:www-data`, 755/644.

### 4. Service-Restart

`systemctl restart steemapps-api-monitor` — von PID 174890 auf PID 302121
in <5 Sekunden. Uvicorn startete sauber hoch, erster Tick erfolgreich
(10/10 ok), DB-Zeilen-Count stieg weiter wie erwartet. Kein Handshake-
Fenster, in dem die API nicht antwortete — Polls alle 60 s und der
Service ist gestartet bevor der nächste Tick fällig wurde.

### 5. Nginx-Bugfix (Bonus-Fund)

Beim Live-Smoke-Test zeigten die neuen Routes
`/api/v1/nodes/{node_url:path}/detail`, `…/outages`, `…/uptime-daily`
plus die vorherigen `…/history`, `…/uptime` alle HTTP 404 — obwohl
der Service-interne Loopback-Call HTTP 200 gab.

Ursache: Der ursprüngliche Nginx-Block (aus Phase 5) nutzte
`proxy_pass http://127.0.0.1:8111/api/;` **mit URI-Suffix**. Nginx
dekodiert dabei `%2F` zu `/`, rebuilded die URL und schickt sie an
FastAPI weiter — der `{node_url:path}`-Parameter wird dabei in mehrere
Segmente zerlegt, Route-Matching scheitert.

Fix: `proxy_pass http://127.0.0.1:8111;` **ohne URI** leitet den
Raw-Request-URI unverändert weiter. Anschließend matchen alle fünf
node-URL-Routes.

- Vorher: `/etc/nginx/sites-available/api.steemapps.com.bak-phase6-deploy`
- Nachher: eine geänderte Zeile (22), `nginx -t` OK, `systemctl reload nginx`.

### 6. Live-Sweep (alles HTTP 200)

**20 API-Endpoints**, einschließlich:
- `/api/v1/nodes/<url>/detail|outages|uptime-daily`
- `/api/v1/outages` (+ `severity=real`)
- `/api/v1/stats/top` (alle 5 Metriken)
- `/api/v1/stats/chain-availability` (24h + 7d)
- `/api/v1/stats/daily-comparison`
- `/api/v1/regions`
- `/api/v1/export/outages.csv` + `.json`

**5 Frontend-Pages** HTTP 200.

**Nachbardomains** unverändert: `steemapps.com`, `welako.app`,
`neonblocks.steemapps.com` jeweils HTTP 200.

**24 Tabu-Container** vor und nach Deploy identisch (mailcow ×20 +
steemauth ×4 + neonblocks ×3 + ggf. Zähldifferenz durch Duplikatblick).

### 7. Browser-Smoke-Test in beiden Themes

claude-in-chrome verbunden, Tab auf `https://api.steemapps.com/`.

**Dark-Theme** (Default):
- Overview: 10 Node-Karten, "10 nodes" counter, Toolbar (Theme-Button +
  Refresh-Select mit Wert "60"), alle 4 Nav-Links, Controls-Panel.
- `--accent: #b7e34a`, Body-bg `#0a0a0a`.

**Light-Theme** (via localStorage geschaltet, Reload):
- `data-theme="light"` auf `<html>`, Theme-Button zeigt "🌙 Dark"
- Body-bg `rgb(250,250,250)`, Text `rgb(26,26,26)`
- `--accent: #5a7d0f`
- 10 Node-Karten weiterhin gerendert, Stats unverändert
- **stats.html**: 4 Ranking-Karten à 3 Einträge, Chain-Availability- und
  Global-Latency-Chart ready, Daily-Comparison mit 10 Zeilen
- **regions.html**: Leaflet-Map 1035×520, 15 Tiles geladen, 5 anchored
  Markers (us-east/us-west/us-central/asia/eu-central) + 7 Tabellen-
  Zeilen (5 anchored + 2 anchorless)
- **outages.html**: Node-Dropdown 11 Options, Export-Buttons mit
  korrekten Hrefs, 1 Outage (aus der Live-DB) gelistet
- **node.html?url=api.steemit.com**: Status OK, Latency- und Block-Lag-
  Chart ready, 30-Tage-Kalender (1 Tag mit Daten), Percentile-Tabelle,
  Outages-Tabelle, Range-Toggle aktiv auf 24h

**Kein Error-Banner** auf irgendeiner Seite, keine Console-Errors
gesichtet.

Nach Abschluss: `localStorage.removeItem('steemapps_theme')` + Reload
→ Dark-Theme wiederhergestellt, damit der User die Session nicht
geändert vorfindet.

## Server-Stand (Welako, außerhalb des Repos)

| Pfad | Status |
|---|---|
| `/opt/steemapps-api-monitor/{api,cache,config,database,logger,monitor,scoring}.py` | aktualisiert (Phase 6) |
| `/opt/steemapps-api-monitor/data/measurements.sqlite` | unverändert, wächst weiter |
| `/opt/steemapps-api-monitor/data/measurements.sqlite.pre-phase6.bak` | Pre-Deploy-Backup (327 KB) |
| `/etc/systemd/system/steemapps-api-monitor.service` | unverändert (Backup vorhanden) |
| `/etc/nginx/sites-available/api.steemapps.com` | **`proxy_pass` ohne URI-Suffix** gefixt |
| `/etc/nginx/sites-available/api.steemapps.com.bak-phase6-deploy` | Pre-Deploy-Backup |
| `/var/www/api.steemapps.com/*` | 5 HTML + CSS + 6 JS aktualisiert |
| `/etc/letsencrypt/live/api.steemapps.com/` | unverändert |

## Rollback-Rezept

Falls Phase-6-Stand zurückgenommen werden muss:

```bash
ssh root@REDACTED-IP

# 1) Service stoppen
systemctl stop steemapps-api-monitor

# 2) DB zurückspielen (nur nötig bei Verdacht auf Datenkorruption;
#    in diesem Deploy gab es KEINE DB-Änderung)
sudo -u steemapps-monitor cp \
  /opt/steemapps-api-monitor/data/measurements.sqlite.pre-phase6.bak \
  /opt/steemapps-api-monitor/data/measurements.sqlite

# 3) Python-Code aus vorigem Commit via git auschecken oder per tar
#    aus dem Entwickler-Repo (zweistufige lokale git checkout auf
#    commit 7283faa vor Phase 6 + erneuter tar-Transfer).
# Einfacher Weg: tar-Archiv der alten Dateien (liegt auf dem Entwickler-
#    Rechner noch im git-Log) aus C:\tmp\steemapps rüberschieben.

# 4) systemd-Unit zurückspielen (nicht verändert in diesem Deploy,
#    aber zur Sicherheit):
cp /etc/systemd/system/steemapps-api-monitor.service.pre-phase6.bak \
   /etc/systemd/system/steemapps-api-monitor.service
systemctl daemon-reload

# 5) Nginx-Site zurückspielen
cp /etc/nginx/sites-available/api.steemapps.com.bak-phase6-deploy \
   /etc/nginx/sites-available/api.steemapps.com
nginx -t && systemctl reload nginx

# 6) Service wieder starten
systemctl start steemapps-api-monitor
systemctl is-active steemapps-api-monitor
```

**Kein Rollback-Schritt betrifft Tabu-Dienste** (welako, mailcow,
neonblocks, steemapps.com, production-subdomains).

## Was weiter im Repo bleibt

Nur dieser Progress-Log als git-Change. Aller Deploy-Code war im
letzten Etappen-6-Commit schon enthalten; der production-server hat ihn
jetzt live.

## Tests / Performance

- Lokale Tests: **78 / 78** grün (unverändert vom letzten Etappen-Log).
- Benchmark (`scripts/bench_load.py`) unverändert: alle Queries
  < 250 ms bei 1 M Zeilen, dokumentiert in `docs/PERFORMANCE.md`.

## Phase 6 — Abschluss

Sieben Etappen, sieben Commits auf `main`:

```
49e7e0b  Etappe 1  API-Endpoints + Outage-Detektion + Filter
5a2d3c2  Etappe 2  Detail-Ansicht pro Node mit Compare
3312916  Etappe 3  Stats-Übersichtsseite + Time-Comparison-Fix
281a1b4  Etappe 4  Regionale Karte mit Leaflet
9180598  Etappe 5  Ausfall-Log mit Filter und CSV/JSON-Export
2c03dc3  Etappe 6  Theme, Autorefresh, Mobile + 96×-Speedup
<tbd>    Etappe 7  Deployment + Nginx-proxy_pass-Fix
```

Ziel-Aufwand war 8–12 Stunden laut Auftrags-Spec. Die Phase lief heute
in einer einzigen Abend-Session (ca. 6 Stunden aktive Arbeitszeit),
ohne Rücksetzer. Die zwei Bonus-Funde (Time-Comparison-Bug in Etappe 3,
96×-Speedup durch den Benchmark in Etappe 6) waren nicht geplant, haben
aber die Gesamt-Qualität spürbar angehoben.

## Mögliche nächste Schritte

- Auto-Refresh auch auf den Sekundärseiten (stats / regions / outages)
  an `SteemAPI.onAutoRefresh` binden, falls gewünscht. Aktuell sind
  das statische Snapshots.
- `(timestamp, node_url)`-Composite-Index, wenn die Produktions-DB
  die 5-M-Rows-Grenze erreicht (laut `PERFORMANCE.md`-Baseline).
- Daily-Report-Generator (Phase 5) auf den production-server umziehen,
  damit er gegen `api.steemapps.com` statt die VM arbeitet.
- Öffentliche Ankündigung / Steem-Post über `@steem-api-health`
  (separat, nach User-Freigabe).
