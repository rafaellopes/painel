"""Agent progress, read-only. No events."""
from __future__ import annotations

from .base import e

TYPE = "tasks"


def render(block: dict, ctx: dict) -> str:
    items = block.get("items", [])
    done = sum(1 for it in items if it.get("status") == "done")
    total = len(items)
    pct = int(done / total * 100) if total else 0
    rows = []
    for it in items:
        st = it.get("status", "pending")
        tc = "done-text" if st == "done" else ""
        rows.append(
            f'<li><span class="dot {e(st)}"></span>'
            f'<span class="{tc}">{e(it.get("text", ""))}</span></li>'
        )
    title = e(block.get("title", "Progresso"))
    return (
        f'<div class="card"><h3>{title}</h3>'
        f'<div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>'
        f'<ul class="tasks">{"".join(rows)}</ul>'
        f'<div class="muted small">{done}/{total} concluídas</div></div>'
    )


def apply(block: dict, event: dict) -> bool:
    return False


def needs_user(block: dict) -> list:
    return []


SILENT_EVENTS: set = set()

JS: str = ""
