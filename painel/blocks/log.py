"""Timeline / decisions log. Read-only, no events."""
from __future__ import annotations

from .base import e

TYPE = "log"


def render(block: dict, ctx: dict) -> str:
    rows = "".join(
        f'<li><span class="muted small">{e(en.get("ts", ""))}</span> {e(en.get("text", ""))}</li>'
        for en in block.get("entries", [])
    )
    title = e(block.get("title", "Registo"))
    return f'<div class="card"><h3>{title}</h3><ul class="log">{rows}</ul></div>'


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


SILENT_EVENTS: set = set()

JS: str = ""
