# Changelog

All notable changes to this project will be documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses semantic milestones rather than strict SemVer until 1.0.

*Deutsche Version: [CHANGELOG.de.md](CHANGELOG.de.md)*

## [Unreleased]

## [Phase 6 Etappe 9] — 2026-04-25

### Added

- `reporter/observations.py` — observation engine with eight categories (`top_performer`, `laggard`, `latency_change`, `new_outage`, `consistent_leader`, `consistent_laggard`, `global_trend`, `biggest_outage`). Categories whose prerequisites are missing (e.g. no yesterday data) are silently skipped — no fake comparisons in the post
- `reporter/image_generator.py` — Pillow-based PNG renderer for the daily cover image (1200×675, brand-aligned: dark gradient, lime accent, "FASTEST"/"SLOWEST" tiles)
- `scripts/dry_run_daily_report.py` — end-to-end preview against 14 days of synthetic data in a tmp DB
- `tests/test_observations.py` (18 tests), `tests/test_image_generator.py` (3 tests), `tests/test_aggregation_etappe9.py` (4 tests)

### Changed

- `reporter/template.py` — fully switched to English (no more German section in the post). New section order per spec: cover image → executive summary → perspective notice → observations → detail table → biggest outage → week over week → methodology → participation block → feedback → resources → footer
- `reporter/aggregation.py` — `NodeStats.source_count` counts distinct `source_location` values per node window; surfaced in the `custom_json` payload. Multi-source latency label `(avg of N sources)` switches on automatically at N≥2
- `reporter/config.py` — `image_dir` and `image_url_base` fields (env-overridable). Defaults point at the production webroot
- `reporter/daily_report.py` — image generation runs **before** the chain broadcast (fail-fast on Pillow errors). Hookup for observations and multi-source logic. New `--image-only` flag for a cover preview without broadcast
- `requirements-reporter.txt` — `Pillow>=10,<12`

### Plan corrections before commit (post first dry-run review)

- Executive summary reduced from "repeat observations" to headline numbers only (uptime, measurement count, median latency). Specifics live in the bulleted Observations section
- Observation bullets switched from `↑/↓` arrows to `**Label:**` bold-prefix — fits the technical voice and avoids Unicode render risk in Steemit
- Perspective notice: the over-optimistic "first community contributors are now being onboarded" replaced with "Want to contribute measurements from your region? See the participation block below."
- Week-over-week formatting: exact zero deltas now render as `±0.00 pp` instead of `+-0.00 pp` (float `-0.0` as the source)

### Locally verified

- 151/151 pytest green (+33 vs Etappe 8, no regressions)
- `scripts/dry_run_daily_report.py`: 14 days of synthetic data → 9 observations for the previous day, clean cover PNG (38 KB), 5.5 KB markdown body in the correct section order

### Pending for cutover on the production server

- Code transfer via `tar | ssh`
- Install `Pillow>=10,<12` into the reporter venv
- Create `/var/www/api.steemapps.com/reports/`, set www-data ownership
- `--image-only` smoke test
- Full dry-run against the live DB for today's date, output presented for approval
- First real broadcast triggered manually (posting key entered by Holger over SSH directly into `.env.local`, never via chat)
- Enable the timer once the first real post is verified on steemit.com

## [Phase 6 Etappe 8] — 2026-04-25

### Added

