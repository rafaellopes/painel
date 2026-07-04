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
from urllib.parse import urlparse

from .blocks import REGISTRY
from .blocks.base import e
from .page import _PAGE

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
    """Everything currently waiting on the human: (block_id, short label)."""
    out = []
    for b in board.get("blocks", []):
        mod = REGISTRY.get(b.get("type"))
        if mod is None:
            continue
        out.extend(mod.needs_user(b))
    return out


# --------------------------------------------------------------------------- #
# Whose-turn signal (M5, docs/SPEC.md §10)                                    #
# --------------------------------------------------------------------------- #
def _agent_status(board: dict) -> str:
    """meta.agent_status, defaulting to 'working' when absent (backward
    compat with boards saved before M5)."""
    return board.get("meta", {}).get("agent_status") or "working"


def _status_chip(pending: int, agent_status: str, has_resolved: bool) -> str:
    """Header chip text (§10.2). 'waiting' with nothing pending renders the
    same as 'idle', per spec."""
    if pending > 0:
        return f"🔴 À espera de ti ({pending})"
    if agent_status == "working":
        return "🟡 O agente está a trabalhar…"
    if has_resolved:
        return "✅ Tudo feito"
    return "⚪ Agente offline"


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


def render(board: dict) -> str:
    blocks_list = board.get("blocks", [])
    total = len(blocks_list)
    blocks = "".join(
        f'<div id="blk-{e(b.get("id", ""))}">{_block_html(b, {"index": i, "total": total})}</div>'
        for i, b in enumerate(blocks_list)
    )
    meta = board.get("meta", {})
    metaline = " · ".join(
        filter(None, [
            f'Projeto: {e(meta["project"])}' if meta.get("project") else "",
            f'Atualizado: {e(meta["updated_at"])}' if meta.get("updated_at") else "",
        ])
    )
    pending = _needs_user(board)
    pending_count = len(pending)
    if pending:
        links = " · ".join(f'<a href="#blk-{e(bid)}">{e(label)}</a>' for bid, label in pending)
        attention = (
            f'<div class="attention"><span class="attention-count">{len(pending)}</span> '
            f'à tua espera: {links}</div>'
        )
    else:
        attention = ""
    board_title = board.get("title", "pAInel")
    wt = _whose_turn(board, blocks, pending_count)
    agent_status, has_resolved = wt["agent_status"], wt["has_resolved"]
    title_text = _title_text(board_title, pending_count, agent_status)
    chip_text = _status_chip(pending_count, agent_status, has_resolved)
    return _PAGE.format(
        title=e(title_text), metaline=metaline, attention=attention,
        blocks=blocks, block_js=_block_js(),
        board_title_js=_js_string(board_title),
        pending_count=pending_count,
        agent_status_js=_js_string(agent_status),
        has_resolved="true" if has_resolved else "false",
        status_chip=e(chip_text),
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
        path = urlparse(self.path).path
        if path == "/":
            with _lock:
                board = load_board(self.board_path)
            self._send(200, render(board).encode("utf-8"), "text/html; charset=utf-8")
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
    url = f"http://127.0.0.1:{port}/"
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
