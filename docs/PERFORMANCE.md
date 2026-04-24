# Query performance

Snapshot of the Phase-6 query layer against a one-million-row SQLite,
measured on the development VM.

Reproducing:

```bash
.venv/Scripts/python scripts/bench_load.py --rows 1000000
```

`scripts/bench_load.py` bulk-inserts `rows` synthetic ticks
(10 nodes × 100 000 minutes, 5 % random failures, realistic latency
distribution), then times every Phase-6 DB helper. Output is Markdown
for direct paste below.

## Baseline: 1 000 000 rows (Etappe 6)

Snapshot: 2026-04-25, SQLite 3, SSD-backed dev DB, WAL mode.

| Query | Time (ms) | Rows |
|---|---:|---:|
| `get_latest_per_node` | 110.4 | 10 |
| `get_recent_measurements(100)` | 1.5 | 100 |
| `get_per_node_aggregates(24h)` | 7.1 | 10 |
| `get_per_node_aggregates(7d)` | 52.2 | 10 |
| `get_per_node_aggregates(30d)` | 212.2 | 10 |
| `get_per_node_aggregates_between(yday)` | 8.1 | 10 |
| `get_measurements_range(24h, one-node)` | 5.6 | 1,440 |
| `get_measurements_range(7d, one-node)` | 29.4 | 10,080 |
| `get_all_measurements_range(24h)` | 164.1 | 14,400 |
| `get_chain_availability(24h,600s)` | 9.1 | 145 |
| `get_chain_availability(7d,3600s)` | 55.8 | 169 |
| `get_uptime_stats(7d, one-node)` | 12.7 | 5 |
| `get_uptime_daily(30d, one-node)` | 50.6 | 31 |
| `row_count (total)` | 40.2 | — |

All under the 200 ms API-response target aside from
`get_per_node_aggregates(30d)` — that one approaches the cap when a
full 30 days of fleet-wide traffic land in the window. In practice the
`/status` endpoint never calls it with a 30-day lookback; rankings use
24h/7d which come back in 7 / 52 ms respectively.

## Index plan sanity-check

The composite index `idx_measurements_node_ts (node_url, timestamp)`
carries every per-node range query. The timestamp-only index
`idx_measurements_timestamp` serves the global range scans that the
chain-availability and outage-aggregation helpers issue.

A surprise from the bench run: the original
`get_per_node_aggregates(lookback_minutes)` was 678 ms on 1 M rows
because its `WHERE timestamp >= ?` with no upper bound prompted
SQLite to pick the `node_url` index and scan 1 M rows front-to-back.
Reshaping the query to a bounded range
(`WHERE timestamp >= ? AND timestamp < ?`) drops it to 7 ms — the
planner now range-seeks the composite `(node_url, timestamp)` index
instead. The fix landed in the commit that introduced this file: the
helper now delegates to `get_per_node_aggregates_between(lookback, 0)`.

## Re-running after load growth

If the production DB grows past 5 M rows, re-run the benchmark and
update this file. Watch in particular:

- `get_per_node_aggregates(30d)` — the longest-range fleet aggregation.
- `get_all_measurements_range(24h)` — drives the global outage list.
- `get_chain_availability(7d, 3600s)` — the stats-page stacked-area query.

Any of these going above ~1 s warrants revisiting the index set (a
`(timestamp, node_url)` composite would accelerate the `get_all_*`
pair) or introducing a pre-aggregated daily summary table.
