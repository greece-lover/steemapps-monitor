# Steemapps Participant — community measurement node

This directory contains everything you need to contribute measurements to
the public dashboard at <https://api.steemapps.com/>. The script is
small (one Python file, one dependency) and can be installed in three
commands either via Docker or as a systemd service.

A German version follows the English one below.

---

## English

### What it does

Every 60 seconds, `monitor.py` issues one JSON-RPC `condenser_api.get_dynamic_global_properties` call to each of the 10 nodes the central dashboard tracks. It records latency, head-block height, success/failure, and any error category. Every five minutes the buffer is shipped to `https://api.steemapps.com/api/v1/ingest`. Your contributions appear in the dashboard's `/sources` page under your Steem handle.

### Before you start

You need an API key. Request one from `@greece-lover` on Steem (or via the contact channels listed at <https://steemapps.com/>) and tell us:

1. Your Steem account name (will be shown on the dashboard).
2. A short label for your server, e.g. `Hetzner FSN1`.
3. The geographic region of the server (e.g. `us-east`, `asia`, `eu-central`).

You will receive a single `sapk_…` key once. Store it on the host running the script and nowhere else; it cannot be recovered.

### Install via Docker (recommended)

```bash
git clone https://github.com/greece-lover/steemapps-monitor.git
cd steemapps-monitor/participant
cp .env.example .env && nano .env       # paste your STEEMAPPS_API_KEY
docker compose up -d --build
docker compose logs -f
```

That is the full installation. The container restarts on failure and uses well under 50 MB of RAM.

### Install via systemd

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin steemapps-participant
sudo install -d -o steemapps-participant -g steemapps-participant /opt/steemapps-participant
sudo -u steemapps-participant bash -c '
  cd /opt/steemapps-participant
  python3 -m venv .venv
  .venv/bin/pip install httpx
  cp /path/to/repo/participant/monitor.py .
  cp /path/to/repo/participant/.env.example .env
  chmod 600 .env
'
# Edit /opt/steemapps-participant/.env and paste your API key.
sudo cp /path/to/repo/participant/systemd-service.example /etc/systemd/system/steemapps-participant.service
sudo systemctl daemon-reload
sudo systemctl enable --now steemapps-participant
sudo journalctl -u steemapps-participant -f
```

### Verifying the install

After ~10 minutes you should see flush-loop log lines like:

```
2026-04-25T19:05:14Z [INFO] Flushed 50 (accepted=50, rejected=0, remaining=50)
```

And on <https://api.steemapps.com/sources.html> you will see your Steem handle with a non-zero `24h` measurement count.

### What we do with the data

- It is stored in the same SQLite database as the central monitor's data, tagged with your `display_label`.
- It powers per-region latency comparisons on the dashboard.
- It is not resold. The dashboard is read-only and public.
- You can ask to have your participation removed at any time. Re-issuing your key resets the attribution.

### What we ask of you

- Don't run more than one instance per Steem account.
- Don't tamper with measurements (e.g. fake low latency). The dashboard has plausibility checks; flagged participants are deactivated.
- Keep `.env` private. If you suspect the key leaked, ask for a re-issue.

### FAQ

**Q: Can I run this on a tiny VPS?**
A: Yes — < 30 MB RAM, < 1 % of one core. A 1 GB / 1 vCPU box is plenty.

**Q: Does it need an open port?**
A: No. The script only makes outbound HTTPS calls.

**Q: What happens if my server can't reach api.steemapps.com?**
A: Buffers stay in memory and retry on the next flush. After a long outage the oldest rows beyond ~1000 are dropped to keep the buffer bounded.

**Q: Will the script update itself?**
A: No. Pull the repo and rebuild the container or restart the service to take a new version.

---

## Deutsch

### Was das Skript tut

Alle 60 Sekunden ruft `monitor.py` bei jedem der 10 vom zentralen Dashboard überwachten Nodes ein JSON-RPC `condenser_api.get_dynamic_global_properties` ab. Es misst Latenz, Head-Block-Höhe, Erfolg/Fehler und Fehlerkategorie. Alle fünf Minuten wird der Buffer an `https://api.steemapps.com/api/v1/ingest` geschickt. Deine Beiträge erscheinen unter deinem Steem-Handle auf der `/sources`-Seite des Dashboards.

### Vor dem Start

Du brauchst einen API-Key. Beantrage einen bei `@greece-lover` auf Steem (oder über die Kontaktkanäle auf <https://steemapps.com/>) und gib uns:

1. Deinen Steem-Account-Namen (wird im Dashboard angezeigt).
2. Ein kurzes Label für deinen Server, z. B. `Hetzner FSN1`.
3. Die geografische Region des Servers (z. B. `us-east`, `asia`, `eu-central`).

Du bekommst einmalig einen `sapk_…`-Key. Speichere ihn ausschließlich auf dem Host, der das Skript ausführt; er lässt sich nicht wiederherstellen.

### Installation per Docker (empfohlen)

```bash
git clone https://github.com/greece-lover/steemapps-monitor.git
cd steemapps-monitor/participant
cp .env.example .env && nano .env       # STEEMAPPS_API_KEY eintragen
docker compose up -d --build
docker compose logs -f
```

Das ist die komplette Installation. Der Container startet bei Fehlern neu und braucht unter 50 MB RAM.

### Installation per systemd

Siehe englischer Abschnitt oben — die Befehle sind identisch.

### Überprüfung

Nach ca. 10 Minuten siehst du Log-Zeilen wie:

```
2026-04-25T19:05:14Z [INFO] Flushed 50 (accepted=50, rejected=0, remaining=50)
```

Und auf <https://api.steemapps.com/sources.html> erscheint dein Steem-Handle mit einem `24h`-Mess-Count > 0.

### Was wir mit den Daten machen

- Sie werden in die gleiche SQLite-Datenbank des zentralen Monitors geschrieben, markiert mit deinem `display_label`.
- Sie speisen die regionalen Latenz-Vergleiche im Dashboard.
- Sie werden nicht weiterverkauft. Das Dashboard ist read-only und öffentlich.
- Du kannst deine Teilnahme jederzeit beenden lassen. Ein neuer Key setzt die Attribution zurück.

### Was wir von dir erwarten

- Nur eine Instanz pro Steem-Account.
- Keine Manipulation (z. B. gefälschte niedrige Latenz). Das Dashboard prüft auf Plausibilität; auffällige Teilnehmer werden deaktiviert.
- `.env` privat halten. Bei Verdacht auf Leakage neuen Key beantragen.

### FAQ

**Reicht ein kleines VPS?** Ja — < 30 MB RAM, < 1 % einer CPU. 1 GB / 1 vCPU genügt.

**Braucht es einen offenen Port?** Nein. Das Skript macht nur ausgehende HTTPS-Verbindungen.

**Was passiert, wenn der Server api.steemapps.com nicht erreicht?** Buffer bleibt im RAM, Retry beim nächsten Flush. Nach langen Ausfällen werden die ältesten Zeilen über ~1000 verworfen, damit der Buffer nicht überläuft.

**Aktualisiert sich das Skript selbst?** Nein. Repo aktualisieren, Container neu bauen oder Service neu starten.
