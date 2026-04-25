# Deployment

This describes the production deployment of the monitor, API server, and daily reporter.

## Target environment

- Linux server with Python 3.12, systemd, outbound HTTPS.
- Non-root user `steemapps-monitor` (create with `adduser --system --group --home /opt/steemapps-monitor steemapps-monitor` if this is a new host).
- Reverse proxy (nginx) in front of the JSON API, terminating TLS for `api.steemapps.com`.

During development, everything runs on the author's local Ubuntu VM at `/opt/steemapps-monitor/`; production target is a separate production server.

## Directory layout on the server

```
/opt/steemapps-monitor/
├── .venv/                     # Python virtualenv
├── monitor/                   # source
├── requirements.txt
├── .env.example               # committed template
├── .env.local                 # NOT in git, mode 0600
├── data/
│   └── monitor.db
└── logs/
    └── monitor.log            # rotated by logrotate
```

## Systemd units

Two units, one timer-driven cron. All under `/etc/systemd/system/`.

```ini
# steemapps-monitor.service
[Unit]
Description=Steem API Monitor (steemapps.com)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=steemapps-monitor
Group=steemapps-monitor
WorkingDirectory=/opt/steemapps-monitor
EnvironmentFile=/opt/steemapps-monitor/.env.local
ExecStart=/opt/steemapps-monitor/.venv/bin/python -m monitor
Restart=on-failure
RestartSec=10
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
ReadWritePaths=/opt/steemapps-monitor/data /opt/steemapps-monitor/logs

[Install]
WantedBy=multi-user.target
```

```ini
# steemapps-api.service
[Unit]
Description=Steem API Monitor — JSON API
After=network-online.target

[Service]
Type=simple
User=steemapps-monitor
Group=steemapps-monitor
WorkingDirectory=/opt/steemapps-monitor
ExecStart=/opt/steemapps-monitor/.venv/bin/uvicorn monitor.api:app --host 127.0.0.1 --port 8110
Restart=on-failure
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
ReadWritePaths=/opt/steemapps-monitor/data

[Install]
WantedBy=multi-user.target
```

The daily reporter runs as a systemd timer, not as a long-running service:

```ini
# steemapps-daily-report.timer
[Unit]
Description=Daily Steem API report to chain

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=yes

[Install]
WantedBy=timers.target
```

## Reverse proxy

nginx on the same server exposes the API as `api.steemapps.com`. The `.conf` lives in the ops repo, not here — this project does not ship a public nginx configuration because hostnames are deployment-specific. A template is given in `ops/nginx-api.steemapps.com.conf.template` (to be added).

## Firewall

- Inbound: 22 (SSH), 80+443 (reverse proxy).
- Outbound: HTTPS to the monitored nodes.
- The monitor binds only to `127.0.0.1:8110`; nginx reaches it via loopback.

## Logs

- App logs to `/opt/steemapps-monitor/logs/monitor.log`, rotated by logrotate daily, kept for 30 days.
- systemd keeps its own journal; query with `journalctl -u steemapps-monitor.service`.

## Upgrades

```bash
cd /opt/steemapps-monitor
sudo -u steemapps-monitor git pull --ff-only
sudo -u steemapps-monitor .venv/bin/pip install -r requirements.txt
sudo systemctl restart steemapps-monitor.service steemapps-api.service
```

Schema migrations run automatically on service start (idempotent). Any destructive migration is gated behind a manual step documented in the commit that introduces it.

## Backup

- `data/monitor.db` snapshot nightly via `sqlite3 monitor.db ".backup /var/backups/steemapps/monitor-$(date +%F).db"` from a cron outside the service.
- Keys (`.env.local`) are backed up by the author outside any automated system.

## Public vs. development host

| Item | Development (local VM) | Production |
|---|---|---|
| Host | `<dev-vm-ip>` | `<production-host>` |
| User | `<dev-user>` | `steemapps-monitor` |
| Reverse proxy | none | nginx on :80/:443 |
| TLS | none | Let's Encrypt |
| DNS | none | api.steemapps.com |
