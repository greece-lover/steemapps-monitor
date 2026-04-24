"""Reporter configuration — env-driven, with safe defaults for dev mode.

The posting key is the one piece of state that must never land in the repo,
so it is *only* read from the environment (populated on the VM by a
systemd `EnvironmentFile=` directive pointing at `.env.local`). Everything
else has a sensible default that works out-of-the-box for a local dry-run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Reuse the monitor's paths so the reporter reads the same measurements DB
# the poller writes to.
import config as monitor_config


MODE_PROD = "prod"
MODE_DEV = "dev"


@dataclass(frozen=True)
class ReporterConfig:
    mode: str
    account: str
    posting_key: Optional[str]
    custom_json_id: str
    tags: list[str]
    app_name: str
    dashboard_url: str
    methodology_url: str
    repo_url: str
    witness_url: str
    db_path: Path
    broadcast_retry_count: int
    broadcast_retry_sleep_s: int

    @property
    def is_dev(self) -> bool:
        return self.mode == MODE_DEV


def _load_env_file(path: Path) -> None:
    """Best-effort loader for `.env.local` so a dev doesn't need a shell alias.

    systemd's `EnvironmentFile=` does the equivalent in production, so this
    exists purely for `python -m reporter.daily_report --dry-run` runs from
    a plain shell without extra setup. Lines are `KEY=VALUE` or `KEY="VALUE"`;
    unset values already in the environment win, so an explicit export on
    the shell keeps precedence over the file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load(env_file: Path | None = None) -> ReporterConfig:
    """Build a ReporterConfig from the current environment."""
    here = Path(__file__).resolve().parent
    default_env = here / ".env.local"
    _load_env_file(env_file if env_file is not None else default_env)

    mode = os.environ.get("STEEMAPPS_REPORTER_MODE", MODE_PROD).lower()
    if mode not in {MODE_PROD, MODE_DEV}:
        raise ValueError(
            f"STEEMAPPS_REPORTER_MODE must be 'prod' or 'dev', got: {mode!r}"
        )
    tags_raw = os.environ.get(
        "STEEMAPPS_REPORTER_TAGS",
        "steem,api,monitoring,witness,steemapps",
    )
    return ReporterConfig(
        mode=mode,
        account=os.environ.get("STEEMAPPS_REPORTER_ACCOUNT", "steem-api-health"),
        posting_key=os.environ.get("STEEMAPPS_REPORTER_POSTING_KEY"),
        custom_json_id=os.environ.get(
            "STEEMAPPS_REPORTER_CUSTOM_JSON_ID",
            "steemapps_api_stats_daily",
        ),
        tags=[t.strip() for t in tags_raw.split(",") if t.strip()],
        app_name=os.environ.get("STEEMAPPS_REPORTER_APP", "steemapps-monitor/0.1"),
        dashboard_url=os.environ.get(
            "STEEMAPPS_REPORTER_DASHBOARD_URL",
            "https://api.steemapps.com",
        ),
        methodology_url=os.environ.get(
            "STEEMAPPS_REPORTER_METHODOLOGY_URL",
            "https://github.com/greece-lover/steemapps-monitor/blob/main/docs/MEASUREMENT-METHODOLOGY.md",
        ),
        repo_url=os.environ.get(
            "STEEMAPPS_REPORTER_REPO_URL",
            "https://github.com/greece-lover/steemapps-monitor",
        ),
        witness_url=os.environ.get(
            "STEEMAPPS_REPORTER_WITNESS_URL",
            "https://steemitwallet.com/~witnesses",
        ),
        db_path=Path(os.environ.get("STEEMAPPS_REPORTER_DB_PATH", str(monitor_config.DB_PATH))),
        broadcast_retry_count=int(os.environ.get("STEEMAPPS_REPORTER_RETRY", "3")),
        broadcast_retry_sleep_s=int(os.environ.get("STEEMAPPS_REPORTER_RETRY_SLEEP", "60")),
    )
