# User Guide

*Deutsche Version: [USER-GUIDE.de.md](USER-GUIDE.de.md)*

This guide is for three audiences: end users reading the dashboard, frontend operators integrating the data, and node operators checking their own record.

## Reading the dashboard

The landing page at `api.steemapps.com` shows a table with one row per monitored node and four traffic-light columns:

- **Now** — current 5-minute status (green / yellow / red / grey).
- **24 h** — uptime percentage in the last 24 hours.
- **7 d** — average daily uptime over the last seven days.
- **Score** — current health score (0–100), see [MEASUREMENT-METHODOLOGY.md](MEASUREMENT-METHODOLOGY.md).

Click a row to see the per-node detail page: latency curve, uptime chart, outage list with timestamps.

The displayed numbers are reproducible from the raw data. If you want to verify, pull the `custom_json` with id `steemapps_api_stats_daily` for the day in question and recompute.

## Reading daily reports on Steemit

Each day the reporter account publishes a post titled "Steem API node report — YYYY-MM-DD" (bilingual DE/EN). The post contains:

- Summary: best node, worst node, largest outage.
- Full table: uptime, latency, error count per node.
- Week-over-week comparison.
- Regional latency map (once multi-region is live).
- Link to the corresponding `custom_json` operation with the raw data.

The post is always factual. No snark, no blame games. If you think a number is wrong, contact the reporter account or @greece-lover with the timestamp — we will publish a correction and log the change here.

## Integrating the data (frontend operators)

Use the JSON API documented in [API.md](API.md). Recommended pattern:

- Poll `/nodes` once a minute to refresh your fallback list.
- Exclude nodes with `status = "down"` from your rotation.
- Prefer nodes with `score_now >= 80`.
- Cache responses locally; do not hammer the API on every user action.

Alternatively, subscribe to the chain stream and watch for `steemapps_api_outage` operations — these are emitted immediately on outage detection, with latency typically under two minutes.

## Checking your own node (node operators)

If you run one of the monitored nodes and want to verify its standing:

1. Look it up on the dashboard — the public number is the same one we use everywhere.
2. If the number surprises you, the `/nodes/{id}/history` endpoint gives per-tick data.
3. Because measurements are external to your service, what we see may differ from what your own internal monitoring shows — especially for network-layer problems upstream of your server. The raw data makes it possible to diagnose where in the stack the discrepancy originates.

## Getting your node monitored

File a request through the channel listed in [CONTRIBUTING.md](CONTRIBUTING.md). Requirements: the node must be publicly reachable, stable-URL, and run an unmodified or compatibly-modified Steem API surface (`condenser_api.get_dynamic_global_properties` is the minimum).
