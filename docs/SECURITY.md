# Security

*Deutsche Version: [SECURITY.de.md](SECURITY.de.md)*

## Threat model

This project runs one writable service (the monitor), one read-only HTTP API, and one scheduled reporter that holds a single posting key. The attack surfaces in order of concern:

1. **Theft of the reporter account's posting key** — would let an attacker post misleading "official" reports under a recognised identity.
2. **Database tampering** — would let an attacker plant false uptime numbers.
3. **API surface** — read-only; minimal risk but must not leak private data.
4. **Source code supply chain** — pip dependencies, systemd unit integrity.

We do not hold user funds, user credentials, or user PII. The monitor does not accept inbound data from users at all.

## Keys and secrets

- **Never in git.** Active and owner keys are never in this repository. CI does not have them. Pull requests do not have access to them.
- **Reporter posting key** is stored in `/opt/steemapps-monitor/.env.local`, mode `0600`, owner `steemapps-monitor:steemapps-monitor` (or the service user). Only the reporter process reads it.
- **No memos** — the reporter never signs transfers, only `comment` and `custom_json`.
- **Key scope** — the dedicated reporter account has only a posting authority. No active authority. No funds stored on the account beyond bandwidth needs.

If a key is suspected compromised, the remediation is to rotate the posting key on-chain and redeploy. The monitor logs and database do not contain any secret that would need rotating as well.

## What we collect and what we do not

The monitor collects measurements it makes itself against public endpoints. It does **not** collect:

- User IP addresses
- User account names that passed through any frontend
- Request payloads, cookies, browser fingerprints
- Geo-IP, user-agent strings, or any browser telemetry

The Welako client-switcher extension (future work) will send aggregated, anonymised counters, never per-user data. That integration is documented separately and reviewed before it lands.

## On-chain data

The `custom_json` operations under the ids `steemapps_api_stats_daily` and `steemapps_api_outage` contain only aggregated node-level numbers. No user data. The chain is immutable, so this data cannot be revoked — this is by design (reproducibility, accountability).

## Repository privacy

The repository is private until Phase 7. During the private phase:

- Collaborator access is limited to the author.
- No CI secrets are configured.
- No production credentials are ever committed; the `.env.example` file in the repo shows the variable names only.

When the repository becomes public, a pre-switch audit will confirm:

- No real keys in history (including git history — use `git log -p | grep -iE 'key|secret|password|pass='`)
- No customer-specific server hostnames beyond the already-public production server address
- No leftover development paths or internal VM identifiers that should not be public

## Service hardening

Minimum bar for the production deployment:

- Non-root service user (`steemapps-monitor`)
- systemd hardening directives: `PrivateTmp=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `NoNewPrivileges=yes`, `ReadWritePaths=/opt/steemapps-monitor/data /opt/steemapps-monitor/logs`
- UFW: only the reverse-proxy port for the API exposed publicly; monitor process speaks outbound only
- Log rotation with bounded retention

## Reporting a vulnerability

Until the repository is public, concerns should go directly to @greece-lover on Steemit or via private Discord. After it is public, a `SECURITY.md` contact section will be added with a preferred reporting channel.
