"""Callout. Read-only, no events."""
from __future__ import annotations

from .base import e, md_inline

TYPE = "note"


def render(block: dict, ctx: dict) -> str:
    tone = block.get("tone", "info")
    return f'<div class="card note note-{e(tone)}">{md_inline(e(block.get("text", "")))}</div>'


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


SILENT_EVENTS: set = set()

JS: str = ""
