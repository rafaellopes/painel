"""Section title. Read-only, no events."""
from __future__ import annotations

from .base import e

TYPE = "heading"


def render(block: dict, ctx: dict) -> str:
    return f'<h2 class="section">{e(block.get("text", ""))}</h2>'


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


SILENT_EVENTS: set = set()

JS: str = ""
