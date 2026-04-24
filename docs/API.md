# Public API

*As of Phase 4, every endpoint under "Current (`/api/v1/`)" is implemented and backing the dashboard under `frontend/`. The VM is still development-only — the API binds to `127.0.0.1:8110` and the dashboard is served from a second VM-internal port during development. A public `api.steemapps.com` exposure on the production server is deferred to a later phase.*

Base URL: `https://api.steemapps.com/` (planned, later phase).
Development: `http://127.0.0.1:8110/` on the author's VM, or `http://localhost:8110/` over an SSH tunnel from a workstation.

All endpoints return JSON, are read-only, require no authentication, and allow cross-origin GET requests (permissive CORS — the surface is read-only and unauthenticated).

## Current (`/api/v1/`)

### `GET /api/v1/health`

Monitor-process liveness. Not the nodes' status.

```json
{
  "service": "steemapps-monitor",
  "status": "ok",
  "uptime_s": 3712,
  "last_tick_ts": "2026-04-24T09:34:00Z",
  "methodology_version": "mv1",
  "now": "2026-04-24T09:34:18Z"
}
```

### `GET /api/v1/status`

Snapshot of every configured node: last-tick measurement plus the derived
health score.

```json
{
  "generated_at": "2026-04-24T09:34:00Z",
  "methodology_version": "mv1",
  "reference_block": 105471530,
  "nodes": [
    {
      "url": "https://api.steemit.com",
      "region": "us-east",
      "status": "ok",
      "score": 100,
      "last_tick_ts": "2026-04-24T09:34:00Z",
      "latency_ms": 523,
      "block_height": 105471530,
      "block_lag": 0,
      "error_message": null,
      "reasons": []
    }
  ]
}
```

`status` ∈ {`ok`, `degraded`, `down`, `unknown`}. `reasons` lists the
penalties the scoring algorithm applied — human-readable strings that
correspond one-to-one with the rules in
[MEASUREMENT-METHODOLOGY.md](MEASUREMENT-METHODOLOGY.md).

### `GET /api/v1/nodes/{node_url}/history?hours=1`

Lean time series for the dashboard sparkline. `node_url` is percent-encoded
in the path (e.g. `https%3A%2F%2Fapi.steemit.com`). `hours` defaults to 1
and is capped at 168 (one week). Points are in chronological order —
oldest first — so a line chart plots naturally left-to-right.

```json
{
  "node_url": "https://api.steemit.com",
  "hours": 1,
  "methodology_version": "mv1",
  "points": [
    { "ts": "2026-04-24T15:35:31Z", "latency_ms": 702, "success": true },
    { "ts": "2026-04-24T15:36:31Z", "latency_ms": 658, "success": true },
    { "ts": "2026-04-24T15:37:31Z", "latency_ms": null, "success": false }
  ]
}
```

`latency_ms` is `null` on failed ticks. Chart.js's `spanGaps: false` is
the right rendering mode — a failed tick becomes a visible break in the
line.

### `GET /api/v1/nodes/{node_url}/uptime?days=7`

Success-rate over a wall-clock window.

```json
{
  "node_url": "https://api.steemit.com",
  "days": 7,
  "total": 61,
  "ok": 61,
  "uptime_pct": 100.0
}
```

`days` ∈ [1, 30]. `total` is the number of ticks in the window; `ok` is
the subset that responded with a valid head block. Ticks where the node
was unreachable still count toward `total` — that is the definition of
uptime we use on the dashboard.

## Planned (public surface on `api.steemapps.com`)

Once the monitor is fronted by a reverse proxy on the production server, the
following `/v2`-prefixed surface consolidates and renames today's
endpoints so the public URL shapes match the concept doc.

### `GET /nodes`

List of all monitored nodes with their current status.

```json
{
  "generated_at": "2026-04-24T09:34:00Z",
  "nodes": [
    {
      "id": "api.steemit.com",
      "url": "https://api.steemit.com",
      "operator": "Steemit Inc.",
      "region": "us-east-1",
      "status": "ok",
      "score_now": 100,
      "latency_ms_5min_p50": 612,
      "uptime_pct_24h": 99.93,
      "last_outage_at": "2026-04-20T14:17:00Z"
    }
  ]
}
```

Possible `status` values: `ok`, `degraded`, `down`, `unknown`.

### `GET /nodes/{id}/history`

Per-tick history for charts. Query params:

- `from` (ISO 8601, default: 24 h ago)
- `to` (ISO 8601, default: now)
- `resolution` — one of `tick`, `5min`, `hour`, `day`; default `5min`

```json
{
  "node_id": "api.steemit.com",
  "resolution": "5min",
  "from": "2026-04-23T09:00:00Z",
  "to": "2026-04-24T09:00:00Z",
  "points": [
    { "ts": "2026-04-23T09:00:00Z", "latency_ms_p50": 620, "uptime_pct": 100, "score_avg": 100 }
  ]
}
```

### `GET /outages`

Recent outages across all nodes. Query params:

- `days` — integer, default 7, max 90
- `classification` — `short_glitch`, `real_outage`, or omitted for both

```json
{
  "range_days": 7,
  "outages": [
    {
      "node_id": "api.steemit.com",
      "started_at": "2026-04-20T14:17:00Z",
      "ended_at": "2026-04-20T14:19:40Z",
      "duration_s": 160,
      "classification": "real_outage"
    }
  ]
}
```

### `GET /reports/daily/{date}`

A previously generated daily report for the given UTC date (`YYYY-MM-DD`). Contains the same numbers as the chain-written `custom_json` — this is a convenience endpoint for consumers who do not want to parse chain data.

## Schema stability

Once the repository goes public, this schema is frozen to additive changes only (new fields, new endpoints). Breaking changes get a versioned prefix: `/v2/nodes`, etc. The `methodology_version` field in `/health` tracks the measurement-layer version independently of the API version.

## Rate limits

No per-app rate limit. nginx in front of the API applies a generous IP-level rate limit (final numbers TBD in Phase 4). Aggressive scraping should use the chain `custom_json` feed instead, which is free and distributed.
