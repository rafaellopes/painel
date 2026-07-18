"""Human manual steps, checked off by the user."""
from __future__ import annotations

from .. import lint
from .base import e, item_change_request_html, md_inline

TYPE = "checklist"


def _lint_marker(block: dict, item: dict) -> str:
    """Render-time safety net (M16, docs/SPEC.md §20.2 layer 2): a small inline
    ⚠ for an item that looks like it wants an answer rather than a tick, plus
    the same finding logged ONCE to stderr (deduped in lint.warn_once -- render
    runs on every poll tick). Strictly non-blocking: the item still renders,
    unchanged and fully usable. The ⚠ copy points at the per-item ❓ already
    next to it (M12, §16) as the one-click fix path -- no new UI."""
    reason = lint.check_text(item.get("text", ""))
    if not reason:
        return ""
    finding = lint.Finding(
        block=str(block.get("id", "")), item=str(item.get("id", "")),
        text=str(item.get("text", "")), reason=reason, suggestion=lint.SUGGESTION,
    )
    lint.warn_once(finding)
    return f'<span class="lint-warn" title="{e(lint.WARN_TITLE.format(reason=reason))}">&#9888;</span>'


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    items = block.get("items", [])
    rows = []
    for it in items:
        iid = e(it.get("id", ""))
        checked = "checked" if it.get("checked") else ""
        cls = "checked" if it.get("checked") else ""
        rows.append(
            f'<li class="{cls}">'
            f'<label>'
            f'<input type="checkbox" {checked} '
            f'onchange="check(\'{bid}\',\'{iid}\',this.checked)">'
            f'<span>{md_inline(e(it.get("text", "")))}</span></label>'
            f'{_lint_marker(block, it)}'
            f'{item_change_request_html(block.get("id", ""), it.get("id", ""))}'
            f'</li>'
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
