"""Thin logging wrapper.

systemd's journal already handles timestamps, colouring, and rotation when
it reads stdout, so we keep our own format minimal: one line per event, with
a level and a module hint. If the format needs to change later (JSON for a
log aggregator, say), this is the single place to do it.
"""

from __future__ import annotations

import logging
import sys


_CONFIGURED = False


def setup(level: int = logging.INFO) -> None:
    """Configure the root logger once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(level)
    # Remove any handlers a dependency might have attached.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root.addHandler(handler)
    _CONFIGURED = True


def get(name: str) -> logging.Logger:
    """Return a logger with standard setup applied."""
    setup()
    return logging.getLogger(name)
