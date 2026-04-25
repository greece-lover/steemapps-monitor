# Deploy notes — Phase 3 + Phase 5

Target: a single VM, see `deploy/steemapps-monitor.service` for paths.
The monitor runs as `holger`, the reporter as a dedicated unprivileged
`steemapps-reporter` user. No reverse proxy yet; the API binds to
`127.0.0.1:8110` and is not exposed outside the VM.

## First-time install — monitor (Phase 3)

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

## First-time install — reporter (Phase 5)

The reporter is a separate systemd unit (`oneshot`) triggered by a daily
timer. It runs as an unprivileged system user so the posting key never
sits under `holger`'s home directory or process tree.

```bash
# 1. Create the system user (no login shell, no home directory).
sudo useradd -r -s /usr/sbin/nologin steemapps-reporter

# 2. Install the reporter's Python deps into the existing venv.
cd /opt/steemapps-monitor
sudo -u holger .venv/bin/pip install -r requirements-reporter.txt

# 3. Stage the env file. The posting key is filled in by Holger
#    manually, by hand, never by paste into a chat log.
sudo cp reporter/.env.example reporter/.env.local
sudo chown steemapps-reporter:steemapps-reporter reporter/.env.local
sudo chmod 600 reporter/.env.local
sudo -u steemapps-reporter $EDITOR reporter/.env.local
# -> set STEEMAPPS_REPORTER_MODE=prod (or leave at dev for a first run)
# -> set STEEMAPPS_REPORTER_POSTING_KEY=<the posting key for @steem-api-health>

# 4. Install the unit and the timer.
sudo cp deploy/steemapps-reporter.service /etc/systemd/system/
sudo cp deploy/steemapps-reporter.timer /etc/systemd/system/
sudo systemctl daemon-reload

# 5. Enable the timer. The *service* is oneshot — it is not enabled
#    directly; the timer drives it.
sudo systemctl enable --now steemapps-reporter.timer
```

### Dry-run the reporter on the VM

```bash
sudo -u steemapps-reporter STEEMAPPS_REPORTER_MODE=dev \
    /opt/steemapps-monitor/.venv/bin/python -m reporter.daily_report --dry-run
```

### Trigger the reporter manually (prod mode)

```bash
sudo systemctl start steemapps-reporter.service
journalctl -u steemapps-reporter.service -n 100 --no-pager
```

### List scheduled runs

```bash
systemctl list-timers steemapps-reporter.timer --no-pager
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
