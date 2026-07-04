"""Rich text (inline md: bold/italic/code/links). Read-only, no events."""
from __future__ import annotations

from .base import e, md_inline

TYPE = "markdown"


def render(block: dict, ctx: dict) -> str:
    return f'<div class="card md">{md_inline(e(block.get("text", "")))}</div>'


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


SILENT_EVENTS: set = set()

JS: str = ""
