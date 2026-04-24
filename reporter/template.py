"""Bilingual DE/EN post renderer.

Produces a Steemit-compatible markdown body with both languages in one
post. The tone is deliberately flat — no superlatives, no marketing
language, no emojis — to match the project's brand voice.

The chain reference fields (tx hash, block) are optional so the dry-run
path can render the full post without a broadcast. In production, the
broadcast module calls `render` again after the `custom_json` has been
sent, passing the real tx hash for the in-post link.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from reporter.aggregation import GlobalStats, NodeStats, WeekComparison


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


def _format_uptime(pct: float) -> str:
    return f"{pct:.2f} %"


def _format_latency(ms: Optional[int]) -> str:
    return f"{ms} ms" if ms is not None else "—"


def _format_delta(pp: float) -> str:
    # Percentage-point delta with an explicit sign so a reader sees the
    # direction at a glance.
    sign = "+" if pp >= 0 else ""
    return f"{sign}{pp:.2f} pp"


def _short_url(url: str) -> str:
    """Strip `https://` for the compact table column."""
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _row_markdown(s: NodeStats) -> str:
    errclass = ", ".join(f"{k} ×{v}" for k, v in sorted(s.error_classes.items())) or "—"
    return (
        f"| `{_short_url(s.url)}` "
        f"| {s.region or '—'} "
        f"| {_format_uptime(s.uptime_pct)} "
        f"| {_format_latency(s.latency.avg_ms)} "
        f"| {_format_latency(s.latency.p95_ms)} "
        f"| {s.errors} "
        f"| {errclass} |"
    )


def _node_table(per_node: dict[str, NodeStats], header_lang: str) -> str:
    if header_lang == "de":
        header = (
            "| Node | Region | Uptime | Ø Latenz | p95 | Fehler | Fehlerklassen |\n"
            "|---|---|---|---|---|---|---|"
        )
    else:
        header = (
            "| Node | Region | Uptime | avg latency | p95 | errors | error classes |\n"
            "|---|---|---|---|---|---|---|"
        )
    # Sort by uptime descending, then by avg latency ascending — readers
    # see the healthiest nodes first, worst at the bottom.
    def _sort_key(s: NodeStats) -> tuple[float, int]:
        return (-s.uptime_pct, s.latency.avg_ms if s.latency.avg_ms is not None else 10**9)
    rows = "\n".join(_row_markdown(s) for s in sorted(per_node.values(), key=_sort_key))
    return f"{header}\n{rows}"


def _chain_reference_line(ref: Optional[ChainReference], lang: str) -> str:
    if ref is None:
        if lang == "de":
            return "Rohdaten: `custom_json`-Operation `steemapps_api_stats_daily` (Transaktion siehe Broadcast-Log dieses Reports)."
        return "Raw data: `custom_json` operation `steemapps_api_stats_daily` (transaction in this report's broadcast log)."
    if lang == "de":
        return (
            f"Rohdaten: `custom_json`-Operation `steemapps_api_stats_daily`, "
            f"Transaktion `{ref.tx_hash}` in Block `{ref.block_num}`."
        )
    return (
        f"Raw data: `custom_json` operation `steemapps_api_stats_daily`, "
        f"transaction `{ref.tx_hash}` in block `{ref.block_num}`."
    )


def _week_section(cmp: Optional[WeekComparison], lang: str) -> str:
    if cmp is None:
        if lang == "de":
            return (
                "**Wochenvergleich:** noch keine Vorwoche verfügbar "
                "(Monitor läuft erst seit kurzem)."
            )
        return (
            "**Week-over-week:** no prior week available yet "
            "(the monitor has not been running long enough)."
        )
    if lang == "de":
        header = (
            f"**Wochenvergleich:** aktuelle Woche {_format_uptime(cmp.current_uptime_pct)}, "
            f"Vorwoche {_format_uptime(cmp.previous_uptime_pct)} "
            f"(Δ {_format_delta(cmp.delta_pp)})."
        )
    else:
        header = (
            f"**Week-over-week:** current week {_format_uptime(cmp.current_uptime_pct)}, "
            f"previous week {_format_uptime(cmp.previous_uptime_pct)} "
            f"(Δ {_format_delta(cmp.delta_pp)})."
        )
    if not cmp.per_node_delta_pp:
        return header
    lines = [header, ""]
    lines.append(
        "| Node | Δ |" if lang == "en" else "| Node | Δ |"
    )
    lines.append("|---|---|")
    for url, delta in sorted(cmp.per_node_delta_pp.items(), key=lambda kv: kv[1]):
        lines.append(f"| `{_short_url(url)}` | {_format_delta(delta)} |")
    return "\n".join(lines)


def _summary_en(day: str, global_stats: GlobalStats, node_count: int,
                ref: Optional[ChainReference]) -> str:
    parts = [
        f"**Summary for {day} (UTC):** monitored {node_count} Steem API "
        f"nodes, {global_stats.total_measurements} measurements, "
        f"{_format_uptime(global_stats.uptime_pct)} global uptime.",
    ]
    if global_stats.best_node and global_stats.worst_node:
        parts.append(
            f"Best: `{_short_url(global_stats.best_node)}`. "
            f"Worst: `{_short_url(global_stats.worst_node)}`."
        )
    if global_stats.longest_outage_ticks > 0 and global_stats.longest_outage_node:
        parts.append(
            f"Longest single outage: `{_short_url(global_stats.longest_outage_node)}`, "
            f"{global_stats.longest_outage_ticks} consecutive failed ticks "
            f"({global_stats.longest_outage_ticks} minutes)."
        )
    parts.append(_chain_reference_line(ref, "en"))
    return "\n\n".join(parts)


def _summary_de(day: str, global_stats: GlobalStats, node_count: int,
                ref: Optional[ChainReference]) -> str:
    parts = [
        f"**Zusammenfassung für {day} (UTC):** {node_count} Steem-API-Nodes "
        f"beobachtet, {global_stats.total_measurements} Messungen, "
        f"{_format_uptime(global_stats.uptime_pct)} globale Uptime.",
    ]
    if global_stats.best_node and global_stats.worst_node:
        parts.append(
            f"Bester Node: `{_short_url(global_stats.best_node)}`. "
            f"Schlechtester Node: `{_short_url(global_stats.worst_node)}`."
        )
    if global_stats.longest_outage_ticks > 0 and global_stats.longest_outage_node:
        parts.append(
            f"Längster zusammenhängender Ausfall: `{_short_url(global_stats.longest_outage_node)}`, "
            f"{global_stats.longest_outage_ticks} aufeinanderfolgende Fehlversuche "
            f"({global_stats.longest_outage_ticks} Minuten)."
        )
    parts.append(_chain_reference_line(ref, "de"))
    return "\n\n".join(parts)


def _methodology_link(methodology_url: str, lang: str) -> str:
    if lang == "de":
        return (
            f"**Methodik:** Jede Minute eine `condenser_api.get_dynamic_global_properties`-"
            f"Anfrage pro Node, 8-Sekunden-Timeout, Messpunkt fix. "
            f"Alle Regeln und Schwellwerte sind in "
            f"[MESSMETHODIK]({methodology_url.replace('MEASUREMENT-METHODOLOGY', 'MESSMETHODIK')}) "
            f"festgeschrieben."
        )
    return (
        f"**Methodology:** one `condenser_api.get_dynamic_global_properties` "
        f"request per node every minute, 8-second timeout, single "
        f"measurement location. All rules and thresholds are pinned in "
        f"[MEASUREMENT-METHODOLOGY]({methodology_url})."
    )


def _footer(repo_url: str, dashboard_url: str, witness_url: str) -> str:
    # The two footer paragraphs are verbatim from the Phase-5 brief —
    # changing them requires an explicit edit, not a template tweak.
    en = (
        "This report is generated automatically by the SteemApps API Monitor,\n"
        "maintained by @greece-lover.\n\n"
        f"Dashboard: {dashboard_url} (coming soon)\n"
        f"GitHub: {repo_url}\n"
        "Raw data: custom_json operation `steemapps_api_stats_daily`\n\n"
        "If you find this work valuable, consider voting for @greece-lover\n"
        f"as witness: {witness_url}"
    )
    de = (
        "Dieser Report wird automatisch vom SteemApps API Monitor generiert,\n"
        "betrieben von @greece-lover.\n\n"
        f"Dashboard: {dashboard_url} (bald verfügbar)\n"
        f"GitHub: {repo_url}\n"
        "Rohdaten: custom_json-Operation `steemapps_api_stats_daily`\n\n"
        "Wer die Arbeit unterstützen möchte, kann @greece-lover als Witness\n"
        f"voten: {witness_url}"
    )
    return (
        "## About this report\n\n"
        "```\n" + en + "\n```\n\n"
        "## Über diesen Report\n\n"
        "```\n" + de + "\n```"
    )


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
    source_location: str,
    app_name: str,
    tags: list[str],
    repo_url: str,
    dashboard_url: str,
    witness_url: str,
    methodology_url: str,
    chain_reference: Optional[ChainReference] = None,
) -> RenderedPost:
    """Produce the final post title, permlink, body, and json_metadata."""
    title = f"Steem API Monitor — Daily Report {day}"

    body_parts: list[str] = []

    body_parts.append("## English")
    body_parts.append(_summary_en(day, global_stats, len(per_node), chain_reference))
    body_parts.append("### Nodes")
    body_parts.append(_node_table(per_node, header_lang="en"))
    body_parts.append(_week_section(week, lang="en"))
    body_parts.append(_methodology_link(methodology_url, lang="en"))

    body_parts.append("---")

    body_parts.append("## Deutsch")
    body_parts.append(_summary_de(day, global_stats, len(per_node), chain_reference))
    body_parts.append("### Nodes")
    body_parts.append(_node_table(per_node, header_lang="de"))
    body_parts.append(_week_section(week, lang="de"))
    body_parts.append(_methodology_link(methodology_url, lang="de"))

    body_parts.append("---")
    body_parts.append(_footer(repo_url, dashboard_url, witness_url))

    body_parts.append("---")
    body_parts.append(
        f"*Measurement window: {window_start} — {window_end}. "
        f"Source location: {source_location}.*"
    )

    body = "\n\n".join(body_parts)

    json_metadata = {
        "tags": tags,
        "app": app_name,
        "format": "markdown",
        "steemapps_monitor": {
            "day": day,
            "window_start": window_start,
            "window_end": window_end,
            "source_location": source_location,
            "custom_json_id": "steemapps_api_stats_daily",
        },
    }
    return RenderedPost(
        title=title,
        permlink=build_permlink(day),
        body=body,
        json_metadata=json_metadata,
    )
