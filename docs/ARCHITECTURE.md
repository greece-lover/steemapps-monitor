# Architecture

*Deutsche Version: [ARCHITEKTUR.md](ARCHITEKTUR.md)*

## Components

```
┌──────────────────┐
│ systemd timer /  │   runs every 60 s, one tick per measurement
│ internal loop    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐    JSON-RPC over HTTPS
│ Poller (Python)  │──────────────────────────► Steem API nodes
│ httpx, asyncio   │◄──────────────────────────── response, latency, block num
└────────┬─────────┘
         │ writes one row per (node, tick)
         ▼
┌──────────────────┐
│ SQLite           │
│ measurements,    │
│ outages, nodes   │
└────────┬─────────┘
         │
         ├──► Aggregator (periodic) ──► daily summary, health scores
         │
         ├──► JSON API (FastAPI) ─────► api.steemapps.com consumers
         │
         └──► Daily reporter (cron) ──► Steemit post + custom_json on chain
```

The monitor is a single Python process; additional components (API server, daily reporter) are separate processes that share the SQLite file. SQLite in WAL mode handles the concurrency pattern (one writer, many readers) well at the volumes we expect (single-digit nodes, one measurement per minute each → < 15 000 rows per node per week).

## Processes

| Process | Unit name | Frequency | Purpose |
|---|---|---|---|
| Monitor | `steemapps-monitor.service` | continuous | poll all nodes every 60 s, write measurements |
| API server | `steemapps-api.service` | continuous | serve read-only JSON endpoints |
| Daily reporter | cron `@daily 02:00` | once a day | aggregate, post to Steemit, write custom_json |

## Data directories

- `/opt/steemapps-monitor/` — source, virtualenv, configuration
- `/opt/steemapps-monitor/data/` — SQLite databases (gitignored; backed up separately)
- `/opt/steemapps-monitor/logs/` — rotated log files
- `/etc/systemd/system/steemapps-monitor.service` — service definition

## Measurement cycle

Each tick:

1. For every configured node, issue one `condenser_api.get_dynamic_global_properties` JSON-RPC call.
2. Record: HTTP status, total round-trip time, returned `head_block_number`, error (if any).
3. Compute derived fields: block lag (reference = maximum head block across all nodes this tick), score components.
4. Insert one row in `measurements`.
5. If the node transitions from healthy to unhealthy or vice versa, open or close an `outages` record.

## Reference block resolution

"Block lag" is always computed relative to the maximum `head_block_number` observed across the node pool in the same tick. If all nodes are equally stale we have no reference — this is logged and treated as a degraded state, not an outage of individual nodes.

## Scoring and outage detection

Implemented per [MEASUREMENT-METHODOLOGY.md](MEASUREMENT-METHODOLOGY.md). The algorithm is centralised in one module (`monitor/scoring.py`) and fully tested so that any change to the formula is explicit, reviewable, and versioned.

## Public API

The FastAPI server exposes read-only endpoints — schema in [API.md](API.md). No write endpoints, no authentication, no rate limiting at the app layer (enforced by nginx later).

## Daily on-chain report

Two artefacts per day:

1. A Steemit post (HTML body) posted by the dedicated reporter account. Contains a human-readable table, comparison to the previous week, and links to the raw data.
2. A `custom_json` operation under `steemapps_api_stats_daily` containing the full aggregated numbers. This is the authoritative source — the post merely presents the data.

## Security boundaries

- The reporter account holds only posting authority.
- Its posting key is stored in `/opt/steemapps-monitor/.env.local`, read-only for the service user, never in git.
- The API server and dashboard are read-only; any command-execution surface (deployment scripts, database migrations) is kept outside the service boundary and requires a manual login.

## Extensibility

- New nodes: one row in the `nodes` table, configuration reload triggers the poller.
- New metrics: additive — old rows simply have `NULL` for new columns.
- New aggregation windows: handled in the reporter, does not require schema changes.
