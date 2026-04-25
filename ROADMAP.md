# Roadmap

*Deutsche Version: [ROADMAP.de.md](ROADMAP.de.md)*

Milestone phases rather than date-locked releases. Dates below are targets, not commitments.

## Phase 1 — Server audit ✅ (2026-04-24)

Read-only inventory of the development VM. Confirmed that existing workloads (Steem-fork witness node, SQV indexer, SQV frontend) are unaffected and that all initial target API nodes are reachable.

## Phase 2 — Scaffolding ✅ (2026-04-24)

Repository, documentation foundation, SSH alias, server working directory. No monitor code yet. Both languages DE/EN in place where required.

## Phase 3 — Monitor core 🟡 (2026-04-24, code complete)

- Python poll loop, JSON-RPC client, per-minute measurement ✅
- SQLite schema (nodes, measurements) ✅
- Health-score computation matching methodology `mv1` ✅
- systemd service, logging, error handling ✅
- Local tests: 18/18 green; live smoke test against all four nodes OK ✅
- **Pending:** VM deployment + 30-minute runtime verification (development VM was unreachable at the end of the coding session; follows as soon as the VM is back up)
- `outages` table deferred to Phase 4 — Phase 3 persists raw measurements and computes outage stretches on the fly from `/api/v1/status`; a materialised table earns its keep only once the aggregator needs faster cross-day queries

## Phase 4 — Public JSON API (target: 2026-04-27)

- Read-only JSON endpoints for status, history, and outages
- Stable schema documented in `docs/API.md`
- Reverse-proxy target `api.steemapps.com` (nginx on the production server, later phase)

## Phase 5 — Dashboard (target: 2026-04-28 to 2026-04-30)

- Static HTML + Chart.js + Leaflet, no build step, no framework
- Per-node detail pages: uptime curve, latency history, outage list
- Regional heatmap once multi-location measurements are live

## Phase 6 — Daily chain report (target: 2026-05-04)

- Aggregator produces the day's summary
- Posts to Steemit under a dedicated account (account name still being decided)
- Writes the raw aggregated numbers as `custom_json` id `steemapps_api_stats_daily`
- First run manual, then fully automated cron at 02:00 MESZ

## Phase 7 — Repository public, announcement (target: 2026-05-04)

- Repository switches from private to public on the same day as the first successful automated report
- Announcement post on Steemit explaining methodology and data access

## Phase 8 — Multi-region measurements (open)

- Additional monitor instances in different regions (USA, Asia) if financially justified
- Point type is stored per measurement so local and regional data can be distinguished

## Phase 9 — Welako client-switcher integration (open)

- Welako frontend sends anonymised measurements to a collection endpoint
- Data is merged with server-side monitoring for a more realistic picture
- Privacy: no IPs, no user IDs, no individual request patterns

## Open decisions

Tracked in `STEEMAPPS_PROJEKT_KONZEPT.md` section "Offene Entscheidungen". These will be closed as implementation progresses.