- `participants.py` — manage external measurement contributors: key generation (`sapk_…` prefix, 256-bit entropy), bcrypt hashing alongside a SHA-256 lookup index for O(1) auth at any participant count, CRUD helpers over the new `participants` table
- `ingest.py` — standalone validation and rate-limit layer: per-participant token bucket (700/h, burst 100), timestamp tolerance `−15 min … +60 s`, plausibility bounds for latency, reject-reason enum surfaced in API responses
- `database.py` — new `participants` table with `UNIQUE` constraint on `steem_account`; new composite index `(source_location, timestamp)`
- `api.py` — six new endpoints: `POST /api/v1/ingest`, `POST/GET/PATCH/DELETE /api/v1/admin/participants[/{id}]`, `GET /api/v1/sources`, `GET /api/v1/nodes`. Admin auth fail-closed against the `STEEMAPPS_ADMIN_TOKEN` env var; constant-time compare via `secrets.compare_digest`
- `participant/` — subdirectory with the contributor measurement script: `monitor.py` (177 effective lines, single dependency httpx), `Dockerfile`, `docker-compose.yml`, `systemd-service.example`, `.env.example`, bilingual README
- `frontend/sources.html` + `js/sources.js` — new dashboard page listing measurement sources (linked Steem handle, region, 24h/7d counts)
- `common.js` — attribution footer rendered on every page; loads `/api/v1/sources` and appends inside the existing `.footnote` block
- "Sources" nav link added to every dashboard page
- `docs/PARTICIPATE.md` + `docs/TEILNEHMEN.md` — bilingual contributor onboarding (prerequisites, install, FAQ)
- `docs/API.md` — full documentation of the six new endpoints
- `scripts/dry_run_participant.py` — end-to-end dry run against an in-process TestClient (mock participant, three measurements, verified in DB and `/api/v1/sources`)
- `tests/test_api_etappe8.py` — 31 new pytest tests: ingest happy/sad paths, auth behaviour, rate-limit trigger, admin CRUD, sources endpoint, pure-module tests for `RateLimiter` and `validate_row`
- `requirements.txt` — `bcrypt>=4.2,<5` as a new backend dependency

### Plan corrections before implementation

- Rate limit raised from the original 120/h to **700/h** — the participant script produces 600 measurements/h (10 nodes × 60 s), so 120/h would have produced an immediate 429. Burst capacity 100 covers two full 5-minute batches plus retry headroom
- Timestamp tolerance widened from the original 5 min to **−15 min / +60 s** — the script's 5-minute batch plus network latency plus NTP drift would have rejected the oldest rows in nearly every batch
- `UNIQUE` constraint on `steem_account` enforced directly in the DB schema rather than only in application logic, so duplicate registration fails at the engine level

### Design decisions

- API keys are double-hashed: bcrypt to satisfy the spec, SHA-256 hex as a lookup index. Lookup is therefore O(1) on a UNIQUE index and verification stays constant-time via `bcrypt.checkpw`. Rationale documented in the schema comment in `database.py` and the module docstring of `participants.py`
- `verify_api_key` returns the same `None` for "key unknown", "key wrong", and "key deactivated"; the API layer surfaces them all as a single 401 message — otherwise an attacker could enumerate active accounts by probing
- Ingest writes with `source_location = participant.display_label`, not the Steem handle — the operator can rename the display label without re-tagging historical rows
- Pydantic models were moved to module scope after a first attempt defined them inside `build_app()` and FastAPI's OpenAPI introspection failed to see them as body parameters (symptom: every POST 422'd with "Field required: query.body")

### Locally verified

