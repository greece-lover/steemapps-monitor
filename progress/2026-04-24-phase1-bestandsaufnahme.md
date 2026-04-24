# Server-Bestandsaufnahme — Ubuntu-VM `steemfork` (REDACTED-IP)

Phase 1 abgeschlossen, ausschliesslich lesend durchgefuehrt. Rohdaten: `_probe_raw.txt`. Erhoben am 2026-04-24 als User `holger` via SSH-Key `~/.ssh/id_ed25519` (passwortlos, vorhandene Einrichtung aus SARH-Projekt).

## 1. Kurz-Zusammenfassung

Die VM ist eine lokale Ubuntu-24.04-Entwicklungsumgebung auf VMware Workstation, hostname `steemfork`. Sie beherbergt zwei aktive Steem-nahe Projekte: den **steem-fork**-Witness-Node (isoliertes Testnet) und den **SQV** (SteemitBoard/QualityView) Indexer + Frontend. Ressourcen sind mehr als reichlich: 8 Cores, 23 GB RAM (wovon aktuell nur ~1 GB genutzt), 257 GB freier Disk. Python 3.12 ist vorhanden, Docker laeuft. Alle getesteten Steem-API-Nodes sind erreichbar (HTTP 200, 450–620 ms). Es gibt keinen Webserver (nginx/apache) und keine SQL-Datenbanken — fuer den Monitor irrelevant, da SQLite in Python eingebaut ist. **Kein Alreco auf dieser VM** — Alreco lebt weiterhin auf dem IONOS-Server (REDACTED-IP) und wird durch Arbeit hier nicht beruehrt.

**Fazit Ressourcen:** Ausreichend fuer Steemapps-Monitor, mit grosser Reserve.

## 2. System-Details

| Kennwert | Wert |
|---|---|
| OS | Ubuntu 24.04.4 LTS (Noble) |
| Kernel | 6.8.0-110-generic |
| Virtualisierung | VMware (VM auf dem Host-PC) |
| Hostname | `steemfork` |
| Boot | 2026-04-22 16:18, Uptime 21 h |
| CPU | AMD Ryzen 7 7840HS, 8 vCPU (zum Host durchgereicht) |
| RAM | 24 GB total, 1 GB used, 9 GB frei, 13 GB buff/cache, **22 GB available** |
| Swap | 8 GB (0 B benutzt) |
| Disk | `/dev/sda2` 295 GB ext4, **23 GB used (9 %), 257 GB frei** |
| Load | 0,06 / 0,02 / 0,00 — praktisch idle |

**Installierte Sprachen/Tools:**

- Python 3.12.3 (`/usr/bin/python3`), pip3, pip — **ausreichend fuer Monitor**
- Git 2.43
- Docker 29.4.1 + docker-compose-plugin + buildx
- **Nicht installiert:** nginx, apache, caddy, node/npm, go, rust, java, php, mysql, mariadb, postgres, redis, sqlite3-CLI (Python-Modul `sqlite3` ist verfuegbar und reicht)

## 3. Laufende Services und ihre Funktion

| Service | Einschaetzung | Ports | Anmerkung |
|---|---|---|---|
| `steem-fork.service` | **Nicht anfassen — aktives Steem-Fork-Projekt** | 2001 (P2P), 8090, 8091 (RPC) | `steemd` laeuft in Docker-Container `steem-fork` auf Basis `steem-builder:ubuntu1804`. Quellcode in `/opt/steem-fork`. |
| `sqv-indexer.service` | **Nicht anfassen — aktives SQV-Projekt** | 8100 | FastAPI (uvicorn) + block streamer, `.venv`-basiert unter `/opt/sqv-indexer` |
| `sqv-frontend.service` | **Nicht anfassen — aktives SQV-Projekt** | 3000 | Statisches `dist/` unter `/opt/sqv-frontend`, via `python http.server` ausgeliefert |
| `cli_wallet` (Docker-Container `cliw`) | Gehoert zu steem-fork | 127.0.0.1:8093 | Nur an Loopback gebunden |
| `docker.service`, `containerd.service` | Fundament der obigen Container | — | Standardbetrieb |
| `ssh.service` | Systemdienst | 22 | |
| `ufw.service` | **Enabled** — Firewall-Status nicht einsehbar (sudo erforderlich) | — | Siehe offene Fragen |
| `cron.service`, `rsyslog`, `systemd-*`, `open-vm-tools`, `ModemManager`, `snapd` usw. | Standard-System | — | |

Keine `failed`-Services. Keine user-Units laufen.

## 4. Vorhandene Verzeichnisse und Inhalte

**`/opt/` (Projekt-Top-Level):**

```
/opt/containerd          — von Docker
/opt/steem-fork          — Steem-Fork Quellcode + Build + Witness-Daten, mit .git
/opt/sqv-indexer         — FastAPI-Indexer, mit eigener .venv
/opt/sqv-frontend        — Statische Frontend-Distribution
```

Alle drei Projektverzeichnisse gehoeren `holger:holger`. `/opt/steem-fork` enthaelt u. a. `build/`, `witness-data/` (Blockchain-Daten), vollstaendige libraries, `.git`.

**`/srv/`** — leer.
**`/var/www/`** — existiert nicht.
**`/home/holger/`** — Standard-Userdirectory (`.ssh`, `.cache/pip`, `.local/share/beem`, `.cmake`). Kein `/home/root/`, kein anderer Login-User auf dem System.

**Git-Repos auf der VM:** genau eines — `/opt/steem-fork/.git`. SQV-Verzeichnisse enthalten kein `.git` (moeglicherweise anderswo oder nicht versioniert — fuer Phase 1 irrelevant).

