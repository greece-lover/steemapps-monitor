# Changelog

All notable changes to this project will be documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses semantic milestones rather than strict SemVer until 1.0.

*Deutsche Version: [CHANGELOG.de.md](CHANGELOG.de.md)*

## [Unreleased]

### Pending for Phase 3 wrap-up (VM deployment)

- Clone repo, install venv, enable systemd unit on `/opt/steemapps-monitor/` (development VM was unreachable at the end of the Phase-3 coding session; follows as soon as the VM is back up)
- 30-minute runtime verification with `curl http://127.0.0.1:8110/api/v1/status` and row-count check

## [Phase 3] — 2026-04-24

### Added

- `monitor.py` — asyncio entry point, one event loop drives both the poll cycle (every 60 s) and an embedded uvicorn server
- `database.py` — SQLite schema + WAL mode, `measurements` and `nodes` tables, indexes on `timestamp`, `node_url`, and `(node_url, timestamp)`; insert/read helpers and `get_latest_per_node`, `get_uptime_stats`
- `scoring.py` — pure health-score computation matching methodology `mv1` (latency bands, block-lag bands, error-rate, no-response floor); score capped at 0
- `api.py` — FastAPI surface with `/api/v1/health`, `/api/v1/status`, `/api/v1/nodes/{url}/history`; human-readable `reasons` list per node
- `config.py` — central paths, intervals, node-list loader; `SOURCE_LOCATION` via env var for future multi-location monitoring
- `logger.py` — stdout logging wired for systemd-journal
- `nodes.json` — initial four Steem API nodes (api.steemit.com, api.justyy.com, api.steem.fans, api.steemyy.com)
- `deploy/steemapps-monitor.service` — systemd unit with hardening (`ProtectSystem=strict`, `ReadWritePaths`, `RestrictAddressFamilies`, `MemoryDenyWriteExecute`)
- `deploy/README.md` — install, update, logs, shutdown commands
- `tests/` — 18 pytest tests (scoring rules per methodology + database round-trip); plus `tests/smoke_one_tick.py` for a manual live check against the real nodes
- `requirements.txt` and `requirements-dev.txt`
- `progress/2026-04-24-phase3.md` — Phase 3 progress log

### Changed

- `docs/API.md` — Phase-3 endpoints documented with example JSON; the richer Phase-4 public surface remains listed separately for external consumers
- `docs/ARCHITECTURE.md` + `docs/ARCHITEKTUR.md` — process table updated (Phase 3: one unit instead of two) and a new "Module layout / Modul-Layout" section

### Verified locally

- 18/18 pytest green
- `smoke_one_tick.py`: all four nodes responded, block 105471530 synchronous, latency 394–629 ms

## [Phase 2] — 2026-04-24

### Added

- Project scaffolding: `README.md`, `CHANGELOG.md`, `ROADMAP.md` (all bilingual DE/EN)
- Documentation foundation under `docs/`: `ARCHITECTURE`, `CONTRIBUTING`, `SECURITY`, `USER-GUIDE` (all bilingual), `DEPLOYMENT`, `KI_TRANSPARENZ`, `MEASUREMENT-METHODOLOGY`/`MESSMETHODIK`, `API`
- `LICENSE` (MIT)
- Python-focused `.gitignore`
- SSH host alias `steemfork` in the author's SSH config for the development VM
- Server working directory `/opt/steemapps-monitor/` on the development VM (Ubuntu 24.04, REDACTED-IP)
- `progress/2026-04-24-phase1-bestandsaufnahme.md` — Phase 1 server audit
- `progress/2026-04-24-phase2.md` — Phase 2 timestamp log
- Private GitHub repository `greece-lover/steemapps-monitor`

### Known deviations from concept

- **Hosting target:** concept names the IONOS server (REDACTED-IP) as production host; initial development happens on the author's local Ubuntu VM. IONOS deployment is deferred to a later phase and will not touch the Alreco installation already running there.

## [Phase 1] — 2026-04-24

### Added

- Server audit of the development VM `steemfork` (REDACTED-IP, Ubuntu 24.04)
- Confirmation that existing workloads (`steem-fork`, `sqv-indexer`, `sqv-frontend`) are unaffected
- Network verification: all four initial Steem API nodes reachable with sub-second latency
