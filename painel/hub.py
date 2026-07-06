"""
The hub (M9, docs/SPEC.md §13): a tiny built-in page, on a fixed well-known
port (default 8765), listing every live pAInel instance from the §6.6
registry as a clickable card.

This is host-app chrome, NOT a board a human composes -- it deliberately does
NOT go through the blocks/ registry (no new public block type). It reuses
page.py's `_PAGE` template/CSS/JS directly so it looks consistent with every
other pAInel page, via a lightweight rendering path that only fills the
placeholders a plain, nav-less, attention-bar-less page needs.

Re-reads the registry on every request -- no caching, exactly like
_needs_user() is recomputed on every render (§13.2).
"""
from __future__ import annotations

import json
import os

from .blocks import REGISTRY
from .blocks.base import e, agent_status as _agent_status, status_chip_text as _status_chip_text
from .page import _PAGE

STRINGS = {
    "title": "pAInel — os teus boards",
    "empty": "Nenhum pAInel a correr neste momento.",
}


def _needs_user_count(board: dict) -> int:
    n = 0
    for b in board.get("blocks", []):
        mod = REGISTRY.get(b.get("type"))
        if mod is None:
            continue
        n += len(mod.needs_user(b))
    return n


def _load_board_safe(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _card_html(inst: dict) -> str:
    """One clickable card for a live instance: title, project, pending
    badge (reusing the same _needs_user() logic as page-nav badges,
    §11.2), and the agent_status chip (§10.2, shared helpers)."""
    port = inst["port"]
    board_path = inst["board"]
    url = f"http://localhost:{port}/"
    board = _load_board_safe(board_path)
    if board is None:
        title = os.path.basename(board_path)
        project = ""
        chip = ""
    else:
        title = board.get("title", "pAInel")
        project = board.get("meta", {}).get("project", "")
        pending = _needs_user_count(board)
        status = _agent_status(board)
        has_resolved = False  # not worth computing full block HTML just for this
        chip = _status_chip_text(pending, status, has_resolved)
    metaline = f"Projeto: {e(project)}" if project else ""
    return (
        f'<a class="card hub-card" href="{e(url)}">'
        f'<h3>{e(title)}</h3>'
        f'<div class="metaline">{metaline}</div>'
        f'<div class="status-chip">{e(chip)}</div>'
        f'</a>'
    )


def render_hub(instances: list) -> str:
    """Render the hub page from the current list of live instances
    (§6.6's `_discover_running_boards()` output: [{"pid","board","port"}])."""
    if instances:
        cards = "".join(_card_html(inst) for inst in instances)
    else:
        cards = f'<div class="card muted">{e(STRINGS["empty"])}</div>'
    title = STRINGS["title"]
    return _PAGE.format(
        title=e(title), metaline="", attention="",
        nav="", nav_class="",
        page_shell_open="", page_shell_close="",
        page_main_open="", page_main_close="",
        blocks=cards, block_js="",
        board_title_js=json.dumps(title, ensure_ascii=False),
        pending_count=0,
        agent_status_js=json.dumps("idle", ensure_ascii=False),
        has_resolved="false",
        status_chip="",
        cr_global="",  # host-app chrome, not a board -- no change-request affordance here
    )
