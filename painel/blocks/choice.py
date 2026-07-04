"""Pick one option."""
from __future__ import annotations

import json

from .base import e, md_inline

TYPE = "choice"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    prompt = md_inline(e(block.get("prompt", "")))
    if block.get("selected") not in (None, ""):
        return (
            f'<div class="card answered"><h3>Escolha</h3><p>{prompt}</p>'
            f'<div class="answer">Escolhido: {e(block.get("selected"))}</div></div>'
        )
    btns = "".join(
        f'<button class="opt" onclick="choose(\'{bid}\',{e(json.dumps(o))})">{e(o)}</button>'
        for o in block.get("options", [])
    )
    return f'<div class="card"><h3>Escolha</h3><p>{prompt}</p><div class="opts">{btns}</div></div>'


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "choose":
        return False
    block["selected"] = event.get("value", "")
    return True


def needs_user(block: dict) -> list:
    bid = block.get("id", "")
    if block.get("selected") in (None, ""):
        return [(bid, "Escolha pendente")]
    return []


SILENT_EVENTS: set = set()

JS = """
function choose(id, value) { send({event:'choose', block:id, value}).then(reloadSoon); }
"""
