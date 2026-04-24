# Daily Report

*Deutsche Version: [TAGES-REPORT.md](TAGES-REPORT.md)*

Once per UTC day, the SteemApps API Monitor publishes a Steem post and an
accompanying `custom_json` operation summarising the previous day's
measurements. The post is human-readable and bilingual (English and
German); the `custom_json` is the machine-readable raw aggregate that
downstream consumers (dashboards, third-party tools) can build on.

## Schedule

- **Timer:** `deploy/steemapps-reporter.timer`, fires daily at **02:30 UTC**.
- **Window reported on:** the UTC day that ended 2.5 hours earlier. A run
  at `2026-04-25 02:30:00 UTC` reports on `2026-04-24 00:00:00Z –
  2026-04-25 00:00:00Z`.
- **Author account:** `@steem-api-health` (dedicated reporter account,
  separate from the `@greece-lover` witness account).

## Operations

Each run produces two blockchain operations, in this order:

1. **`custom_json`** with id `steemapps_api_stats_daily` — the raw
   aggregate payload, signed by the reporter account's posting authority.
   Sent first so the comment can reference the transaction.
2. **`comment`** — the bilingual report post, with a link in the body
   pointing at the `custom_json` transaction and block.

Retry policy: three attempts per operation, 60 seconds apart. Permanent
errors (duplicate permlink, invalid signature, insufficient RC) are
raised immediately — retrying them would just log the same error three
times. Transient errors (network timeout, RPC unreachable) retry.

## `custom_json` payload schema

The payload is a stable public schema; breaking changes need a new
operation id, not a silent shift.

```json
{
  "version": "mv1",
  "day": "2026-04-24",
  "window": {
    "start": "2026-04-24T00:00:00Z",
    "end":   "2026-04-25T00:00:00Z"
  },
  "source_location": "contabo-de-1",
  "summary": {
    "total_measurements": 14400,
    "total_ok": 14281,
    "uptime_pct": 99.17,
    "best_node": "https://api.moecki.online",
    "worst_node": "https://steem.justyy.com",
    "longest_outage_node": "https://steem.justyy.com",
    "longest_outage_ticks": 7
  },
  "nodes": [
    {
      "url": "https://api.steemit.com",
      "region": "us-east",
      "total": 1440,
      "ok": 1421,
      "uptime_pct": 98.68,
      "errors": 19,
      "latency_ms": {"avg": 712, "min": 340, "max": 4210, "p95": 1520},
      "error_classes": {"timeout": 11, "http_5xx": 8}
    }
    // … one entry per configured node
  ]
}
```

### Field semantics

- `version` — mirrors the methodology version pinned in
  `docs/MEASUREMENT-METHODOLOGY.md`. Consumers should check this before
  trusting any derived field.
- `window` — half-open `[start, end)` in ISO-8601 Z. Two consecutive
  reports share no ticks.
- `source_location` — identifier of the monitor instance that produced
  the raw data. Today there is one (`contabo-de-1` on the development
  VM); a multi-location extension is on the Phase-6+ roadmap.
- `summary.best_node` / `worst_node` — ranked by uptime, ties broken by
  average latency (lower is better).
- `summary.longest_outage_ticks` — number of consecutive failed 60-second
  ticks on the worst-affected node; each tick is one minute.
- `nodes[].errors` — total failed ticks in the window.
- `nodes[].error_classes` — coarse buckets (`timeout`, `connect_error`,
  `http_4xx`, `http_5xx`, `rpc_error`, `body_invalid`, `body_stale`,
  `other`); individual messages from the monitor's raw `error_message`
  column are not exposed, to keep the on-chain payload compact.

## Reading the raw data

Every daily `custom_json` is recorded on the Steem chain. To fetch the
last N days of aggregates without scraping individual posts, query
`required_posting_auths=@steem-api-health` with id
`steemapps_api_stats_daily` from any Steem block explorer or a
`condenser_api.get_account_history` call filtered on the `custom_json`
op. The `comment` body links to the exact transaction and block for each
day's aggregate, which is the fastest path for a human auditor.

## Post format

The comment body contains:

1. **English section** — executive summary, node table (uptime, avg
   latency, p95 latency, errors, error classes), week-over-week delta,
   methodology link.
2. **German section** — identical structure, German copy.
3. **About this report** — verbatim footer paragraphs in English and
   German (attribution to `@greece-lover` as the maintainer, dashboard
   link, GitHub link, witness ask).

The footer copy is pinned by test (`tests/test_template.py`); changing
it requires an explicit edit.

## Operational modes

Two env-driven modes:

- **`STEEMAPPS_REPORTER_MODE=prod`** — signs and broadcasts both
  operations. Requires `STEEMAPPS_REPORTER_POSTING_KEY` set to a valid
  posting key for the account.
- **`STEEMAPPS_REPORTER_MODE=dev`** — renders the post and the
  `custom_json` payload to stdout and exits. No chain interaction. No
  key required. Used for local development, CI-style smoke tests, and
  the first Phase-5 run before production cutover.

`--dry-run` on the CLI forces dev mode regardless of the environment.

## Failure handling

- **No data in window** — exit code 2, no broadcast. Protects against
  posting an empty report when the monitor has been offline.
- **`custom_json` broadcast fails** — exit code 3, the comment is not
  attempted. The day is skipped; the systemd timer's `Persistent=true`
  does not retry the same day automatically (the VM being up is not
  enough — the RPC endpoint must also be reachable), so a manual
  `systemctl start steemapps-reporter.service` can be used to replay
  the day once the cause is fixed.
- **Comment broadcast fails after `custom_json` succeeded** — exit
  code 4. The raw aggregate is already on chain, so downstream
  consumers are not affected; the human-readable post is simply missing
  for that day. The permlink is stable (`steemapps-api-daily-report-YYYY-MM-DD`),
  so a replayed comment would collide with the failed attempt only if
  the first attempt actually reached the block; that case also raises
  "duplicate permlink" which is classed as permanent and logged clearly.

## Running manually

```bash
# Local dry-run against the committed measurements DB (seed first):
python -m reporter.daily_report --seed-synthetic
python -m reporter.daily_report --dry-run

# On the VM, dry-run against the live DB:
sudo -u steemapps-reporter STEEMAPPS_REPORTER_MODE=dev \
    /opt/steemapps-monitor/.venv/bin/python -m reporter.daily_report --dry-run

# On the VM, explicit day (re-run for yesterday's UTC day after a failure):
sudo -u steemapps-reporter \
    /opt/steemapps-monitor/.venv/bin/python -m reporter.daily_report \
    --date 2026-04-24
```