- 109/109 pytest green (78 prior + 31 new, no regressions)
- `scripts/dry_run_participant.py` succeeded: mock participant registered, three measurements ingested, correctly persisted with `display_label` in the DB, counted in `/api/v1/sources`
- Participant script: syntax compile OK, 177 effective lines of code (under the spec's 200-line guideline)

### Cutover on production server (live since 2026-04-25 04:06 UTC)

- Service restart in **226 ms** wall time; no tick missed (5,990 → 6,000 rows +10 in one tick)
- `participants` table created on first startup via `CREATE TABLE IF NOT EXISTS` (idempotent)
- `bcrypt 4.3.0` installed into the server venv
- `STEEMAPPS_ADMIN_TOKEN` written to `<production-path>/.env.local` (mode 600, owner steemapps-monitor) — value retrievable via SSH, not in repo
- systemd unit gained `EnvironmentFile=-<production-path>/.env.local` (dash prefix = optional)
- End-to-end smoke test with mock participant succeeded (POST → ingest 3 rows → visible in `/sources` → DELETE)
- Tabu verification: 24 containers and 12 nginx sites unchanged from the pre-flight baseline, all sister domains still HTTP 200
- Live at `https://api.steemapps.com/sources.html` and `/api/v1/{ingest,sources,nodes,admin/participants}`
- Backups under `<production-path>/*.pre-etappe8.bak` and `<server>:<backup-path>/etappe8-www-pre.tar.gz`; rollback recipe kept in internal deployment notes

### Still pending

- Publish the call-for-participation post after author review (once the repo is public)

### Pending for Phase 5 production cutover

- `reporter/.env.local` on the VM, posting key entered manually by Holger (never transmitted in chat)
- First dry-run on the VM against the live measurements DB
- First `STEEMAPPS_REPORTER_MODE=prod` broadcast triggered manually via `systemctl start steemapps-reporter.service`
- Timer enabled once the first real post is verified on steemit.com

## [Phase 5] — 2026-04-24

### Added

- `reporter/` — new Python package: `config.py` (env loading, `.env.local` reader, `ReporterConfig` dataclass), `query.py` (read-only SQL over the UTC day window), `aggregation.py` (pure per-node/global/week-over-week rollups, `custom_json` payload builder), `template.py` (bilingual DE/EN post renderer), `broadcast.py` (beem lazy-import wrapper with 3×60s retry and permanent/transient error classification), `daily_report.py` (CLI entry + `--seed-synthetic` dev helper)
- `reporter/.env.example` — commented env template; `.env.local` is the live copy on the VM, always chmod 600 and owned by `steemapps-reporter`
- `requirements-reporter.txt` — `beem>=0.24.26,<0.30`, kept separate from `requirements.txt` so the monitor service's footprint is unchanged
- `deploy/steemapps-reporter.service` — oneshot systemd unit running as `steemapps-reporter` with an `EnvironmentFile=` pointing at `.env.local`; same hardening base as the monitor unit plus `ReadOnlyPaths=` for the measurements DB
- `deploy/steemapps-reporter.timer` — daily trigger at 02:30 UTC with `Persistent=true` so a missed run is retried on next boot
- `deploy/README.md` — reporter install, dry-run, and manual-trigger instructions
- `docs/DAILY-REPORT.md` + `docs/TAGES-REPORT.md` — methodology, schedule, `custom_json` schema, error-handling semantics, manual-run recipes
- `tests/test_aggregation.py` (9 tests), `tests/test_template.py` (9 tests), `tests/test_broadcast.py` (7 tests) — new coverage for the reporter layer

### Design decisions

- Dedicated `@steem-api-health` reporter account instead of `@greece-lover` — separation of the witness identity from the automation output; a compromised VM does not expose the witness key
- Two-stage broadcast: `custom_json` first (raw aggregate), then `comment` (human-readable post), so the post body can cite the on-chain tx hash
- beem imported lazily inside `_build_steem()` — dev mode and the test suite run without beem installed
- Footer copy (English and German witness-vote paragraph) pinned by test; an edit that changes the wording will fail the suite

### Verified locally

- 54/54 pytest green (29 existing + 25 new)
- Dry-run against a 14-day deterministic synthetic seed produces a bilingual post and a 2 905-byte `custom_json` payload; sample captured in the Phase-5 progress log

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
- SSH host alias for the development VM in the author's SSH config
- Server working directory `/opt/steemapps-monitor/` on the local development VM (Ubuntu 24.04)
- Private GitHub repository `greece-lover/steemapps-monitor`

### Known deviations from concept

- **Hosting target:** the production host is deferred to a later phase; initial development happens on the author's local Ubuntu VM.

## [Phase 1] — 2026-04-24

### Added

- Server audit of the local development VM (Ubuntu 24.04)
- Confirmation that existing workloads (`steem-fork`, `sqv-indexer`, `sqv-frontend`) are unaffected
- Network verification: all four initial Steem API nodes reachable with sub-second latency
