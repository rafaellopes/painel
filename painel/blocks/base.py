"""Shared helpers for block modules."""
from __future__ import annotations

import html


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def md_inline(s: str) -> str:
    """Tiny inline markdown: **bold**, `code`, and line breaks. Input pre-escaped."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s.startswith("**", i):
            j = s.find("**", i + 2)
            if j != -1:
                out.append("<strong>" + s[i + 2:j] + "</strong>")
                i = j + 2
                continue
        if s[i] == "`":
            j = s.find("`", i + 1)
            if j != -1:
                out.append("<code>" + s[i + 1:j] + "</code>")
                i = j + 1
                continue
        out.append(s[i])
        i += 1
    return "".join(out).replace("\n", "<br>")


def find_item(block: dict, item_id: str) -> dict | None:
    for it in block.get("items", []):
        if str(it.get("id")) == str(item_id):
            return it
    return None


# --------------------------------------------------------------------------- #
# Whose-turn signal helpers (M5, docs/SPEC.md §10), shared between the page   #
# shell (server.py) and any block wanting the same status chip (chat.py, M7,  #
# docs/SPEC.md §5.5). Kept here rather than in server.py so block modules can #
# import them without a circular import -- server.py imports from blocks.*,   #
# never the other way around. server.py's own _agent_status()/_status_chip() #
# now delegate to these (kept as thin wrappers for API/test compatibility).   #
# --------------------------------------------------------------------------- #
def agent_status(board: dict) -> str:
    """meta.agent_status, defaulting to 'working' when absent (backward
    compat with boards saved before M5)."""
    return board.get("meta", {}).get("agent_status") or "working"


def status_chip_text(pending: int, status: str, has_resolved: bool) -> str:
    """Header/card chip text (§10.2). 'waiting' with nothing pending renders
    the same as 'idle', per spec."""
    if pending > 0:
        return f"🔴 À espera de ti ({pending})"
    if status == "working":
        return "🟡 O agente está a trabalhar…"
    if has_resolved:
        return "✅ Tudo feito"
    return "⚪ Agente offline"
