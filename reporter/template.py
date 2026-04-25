"""English-only Steem post renderer.

Replaces the original bilingual layout with a single-language English
post optimised for the new daily-report format: cover image at the top,
executive summary, observations, detail table, and a participation block
that drives community contributors to the ingest pipeline.

The rendered body is a Steemit-compatible markdown string. The chain-
reference fields are optional so a dry-run can produce the full body
without broadcasting; the live broadcast path passes the real tx hash
on the second pass through `render`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from reporter.aggregation import GlobalStats, NodeStats, WeekComparison
from reporter.observations import Observation, make_executive_summary


@dataclass(frozen=True)
class ChainReference:
    tx_hash: str
    block_num: int


@dataclass(frozen=True)
class RenderedPost:
    title: str
    permlink: str
    body: str
    json_metadata: dict


# -----------------------------------------------------------------
#  Formatting helpers
# -----------------------------------------------------------------


def _format_uptime(pct: float) -> str:
    return f"{pct:.2f} %"


def _format_latency(ms: Optional[int]) -> str:
    return f"{ms} ms" if ms is not None else "—"


def _format_latency_with_sources(stats: NodeStats) -> str:
    """Latency cell with the source-count annotation when relevant."""
    base = _format_latency(stats.latency.avg_ms)
    if stats.source_count > 1:
        return f"{base} (avg of {stats.source_count} sources)"
    return base


def _format_delta(pp: float) -> str:
    # Float arithmetic can produce -0.0 here; if we let the sign default
    # in the f-string fire, we get "+-0.00 pp" instead of a clean zero.
    # We pin "±0.00 pp" for the no-change case so the Δ column stays
    # eye-readable in the per-node W-o-W table.
    if abs(pp) < 0.005:
        return "±0.00 pp"
    sign = "+" if pp > 0 else ""
    return f"{sign}{pp:.2f} pp"


def _short_url(url: str) -> str:
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _bullet(observation: Observation) -> str:
    """Render an observation as a bulleted markdown line.

    All headlines start with a `Label: rest` shape (enforced in
    observations.py), so we bold everything up to and including the
    first colon. That gives a uniform visual anchor without arrow
    decorations cluttering the technical voice."""
    text = observation.headline
    if observation.detail:
        text = f"{text} {observation.detail}"
    if ":" in text:
        before, _, after = text.partition(":")
        return f"- **{before}:**{after}"
    return f"- {text}"


# -----------------------------------------------------------------
#  Section builders
# -----------------------------------------------------------------


def _node_table(per_node: dict[str, NodeStats]) -> str:
    """All-nodes detail table, sorted by uptime desc then avg latency asc."""
    header = (
        "| Node | Region | Uptime | Avg latency | p95 | Errors | Error classes |\n"
        "|---|---|---|---|---|---|---|"
    )
    def _sort_key(s: NodeStats) -> tuple[float, int]:
        return (-s.uptime_pct, s.latency.avg_ms if s.latency.avg_ms is not None else 10**9)
    rows = []
    for s in sorted(per_node.values(), key=_sort_key):
        errclass = ", ".join(f"{k} ×{v}" for k, v in sorted(s.error_classes.items())) or "—"
        rows.append(
            f"| `{_short_url(s.url)}` "
            f"| {s.region or '—'} "
            f"| {_format_uptime(s.uptime_pct)} "
            f"| {_format_latency_with_sources(s)} "
            f"| {_format_latency(s.latency.p95_ms)} "
            f"| {s.errors} "
            f"| {errclass} |"
        )
    return header + "\n" + "\n".join(rows)


def _perspective_notice(any_multi_source: bool) -> str:
    """Short paragraph explaining where the measurements come from.

    Once multiple participants are active, the wording switches to credit
    the contributors instead of warning about a single-location bias."""
    if any_multi_source:
        return (
            "*Measurements in this report come from multiple geographic locations "
            "thanks to community contributors. See the "
            "[Sources page](https://api.steemapps.com/sources.html) for the full "
            "list of operators feeding this dashboard.*"
        )
    return (
        "*All measurements are taken from a single European location (Germany). "
        "Latency to nodes hosted outside Europe will naturally be higher than for "
        "users connecting from those regions. Want to contribute measurements "
        "from your region? See the participation block below.*"
    )


def _biggest_outage_section(global_stats: GlobalStats) -> Optional[str]:
    """A standalone section for the day's worst outage — only renders when
    there *was* one. Skipped silently on clean days."""
    if not global_stats.longest_outage_node or global_stats.longest_outage_ticks <= 0:
        return None
    minutes = global_stats.longest_outage_ticks
    return (
        "## Biggest outage of the day\n\n"
        f"`{_short_url(global_stats.longest_outage_node)}` had a stretch of "
        f"**{minutes} consecutive failed minute{'s' if minutes != 1 else ''}** today. "
        "Full per-tick view: "
        f"[node detail page](https://api.steemapps.com/node.html?url={global_stats.longest_outage_node})."
    )


def _week_section(cmp: Optional[WeekComparison]) -> Optional[str]:
    """Week-over-week comparison. Returns None when no prior week is
    available — we'd rather omit the section than show an unhelpful
    'no data' line in the body."""
    if cmp is None:
        return None
    parts = [
        f"**Week-over-week:** current week {_format_uptime(cmp.current_uptime_pct)}, "
        f"previous week {_format_uptime(cmp.previous_uptime_pct)} "
        f"(Δ {_format_delta(cmp.delta_pp)})."
    ]
    if cmp.per_node_delta_pp:
        parts.append("")
        parts.append("| Node | Δ uptime |\n|---|---|")
        for url, delta in sorted(cmp.per_node_delta_pp.items(), key=lambda kv: kv[1]):
            parts.append(f"| `{_short_url(url)}` | {_format_delta(delta)} |")
    return "## Week over week\n\n" + "\n".join(parts)


def _observations_section(observations: list[Observation]) -> Optional[str]:
    """Bulleted list of observations. None when nothing fired."""
    if not observations:
        return None
    bullets = "\n".join(_bullet(o) for o in observations)
    return "## Observations\n\n" + bullets


def _participation_block(repo_url: str) -> str:
    """Verbatim copy from the Etappe-9 brief. Drives community ingest sign-ups."""
    participant_dir = f"{repo_url}/tree/main/participant"
    participate_md = f"{repo_url}/blob/main/docs/PARTICIPATE.md"
    return (
        "## Want to make these reports more accurate?\n\n"
        "Anyone can contribute measurements from their own server. The participant "
        "script runs in Docker (3 commands to install) and helps build a global "
        "view of node performance.\n\n"
        f"- Participant script and instructions: {participant_dir}\n"
        f"- Full participation guide: {participate_md}\n"
        "- Request an API key: comment below or send a Steem memo to "
        "@greece-lover with your account name, server label, and region.\n\n"
        "Contributors get attribution on the "
        "[Sources page](https://api.steemapps.com/sources.html)."
    )


def _feedback_block() -> str:
    return (
        "## Feedback wanted\n\n"
        "Have ideas for additional metrics, views, or analyses you'd like to see? "
        "Leave a comment below — the report format is still evolving and your "
        "input shapes future versions."
    )


def _resources_block(
    *,
    repo_url: str,
    dashboard_url: str,
    methodology_url: str,
    witness_url: str,
    custom_json_id: str,
    chain_reference: Optional[ChainReference],
) -> str:
    """Standardised link list at the foot of every report."""
    if chain_reference is None:
        raw_data_line = (
            f"- Raw data of this report: `custom_json` operation `{custom_json_id}` "
            "(transaction in this report's broadcast log)"
        )
    else:
        raw_data_line = (
            f"- Raw data of this report: `custom_json` operation `{custom_json_id}`, "
            f"transaction `{chain_reference.tx_hash}` in block `{chain_reference.block_num}`"
        )
    api_doc = f"{repo_url}/blob/main/docs/API.md"
    return (
        "## Resources\n\n"
        f"- Live dashboard: {dashboard_url}\n"
        f"- API documentation: {api_doc}\n"
        f"- Source code: {repo_url}\n"
        f"- Methodology: {methodology_url}\n"
        f"{raw_data_line}\n"
        "- Reporter account: @steem-api-health\n"
        f"- Operated by: @greece-lover (witness vote: {witness_url})"
    )


def _methodology_one_liner(methodology_url: str) -> str:
    return (
        f"**Methodology:** one `condenser_api.get_dynamic_global_properties` "
        f"request per node every 60 seconds, 8-second timeout. Full rules and "
        f"thresholds in [MEASUREMENT-METHODOLOGY]({methodology_url})."
    )


# -----------------------------------------------------------------
#  Public entry point
# -----------------------------------------------------------------


def build_permlink(day: str) -> str:
    """Stable permlink derived from the reporting day."""
    return f"steemapps-api-daily-report-{day}"


def render(
    *,
    day: str,
    window_start: str,
    window_end: str,
    per_node: dict[str, NodeStats],
    global_stats: GlobalStats,
    week: Optional[WeekComparison],
    observations: list[Observation],
    source_location: str,
    app_name: str,
    tags: list[str],
    repo_url: str,
    dashboard_url: str,
    witness_url: str,
    methodology_url: str,
    custom_json_id: str = "steemapps_api_stats_daily",
    cover_image_url: Optional[str] = None,
    chain_reference: Optional[ChainReference] = None,
) -> RenderedPost:
    """Produce the final post title, permlink, body, and json_metadata.

    `cover_image_url` is the public URL of the day's PNG. When None, the
    cover image markdown is omitted (useful for tests and dry-runs that
    do not generate the image)."""
    title = f"Steem API Health — Daily Report {day}"

    # 1. Cover image at the very top — Steemit-feed previews pull it.
    body_parts: list[str] = []
    if cover_image_url:
        body_parts.append(f"![Steem API Health · {day}]({cover_image_url})")

    # 2. Executive summary — headline numbers only.
    body_parts.append(make_executive_summary(per_node, global_stats, day))

    # 3. Measurement-perspective notice.
    any_multi = any(s.source_count > 1 for s in per_node.values())
    body_parts.append(_perspective_notice(any_multi))

    # 4. Observations — only when something fired.
    if (obs_block := _observations_section(observations)):
        body_parts.append(obs_block)

    # 5. Detail table.
    body_parts.append("## Nodes\n\n" + _node_table(per_node))

    # 6. Biggest outage of the day — conditional.
    if (out_block := _biggest_outage_section(global_stats)):
        body_parts.append(out_block)

    # 7. Week-over-week — conditional.
    if (week_block := _week_section(week)):
        body_parts.append(week_block)

    # Methodology one-liner sits between the data and the asks so the
    # reader knows what the numbers mean before the "join in" block.
    body_parts.append(_methodology_one_liner(methodology_url))

    # 8. Participation appeal.
    body_parts.append(_participation_block(repo_url))

    # 9. Feedback invitation.
    body_parts.append(_feedback_block())

    # 10. Resources block.
    body_parts.append(_resources_block(
        repo_url=repo_url,
        dashboard_url=dashboard_url,
        methodology_url=methodology_url,
        witness_url=witness_url,
        custom_json_id=custom_json_id,
        chain_reference=chain_reference,
    ))

    # 11. Witness vote — subtle one-liner at the bottom (already part of
    # the resources block, intentional duplication kept out).
    body_parts.append(
        "---\n\n"
        f"*Measurement window: {window_start} — {window_end}. "
        f"Source location: `{source_location}`.*"
    )

    body = "\n\n".join(body_parts)

    json_metadata = {
        "tags": tags,
        "app": app_name,
        "format": "markdown",
        "image": [cover_image_url] if cover_image_url else [],
        "steemapps_monitor": {
            "day": day,
            "window_start": window_start,
            "window_end": window_end,
            "source_location": source_location,
            "custom_json_id": custom_json_id,
        },
    }
    return RenderedPost(
        title=title,
        permlink=build_permlink(day),
        body=body,
        json_metadata=json_metadata,
    )
