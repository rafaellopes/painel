"""Free-text ask."""
from __future__ import annotations

from .base import e, md_inline

TYPE = "question"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    prompt = md_inline(e(block.get("prompt", "")))
    if block.get("answer") not in (None, ""):
        return (
            f'<div class="card answered"><h3>Question</h3><p>{prompt}</p>'
            f'<div class="answer">Answer: {e(block.get("answer"))}</div></div>'
        )
    # Export (M3, §24.2): no submit input -- show the open STATE (prompt marked
    # open), not an interactive control that a static file can't drive.
    if (ctx or {}).get("export"):
        return (
            f'<div class="card"><h3>Question</h3><p>{prompt}</p>'
            f'<div class="answer muted">Awaiting answer</div></div>'
        )
    return (
        f'<div class="card"><h3>Question</h3><p>{prompt}</p>'
        f'<textarea id="ta-{bid}" data-orig="" placeholder="Type your answer…"></textarea>'
        f'<button onclick="answer(\'{bid}\')">Send</button></div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "answer":
        return False
    block["answer"] = event.get("value", "")
    return True


def needs_user(block: dict) -> list:
    bid = block.get("id", "")
    if block.get("answer") in (None, ""):
        return [(bid, "Question to answer")]
    return []


SILENT_EVENTS: set = set()

JS = """
function answer(id) {
  const v = document.getElementById('ta-'+id).value;
  if (!v.trim()) return;
  send({event:'answer', block:id, value:v}).then(reloadSoon);
}
"""
