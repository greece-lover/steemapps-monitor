"""Daily-report generator.

Produces a bilingual (DE/EN) Steem post summarising the previous UTC day's
monitoring data, and writes the raw aggregate as a `custom_json` operation
to the Steem blockchain. The monitor process is the upstream producer; this
package is a pure consumer of the SQLite file in `data/`.

The CLI entry point is `reporter.daily_report` and is invoked daily by the
systemd timer under `deploy/steemapps-reporter.timer`.
"""