## 5. Domain-Konfiguration

Keine. Die VM ist eine lokale Entwicklungsumgebung ohne nginx/apache/caddy, ohne Let's-Encrypt-Verzeichnis, ohne Reverse-Proxy. `/etc/hosts` enthaelt nur `127.0.0.1 localhost` und `127.0.1.1 steemfork`. Alle Projekt-Ports (3000, 8090, 8091, 8100, 2001) binden auf `0.0.0.0`, sind also innerhalb des VM-Host-Netzes (REDACTED-SUBNET) erreichbar — aber nicht oeffentlich.

## 6. Ausgehende Netzwerk-Verifikation

Alle vier geprueften Steem-API-Nodes antworten mit HTTP 200 auf JSON-RPC:

| Node | HTTP | Latenz |
|---|---|---|
| api.steemit.com | 200 | 0,62 s |
| api.justyy.com | 200 | 0,49 s |
| api.steem.fans | 200 | 0,59 s |
| api.steemyy.com | 200 | 0,46 s |

DNS-Aufloesung funktioniert fuer alle Nodes; `steemd.pevo.science` loest nicht auf (vermutlich wirklich weg oder Tippfehler im Listenvorschlag — Check empfohlen). ICMP-Ping an `api.steemit.com` scheitert (AWS-ELB blockt ICMP, das ist normal — TCP/443 funktioniert).

Der Monitor kann von dieser VM aus also direkt gegen die echten Steem-API-Nodes messen.

## 7. Cron, Firewall, Sicherheits-Konfiguration

- `crontab -l` fuer `holger`: leer.
- `/etc/cron.d/`, `/etc/cron.daily/` etc.: nur Standard-System-Jobs (logrotate, man-db, apt-compat, sysstat, apport, e2scrub, dpkg).
- `ufw.service` ist enabled, aber Status/Regeln brauchen sudo — nicht einsehbar ohne Passwort.
- `iptables`, `nft`: ebenfalls sudo-geschuetzt.
- sshd-Konfig: brauch sudo zum Lesen.
- `/home/holger/.ssh/authorized_keys`: enthaelt 1 Zeile (der vorhandene Key).
- Eingeloggte User: `holger` auf tty1 (Konsole, idle 40 min) + die aktuelle SSH-Session.

## 8. Offene Fragen an den Autor

**Alle leicht und jeweils mit konkreter Empfehlung:**

1. **Tabu-Liste bestaetigen:** Aus meiner Sicht sind `/opt/steem-fork/`, `/opt/sqv-indexer/`, `/opt/sqv-frontend/` sowie die drei zugehoerigen systemd-Units (`steem-fork`, `sqv-indexer`, `sqv-frontend`) und die belegten Ports (2001, 3000, 8090, 8091, 8100) tabu. **Empfehlung:** Bestaetige diese Liste; dann schlage ich fuer Steemapps als Arbeitsverzeichnis `/opt/steemapps-monitor/` und als Service-Namen `steemapps-monitor.service` vor. Fuer einen optionalen lokalen HTTP-Port waehle ich z. B. 8110 (kollisionsfrei).

2. **sudo-Rechte fuer holger:** `sudo` verlangt Passwort (keine NOPASSWD-Regel). Fuer Phase 3 brauche ich Rechte, um `systemd`-Units unter `/etc/systemd/system/` anzulegen und zu aktivieren. **Empfehlung:** In Phase 2 einfach `sudo`-Passwort via `! sudo -v` in der Session auffrischen, wenn noetig — dauerhafte NOPASSWD-Regel nicht erforderlich.

3. **UFW-Status:** Ob UFW Regeln hat, konnte ich nicht sehen. **Empfehlung:** Fuer Phase 2 kurz `sudo ufw status verbose` laufen lassen und das Ergebnis hier einfuegen, damit ich weiss, ob spaetere lokale Ports zusaetzliche Regeln brauchen.

4. **SSH-Key-Setup „wie bei SARH“ ist bereits erledigt.** Dein vorhandener Key `~/.ssh/id_ed25519` funktioniert passwortlos gegen `holger@REDACTED-IP`. Eine separate Phase 2 (SSH-Einrichtung) braucht es nur, falls du einen **eigenen** Key speziell fuer Steemapps haben willst (Vorteil: Trennung; Nachteil: wartungsaufwendiger). **Empfehlung:** Den vorhandenen Key weiterverwenden und Phase 2 auf einen Host-Alias (`ssh steemfork` statt `ssh holger@REDACTED-IP`) reduzieren.

5. **Knoten-Liste:** `steemd.pevo.science` ist per DNS nicht erreichbar. **Empfehlung:** Aus der initialen Node-Liste des Monitors entfernen oder den korrekten Hostnamen liefern.

## 9. Zustand des lokalen Arbeitsverzeichnisses `C:\tmp\steemapps\`

Das Verzeichnis existierte bereits und enthielt zwei Artefakte aus einer vorherigen Session, in der die Server-IP falsch gesetzt war (REDACTED-IP statt REDACTED-IP): `_probe.py` (Paramiko-Probe-Skript mit falschem Host und User `root`) und `_probe_output.txt` (Authentication-Failed-Meldung). Beide sollten geloescht werden — sie sind irrefuehrend. Das aktuelle, funktionierende Probe-Skript liegt als `_probe_remote.sh`, Rohdaten als `_probe_raw.txt`.

**Empfehlung:** `_probe.py` und `_probe_output.txt` loeschen. `_probe_remote.sh` und `_probe_raw.txt` zur Nachvollziehbarkeit behalten, bis Phase 3 abgeschlossen ist.

---

**Naechster Schritt:** Warten auf Freigabe fuer Phase 2.
