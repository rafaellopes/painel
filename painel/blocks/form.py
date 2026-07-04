"""Multi-field input form."""
from __future__ import annotations

import json

from .base import e, md_inline

TYPE = "form"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    prompt = md_inline(e(block.get("prompt", "")))
    if block.get("submitted"):
        rows = "".join(
            f'<div class="answer">{e(f.get("label"))}: {e(f.get("value"))}</div>'
            for f in block.get("fields", [])
        )
        return f'<div class="card answered"><h3>Formulário</h3><p>{prompt}</p>{rows}</div>'
    fields = []
    for f in block.get("fields", []):
        fid = e(f.get("id", ""))
        label = e(f.get("label", ""))
        kind = f.get("kind", "text")
        val = e(f.get("value", ""))
        if kind == "select":
            opts = "".join(f"<option>{e(o)}</option>" for o in f.get("options", []))
            inp = f'<select id="fld-{bid}-{fid}">{opts}</select>'
        elif kind == "textarea":
            inp = f'<textarea id="fld-{bid}-{fid}" data-orig="">{val}</textarea>'
        else:
            itype = kind if kind in ("number", "date", "email") else "text"
            inp = f'<input id="fld-{bid}-{fid}" type="{itype}" value="{val}" data-orig="{val}">'
        fields.append(f'<label class="field"><span>{label}</span>{inp}</label>')
    ids = e(json.dumps([f.get("id") for f in block.get("fields", [])]))
    return (
        f'<div class="card"><h3>Formulário</h3><p>{prompt}</p>{"".join(fields)}'
        f'<button onclick="submitForm(\'{bid}\',{ids})">Enviar</button></div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "submit":
        return False
    vals = event.get("values", {})
    for f in block.get("fields", []):
        if f.get("id") in vals:
            f["value"] = vals[f["id"]]
    block["submitted"] = True
    return True


def needs_user(block: dict) -> list:
    bid = block.get("id", "")
    if not block.get("submitted"):
        return [(bid, "Formulário por preencher")]
    return []


SILENT_EVENTS: set = set()

JS = """
function submitForm(id, ids) {
  const values = {};
  ids.forEach(fid => { const el = document.getElementById('fld-'+id+'-'+fid); if (el) values[fid]=el.value; });
  send({event:'submit', block:id, values}).then(reloadSoon);
}
"""
