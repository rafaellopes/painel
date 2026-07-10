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
- Output: one JSON line per interaction on stdout

Run:  python -m painel serve board.json --port 8765 --open

This module is the HTTP layer + event dispatch + page shell only. Block
rendering/behavior lives in painel/blocks/; the page template, CSS, and
global JS live in painel/page.py. See docs/SPEC.md for the full contract.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, unquote

from .blocks import REGISTRY
from .blocks.base import e, agent_status as _blocks_agent_status, status_chip_text as _blocks_status_chip_text
from .page import _PAGE, CR_GLOBAL_HTML

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


def _change_requests_html(board: dict) -> str:
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
            href = f"{_page_href(block_page.get(str(bid)))}#blk-{e(bid)}"
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


def _page_href(page) -> str:
    """Friendly path-based URL for a page (§11.2): '/' for Home, '/<page>'
    otherwise -- e.g. '/Estrat%C3%A9gia' instead of '/?page=Estrat%C3%A9gia'.
    Browsers commonly render the percent-escaped UTF-8 back to readable
    accented text in the address bar. `?page=` on '/' is still accepted by
    do_GET for old bookmarked/shared links (see do_GET)."""
    return "/" if page is None else f"/{quote(page, safe='')}"


def _nav_html(board: dict, active_page) -> str:
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
            f'<a class="{cls}" href="{e(_page_href(p))}">{e(name)}{_badge(counts.get(p, 0))}</a>'
        )
    options = "".join(
        f'<option value="{e(_page_href(p))}"{" selected" if p == active_page else ""}>'
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


def render(board: dict, active_page=None) -> str:
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
        blocks += _change_requests_html(board)
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
            href = f"{_page_href(p)}#blk-{e(bid)}"
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
    nav = _nav_html(board, active_page)
    # Backward compat (§11.1): pageless boards get zero nav-related markup --
    # no wrapper divs, no body class -- byte-identical to the pre-M6 shell.
    page_shell_open = '<div class="page-shell">' if nav else ""
    page_shell_close = "</div>\n" if nav else ""
    page_main_open = '<div class="page-main">\n' if nav else ""
    page_main_close = "\n</div>" if nav else ""
    return _PAGE.format(
        title=e(title_text), metaline=metaline, attention=attention,
        nav=nav, nav_class=" class=\"has-nav\"" if nav else "",
        page_shell_open=page_shell_open, page_shell_close=page_shell_close,
        page_main_open=page_main_open, page_main_close=page_main_close,
        blocks=blocks, block_js=_block_js(),
        board_title_js=_js_string(board_title),
        pending_count=pending_count,
        agent_status_js=_js_string(agent_status),
        has_resolved="true" if has_resolved else "false",
        status_chip=e(chip_text),
        cr_global=CR_GLOBAL_HTML,
    )


# --------------------------------------------------------------------------- #
# HTTP                                                                         #
# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    board_path = "board.json"

    def log_message(self, *_):  # silence default logging
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            # Friendly path-based routing (§11.2): "/" is Home unless the
            # old-style "?page=" query is present (kept for compatibility
            # with any already-shared/bookmarked links from before this
            # change -- see docs/SPEC.md §11.2).
            qs = parse_qs(parsed.query)
            active_page = qs.get("page", [None])[0]
            with _lock:
                board = load_board(self.board_path)
            self._send(200, render(board, active_page).encode("utf-8"), "text/html; charset=utf-8")
        elif path not in ("/version", "/event"):
            # Any other path segment is treated as a page name, e.g.
            # "/Estrat%C3%A9gia" -> page "Estratégia". render() already
            # falls back to Home for a name that isn't a real page (covers
            # stray requests like /favicon.ico harmlessly).
            active_page = unquote(path.lstrip("/")) or None
            with _lock:
                board = load_board(self.board_path)
            self._send(200, render(board, active_page).encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/version":
            try:
                v = os.path.getmtime(self.board_path)
            except OSError:
                v = 0
            # Whose-turn fields ride along on the poll endpoint so the page
            # can refresh title/favicon/chip every tick (§10.2) without a
            # full reload -- reload only happens when the version itself changes.
            with _lock:
                board = load_board(self.board_path)
            # M11 (docs/SPEC.md §15.2): fold in the mtime of any on-disk path a
            # block cares about, via the generic, block-type-agnostic
            # watched_paths() hook (§2.1) -- so the page auto-refreshes when a
            # linked file/folder changes, not just when board.json itself does.
            # Deliberately NOT special-cased to "resources" by name: any block
            # type, present or future, gets this for free by defining the hook.
            v = max(v, _watched_paths_mtime(board))
            blocks_list = board.get("blocks", [])
            total = len(blocks_list)
            blocks_html = "".join(
                _block_html(b, {"index": i, "total": total}) for i, b in enumerate(blocks_list)
            )
            pending_count = len(_needs_user(board))
            payload = {"v": v, **_whose_turn(board, blocks_html, pending_count)}
            self._send(200, json.dumps(payload).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/event":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            data = {}
        silent = self._apply(data)
        # Emit exactly one JSONL line per interaction so the agent can react.
        # Events in a block's SILENT_EVENTS are UI housekeeping — not worth
        # waking the agent (e.g. plan_seen just clears an unread badge).
        if not silent:
            sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        self._send(200, b'{"ok":true}', "application/json")

    def _apply(self, data: dict) -> bool:
        """Apply an incoming event to the board. Returns True if the event
        is silent (must not be emitted to stdout)."""
        ev = data.get("event")
        silent = False
        with _lock:
            board = load_board(self.board_path)
            if ev == "change_request":
                # Universal event (docs/SPEC.md §12.1) -- not addressed to a
                # block module at all (block may be null for the global
                # affordance, §12.3), so it's handled here directly rather
                # than dispatched through a block's apply(). Never silent:
                # the entire point is that this reaches the agent.
                _append_change_request(board, data)
                save_board(self.board_path, board)
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
            save_board(self.board_path, board)
        return silent


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
# The hub (M9, docs/SPEC.md §13)                                              #
# --------------------------------------------------------------------------- #
class _HubHandler(BaseHTTPRequestHandler):
    """Serves painel/hub.py's render_hub() on every GET /. Deliberately a
    separate, much smaller handler rather than a second full HTTP server
    implementation -- same ThreadingHTTPServer bootstrapping and READY-line
    convention as _Handler/serve() above, just a different (board-less)
    route table, since the hub has no board.json, no /event, no /version
    polling target of its own (§13.2: reuse serve()'s machinery, don't fork
    a second server implementation)."""

    def log_message(self, *_):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path != "/":
            self._send(404, b"not found", "text/plain")
            return
        from . import hub as _hub
        from .__main__ import _discover_running_boards
        instances = _discover_running_boards(kind="board")
        html = _hub.render_hub(instances).encode("utf-8")
        self._send(200, html, "text/html; charset=utf-8")


def serve_hub(port: int = 8765) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _HubHandler)
    url = f"http://localhost:{port}/"
    sys.stdout.write(f"READY {url} hub\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
