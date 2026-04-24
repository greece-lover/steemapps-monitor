# 2026-04-24 — Deployment api.steemapps.com (production-server)

Deployment des Steem-API-Monitor-Dashboards unter `https://api.steemapps.com/`
auf dem Produktionsserver `REDACTED-IP`. Entwickelt wurde Phasen 1–4
auf der VM `REDACTED-IP`; diese VM bleibt als Dev-Umgebung bestehen.

## Entscheidung: Option B (Server-seitige Zweit-Instanz)

Statt die VM über einen SSH-Tunnel oder VPN zu exponieren, läuft auf dem
production-server eine eigene Monitor-Instanz. Vorteile: Unabhängigkeit vom
Heim-PC, keine Tunnel-Komplexität, keine Exposition der VM.

Die `source_location`-Spalte (aus dem bestehenden DB-Schema) trennt die
beiden Messstellen:

- VM: `source_location = 'contabo-de-1'` (Default)
- Produktion: `source_location = 'production-source'` (per ENV gesetzt)

Damit lassen sich beide Datenströme später vergleichen — regionale
Erreichbarkeit ist interessanter, wenn sie aus zwei Positionen gemessen wird.

## Durchgeführte Schritte

### Code-Anpassungen im Repo

- `config.py`: `API_PORT` nimmt jetzt `STEEMAPPS_API_PORT` als ENV-Override
  (Default bleibt 8110 für lokale Entwicklung).
- `frontend/js/main.js`: `DEFAULT_API = ''` statt
  `'http://localhost:8110'` — ausgelieferte Seite benutzt jetzt same-origin,
  der `?api=...`-Query-Parameter bleibt für lokale Tunnel-Tests erhalten.

### production-server

1. System-User `steemapps-monitor` (uid 999, `/usr/sbin/nologin`,
   `home=/opt/steemapps-api-monitor`) via `useradd --system`.
2. Verzeichnisse `/opt/steemapps-api-monitor/` (755) + `data/` + `logs/` (0750).
3. Code-Transfer via `tar -cz | ssh 'tar -xz'`:
   `monitor.py`, `api.py`, `config.py`, `database.py`, `logger.py`,
   `scoring.py`, `nodes.json`, `requirements.txt`.
4. Python-venv + `pip install -r requirements.txt`
   (fastapi 0.120.4, httpx 0.28.1, uvicorn 0.37.0, pydantic 2.13.3).
   Dafür musste `python3-venv` per apt nachinstalliert werden.
5. systemd-Unit `/etc/systemd/system/steemapps-api-monitor.service` mit vollem
   Sandbox-Set:
   - `NoNewPrivileges=true`, `ProtectSystem=strict`, `ProtectHome=true`,
     `PrivateTmp=true`, `PrivateDevices=true`,
     `ProtectKernel{Tunables,Modules,Logs}`, `ProtectControlGroups`,
     `ProtectHostname`, `ProtectClock`, `LockPersonality`,
     `RestrictRealtime`, `RestrictSUIDSGID`, `RestrictNamespaces`,
     `MemoryDenyWriteExecute`, `SystemCallFilter=@system-service ~@privileged`,
     `CapabilityBoundingSet=` (leer), `AmbientCapabilities=` (leer).
   - `ReadWritePaths=/opt/steemapps-api-monitor/data
      /opt/steemapps-api-monitor/logs` — sonst wäre alles read-only.
   - ENV: `STEEMAPPS_API_PORT=8111`, `STEEMAPPS_SOURCE_LOCATION=production-source`.
6. `systemd-analyze verify` OK, `systemctl enable --now`.
7. Frontend nach `/var/www/api.steemapps.com/` (www-data:www-data, 755/644).
8. Nginx-Site `/etc/nginx/sites-available/api.steemapps.com`:
   - `listen 80` + `server_name api.steemapps.com`
   - `root /var/www/api.steemapps.com`
   - `location /` → static mit `try_files $uri $uri/ /index.html`
   - `location ~* \.(js|css|woff|...)$` → `expires 5m`
   - `location /api/` → `proxy_pass http://127.0.0.1:8111/api/` mit
     X-Forwarded-*-Headern
