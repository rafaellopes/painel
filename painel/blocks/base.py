"""Shared helpers for block modules."""
from __future__ import annotations

import html
import time


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


# --------------------------------------------------------------------------- #
# Relative-time formatting (M11, docs/SPEC.md §15.2) -- shared here (not just  #
# resources.py) so any future block that points at something on disk can      #
# reuse it. No equivalent existed anywhere in the codebase before M11.        #
# --------------------------------------------------------------------------- #
def relative_time(ts: float, now: float | None = None) -> str:
    """"atualizado há Xm/h/d" for a unix timestamp, falling back to an
    absolute date beyond ~7 days (§15.2). `now` is injectable for tests."""
    now = time.time() if now is None else now
    delta = max(0, now - ts)
    minutes = int(delta // 60)
    if minutes < 1:
        return "atualizado agora mesmo"
    if minutes < 60:
        return f"atualizado há {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"atualizado há {hours}h"
    days = hours // 24
    if days < 7:
        return f"atualizado há {days}d"
    return f"atualizado em {time.strftime('%Y-%m-%d', time.localtime(ts))}"


# --------------------------------------------------------------------------- #
# Per-item change requests (M12) -- opt-in helper for any block whose items   #
# have a stable id and where per-item ambiguity is common enough to need a    #
# dedicated "ask about this one" affordance, not just the block-level ✎.      #
# checklist.py is the first consumer (a manual step that's unclear/ambiguous  #
# to the human is exactly the case that motivated this); any future          #
# item-bearing block (e.g. table, M2) can reuse this the same way instead of #
# inventing its own per-item mechanism.                                      #
# --------------------------------------------------------------------------- #
def item_change_request_html(block_id, item_id) -> str:
    """Small ❓ button + inline collapsed box, scoped to one item inside a
    block. Reuses the exact same generic 'cr-box-<key>'/'cr-ta-<key>' DOM id
    convention and page.py's `_crToggleBox`/sessionStorage persistence as the
    block-level change-request box (docs/SPEC.md §12) -- the key is just
    '<block>-<item>' instead of '<block>', so open/closed state survives
    reloads for free, no new JS plumbing beyond the send call itself
    (`crToggleItem`/`crSendItem` in page.py)."""
    bid, iid = e(block_id), e(item_id)
    key = f"{bid}-{iid}"
    return (
        f'<button class="ico item-cr-btn" title="Perguntar / pedir ajuda sobre este passo" '
        f'onclick="crToggleItem(\'{bid}\',\'{iid}\')">&#10067;</button>'
        f'<div id="cr-box-{key}" class="cr-box" style="display:none">'
        f'<textarea id="cr-ta-{key}" data-orig="" '
        f'placeholder="O que precisas de saber ou mudar neste passo?"></textarea>'
        f'<button onclick="crSendItem(\'{bid}\',\'{iid}\')">Enviar</button>'
        f'</div>'
    )
