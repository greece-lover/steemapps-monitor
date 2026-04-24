# Deploy notes — Phase 3

Target: single VM (`REDACTED-IP`), user `holger`, workdir
`/opt/steemapps-monitor/`. No reverse proxy yet; the API binds to
`127.0.0.1:8110` and is not exposed outside the VM.

## First-time install

```bash
cd /opt/steemapps-monitor
git clone git@github.com:greece-lover/steemapps-monitor.git .
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p data logs

sudo cp deploy/steemapps-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now steemapps-monitor.service
```

## Verify

```bash
systemctl status steemapps-monitor.service
curl -s http://127.0.0.1:8110/api/v1/health | jq
curl -s http://127.0.0.1:8110/api/v1/status | jq '.nodes[] | {url, status, score, latency_ms}'
```

## Update

```bash
cd /opt/steemapps-monitor
git pull --ff-only
.venv/bin/pip install -r requirements.txt
sudo systemctl restart steemapps-monitor.service
```

## Logs

```bash
journalctl -u steemapps-monitor.service -f
```

## Shutdown

```bash
sudo systemctl stop steemapps-monitor.service
sudo systemctl disable steemapps-monitor.service
```

The SQLite file under `data/` is the only mutable state; it survives
restarts and redeploys.
