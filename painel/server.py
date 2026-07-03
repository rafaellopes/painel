"""
pAInel — the second interface for CLI agents.

A single-file, dependency-free web server that turns a `board.json` file into
an interactive dashboard. The agent composes typed blocks (checklists,
questions, approvals, progress, forms...); the human interacts in the browser;
every interaction is written back to the board AND emitted as one JSONL line on
stdout, so the agent can react in real time.

Protocol
--------
- Input:  board.json  (ordered list of typed blocks)
- Output: one JSON line per interaction on stdout

Run:  python -m painel serve board.json --port 8765 --open
"""
from __future__ import annotations

import html
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# State                                                                        #
# --------------------------------------------------------------------------- #
def _empty_board() -> dict:
    return {"title": "pAInel", "meta": {}, "blocks": []}


def load_board(path: str) -> dict:
    if not os.path.exists(path):
        save_board(path, _empty_board())
    with open(path, "r", encoding="utf-8") as fh:
        board = json.load(fh)
    board.setdefault("title", "pAInel")
    board.setdefault("meta", {})
    board.setdefault("blocks", [])
    return board


def save_board(path: str, board: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(board, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _find(board: dict, block_id: str) -> dict | None:
    for b in board.get("blocks", []):
        if str(b.get("id")) == str(block_id):
            return b
    return None


def _find_item(block: dict, item_id: str) -> dict | None:
    for it in block.get("items", []):
        if str(it.get("id")) == str(item_id):
            return it
    return None


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #
def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _md_inline(s: str) -> str:
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


def _block_html(b: dict) -> str:
    t = b.get("type")
    bid = e(b.get("id", ""))

    if t == "heading":
        return f'<h2 class="section">{e(b.get("text", ""))}</h2>'

    if t == "markdown":
        return f'<div class="card md">{_md_inline(e(b.get("text", "")))}</div>'

    if t == "note":
        tone = b.get("tone", "info")
        return f'<div class="card note note-{e(tone)}">{_md_inline(e(b.get("text", "")))}</div>'

    if t == "tasks":
        items = b.get("items", [])
        done = sum(1 for it in items if it.get("status") == "done")
        total = len(items)
        pct = int(done / total * 100) if total else 0
        rows = []
        for it in items:
            st = it.get("status", "pending")
            tc = "done-text" if st == "done" else ""
            rows.append(
                f'<li><span class="dot {e(st)}"></span>'
                f'<span class="{tc}">{e(it.get("text", ""))}</span></li>'
            )
        title = e(b.get("title", "Progresso"))
        return (
            f'<div class="card"><h3>{title}</h3>'
            f'<div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>'
            f'<ul class="tasks">{"".join(rows)}</ul>'
            f'<div class="muted small">{done}/{total} concluídas</div></div>'
        )

    if t == "plan":
        items = b.get("items", [])
        active = [it for it in items if it.get("status") != "skipped"]
        done = sum(1 for it in active if it.get("status") == "done")
        total = len(active)
        pct = int(done / total * 100) if total else 0
        rows = []
        for idx, it in enumerate(items):
            iid = e(it.get("id", ""))
            st = it.get("status", "pending")
            text = e(it.get("text", ""))
            tc = "done-text" if st == "done" else ("skip-text" if st == "skipped" else "")
            thread = it.get("thread", [])
            unread = (bool(thread) and thread[-1].get("from") == "agent"
                      and it.get("seen", 0) < len(thread))
            badge = f' ({len(thread)})' if thread else ""
            reply_cls = " has-reply" if unread else ""
            reply_dot = '<span class="reply-dot"></span>' if unread else ""
            thread_msgs = "".join(
                f'<div class="thread-msg {e(m.get("from",""))}">'
                f'<b>{"Tu" if m.get("from") == "user" else "Agente"}:</b> {_md_inline(e(m.get("text","")))}</div>'
                for m in thread
            )
            rows.append(f'''<li class="plan-item">
              <div class="plan-row">
                <span class="dot {e(st)}"></span>
                <span class="plan-text {tc}">{_md_inline(text)}</span>
                <span class="plan-actions">
                  <button class="ico play" title="Começar agora" onclick="planPlay('{bid}','{iid}')">&#9654;</button>
                  <button class="ico" title="Editar" onclick="planToggleEdit('{bid}','{iid}')">&#9998;</button>
                  <button class="ico{reply_cls}" title="{"Resposta nova do agente!" if unread else "Perguntar / discutir este passo"}" onclick="planToggleThread('{bid}','{iid}')">&#128172;{badge}{reply_dot}</button>
                  <button class="ico" title="Saltar" onclick="planSkip('{bid}','{iid}')">&#9197;</button>
                  <button class="ico" title="Mover para cima" onclick="planMove('{bid}','{iid}','up')" {"disabled" if idx == 0 else ""}>&#9650;</button>
                  <button class="ico" title="Mover para baixo" onclick="planMove('{bid}','{iid}','down')" {"disabled" if idx == len(items) - 1 else ""}>&#9660;</button>
                </span>
              </div>
              <div id="plan-edit-{bid}-{iid}" class="plan-edit" style="display:none">
                <textarea id="plan-ta-{bid}-{iid}" data-orig="{text}">{text}</textarea>
                <button onclick="planSaveEdit('{bid}','{iid}')">Guardar</button>
              </div>
              <div id="plan-thread-{bid}-{iid}" class="plan-thread" style="display:none">
                {f'<div class="thread-msgs">{thread_msgs}</div>' if thread else ''}
                <textarea id="plan-comment-{bid}-{iid}" data-orig="" placeholder="Pergunta ou comentário sobre este passo..."></textarea>
                <button onclick="planSendComment('{bid}','{iid}')">Enviar</button>
              </div>
            </li>''')
        title = e(b.get("title", "Plano"))
        return (
            f'<div class="card"><h3>{title}</h3>'
            f'<div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>'
            f'<ul class="plan-items">{"".join(rows)}</ul>'
            f'<div class="muted small">{done}/{total} concluídos'
            f'{" · " + str(len(items) - total) + " saltados" if len(items) > total else ""}</div></div>'
        )

    if t == "checklist":
        items = b.get("items", [])
        rows = []
        for it in items:
            iid = e(it.get("id", ""))
            checked = "checked" if it.get("checked") else ""
            cls = "checked" if it.get("checked") else ""
            rows.append(
                f'<li class="{cls}"><label>'
                f'<input type="checkbox" {checked} '
                f'onchange="check(\'{bid}\',\'{iid}\',this.checked)">'
                f'<span>{_md_inline(e(it.get("text", "")))}</span></label></li>'
            )
        title = e(b.get("title", "A fazer (manual)"))
        return f'<div class="card"><h3>{title}</h3><ul class="checklist">{"".join(rows)}</ul></div>'

    if t == "question":
        prompt = _md_inline(e(b.get("prompt", "")))
        if b.get("answer") not in (None, ""):
            return (
                f'<div class="card answered"><h3>Pergunta</h3><p>{prompt}</p>'
                f'<div class="answer">Resposta: {e(b.get("answer"))}</div></div>'
            )
        return (
            f'<div class="card"><h3>Pergunta</h3><p>{prompt}</p>'
            f'<textarea id="ta-{bid}" data-orig="" placeholder="Escreve a tua resposta..."></textarea>'
            f'<button onclick="answer(\'{bid}\')">Enviar</button></div>'
        )

    if t == "choice":
        prompt = _md_inline(e(b.get("prompt", "")))
        if b.get("selected") not in (None, ""):
            return (
                f'<div class="card answered"><h3>Escolha</h3><p>{prompt}</p>'
                f'<div class="answer">Escolhido: {e(b.get("selected"))}</div></div>'
            )
        btns = "".join(
            f'<button class="opt" onclick="choose(\'{bid}\',{e(json.dumps(o))})">{e(o)}</button>'
            for o in b.get("options", [])
        )
        return f'<div class="card"><h3>Escolha</h3><p>{prompt}</p><div class="opts">{btns}</div></div>'

    if t == "approval":
        prompt = _md_inline(e(b.get("prompt", "")))
        if b.get("decision"):
            d = e(b.get("decision"))
            c = e(b.get("comment", ""))
            extra = f' — {c}' if c else ""
            return (
                f'<div class="card answered"><h3>Aprovação</h3><p>{prompt}</p>'
                f'<div class="answer">Decisão: {d}{extra}</div></div>'
            )
        return (
            f'<div class="card"><h3>Aprovação</h3><p>{prompt}</p>'
            f'<textarea id="cm-{bid}" data-orig="" placeholder="Comentário (opcional)"></textarea>'
            f'<div class="opts">'
            f'<button class="ok" onclick="approve(\'{bid}\',\'approved\')">Aprovar</button>'
            f'<button class="no" onclick="approve(\'{bid}\',\'rejected\')">Rejeitar</button>'
            f'</div></div>'
        )

    if t == "form":
        prompt = _md_inline(e(b.get("prompt", "")))
        if b.get("submitted"):
            rows = "".join(
                f'<div class="answer">{e(f.get("label"))}: {e(f.get("value"))}</div>'
                for f in b.get("fields", [])
            )
            return f'<div class="card answered"><h3>Formulário</h3><p>{prompt}</p>{rows}</div>'
        fields = []
        for f in b.get("fields", []):
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
        ids = e(json.dumps([f.get("id") for f in b.get("fields", [])]))
        return (
            f'<div class="card"><h3>Formulário</h3><p>{prompt}</p>{"".join(fields)}'
            f'<button onclick="submitForm(\'{bid}\',{ids})">Enviar</button></div>'
        )

    if t == "log":
        rows = "".join(
            f'<li><span class="muted small">{e(en.get("ts", ""))}</span> {e(en.get("text", ""))}</li>'
            for en in b.get("entries", [])
        )
        title = e(b.get("title", "Registo"))
        return f'<div class="card"><h3>{title}</h3><ul class="log">{rows}</ul></div>'

    return f'<div class="card muted">bloco desconhecido: {e(t)}</div>'


def _needs_user(board: dict) -> list:
    """Everything currently waiting on the human: (block_id, short label)."""
    out = []
    for b in board.get("blocks", []):
        t, bid = b.get("type"), b.get("id", "")
        if t == "question" and b.get("answer") in (None, ""):
            out.append((bid, "Pergunta por responder"))
        elif t == "choice" and b.get("selected") in (None, ""):
            out.append((bid, "Escolha pendente"))
        elif t == "approval" and not b.get("decision"):
            out.append((bid, "Aprovação pendente"))
        elif t == "form" and not b.get("submitted"):
            out.append((bid, "Formulário por preencher"))
        elif t == "checklist":
            n = sum(1 for it in b.get("items", []) if not it.get("checked"))
            if n:
                out.append((bid, f"{n} passo{'s' if n > 1 else ''} manua{'is' if n > 1 else 'l'} por marcar"))
        elif t == "plan":
            for it in b.get("items", []):
                th = it.get("thread", [])
                if th and th[-1].get("from") == "agent" and it.get("seen", 0) < len(th):
                    out.append((bid, f"Resposta nova em “{it.get('text', '')[:40]}”"))
    return out


def render(board: dict) -> str:
    blocks = "".join(
        f'<div id="blk-{e(b.get("id", ""))}">{_block_html(b)}</div>'
        for b in board.get("blocks", [])
    )
    meta = board.get("meta", {})
    metaline = " · ".join(
        filter(None, [
            f'Projeto: {e(meta["project"])}' if meta.get("project") else "",
            f'Atualizado: {e(meta["updated_at"])}' if meta.get("updated_at") else "",
        ])
    )
    pending = _needs_user(board)
    if pending:
        links = " · ".join(f'<a href="#blk-{e(bid)}">{e(label)}</a>' for bid, label in pending)
        attention = (
            f'<div class="attention"><span class="attention-count">{len(pending)}</span> '
            f'à tua espera: {links}</div>'
        )
    else:
        attention = ""
    return _PAGE.format(title=e(board.get("title", "pAInel")), metaline=metaline,
                        attention=attention, blocks=blocks)


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
            self._send(200, json.dumps({"v": v}).encode(), "application/json")
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
        self._apply(data)
        # Emit exactly one JSONL line per interaction so the agent can react.
        # plan_seen is UI housekeeping (badge cleared) — not worth waking the agent.
        if data.get("event") != "plan_seen":
            sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        self._send(200, b'{"ok":true}', "application/json")

    def _apply(self, data: dict) -> None:
        ev = data.get("event")
        with _lock:
            board = load_board(self.board_path)
            blk = _find(board, data.get("block"))
            if blk is not None:
                if ev == "check":
                    for it in blk.get("items", []):
                        if str(it.get("id")) == str(data.get("item")):
                            it["checked"] = bool(data.get("checked"))
                elif ev == "answer":
                    blk["answer"] = data.get("value", "")
                elif ev == "choose":
                    blk["selected"] = data.get("value", "")
                elif ev == "approve":
                    blk["decision"] = data.get("decision", "")
                    blk["comment"] = data.get("comment", "")
                elif ev == "submit":
                    vals = data.get("values", {})
                    for f in blk.get("fields", []):
                        if f.get("id") in vals:
                            f["value"] = vals[f["id"]]
                    blk["submitted"] = True
                elif ev == "plan_edit":
                    it = _find_item(blk, data.get("item"))
                    if it is not None:
                        it["text"] = data.get("value", "")
                elif ev == "plan_play":
                    it = _find_item(blk, data.get("item"))
                    if it is not None:
                        it["status"] = "wip"
                elif ev == "plan_skip":
                    it = _find_item(blk, data.get("item"))
                    if it is not None:
                        it["status"] = "skipped"
                elif ev == "plan_move":
                    items = blk.get("items", [])
                    idx = next((i for i, x in enumerate(items) if str(x.get("id")) == str(data.get("item"))), None)
                    if idx is not None:
                        j = idx - 1 if data.get("direction") == "up" else idx + 1
                        if 0 <= j < len(items):
                            items[idx], items[j] = items[j], items[idx]
                elif ev == "plan_comment":
                    it = _find_item(blk, data.get("item"))
                    if it is not None:
                        it.setdefault("thread", []).append({"from": "user", "text": data.get("value", "")})
                        it["seen"] = len(it["thread"])
                elif ev == "plan_seen":
                    it = _find_item(blk, data.get("item"))
                    if it is not None:
                        it["seen"] = len(it.get("thread", []))
            save_board(self.board_path, board)


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


# --------------------------------------------------------------------------- #
# Page template (CSS + JS inlined, no external deps)                           #
# --------------------------------------------------------------------------- #
_PAGE = """<!doctype html>
<html lang="pt"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light dark;
  --bg:#0e1013; --card:#171a21; --text:#e9eaee; --muted:#9aa0aa; --border:#252b36;
  --accent:#7dd3fc; --accent-ink:#0e1013;
  --ok:#4ade80; --wip:#facc15; --pending:#6b7280; --blocked:#f87171;
}}
@media (prefers-color-scheme: light) {{
  :root {{ --bg:#f6f7f9; --card:#fff; --text:#16181d; --muted:#667085; --border:#e5e7eb; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",Helvetica,Arial,sans-serif;
  line-height:1.5; max-width:780px; margin-inline:auto; }}
header {{ margin-bottom:1.25rem; }}
h1 {{ font-size:1.35rem; margin:0 0 .2rem; letter-spacing:-.01em; }}
h1 .ai {{ color:var(--accent); }}
.metaline {{ color:var(--muted); font-size:.82rem; }}
h2.section {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.07em;
  color:var(--muted); margin:1.6rem 0 .6rem; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px;
  padding:1rem 1.15rem; margin-bottom:.85rem; }}
.card h3 {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); margin:0 0 .6rem; }}
.card p {{ margin:.2rem 0 .7rem; }}
.md {{ color:var(--text); }}
.note {{ border-left:3px solid var(--accent); }}
.note-warn {{ border-left-color:var(--wip); }}
.note-danger {{ border-left-color:var(--blocked); }}
.note-ok {{ border-left-color:var(--ok); }}
.muted {{ color:var(--muted); }} .small {{ font-size:.8rem; }}
.bar {{ background:var(--border); border-radius:6px; height:8px; overflow:hidden; margin:.2rem 0 .6rem; }}
.bar-fill {{ height:100%; background:var(--accent); transition:width .3s; }}
ul {{ margin:0; padding:0; list-style:none; }}
ul.tasks li {{ padding:.32rem 0; }}
.dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:.55rem; }}
.dot.done {{ background:var(--ok); }} .dot.wip {{ background:var(--wip); }}
.dot.pending {{ background:var(--pending); }} .dot.blocked {{ background:var(--blocked); }}
.dot.skipped {{ background:transparent; border:1px solid var(--muted); }}
.done-text {{ text-decoration:line-through; color:var(--muted); }}
.skip-text {{ text-decoration:line-through; color:var(--muted); font-style:italic; }}
ul.plan-items li.plan-item {{ padding:.45rem 0; border-bottom:1px solid var(--border); }}
ul.plan-items li.plan-item:last-child {{ border-bottom:none; }}
.plan-row {{ display:flex; align-items:center; gap:.3rem; }}
.plan-text {{ flex:1; }}
.plan-actions {{ display:flex; gap:.15rem; flex:none; }}
button.ico {{ margin:0; padding:.25rem .4rem; background:transparent; color:var(--muted);
  border:1px solid var(--border); font-size:.75rem; line-height:1; }}
button.ico:hover {{ color:var(--text); border-color:var(--accent); }}
button.ico.play {{ color:var(--ok); border-color:var(--ok); }}
button.ico:disabled {{ opacity:.3; cursor:default; }}
button.ico:disabled:hover {{ color:var(--muted); border-color:var(--border); }}
.plan-edit {{ margin-top:.4rem; padding-left:1.4rem; }}
.plan-thread {{ margin-top:.4rem; padding-left:1.4rem; }}
.thread-msgs {{ margin-bottom:.5rem; display:flex; flex-direction:column; gap:.35rem; }}
.thread-msg {{ padding:.4rem .6rem; border-radius:8px; font-size:.85rem; max-width:85%; }}
.thread-msg.user {{ background:var(--border); align-self:flex-end; }}
.thread-msg.agent {{ background:rgba(125,211,252,.15); align-self:flex-start; }}
.thread-msg b {{ font-weight:600; }}
ul.checklist li {{ padding:.4rem 0; border-bottom:1px solid var(--border); }}
ul.checklist li:last-child {{ border-bottom:none; }}
ul.checklist label {{ display:flex; gap:.6rem; align-items:flex-start; cursor:pointer; }}
ul.checklist input {{ margin-top:.28rem; width:16px; height:16px; accent-color:var(--accent); flex:none; }}
ul.checklist li.checked span {{ color:var(--muted); text-decoration:line-through; }}
ul.log li {{ padding:.28rem 0; border-bottom:1px solid var(--border); }}
ul.log li:last-child {{ border-bottom:none; }}
textarea, input, select {{ width:100%; padding:.5rem .6rem; margin-top:.3rem;
  background:var(--bg); color:var(--text); border:1px solid var(--border);
  border-radius:8px; font-family:inherit; font-size:.92rem; }}
textarea {{ min-height:62px; resize:vertical; }}
.field {{ display:block; margin-bottom:.6rem; }}
.field span {{ font-size:.82rem; color:var(--muted); }}
button {{ margin-top:.55rem; padding:.45rem 1rem; border:none; border-radius:8px;
  background:var(--accent); color:var(--accent-ink); font-weight:600; cursor:pointer;
  font-size:.86rem; }}
button:hover {{ filter:brightness(1.08); }}
button.opt {{ background:var(--border); color:var(--text); margin-right:.5rem; }}
button.ok {{ background:var(--ok); color:#06210f; }}
button.no {{ background:var(--blocked); color:#2a0a0a; margin-left:.5rem; }}
.opts {{ display:flex; flex-wrap:wrap; gap:.2rem; }}
.answer {{ color:var(--accent); font-size:.9rem; margin-top:.3rem; }}
.answered {{ opacity:.72; }}
.attention {{ position:sticky; top:0; z-index:10; background:var(--wip); color:#1a1a1a;
  padding:.55rem .9rem; border-radius:0 0 10px 10px; font-size:.88rem; font-weight:500;
  margin:-2rem -1.25rem 1.2rem; box-shadow:0 2px 8px rgba(0,0,0,.25); }}
.attention a {{ color:inherit; text-decoration:underline; font-weight:400; }}
.attention-count {{ display:inline-block; background:#1a1a1a; color:var(--wip);
  border-radius:50%; min-width:1.4rem; height:1.4rem; line-height:1.4rem;
  text-align:center; font-weight:700; margin-right:.35rem; }}
button.ico.has-reply {{ color:var(--accent); border-color:var(--accent);
  animation:pulse 1.6s ease-in-out infinite; position:relative; }}
.reply-dot {{ display:inline-block; width:7px; height:7px; border-radius:50%;
  background:var(--blocked); margin-left:.25rem; vertical-align:top; }}
@keyframes pulse {{ 0%,100% {{ box-shadow:0 0 0 0 rgba(125,211,252,.5); }}
  50% {{ box-shadow:0 0 0 5px rgba(125,211,252,0); }} }}
footer {{ color:var(--muted); font-size:.72rem; text-align:center; margin-top:1.5rem; }}
</style></head><body>
{attention}
<header>
  <h1>{title}</h1>
  <div class="metaline">{metaline}</div>
</header>
{blocks}
<footer>p<span style="color:var(--accent)">AI</span>nel · a segunda interface do teu agente</footer>
<script>
async function send(payload) {{
  try {{
    await fetch('/event', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify(payload)}});
  }} catch (e) {{}}
}}
function reloadSoon() {{ knownVersion = null; setTimeout(() => location.reload(), 250); }}
function answer(id) {{
  const v = document.getElementById('ta-'+id).value;
  if (!v.trim()) return;
  send({{event:'answer', block:id, value:v}}).then(reloadSoon);
}}
function choose(id, value) {{ send({{event:'choose', block:id, value}}).then(reloadSoon); }}
function check(bid, item, checked) {{ send({{event:'check', block:bid, item, checked}}); }}
function approve(id, decision) {{
  const cm = document.getElementById('cm-'+id);
  send({{event:'approve', block:id, decision, comment: cm ? cm.value : ''}}).then(reloadSoon);
}}
function submitForm(id, ids) {{
  const values = {{}};
  ids.forEach(fid => {{ const el = document.getElementById('fld-'+id+'-'+fid); if (el) values[fid]=el.value; }});
  send({{event:'submit', block:id, values}}).then(reloadSoon);
}}
function planPlay(bid, item) {{ send({{event:'plan_play', block:bid, item}}).then(reloadSoon); }}
function planSkip(bid, item) {{ send({{event:'plan_skip', block:bid, item}}).then(reloadSoon); }}
function planMove(bid, item, direction) {{ send({{event:'plan_move', block:bid, item, direction}}).then(reloadSoon); }}
function planToggleEdit(bid, item) {{
  const box = document.getElementById('plan-edit-' + bid + '-' + item);
  box.style.display = (box.style.display === 'none' || !box.style.display) ? 'block' : 'none';
}}
function planSaveEdit(bid, item) {{
  const v = document.getElementById('plan-ta-' + bid + '-' + item).value;
  send({{event:'plan_edit', block:bid, item, value:v}}).then(reloadSoon);
}}
function _openThreads() {{
  try {{ return new Set(JSON.parse(sessionStorage.getItem('openThreads') || '[]')); }}
  catch (e) {{ return new Set(); }}
}}
function _saveThreads(s) {{ sessionStorage.setItem('openThreads', JSON.stringify([...s])); }}
function planToggleThread(bid, item) {{
  const key = bid + '-' + item;
  const box = document.getElementById('plan-thread-' + key);
  const opening = (box.style.display === 'none' || !box.style.display);
  box.style.display = opening ? 'block' : 'none';
  const open = _openThreads();
  if (opening) open.add(key); else open.delete(key);
  _saveThreads(open);
  if (opening) send({{event:'plan_seen', block:bid, item}});  // clears the unread badge
}}
function planSendComment(bid, item) {{
  const ta = document.getElementById('plan-comment-' + bid + '-' + item);
  const v = ta.value;
  if (!v.trim()) return;
  send({{event:'plan_comment', block:bid, item, value:v}}).then(reloadSoon);
}}
// Re-open threads the user had open before the last reload.
for (const key of _openThreads()) {{
  const box = document.getElementById('plan-thread-' + key);
  if (box) box.style.display = 'block';
}}
// Smart auto-refresh: reload only when the board changed on the server AND the
// user is not typing (no field focused, nothing unsent). Fixes the classic
// "refresh wiped what I was typing" bug.
function isBusy() {{
  const a = document.activeElement;
  if (a && (a.tagName === 'TEXTAREA' || a.tagName === 'INPUT' || a.tagName === 'SELECT')) return true;
  for (const el of document.querySelectorAll('textarea, input[type=text], input[type=number], input[type=date], input[type=email]')) {{
    if (el.value !== (el.getAttribute('data-orig') || '')) return true;
  }}
  return false;
}}
let knownVersion = null;
async function poll() {{
  try {{
    const r = await fetch('/version', {{cache:'no-store'}});
    const {{v}} = await r.json();
    if (knownVersion === null) {{ knownVersion = v; return; }}
    if (v !== knownVersion && !isBusy()) location.reload();
  }} catch (e) {{}}
}}
setInterval(poll, 1500);
</script>
</body></html>"""
