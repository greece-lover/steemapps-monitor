# Measurement Methodology

*Deutsche Version: [MESSMETHODIK.md](MESSMETHODIK.md)*

Every published number in this project is reproducible from the raw data. This document describes exactly how each number is measured, normalised, and aggregated.

## What we measure per tick

Every 60 seconds, for each configured Steem API node, the monitor performs one JSON-RPC call:

- **Method:** `condenser_api.get_dynamic_global_properties`
- **Transport:** HTTPS POST, `Content-Type: application/json`
- **Timeout:** 8 seconds (connect + read)

The call is chosen because it is cheap, exercises the same code path regular frontends use, and returns the current head block number — the one piece of information needed to detect a lagging node.

## Raw fields recorded

| Field | Type | Notes |
|---|---|---|
| `tick_ts` | UTC timestamp | rounded to the 60-second boundary |
| `node_id` | string | stable identifier from the `nodes` table |
| `http_status` | integer or NULL | NULL on network failure (timeout, DNS error, TLS error) |
| `latency_ms` | integer or NULL | full client-observed round-trip in milliseconds; NULL on network failure |
| `head_block` | integer or NULL | value from the response, or NULL if the response could not be parsed |
| `error_class` | string | `ok`, `timeout`, `dns`, `tls`, `http_5xx`, `http_4xx`, `body_invalid`, `body_stale` |

## Derived fields per tick

- **`block_lag`** — `max(head_block across all reachable nodes this tick) − head_block for this node`. Can be 0 or positive. Undefined (NULL) if no node in the tick returned a valid head block.
- **`ok_flag`** — True iff `error_class == "ok"` and `block_lag ≤ 10`.

## Health score

Score is computed per tick per node; higher is better, max 100, minimum 0.

| Rule | Penalty (cumulative) |
|---|---|
| Starting value | +100 |
| `latency_ms > 500` | −20 |
| `latency_ms > 2000` | −50 (in addition to the −20) |
| `block_lag > 3` | −30 |
| `block_lag > 10` | −70 (in addition to the −30) |
| `error_class != "ok"` within the last 20 ticks for this node, rate > 20 % | −40 |
| No response this tick (timeout or connection error) | −100 (floor at 0) |

Rules are applied in order and are additive; scores cannot go below 0. The penalties are intentional design choices chosen to match observable user pain — a single slow tick drops the score gently, a clearly broken node collapses immediately.

## Uptime

Per day: `uptime_pct_day = 100 * count(ok_flag=True) / count(*)` for that node on that UTC day. Ticks where the node did not return are counted as non-ok.

Per week: simple mean of the seven daily uptime percentages. Per month: mean of daily values (28 to 31 depending on the month). No weighting by traffic — we are measuring the node, not our usage of it.

## Outage definition

An **outage** is a consecutive stretch of ticks in which `ok_flag = False`. An outage has:

- `started_at` — timestamp of the first failing tick
- `ended_at` — timestamp of the first subsequent ok tick (exclusive), or `NULL` if ongoing
- `duration_s` — difference; stored on close
- `classification`:
  - `< 120 s` → **short glitch**
  - `≥ 120 s` → **real outage**

Short glitches are counted separately in daily reports and do not pull down the "outages today" count used in the public summary, but they are still recorded in the database and visible on the detail page.

## Aggregation windows

| Window | Used where |
|---|---|
| 1 tick | live status endpoint, current health score |
| 5 min | dashboard "now" ampel (coloured traffic light) |
| 1 hour | latency chart resolution |
| 1 day | daily report, uptime chart |
| 7 days | week-over-week comparison |
| 30 days | monthly trend, currently informational only |

## Explicit non-goals

- We do not measure the full condenser API surface; the dynamic global properties call is a proxy for liveness, not a full health check.
- We do not measure JUSSI cache behaviour separately from the underlying node; they are measured as one unit because that is what frontends see.
- We do not test write operations — this is a read-path monitor.
- We do not attempt to geolocate users or infer load on the operator's side; we only measure what the public endpoint returns to our monitor.

## Versioning of this methodology

If the algorithm changes (new penalty, new metric), the change is:

1. Described in a dated section at the bottom of this file.
2. Given a methodology version number `mv1`, `mv2`, etc.
3. Stored per measurement so historical scores can be recomputed or left as-is.

Current version: **`mv1`** (initial, in force since Phase 3 launch).

## Raw data access

Every tick's raw row is written to SQLite and, in aggregated form, to the chain as `custom_json` id `steemapps_api_stats_daily`. Anyone can re-aggregate from the raw data and arrive at the same numbers — that is the point.
