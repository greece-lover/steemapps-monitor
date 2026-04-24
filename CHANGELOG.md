# Changelog

All notable changes to this project will be documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses semantic milestones rather than strict SemVer until 1.0.

*Deutsche Version: [CHANGELOG.de.md](CHANGELOG.de.md)*

## [Unreleased]

### Planned for Phase 3

- Python monitor core (`monitor/main.py`), poll loop, JSON-RPC client against the Steem node interface
- SQLite schema for per-minute measurements
- Health-score computation per [docs/MEASUREMENT-METHODOLOGY.md](docs/MEASUREMENT-METHODOLOGY.md)
- systemd service `steemapps-monitor.service`
- Initial node list: api.steemit.com, api.justyy.com, api.steem.fans, api.steemyy.com

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
