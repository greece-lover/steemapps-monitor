# Contribute measurements (English)

The Steem API monitor at <https://api.steemapps.com/> measures every public
node from a single VM in Germany. That is enough to spot outright outages
but it cannot tell whether a node is fast for users in the US or in Asia.
Community contributors run a small script on their own server to add
those perspectives.

A German version of this document lives at [TEILNEHMEN.md](TEILNEHMEN.md).

## Who this is for

Any operator with a small VPS and an outbound HTTPS connection — typically
witnesses, dapp operators, and node runners. We are especially looking for
contributors in:

- **North America** (US East / US West)
- **Asia** (Singapore, Tokyo, Seoul)
- **South America**
- **Africa**
- **Australia / Oceania**

You do not need to operate a Steem node yourself. The script only makes
outbound JSON-RPC calls to the public nodes.

## How to participate

1. **Get an API key.**
   Open <https://api.steemapps.com/join.html> and submit:
   - Your Steem account name
   - A short label for your server (e.g. `Hetzner FSN1`)
   - The geographic region of the server

   The form checks that the account exists on the Steem chain and
   issues an API key on the spot. The key has the form `sapk_…` —
   store it on the host that will run the script and nowhere else. It
   cannot be retrieved a second time; if you lose it, ask the operator
   to issue a fresh one.

2. **Install the script.**
   The participant code lives at <https://github.com/greece-lover/steemapps-monitor/tree/main/participant>.
   Three commands install it via Docker:

   ```bash
   git clone https://github.com/greece-lover/steemapps-monitor.git
   cd steemapps-monitor/participant
   cp .env.example .env && nano .env       # paste STEEMAPPS_API_KEY
   docker compose up -d --build
   ```

   A `systemd` recipe is included for hosts without Docker. See the
   participant directory's [README](../participant/README.md) for both
   paths.

3. **Verify.**
   After 5–10 minutes you should see flush log lines from the script and a
   non-zero `24h` count for your Steem handle on
   <https://api.steemapps.com/sources.html>.

## What the script does

Once per minute the script issues one JSON-RPC `condenser_api.get_dynamic_global_properties` request to each of the 10 nodes the central dashboard tracks. Latency, head-block height and any error are buffered in memory. Every five minutes the buffer is shipped to `https://api.steemapps.com/api/v1/ingest` over HTTPS, authenticated with your `X-API-Key` header.

The buffer is in-memory only. A restart loses at most five minutes of data — a deliberate trade-off against introducing a write-path that needs cleanup.

## Resource cost

| Resource | Typical |
|---|---|
| RAM | < 30 MB |
| CPU | < 1 % of one core |
| Outbound bandwidth | ~ 5 MB / day |
| Inbound bandwidth | none required |

A 1 GB / 1 vCPU box is plenty.

## Trust boundary and what we do with the data

- Your measurements land in the same SQLite database as the central
  monitor's data, tagged with the `display_label` you chose.
- They power per-region latency comparisons on the dashboard.
- They are not resold. The dashboard is read-only and public.
- You can ask to have your participation removed at any time. Re-issuing
  your key resets the attribution and counts.

## Rules of the road

- Only one instance per Steem account.
- No tampering with measurements. The dashboard runs plausibility checks
  (latency bounds, timestamp window, success/latency consistency) and
  flagged participants are deactivated.
- Keep `.env` private. If you suspect the key leaked, ask for a re-issue
  and we will rotate it within hours.

## FAQ

**Q: Does the script need an open port?**
A: No. Only outbound HTTPS to `api.steemapps.com` and JSON-RPC to the
   ten monitored nodes.

**Q: What if my server can't reach `api.steemapps.com`?**
A: Buffers stay in memory and are retried on the next flush. After very
   long outages the oldest rows beyond ~1000 are dropped to keep the
   buffer bounded.

**Q: Do I need to update the script when nodes change?**
A: No. The script fetches the current node list from
   `/api/v1/nodes` at startup, so adding or removing a node on the
   central side propagates on the next restart.

**Q: How often does the script update itself?**
A: It does not. Pull the repo and rebuild the container or restart the
   service when a new version drops.

**Q: Can I see what data is sent?**
A: Yes. `monitor.py` is a single 200-line Python file you can read in
   under five minutes. The wire format is documented at
   [docs/API.md](API.md) under the `POST /api/v1/ingest` section.

**Q: Build fails with "No matching distribution found"?**
A: On Ubuntu with `systemd-resolved` (default since 18.04),
   `/etc/resolv.conf` points to `127.0.0.53`, which is not reachable
   from inside the Docker build sandbox. Create a
   `docker-compose.override.yml` next to `docker-compose.yml`:

   ```yaml
   services:
     participant:
       build:
         context: .
         network: host
       dns:
         - 1.1.1.1
         - 8.8.8.8
   ```

   Alternatively system-wide: `/etc/docker/daemon.json` with
   `{"dns": ["1.1.1.1", "8.8.8.8"]}`, then
   `sudo systemctl restart docker`.

## Contact

- Steem: `@greece-lover`
- The same channels that handle SteemApps support
