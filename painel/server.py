"""
pAInel — the second interface for CLI agents.

A single-file-feeling, dependency-free web server that turns a `board.json`
file into an interactive dashboard. The agent composes typed blocks
(checklists, questions, approvals, progress, forms...); the human interacts
in the browser; every interaction is written back to the board AND emitted
as one JSONL line on stdout, so the agent can react in real time.

Protocol
--------
- Input:  board.json  (ordered list of typed blocks)
- Output: one JSON line per interaction, in that board's own `<board>.log`
          (and on stdout). See emit_event() -- this is the agent's channel
          and the contract M13 was built around, not incidental logging.

Run:  python -m painel service            # every registered project (M13)
      python -m painel serve board.json   # one board, foreground

Two serving modes live here (docs/SPEC.md §17):
- `_Handler`/`serve()`   -- one process, one board, board at the root.
- `_ServiceHandler`/`serve_service()` -- one process, every registered
  project, addressed by slug. Both share `_Routes` for what a board page, a
  version payload and an event *are*; only their route tables differ.

This module is the HTTP layer + event dispatch + page shell only. Block
rendering/behavior lives in painel/blocks/; the page template, CSS, and
global JS live in painel/page.py. See docs/SPEC.md for the full contract.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, unquote

from . import directory, registry
from .blocks import REGISTRY
from .blocks.base import e, agent_status as _blocks_agent_status, status_chip_text as _blocks_status_chip_text
from .page import _PAGE, CR_GLOBAL_HTML, UPLOAD_GLOBAL_HTML

_lock = threading.Lock()

# Deterministic order for joining per-block JS into the page: matches the
# order blocks were introduced historically, so the generated <script> is
# byte-identical to the pre-refactor monolith. New block types (not in this
# list) are appended after, sorted by type name, for stable output.
_JS_ORDER = ["question", "choice", "checklist", "approval", "form", "plan"]


# --------------------------------------------------------------------------- #
# State                                                                        #
# --------------------------------------------------------------------------- #
def _empty_board() -> dict:
    return {"protocol": 1, "title": "pAInel", "meta": {}, "blocks": []}


def load_board(path: str) -> dict:
    if not os.path.exists(path):
        save_board(path, _empty_board())
    with open(path, "r", encoding="utf-8") as fh:
        board = json.load(fh)
    board.setdefault("protocol", 1)
    board.setdefault("title", "pAInel")
    board.setdefault("meta", {})
    board.setdefault("blocks", [])
    return board


def save_board(path: str, board: dict) -> None:
    board.setdefault("protocol", 1)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(board, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _find(board: dict, block_id: str) -> dict | None:
    for b in board.get("blocks", []):
        if str(b.get("id")) == str(block_id):
            return b
    return None


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #
def _block_html(b: dict, ctx: dict) -> str:
    t = b.get("type")
    mod = REGISTRY.get(t)
    if mod is None:
        return f'<div class="card muted">bloco desconhecido: {e(t)}</div>'
    return mod.render(b, ctx)


def _needs_user(board: dict) -> list:
    """Everything currently waiting on the human: (block_id, short label).

    Open change requests (docs/SPEC.md §12.4) are deliberately NOT included
    here: an open change request is something the AGENT owes a resolution
    to, mirroring the same reasoning M7/chat.py already applies to an
    unanswered user message -- it's the agent's turn, not the human's, so it
    must never appear in this human-facing attention bar."""
    out = []
    for b in board.get("blocks", []):
        mod = REGISTRY.get(b.get("type"))
        if mod is None:
            continue
        out.extend(mod.needs_user(b))
    return out


def _watched_paths_mtime(board: dict) -> float:
    """M11 (docs/SPEC.md §15.2): max mtime across every path any block's
    optional watched_paths(block) hook returns. Generic and block-type
    agnostic -- calls REGISTRY[type].watched_paths(block) only when the
    module actually defines it (most blocks won't; use getattr, not a
    name check), so any future block type can opt into the same
    auto-refresh mechanism without ever touching this function again.
    Missing paths (or blocks without the hook) are silently ignored, never
    an error -- matches every other graceful-degradation rule in this file."""
    best = 0.0
    for b in board.get("blocks", []):
        mod = REGISTRY.get(b.get("type"))
        if mod is None:
            continue
        watched_paths = getattr(mod, "watched_paths", None)
        if watched_paths is None:
            continue
        for p in watched_paths(b):
            try:
                best = max(best, os.path.getmtime(p))
            except OSError:
                pass
    return best


# --------------------------------------------------------------------------- #
# Change requests (M8, docs/SPEC.md §12)                                      #
# --------------------------------------------------------------------------- #
def _open_change_requests(board: dict) -> list:
    return [cr for cr in board.get("change_requests", []) if cr.get("status", "open") == "open"]


def _append_change_request(board: dict, data: dict) -> dict:
    """Append one entry to the board-level change_requests array (§12.1).
    Not stored on any block -- it survives even if the referenced block is
    later removed/changed. `ts` is left to the agent to fill in later (the
    server does not generate timestamps, matching every other event in this
    codebase); a numeric, monotonic `id` is generated here purely so the
    agent has something stable to reference when flipping `status`.
    `item` (M12) is optional -- present when the request came from a
    per-item ❓ (docs/SPEC.md §12, checklist.py's item_change_request_html),
    absent/None for the ordinary block-level ✎ or the global affordance,
    exactly as before."""
    crs = board.setdefault("change_requests", [])
    cr = {
        "id": f"cr{len(crs) + 1}",
        "block": data.get("block"),
        "item": data.get("item"),
        "text": data.get("value", ""),
        "status": "open",
        "ts": "",
    }
    crs.append(cr)
    return cr


def _change_requests_html(board: dict, base: str = "") -> str:
    """'Pedidos em aberto' card (§12.4) -- board-level rendering, not a
    blocks/*.py module, since change_requests is board-level state, not a
    block. Reuses log-block-style rows conceptually."""
    open_crs = _open_change_requests(board)
    if not open_crs:
        return ""
    block_page = {str(b.get("id")): b.get("page") for b in board.get("blocks", [])}
    block_by_id = {str(b.get("id")): b for b in board.get("blocks", [])}
    rows = []
    for cr in open_crs:
        text = e(cr.get("text", ""))
        bid = cr.get("block")
        item_id = cr.get("item")
        item_suffix = ""
        if bid and item_id:
            # Resolve the item's own text (M12) so "Pedidos em aberto" is
            # readable without opening the board to figure out which of N
            # checklist items the human meant -- best-effort, falls back to
            # nothing if the item was since removed/renamed.
            blk = block_by_id.get(str(bid))
            item_text = next(
                (it.get("text") for it in (blk.get("items", []) if blk else [])
                 if str(it.get("id")) == str(item_id)),
                None,
            )
            if item_text:
                item_suffix = f' — <em>{e(item_text)}</em>'
        if bid:
            href = f"{_page_href(block_page.get(str(bid)), base)}#blk-{e(bid)}"
            link = f' <a href="{e(href)}">→ {e(bid)}</a>'
        else:
            link = ""
        rows.append(f"<li>{text}{item_suffix}{link}</li>")
    return (
        '<div class="card cr-card"><h3>Pedidos em aberto</h3>'
        f'<ul class="log">{"".join(rows)}</ul></div>'
    )


# --------------------------------------------------------------------------- #
# Multi-page navigation (M6, docs/SPEC.md §11)                                #
# --------------------------------------------------------------------------- #
def _pages(board: dict) -> list:
    """Distinct page names in order of first appearance, Home (None) always
    first regardless of where it first appears among the blocks."""
    pages = [None]
    for b in board.get("blocks", []):
        p = b.get("page")
        if p is not None and p not in pages:
            pages.append(p)
    return pages


def _blocks_by_page(board: dict) -> dict:
    """{page_name_or_None: [blocks]} preserving overall board order."""
    out: dict = {}
    for b in board.get("blocks", []):
        out.setdefault(b.get("page"), []).append(b)
    return out


def _page_pending_counts(board: dict) -> dict:
    """{page_name_or_None: pending_count} -- intersect needs_user() block ids
    with each page's block ids."""
    by_page = _blocks_by_page(board)
    pending_ids = {bid for bid, _ in _needs_user(board)}
    counts = {}
    for page, blocks_list in by_page.items():
        ids = {str(b.get("id")) for b in blocks_list}
        counts[page] = len(pending_ids & ids)
    return counts


_BADGE_DIGITS = "⓪①②③④⑤⑥⑦⑧⑨"


def _badge(n: int) -> str:
    if n <= 0:
        return ""
    if n < len(_BADGE_DIGITS):
        return f" {_BADGE_DIGITS[n]}"
    return f" ({n})"


def _page_label(page) -> str:
    return page if page is not None else None  # resolved against board title by caller


def _page_href(page, base: str = "") -> str:
    """Friendly path-based URL for a page (§11.2): '/' for Home, '/<page>'
    otherwise -- e.g. '/Estrat%C3%A9gia' instead of '/?page=Estrat%C3%A9gia'.
    Browsers commonly render the percent-escaped UTF-8 back to readable
    accented text in the address bar. `?page=` on Home is still accepted by
    do_GET for old bookmarked/shared links (see do_GET).

    `base` (M13, §17.4) prefixes every link with the board's own mount point
    under the unified service ('/livrete' -> '/livrete', '/livrete/Estratégia').
    It stays '' in single-board mode, where the board IS the server root, so
    every pre-M13 URL is produced byte-identically."""
    if page is None:
        return base or "/"
    return f"{base}/{quote(page, safe='')}"


def _nav_html(board: dict, active_page, base: str = "") -> str:
    """Sidebar/dropdown nav (§11.2). Empty string when < 2 distinct pages --
    this is the backward-compat guarantee: pageless boards get zero nav markup."""
    pages = _pages(board)
    if len(pages) < 2:
        return ""
    board_title = board.get("title", "pAInel")
    counts = _page_pending_counts(board)
    items = []
    for p in pages:
        name = board_title if p is None else p
        cls = "nav-item active" if p == active_page else "nav-item"
        items.append(
            f'<a class="{cls}" href="{e(_page_href(p, base))}">{e(name)}{_badge(counts.get(p, 0))}</a>'
        )
    options = "".join(
        f'<option value="{e(_page_href(p, base))}"{" selected" if p == active_page else ""}>'
        f'{e(board_title if p is None else p)}{_badge(counts.get(p, 0))}</option>'
        for p in pages
    )
    return (
        '<nav class="pages-nav">'
        f'<div class="pages-sidebar">{"".join(items)}</div>'
        '<div class="pages-dropdown">'
        '<select onchange="if (this.value) location.href = this.value;">'
        f'{options}</select></div>'
        '</nav>'
    )


# --------------------------------------------------------------------------- #
# Navigation shell (M14, docs/SPEC.md §18)                                    #
# --------------------------------------------------------------------------- #
def _breadcrumb_html(board: dict, active_page, base_path: str, service_mode: bool) -> str:
    """The linked trail atop every board page (§18.1):

        📋 Todos os projetos › <Projeto> › <Página>

    On a board's Home the trail stops at <Projeto> (no page segment). Under the
    unified service `Todos os projetos` links to `/` (the directory) and
    <Projeto> links to the board's Home (`/<slug>`); the current segment is
    always plain text -- you're on it.

    In single-board `painel serve` there is no directory and no `/` route to
    link to (§18.1): the `Todos os projetos` segment is omitted entirely and
    the project segment is plain text, so the breadcrumb never points at a
    route this mode doesn't serve. The server knows its mode (same signal M13
    threads for the base path), so this is decided server-side, never in JS."""
    board_title = board.get("title", "pAInel")
    sep = '<span class="crumb-sep">›</span>'
    parts = []
    if service_mode:
        parts.append('<a href="/">📋 Todos os projetos</a>')
        if active_page is None:
            parts.append(f'<span class="crumb-current">{e(board_title)}</span>')
        else:
            parts.append(f'<a href="{e(base_path or "/")}">{e(board_title)}</a>')
            parts.append(f'<span class="crumb-current">{e(active_page)}</span>')
    else:
        # Single-board: no `/` directory link at all; segments are plain text.
        parts.append(f'<span class="crumb-current">{e(board_title)}</span>')
        if active_page is not None:
            parts.append(f'<span class="crumb-current">{e(active_page)}</span>')
    return f'<div class="breadcrumb">{f" {sep} ".join(parts)}</div>'


def _switcher_html(board: dict, slug, entries) -> str:
    """Region 1 of the app shell (§18.2): the project switcher.

    Under the unified service (`entries` is the registry snapshot) it shows the
    current project plus a collapsible list of every registered project, each
    with its own pending badge -- the exact same per-project count the
    directory card shows, computed by the shared `directory._needs_user_count`
    so the two can never drift. The current project is marked; the collapsed
    summary calls out "N à tua espera noutros projetos" whenever any OTHER
    project has pending, which is what makes that count travel across pages.

    Under single-board `painel serve` there is no registry (`entries is None`),
    so it degrades cleanly to just the current project's name -- no list, no
    other projects, no crash (§18.2)."""
    board_title = board.get("title", "pAInel")
    if entries is None:
        return (
            '<div class="switcher">'
            f'<div class="switcher-current">📋 {e(board_title)}</div>'
            '</div>'
        )
    others_pending = 0
    items = []
    for entry in entries:
        is_current = entry["slug"] == slug
        b = directory._load_board_safe(entry["path"])
        count = directory._needs_user_count(b) if b else 0
        if not is_current:
            others_pending += count
        cls = "switcher-item current" if is_current else "switcher-item"
        items.append(
            f'<a class="{cls}" href="/{e(entry["slug"])}">'
            f'{e(entry["title"])}{_badge(count)}</a>'
        )
    if others_pending > 0:
        summary = f"{others_pending} à tua espera noutros projetos"
    else:
        summary = "Mudar de projeto"
    return (
        '<div class="switcher">'
        f'<div class="switcher-current">📋 {e(board_title)}</div>'
        '<details id="switcher-others">'
        f'<summary>{e(summary)}</summary>'
        f'<div class="switcher-list">{"".join(items)}</div>'
        '</details>'
        '</div>'
    )


# --------------------------------------------------------------------------- #
# Whose-turn signal (M5, docs/SPEC.md §10)                                    #
# --------------------------------------------------------------------------- #
def _agent_status(board: dict) -> str:
    """meta.agent_status, defaulting to 'working' when absent (backward
    compat with boards saved before M5). Delegates to blocks.base so chat.py
    (M7) can show the identical chip without a circular import."""
    return _blocks_agent_status(board)


def _status_chip(pending: int, agent_status: str, has_resolved: bool) -> str:
    """Header chip text (§10.2). 'waiting' with nothing pending renders the
    same as 'idle', per spec. Delegates to blocks.base (see _agent_status)."""
    return _blocks_status_chip_text(pending, agent_status, has_resolved)


def _title_text(board_title: str, pending: int, agent_status: str) -> str:
    """<title> text (§10.2)."""
    if pending > 0:
        return f"🔴 {pending} à tua espera — {board_title}"
    if agent_status == "working":
        return f"🟡 {board_title}"
    return f"⚪ {board_title}"


def _js_string(s: str) -> str:
    """JSON-encode a string for safe embedding inside an inline <script>
    block: escape every '<' so user content (e.g. a board title containing
    '<script>...') can never introduce a raw tag, opening or closing -- the
    <script>-body analogue of the e(json.dumps(x)) rule for HTML attributes
    (docs/SPEC.md §1)."""
    return json.dumps(s, ensure_ascii=False).replace("<", "\\u003c")


def _block_js() -> str:
    """Join every registered block module's JS, in a stable, deterministic order."""
    ordered_types = list(_JS_ORDER) + sorted(t for t in REGISTRY if t not in _JS_ORDER)
    parts = []
    for t in ordered_types:
        mod = REGISTRY.get(t)
        if mod is None:
            continue
        js = getattr(mod, "JS", "")
        if js:
            parts.append(js.strip("\n"))
    return "\n".join(parts)


def _whose_turn(board: dict, blocks_html: str, pending_count: int) -> dict:
    """Everything the M5 whose-turn signal needs, computed once and reused
    by both the full page render and the /version polling endpoint."""
    agent_status = _agent_status(board)
    has_resolved = 'class="card answered"' in blocks_html
    return {"pending": pending_count, "agent_status": agent_status, "has_resolved": has_resolved}


def _change_request_box_html(block_id) -> str:
    """The generic ✎ 'Pedir alteração' button + inline collapsed box injected
    into every block's wrapper div by render() itself -- NOT by any
    blocks/*.py module, reusing §6.5's exact generic-wrapper reasoning so
    every block type, present and future, gets this for free (docs/SPEC.md
    §12.2). Same show/hide + data-orig conventions as plan.py's ✎ edit box."""
    bid = e(block_id)
    return (
        f'<div class="block-actions">'
        f'<button class="ico" title="Pedir alteração" onclick="crToggle(\'{bid}\')">&#9998;</button>'
        f'</div>'
        f'<div id="cr-box-{bid}" class="cr-box" style="display:none">'
        f'<textarea id="cr-ta-{bid}" data-orig="" placeholder="O que precisa de mudar aqui?"></textarea>'
        f'<button onclick="crSend(\'{bid}\')">Enviar pedido</button>'
        f'</div>'
    )


def render(board: dict, active_page=None, base_path: str = "", slug: str | None = None,
           entries: list | None = None) -> str:
    """Render one board page.

    `base_path`/`slug` are M13's additions (docs/SPEC.md §17.4) and both default
    to single-board mode, so every pre-M13 caller renders exactly what it
    rendered before:

    - `base_path`: '' when the board is the server root (`painel serve`), or
      '/<slug>' when it's mounted under the unified service. Every link and
      every JS endpoint hangs off it.
    - `slug`: the board's BroadcastChannel identity under the service. None
      keeps M10's port-derived channel name (§14.1), which is still correct
      when one process serves exactly one board.

    `entries` is M14's addition (docs/SPEC.md §18): the registry snapshot the
    project switcher itemizes, passed only by the unified service. None means
    single-board mode -- the shell degrades to just the current project's name,
    and the breadcrumb drops the `Todos os projetos` / `/` directory segment
    (there is no directory to link to). It IS the mode signal for the shell,
    the same way `slug`/`base_path` are for the channel and endpoints."""
    service_mode = entries is not None
    all_blocks = board.get("blocks", [])
    pages = _pages(board)
    if active_page not in pages:
        active_page = None  # unknown/absent ?page= -> Home
    by_page = _blocks_by_page(board)
    blocks_list = by_page.get(active_page, [])
    total = len(blocks_list)
    # Computed early (needs only meta, not the rendered HTML) so blocks that
    # want to show the M5 whose-turn chip themselves (chat.py, M7, §5.5) can
    # read it from ctx during their own render().
    current_agent_status = _agent_status(board)
    # Which block ids are currently pending on the human (§6.2's own
    # definition), computed once so the wrapper div can flag them -- this is
    # what makes a pending block visually jump out among plain info cards
    # (markdown/note/log) without any per-block-module change, present or
    # future: the marker lives entirely in this generic wrapper + page.py's
    # CSS, never in a block's own render().
    pending = _needs_user(board)  # spans ALL pages (§11.2), reused below for the attention bar
    pending_ids = {str(bid) for bid, _label in pending}
    blocks = "".join(
        f'<div id="blk-{e(b.get("id", ""))}"'
        + (' class="needs-user"' if str(b.get("id")) in pending_ids else "")
        + ">"
        + _block_html(b, {"index": i, "total": total, "agent_status": current_agent_status})
        + _change_request_box_html(b.get("id", ""))
        + "</div>"
        for i, b in enumerate(blocks_list)
    )
    # Open change requests card (§12.4) -- board-level state, only shown on
    # Home so it doesn't repeat identically on every page of a multi-page
    # board (its rows already link cross-page via _page_href when relevant).
    if active_page is None:
        blocks += _change_requests_html(board, base_path)
    meta = board.get("meta", {})
    metaline = " · ".join(
        filter(None, [
            f'Projeto: {e(meta["project"])}' if meta.get("project") else "",
            f'Atualizado: {e(meta["updated_at"])}' if meta.get("updated_at") else "",
        ])
    )
    # Attention bar (uses `pending` computed above, which already spans all pages).
    pending_count = len(pending)
    if pending:
        block_page = {str(b.get("id")): b.get("page") for b in all_blocks}
        links = []
        for bid, label in pending:
            p = block_page.get(str(bid))
            # Always an absolute path + fragment (not a bare "#blk-id") so the
            # link works regardless of which page is currently active -- a
            # bare fragment previously failed silently when a Home-page item
            # was pending while viewing a different page.
            href = f"{_page_href(p, base_path)}#blk-{e(bid)}"
            links.append(f'<a href="{e(href)}">{e(label)}</a>')
        attention = (
            f'<div class="attention"><span class="attention-count">{len(pending)}</span> '
            f'à tua espera: {" · ".join(links)}</div>'
        )
    else:
        attention = ""
    board_title = board.get("title", "pAInel")
    wt = _whose_turn(board, blocks, pending_count)
    agent_status, has_resolved = wt["agent_status"], wt["has_resolved"]
    title_text = _title_text(board_title, pending_count, agent_status)
    chip_text = _status_chip(pending_count, agent_status, has_resolved)
    # M14 (§18.2): the app-shell -- project switcher (region 1) + the §11.2
    # page list (region 2, still empty for a 0-1 page board) -- is present on
    # EVERY board page now, not only when >=2 pages exist. So the .page-shell/
    # .page-main flex layout (reused from M6) and the wide body always apply to
    # a board page; the directory (host-app chrome) renders its own nav-less
    # shell straight from page.py and is untouched by any of this.
    page_list = _nav_html(board, active_page, base_path)  # "" when < 2 pages
    switcher = _switcher_html(board, slug, entries)
    breadcrumb = _breadcrumb_html(board, active_page, base_path, service_mode)
    nav = f'<aside class="app-shell">{switcher}{page_list}</aside>'
    return _PAGE.format(
        title=e(title_text), metaline=metaline, attention=attention,
        breadcrumb=breadcrumb,
        nav=nav, nav_class=" class=\"has-nav\"",
        page_shell_open='<div class="page-shell">', page_shell_close="</div>\n",
        page_main_open='<div class="page-main">\n', page_main_close="\n</div>",
        blocks=blocks, block_js=_block_js(),
        base_path_js=_js_string(base_path),
        # None -> M10's original client-side, port-derived channel name, byte
        # for byte (single-board mode). A slug -> that board's own channel, so
        # two different boards sharing the service's one port never mistake
        # each other for duplicate tabs (§17.4).
        channel_id_js=_js_string(slug) if slug else "(location.port || '80')",
        board_title_js=_js_string(board_title),
        pending_count=pending_count,
        agent_status_js=_js_string(agent_status),
        has_resolved="true" if has_resolved else "false",
        status_chip=e(chip_text),
        cr_global=CR_GLOBAL_HTML,
        upload_global=UPLOAD_GLOBAL_HTML,
    )


# --------------------------------------------------------------------------- #
# HTTP                                                                         #
# --------------------------------------------------------------------------- #
def apply_event(board_path: str, data: dict) -> bool:
    """Apply an incoming event to the board at `board_path`. Returns True if
    the event is silent (must not be emitted to the agent).

    Board-path-parameterized rather than reading a handler attribute, because
    M13's service applies events to N different boards from one process --
    but this is the exact same code path single-board mode has always used,
    so an event means precisely the same thing in both modes."""
    ev = data.get("event")
    silent = False
    with _lock:
        board = load_board(board_path)
        if ev == "change_request":
            # Universal event (docs/SPEC.md §12.1) -- not addressed to a
            # block module at all (block may be null for the global
            # affordance, §12.3), so it's handled here directly rather
            # than dispatched through a block's apply(). Never silent:
            # the entire point is that this reaches the agent.
            _append_change_request(board, data)
            save_board(board_path, board)
            return False
        blk = _find(board, data.get("block"))
        if blk is not None:
            mod = REGISTRY.get(blk.get("type"))
            if mod is not None:
                try:
                    handled = mod.apply(blk, data)
                except Exception as exc:
                    print(f"pAInel: erro ao aplicar evento {ev!r}: {exc}", file=sys.stderr)
                    handled = False
                if handled and ev in getattr(mod, "SILENT_EVENTS", ()):
                    silent = True
                if not handled:
                    print(f"pAInel: evento {ev!r} não reconhecido pelo bloco {blk.get('id')!r}", file=sys.stderr)
            else:
                print(f"pAInel: tipo de bloco desconhecido {blk.get('type')!r}", file=sys.stderr)
        else:
            print(f"pAInel: bloco {data.get('block')!r} não encontrado para evento {ev!r}", file=sys.stderr)
        save_board(board_path, board)
    return silent


def board_log_path(board_path: str) -> str:
    return board_path + ".log"


def emit_event(data: dict, board_path: str | None = None) -> None:
    """Emit exactly one JSONL line per interaction, so the agent can react.

    THE load-bearing contract of M13 (docs/SPEC.md §17.2.2). Pre-M13, each
    board had its own `painel serve` process whose stdout the CLI's `_spawn`
    redirected into `<board>.log`; the agent tails that file, per project:

        tail -n0 -F .painel-board.json.log | grep --line-buffered '^{'

    The unified service has one stdout for every board, so redirecting it
    would merge every project's events into one stream and force each
    project's agent to filter out the others'. Instead the service writes
    each event DIRECTLY to that board's own `<board>.log` (append + flush,
    one open per line -- cheap at human click rates, and it survives the log
    being rotated or deleted underneath us, which a long-lived handle would
    not). Same file, same JSONL, same tail command, no agent-side change.

    stdout still gets the line too: in single-board mode (`painel serve`,
    board_path=None here) that IS the channel, unchanged; under the service
    it's just an echo for debugging (§17.2.2 explicitly allows this) landing
    in ~/.painel/service.log."""
    line = json.dumps(data, ensure_ascii=False) + "\n"
    if board_path is not None:
        try:
            with open(board_log_path(board_path), "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        except OSError as exc:
            # Never let a log-write failure break the interaction itself: the
            # board is already saved by the time we get here.
            print(f"pAInel: não consegui escrever em {board_log_path(board_path)!r}: {exc}",
                  file=sys.stderr)
    sys.stdout.write(line)
    sys.stdout.flush()


def _version_payload(board_path: str) -> dict:
    """The freshness payload (§10.2's {v, pending, agent_status, has_resolved}
    plus §15.2's watched_paths mtimes). Shared verbatim by single-board
    /version and the service's /<slug>/version -- the payload is a property of
    the board, not of how it's mounted."""
    try:
        v = os.path.getmtime(board_path)
    except OSError:
        v = 0
    # Whose-turn fields ride along on the poll endpoint so the page can
    # refresh title/favicon/chip every tick (§10.2) without a full reload --
    # reload only happens when the version itself changes.
    with _lock:
        board = load_board(board_path)
    # M11 (docs/SPEC.md §15.2): fold in the mtime of any on-disk path a block
    # cares about, via the generic, block-type-agnostic watched_paths() hook
    # (§2.1) -- so the page auto-refreshes when a linked file/folder changes,
    # not just when board.json itself does. Deliberately NOT special-cased to
    # "resources" by name: any block type, present or future, gets this for
    # free by defining the hook.
    v = max(v, _watched_paths_mtime(board))
    blocks_list = board.get("blocks", [])
    total = len(blocks_list)
    blocks_html = "".join(
        _block_html(b, {"index": i, "total": total}) for i, b in enumerate(blocks_list)
    )
    pending_count = len(_needs_user(board))
    return {"v": v, **_whose_turn(board, blocks_html, pending_count)}


# --------------------------------------------------------------------------- #
# Uploads (M15, docs/SPEC.md §19)                                              #
# --------------------------------------------------------------------------- #
MAX_UPLOAD_BYTES = 25 * 1024 * 1024          # per-file cap (§19.4.3)
# Hard ceiling on the whole request body, purely a memory guard so an
# over-large POST is refused before rfile.read() buffers it (§19.4.3: "don't
# buffer an unbounded body in memory"). Generous enough for a legit batch of
# several near-cap files; the real per-file limit is enforced part by part.
_MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES * 5
_FILENAME_STRIP_RE = re.compile(r"[^A-Za-z0-9._-]")
DEFAULT_UPLOAD_DIR = "painel-uploads"        # global affordance target (§19.3)


class UploadTooLarge(Exception):
    """Raised by parse_multipart when a single file part exceeds the cap."""


def _boundary_from_content_type(ctype: str) -> bytes | None:
    for part in ctype.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            return part[len("boundary="):].strip().strip('"').encode("latin-1")
    return None


def _part_headers(head: bytes) -> dict:
    out = {}
    for line in head.split(b"\r\n"):
        if b":" in line:
            k, _, v = line.partition(b":")
            out[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
    return out


def _disposition_filename(disposition: str) -> str | None:
    """The filename from a Content-Disposition header, or None for a part that
    isn't a file upload (a plain form field). May legitimately return '' for a
    file part with an empty filename -- the caller sanitizes anyway."""
    for token in disposition.split(";"):
        token = token.strip()
        if token.lower().startswith("filename="):
            val = token[len("filename="):].strip()
            if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
                val = val[1:-1]
            return val
    return None


def parse_multipart(body: bytes, boundary: bytes,
                    max_part: int = MAX_UPLOAD_BYTES) -> list:
    """Parse a multipart/form-data body into [(filename, content_bytes), ...]
    for its FILE parts only (parts carrying a Content-Disposition filename),
    stdlib-only -- Python 3.13 removed cgi.FieldStorage, and pAInel takes no
    dependencies (§0), so we split the body on the boundary ourselves (§19.4).

    Raises UploadTooLarge the moment any single file part's content exceeds
    `max_part`, so an over-cap file is rejected rather than written."""
    files = []
    delimiter = b"--" + boundary
    for segment in body.split(delimiter):
        # Skip the preamble ('' before the first boundary) and the closing
        # delimiter ('--\r\n', which starts with '--' after the split).
        if not segment or segment.startswith(b"--"):
            continue
        if segment.startswith(b"\r\n"):
            segment = segment[2:]
        head, sep, rest = segment.partition(b"\r\n\r\n")
        if not sep:
            continue
        # The CRLF that precedes the next boundary belongs to the delimiter,
        # not to the file's bytes.
        content = rest[:-2] if rest.endswith(b"\r\n") else rest
        filename = _disposition_filename(
            _part_headers(head).get("content-disposition", ""))
        if filename is None:
            continue  # a non-file form field
        if len(content) > max_part:
            raise UploadTooLarge(filename)
        files.append((filename, content))
    return files


def sanitize_filename(name: str) -> str:
    """Strip a client-supplied filename to [A-Za-z0-9._-] with no path
    separators and no leading dots (§19.4.2). basename() drops any directory
    part first, so '../../etc/passwd' becomes 'passwd'; the regex then removes
    everything outside the safe set, and lstrip('.') forbids leading dots that
    would hide the file or form '..'. Never returns an empty string."""
    name = os.path.basename(name or "").strip()
    name = _FILENAME_STRIP_RE.sub("", name)
    name = name.lstrip(".")
    if not name:
        return "ficheiro"
    return name


def _contain(project_dir: str, candidate: str) -> str | None:
    """Realpath-resolve `candidate` and return it only if it stays inside
    `project_dir`; None if it escapes (§19.4.1). Used both to resolve dest_dir
    against an untrusted board and to re-assert containment after joining the
    sanitized filename."""
    root = os.path.realpath(project_dir)
    resolved = os.path.realpath(candidate)
    if resolved == root or resolved.startswith(root + os.sep):
        return resolved
    return None


def _unique_dest(dest_dir: str, filename: str) -> str:
    """A path under dest_dir that does not already exist: suffix '-2', '-3'…
    before the extension rather than overwrite (§19.4.2)."""
    base, ext = os.path.splitext(filename)
    candidate = filename
    n = 1
    while os.path.exists(os.path.join(dest_dir, candidate)):
        n += 1
        candidate = f"{base}-{n}{ext}"
    return os.path.join(dest_dir, candidate)


def save_uploads(board_path: str, block_id, parsed: list) -> tuple:
    """Write already-parsed (filename, content) pairs to disk under the target
    block's dest_dir (or DEFAULT_UPLOAD_DIR for the global affordance, §19.3),
    append {name,path,size} to a named block's `files`, persist the board, and
    return (events, error). `error` is a message string when the destination
    escapes the project dir (fail-closed, nothing written); otherwise None and
    `events` is the list of file_added events to emit.

    Mirrors the change_request endpoint's server-side handling: the board is
    mutated and the event emitted here, never through a block's apply()."""
    project_dir = os.path.dirname(os.path.abspath(board_path))
    events = []
    with _lock:
        board = load_board(board_path)
        block = _find(board, block_id) if block_id else None
        dest_rel = (block.get("dest_dir") if block else None) or DEFAULT_UPLOAD_DIR
        # Containment is checked with realpath (_contain), but the directory we
        # actually create/write/store is the plain abspath join, so the path
        # handed back to the agent matches the project's own path style rather
        # than a symlink-resolved one (e.g. /var vs macOS's /private/var).
        dest = os.path.normpath(os.path.join(project_dir, dest_rel))
        if _contain(project_dir, dest) is None:
            return [], f"destino fora do projeto: {dest_rel}"
        os.makedirs(dest, exist_ok=True)
        for filename, content in parsed:
            safe = sanitize_filename(filename)
            final = _unique_dest(dest, safe)
            # Belt-and-suspenders: sanitize already removes every separator, so
            # this can't fail, but §19.4.1 asks to re-assert after the join.
            if _contain(project_dir, final) is None:
                continue
            with open(final, "wb") as fh:
                fh.write(content)
            rec = {"name": os.path.basename(final), "path": final, "size": len(content)}
            if block is not None:
                block.setdefault("files", []).append(rec)
            events.append({
                "event": "file_added", "block": block_id if block else None,
                "name": rec["name"], "path": final, "size": rec["size"],
            })
        save_board(board_path, board)
    return events, None


class _Routes:
    """HTTP plumbing + the three things "serving a board" means, shared by the
    single-board handler and the unified service (M13).

    The two handlers deliberately keep their own do_GET/do_POST: their ROUTE
    TABLES genuinely differ (one board at the root vs N boards under slugs,
    plus a directory and a 404 page), and flattening that into one
    parameterized router was more confusing than the ~15 lines it saved. What
    they must never diverge on -- what a board page, a version payload and an
    event ARE -- lives here and is written once."""

    def log_message(self, *_):  # silence default logging
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, code: int = 200) -> None:
        self._send(code, html.encode("utf-8"), "text/html; charset=utf-8")

    def _send_board_page(self, board_path, active_page, base_path="", slug=None,
                         entries=None) -> None:
        with _lock:
            board = load_board(board_path)
        self._send_html(render(board, active_page, base_path=base_path, slug=slug,
                               entries=entries))

    def _send_version(self, board_path: str) -> None:
        self._send(200, json.dumps(_version_payload(board_path)).encode(), "application/json")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _handle_event(self, board_path: str, log_to_board: bool) -> None:
        data = self._read_json_body()
        silent = apply_event(board_path, data)
        # Events in a block's SILENT_EVENTS are UI housekeeping -- not worth
        # waking the agent (e.g. plan_seen just clears an unread badge).
        if not silent:
            emit_event(data, board_path if log_to_board else None)
        self._send(200, b'{"ok":true}', "application/json")

    def _json_error(self, code: int, message: str) -> None:
        self._send(code, json.dumps({"error": message}, ensure_ascii=False).encode(),
                   "application/json")

    def _handle_upload(self, board_path: str, block_id, log_to_board: bool) -> None:
        """POST /upload (single-board) or /<slug>/upload (service), M15 §19.2.

        Derives its target board exactly like /event does (the caller passes
        the resolved board_path), parses the multipart body with the stdlib,
        writes each file under the block's dest_dir (or painel-uploads/ for the
        global affordance), and emits ONE non-silent file_added event per file
        into that board's own <board>.log -- the same emit_event contract every
        other interaction uses (§17.2.2)."""
        ctype = self.headers.get("Content-Type", "")
        boundary = _boundary_from_content_type(ctype)
        length = int(self.headers.get("Content-Length", 0) or 0)
        if boundary is None or length <= 0:
            self._json_error(400, "esperava multipart/form-data com ficheiros")
            return
        # Memory guard (§19.4.3): refuse an over-large body before buffering it.
        if length > _MAX_REQUEST_BYTES:
            self._json_error(413, "envio demasiado grande")
            return
        body = self.rfile.read(length)
        try:
            parsed = parse_multipart(body, boundary)
        except UploadTooLarge:
            self._json_error(413, "ficheiro demasiado grande (máximo 25 MB por ficheiro)")
            return
        if not parsed:
            self._json_error(400, "nenhum ficheiro no envio")
            return
        events, err = save_uploads(board_path, block_id, parsed)
        if err is not None:
            self._json_error(400, err)  # fail-closed: dest escaped the project dir
            return
        for ev in events:
            emit_event(ev, board_path if log_to_board else None)
        self._send(200, b'{"ok":true}', "application/json")


# --------------------------------------------------------------------------- #
# Single-board mode: `painel serve <board>` (unchanged, docs/SPEC.md §17.5)   #
# --------------------------------------------------------------------------- #
class _Handler(_Routes, BaseHTTPRequestHandler):
    """One process, one board, board at the server root. Untouched by M13 by
    design: it's the vendored/embedded path, the right tool for tests, and
    keeping it is what keeps every pre-M13 test meaningful (§17.5)."""

    board_path = "board.json"

    def _apply(self, data: dict) -> bool:
        return apply_event(self.board_path, data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            # Friendly path-based routing (§11.2): "/" is Home unless the
            # old-style "?page=" query is present (kept for compatibility
            # with any already-shared/bookmarked links from before this
            # change -- see docs/SPEC.md §11.2).
            qs = parse_qs(parsed.query)
            self._send_board_page(self.board_path, qs.get("page", [None])[0])
        elif path not in ("/version", "/event", "/upload"):
            # Any other path segment is treated as a page name, e.g.
            # "/Estrat%C3%A9gia" -> page "Estratégia". render() already
            # falls back to Home for a name that isn't a real page (covers
            # stray requests like /favicon.ico harmlessly).
            self._send_board_page(self.board_path, unquote(path.lstrip("/")) or None)
        elif path == "/version":
            self._send_version(self.board_path)
        else:
            # /event and /upload are POST-only, exactly as /event always was.
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        # log_to_board=False: this process's stdout is the agent's channel in
        # single-board mode (the CLI has always redirected it into
        # <board>.log). Writing the file here too would double every line.
        if path == "/event":
            self._handle_event(self.board_path, log_to_board=False)
        elif path == "/upload":
            block_id = parse_qs(parsed.query).get("block", [None])[0]
            self._handle_upload(self.board_path, block_id, log_to_board=False)
        else:
            self._send(404, b"not found", "text/plain")


def serve(board_path: str, port: int = 8765, open_browser: bool = False) -> None:
    _Handler.board_path = board_path
    load_board(board_path)  # ensure file exists
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://localhost:{port}/"  # friendlier than the raw IP; same loopback
    sys.stdout.write(f"READY {url} board={board_path}\n")
    sys.stdout.flush()
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------- #
# The unified service (M13, docs/SPEC.md §17)                                  #
# --------------------------------------------------------------------------- #
class _ServiceHandler(_Routes, BaseHTTPRequestHandler):
    """One process, every registered project, addressed by slug (§17.4):

        /                 the directory
        /<slug>           that board's Home        (?page= still accepted)
        /<slug>/<page>    a specific page (§11)
        /<slug>/version   that board's freshness payload
        /<slug>/event     POST -- events for that board

    'version' and 'event' are reserved page names under a slug, exactly as
    /version and /event already were at the root pre-M13: a page named either
    is unreachable. Known limitation, documented, not worth an /api/ prefix.

    The registry is re-read on every request -- no caching, so `painel add` in
    another terminal shows up on the next refresh (§13.2's rule, kept)."""

    def _resolve(self, parsed):
        """(entry, rest) for a parsed URL, or (None, slug) for an unknown slug,
        or (None, None) for the service root."""
        segments = [s for s in parsed.path.split("/") if s]
        if not segments:
            return None, None
        slug = unquote(segments[0])
        entry = registry.get(slug)
        if entry is None:
            return None, slug
        rest = unquote(segments[1]) if len(segments) > 1 else ""
        return entry, rest

    def _send_unknown_slug(self, slug: str) -> None:
        # §17.4: not a bare 404 -- list what IS registered, because the human
        # either mistyped or the project was removed, and both are one click
        # from recoverable.
        self._send_html(directory.render_unknown_slug(slug, registry.entries()), code=404)

    def do_GET(self):
        parsed = urlparse(self.path)
        entry, rest = self._resolve(parsed)
        if entry is None and rest is None:
            self._send_html(directory.render_directory(registry.entries()))
            return
        if entry is None:
            self._send_unknown_slug(rest)
            return
        base_path = f"/{entry['slug']}"
        if rest == "version":
            self._send_version(entry["path"])
        elif rest in ("event", "upload"):
            self._send(404, b"not found", "text/plain")  # POST-only, same as pre-M13's /event
            return
        # M14 (§18.2): the project switcher needs the full registry snapshot,
        # re-read per request (no caching, exactly like the directory) so
        # another project's pending count travels here and is current.
        snapshot = registry.entries()
        if rest:
            self._send_board_page(entry["path"], rest, base_path, entry["slug"], snapshot)
        else:
            # ?page= still accepted on a board's Home for old bookmarks (§17.4).
            page = parse_qs(parsed.query).get("page", [None])[0]
            self._send_board_page(entry["path"], page, base_path, entry["slug"], snapshot)

    def do_POST(self):
        parsed = urlparse(self.path)
        entry, rest = self._resolve(parsed)
        if entry is None or rest not in ("event", "upload"):
            self._send(404, b"not found", "text/plain")
            return
        # log_to_board=True: THE M13 contract (§17.2.2) -- events (and now
        # file_added uploads) go to THIS board's own <board>.log and no
        # other's. Same base-path/board resolution as /event. See emit_event().
        if rest == "event":
            self._handle_event(entry["path"], log_to_board=True)
        else:
            block_id = parse_qs(parsed.query).get("block", [None])[0]
            self._handle_upload(entry["path"], block_id, log_to_board=True)


def serve_service(port: int = 8765, host: str = "127.0.0.1") -> None:
    """The unified service, foreground/blocking (§17.5).

    `host` defaults to loopback and the CLI refuses anything else without an
    explicit acknowledgement flag (§17.6) -- boards routinely hold plaintext
    credentials, so an exposed bind must never be reachable by typo."""
    registry.clean_legacy_instances()  # §17.7 migration, one-line and idempotent
    httpd = ThreadingHTTPServer((host, port), _ServiceHandler)
    url = f"http://localhost:{port}/"
    sys.stdout.write(f"READY {url} service host={host}\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
