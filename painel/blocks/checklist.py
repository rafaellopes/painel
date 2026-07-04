"""Human manual steps, checked off by the user."""
from __future__ import annotations

from .base import e, md_inline

TYPE = "checklist"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    items = block.get("items", [])
    rows = []
    for it in items:
        iid = e(it.get("id", ""))
        checked = "checked" if it.get("checked") else ""
        cls = "checked" if it.get("checked") else ""
        rows.append(
            f'<li class="{cls}"><label>'
            f'<input type="checkbox" {checked} '
            f'onchange="check(\'{bid}\',\'{iid}\',this.checked)">'
            f'<span>{md_inline(e(it.get("text", "")))}</span></label></li>'
        )
    title = e(block.get("title", "A fazer (manual)"))
    return f'<div class="card"><h3>{title}</h3><ul class="checklist">{"".join(rows)}</ul></div>'


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "check":
        return False
    for it in block.get("items", []):
        if str(it.get("id")) == str(event.get("item")):
            it["checked"] = bool(event.get("checked"))
    return True


def needs_user(block: dict) -> list:
    bid = block.get("id", "")
    n = sum(1 for it in block.get("items", []) if not it.get("checked"))
    if n:
        return [(bid, f"{n} passo{'s' if n > 1 else ''} manua{'is' if n > 1 else 'l'} por marcar")]
    return []


SILENT_EVENTS: set = set()

JS = """
function check(bid, item, checked) { send({event:'check', block:bid, item, checked}); }
"""