9. Symlink nach `sites-enabled`, `nginx -t` OK, `reload`.
10. `certbot --nginx -d api.steemapps.com -n --agree-tos --redirect`:
    Let's-Encrypt-Zertifikat bis 2026-07-23, Auto-Renew aktiv, Nginx-Config
    um `listen 443 ssl` + HTTP→HTTPS-Redirect erweitert.

## Startup-Vorfall (intern)

Die ersten 19 systemd-Restarts schlugen mit
`ModuleNotFoundError: No module named 'scoring'` fehl — `scoring.py` war beim
initialen `tar`-Select versehentlich nicht in der Liste. Nachgeschoben,
`systemctl reset-failed`, seither läuft der Service stabil.
Zum Zeitpunkt der Crashs gab es keinen öffentlich erreichbaren Listener
(Loopback-only, keine Nginx-Verkettung aktiv), also kein Impact nach außen.

## Verifikation (End-to-End)

```
$ curl -I http://api.steemapps.com/
HTTP/1.1 301  ->  https://api.steemapps.com/

$ curl -sI https://api.steemapps.com/
HTTP/1.1 200 OK  (2141 B, text/html)

$ curl -s https://api.steemapps.com/api/v1/status | jq .
methodology=mv1, reference_block=105476030, nodes=10, green=10
```

Datenbank 3 Minuten nach Start:
```
('production-source', 30, 30, '2026-04-24T17:59:43Z', '2026-04-24T18:01:44Z')
```
3 Polling-Runs × 10 Nodes = 30 Messungen, alle `success=1`.

### Nachbardienste unverändert

- `https://steemapps.com/` — **200**, V3-Design (`For Everyone`, `WelBook`,
  `WelSnap`, `project_welako`) unverändert.
- `https://neonblocks.steemapps.com/` — **200**.
- `https://welako.app/` — **200**.
- 24 Tabu-Docker-Container (mailcow + steemauth + neonblocks) unberührt —
  keine Config-Datei eines Tabu-Dienstes angefasst.
- Bestehender `/etc/nginx/sites-available/steemapps.com`-Block unverändert.

## Server-Stand

| | |
|---|---|
| Neue systemd-Unit | `/etc/systemd/system/steemapps-api-monitor.service` |
| Neuer User | `steemapps-monitor` (uid 999) |
| Neuer Nginx-Block | `/etc/nginx/sites-available/api.steemapps.com` (SSL, Redirect) |
| Backup der Nginx-Site vor Certbot | `/etc/nginx/sites-available/api.steemapps.com.bak-pre-certbot` |
| Neues Zertifikat | `/etc/letsencrypt/live/api.steemapps.com/` (bis 2026-07-23) |
| Neues docroot | `/var/www/api.steemapps.com/` |
| Neuer App-Pfad | `/opt/steemapps-api-monitor/` (Code + venv + SQLite unter `data/`) |

## Rollback-Rezept

Falls die api.steemapps.com-Site entfernt werden muss, ohne Nachbardienste
anzufassen:

```bash
# 1. Service stoppen
systemctl disable --now steemapps-api-monitor.service

# 2. Nginx-Site deaktivieren
rm /etc/nginx/sites-enabled/api.steemapps.com
nginx -t && systemctl reload nginx

# 3. Zertifikat entfernen (optional, bleibt sonst 90 Tage)
certbot delete --cert-name api.steemapps.com

# 4. Dateien entsorgen (nur wenn wirklich alles weg soll)
rm -rf /opt/steemapps-api-monitor
rm -rf /var/www/api.steemapps.com
rm /etc/systemd/system/steemapps-api-monitor.service
rm /etc/nginx/sites-available/api.steemapps.com*
userdel steemapps-monitor
```

Die Tabu-Dienste (Welako, mailcow, neonblocks, steemapps.com, …) sind in
keinem dieser Kommandos berührt.

## Nächste Schritte

- Produktion 24–48 h laufen lassen, Log-Stichproben, Memory-Verlauf beobachten.
- Sobald zwei Tage Daten vorliegen: Daily-Report-Generator (Phase 5) an diese
  Produktions-Instanz hängen.
- DNS-TTL bei IONOS zurück auf 3600 oder höher stellen (während des Setups
  auf 300 gesetzt).
