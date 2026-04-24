# steemapps.com — Steem API Monitor

> Continuous, independent, open-source monitoring of all known Steem API nodes. Public accountability for infrastructure reliability.

*Deutsche Version: [README.de.md](README.de.md)*

## Why this exists

Frontend operators on the Steem blockchain depend on public API nodes. When `api.steemit.com` — the de-facto central node — becomes slow or unreachable, users lose access. Today there is no independent, long-running, methodically transparent record of how reliable each public node actually is.

This project fills that gap with a Python service that measures every known Steem API node every 60 seconds, stores the results in SQLite, exposes them on a public dashboard at `api.steemapps.com`, and posts a daily summary on-chain as a Steemit post and `custom_json` operation.

## What it does

1. **Monitor** — polls each configured node every 60 seconds, records latency, HTTP status, block lag, and error patterns.
2. **Score** — computes a transparent per-node health score (see [docs/MEASUREMENT-METHODOLOGY.md](docs/MEASUREMENT-METHODOLOGY.md)).
3. **Serve** — exposes JSON endpoints for external consumers and a live dashboard (later phase).
4. **Report** — once a day, compiles a structured summary, posts it to Steemit under a dedicated account, and writes the raw numbers to the chain as a `custom_json` operation under the id `steemapps_api_stats_daily`.

## Who this is for

- **Witnesses** — an objective baseline for evaluating API-node operators.
- **Frontend operators** — a data source for automatic node switching (Welako, Condenser forks).
- **Node operators** — honest feedback on their own service quality.
- **Regular users** — benefit passively through more reliable frontends.

## Status

Phase 3 — monitor core implemented (poll loop, SQLite, scoring, FastAPI, systemd unit). 18/18 tests green locally; VM deployment pending. See [ROADMAP.md](ROADMAP.md).

The repository is **private** until the first automated daily report runs successfully. At that point it will be switched to public, with an announcement post on Steemit.

## Quick start (developer preview)

```bash
git clone git@github.com:greece-lover/steemapps-monitor.git
cd steemapps-monitor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python monitor.py                  # polls every 60 s, serves 127.0.0.1:8110
```

Tests:

```bash
pip install -r requirements-dev.txt
pytest tests/
```

See [deploy/README.md](deploy/README.md) for the VM install (systemd unit, data path).

## Architecture at a glance

```
 Monitor (Python, systemd) ──60s──► Steem API nodes
          │
          └─► SQLite  ──► JSON API  ──► Dashboard (api.steemapps.com)
                      │
                      └─► Daily report ──► Steemit post + custom_json
```

Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Methodology transparency

Every published number is reproducible. The score algorithm, uptime calculation, outage definition, and aggregation windows are documented in [docs/MEASUREMENT-METHODOLOGY.md](docs/MEASUREMENT-METHODOLOGY.md). Raw per-minute measurements are written to chain so anyone can verify or re-aggregate.

## Public API

When the dashboard is live, a JSON API will be published. The schema is tracked in [docs/API.md](docs/API.md) so external consumers can build on top of our data without scraping HTML.

## Security and privacy

- Only the monitor server measures Steem nodes — no user data, IPs, or request patterns are ever collected or published.
- The daily-report Steem account holds only posting authority, no funds.
- Active/owner keys are never in this repository. See [docs/SECURITY.md](docs/SECURITY.md).

## Contributing

Pull requests welcome once the repository is public. Until then, issues and concept feedback go to @greece-lover directly. See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Contact

- Maintainer: **@greece-lover**
- Related projects: [Welako](https://welako.app), SARH (Steem Recovery Hub), SQV (Steemit Quantum Vault)
- Issues: will be enabled when the repository goes public.

## License

[MIT](LICENSE) — fork it, host your own monitor, publish your own numbers. The only thing we ask is that forks clearly mark themselves as independent so users can tell them apart.
