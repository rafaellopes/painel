"""
The directory (M13, docs/SPEC.md §17.4): the unified service's `/` page,
listing every *registered project* as a clickable card linking to `/<slug>`.

Supersedes M9's hub (§13), which listed live processes. Same rendering, new
data source: painel/registry.py instead of a per-port process registry. A
project with no process of its own still appears -- which, post-M13, is every
project, and is precisely the point (§17.1).

This is host-app chrome, NOT a board a human composes -- §13.2's rule still
holds: it deliberately does NOT go through the blocks/ registry (no new
public block type). It reuses page.py's `_PAGE` template/CSS/JS directly,
filling only the placeholders a plain, nav-less, attention-bar-less page needs.

Re-reads the registry on every request -- no caching, exactly like
_needs_user() is recomputed on every render.
"""
from __future__ import annotations

import json

from .blocks import REGISTRY
from .blocks.base import e, agent_status as _agent_status, status_chip_text as _status_chip_text
from .page import _PAGE

STRINGS = {
    "title": "pAInel — os teus projetos",
    "empty": "Nenhum projeto registado. Corre 'painel add' na pasta de um projeto.",
    "missing": "⚠ board não encontrado neste caminho",
    "unknown": "pAInel — projeto desconhecido",
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


def _card_html(entry: dict) -> str:
    """One card per registered project: title, project metaline, and the
    agent_status chip (§10.2, shared helpers) whose pending count reuses the
    same _needs_user() logic as the page-nav badges (§11.2)."""
    board = _load_board_safe(entry["path"])
    if board is None:
        # §17.3: visibly missing, never silently dropped. Not a link -- there
        # is nothing to open -- and it names the path, so a moved project is
        # diagnosable at a glance instead of just vanishing from the list.
        return (
            f'<div class="card dir-missing">'
            f'<h3>{e(entry["title"])}</h3>'
            f'<div class="metaline res-path">{e(entry["path"])}</div>'
            f'<div class="res-warn">{e(STRINGS["missing"])} — '
            f'<code>painel remove {e(entry["slug"])}</code></div>'
            f'</div>'
        )
    title = board.get("title", entry["title"])
    project = board.get("meta", {}).get("project", "")
    pending = _needs_user_count(board)
    has_resolved = False  # not worth rendering every block's HTML just for this
    chip = _status_chip_text(pending, _agent_status(board), has_resolved)
    metaline = f"Projeto: {e(project)}" if project else ""
    return (
        f'<a class="card dir-card" href="/{e(entry["slug"])}">'
        f'<h3>{e(title)}</h3>'
        f'<div class="metaline">{metaline}</div>'
        f'<div class="status-chip">{e(chip)}</div>'
        f'</a>'
    )


def _shell(title: str, cards: str) -> str:
    """page.py's _PAGE with only what host-app chrome needs. base_path is ''
    and channel_id is absent: the directory lives at the service root, so its
    JS keeps M10's port-derived BroadcastChannel name -- directory tabs dedupe
    against each other and never against a board's tab, since boards key on
    their own slug (§17.4)."""
    return _PAGE.format(
        title=e(title), metaline="", attention="",
        # M14 (§18): the directory IS the top of the hierarchy -- it gets no
        # board-shell breadcrumb and no project switcher (§18.4).
        breadcrumb="",
        nav="", nav_class="",
        page_shell_open="", page_shell_close="",
        page_main_open="", page_main_close="",
        blocks=cards, block_js="",
        base_path_js='""',
        channel_id_js="(location.port || '80')",
        board_title_js=json.dumps(title, ensure_ascii=False),
        pending_count=0,
        agent_status_js=json.dumps("idle", ensure_ascii=False),
        has_resolved="false",
        status_chip="",
        cr_global="",  # host-app chrome, not a board -- no change-request affordance
    )


def render_directory(entries: list) -> str:
    """The `/` page, from registry.entries()'s output
    ([{"slug","path","title","missing"}])."""
    if entries:
        cards = "".join(_card_html(entry) for entry in entries)
    else:
        cards = f'<div class="card muted">{e(STRINGS["empty"])}</div>'
    return _shell(STRINGS["title"], cards)


def render_unknown_slug(slug: str, entries: list) -> str:
    """§17.4: an unknown slug gets a clear page listing what *is* registered,
    not a bare 404 -- the human either mistyped or the project was removed,
    and both are recoverable in one click from here."""
    if entries:
        listing = "".join(
            f'<li><a href="/{e(x["slug"])}">{e(x["title"])}</a> '
            f'<code>/{e(x["slug"])}</code></li>'
            for x in entries
        )
        known = f'<div class="card"><h3>Projetos registados</h3><ul class="log">{listing}</ul></div>'
    else:
        known = f'<div class="card muted">{e(STRINGS["empty"])}</div>'
    head = (
        f'<div class="card note note-warn">'
        f'<p>Não há nenhum projeto registado como <code>{e(slug)}</code>.</p>'
        f'<p class="muted small">Ou o endereço tem uma gralha, ou o projeto foi removido. '
        f'Para registar: <code>painel add &lt;pasta&gt;</code>.</p>'
        f'</div>'
    )
    return _shell(STRINGS["unknown"], head + known)
