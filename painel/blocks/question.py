"""Free-text ask."""
from __future__ import annotations

from .base import e, md_inline

TYPE = "question"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    prompt = md_inline(e(block.get("prompt", "")))
    if block.get("answer") not in (None, ""):
        return (
            f'<div class="card answered"><h3>Pergunta</h3><p>{prompt}</p>'
            f'<div class="answer">Resposta: {e(block.get("answer"))}</div></div>'
        )
    return (
        f'<div class="card"><h3>Pergunta</h3><p>{prompt}</p>'
        f'<textarea id="ta-{bid}" data-orig="" placeholder="Escreve a tua resposta..."></textarea>'
        f'<button onclick="answer(\'{bid}\')">Enviar</button></div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "answer":
        return False
    block["answer"] = event.get("value", "")
    return True


def needs_user(block: dict) -> list:
    bid = block.get("id", "")
    if block.get("answer") in (None, ""):
        return [(bid, "Pergunta por responder")]
    return []


SILENT_EVENTS: set = set()

JS = """
function answer(id) {
  const v = document.getElementById('ta-'+id).value;
  if (!v.trim()) return;
  send({event:'answer', block:id, value:v}).then(reloadSoon);
}
"""
