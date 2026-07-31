"""Authorize / reject with an optional comment."""
from __future__ import annotations

from .base import e, md_inline

TYPE = "approval"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    prompt = md_inline(e(block.get("prompt", "")))
    if block.get("decision"):
        d = e(block.get("decision"))
        c = e(block.get("comment", ""))
        extra = f' — {c}' if c else ""
        return (
            f'<div class="card answered"><h3>Approval</h3><p>{prompt}</p>'
            f'<div class="answer">Decision: {d}{extra}</div></div>'
        )
    # Export (M3, §24.2): no approve/reject controls -- show the open STATE.
    if (ctx or {}).get("export"):
        return (
            f'<div class="card"><h3>Approval</h3><p>{prompt}</p>'
            f'<div class="answer muted">Awaiting decision</div></div>'
        )
    return (
        f'<div class="card"><h3>Approval</h3><p>{prompt}</p>'
        f'<textarea id="cm-{bid}" data-orig="" placeholder="Comment (optional)"></textarea>'
        f'<div class="opts">'
        f'<button class="ok" onclick="approve(\'{bid}\',\'approved\')">Approve</button>'
        f'<button class="no" onclick="approve(\'{bid}\',\'rejected\')">Reject</button>'
        f'</div></div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "approve":
        return False
    block["decision"] = event.get("decision", "")
    block["comment"] = event.get("comment", "")
    return True


def needs_user(block: dict) -> list:
    bid = block.get("id", "")
    if not block.get("decision"):
        return [(bid, "Approval pending")]
    return []


SILENT_EVENTS: set = set()

JS = """
function approve(id, decision) {
  const cm = document.getElementById('cm-'+id);
  send({event:'approve', block:id, decision, comment: cm ? cm.value : ''}).then(reloadSoon);
}
"""
