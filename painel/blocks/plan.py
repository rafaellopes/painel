"""Steerable plan: play/edit/skip/reorder/threads."""
from __future__ import annotations

from .base import e, md_inline, find_item

TYPE = "plan"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    items = block.get("items", [])
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
            f'<b>{"Tu" if m.get("from") == "user" else "Agente"}:</b> {md_inline(e(m.get("text","")))}</div>'
            for m in thread
        )
        rows.append(f'''<li class="plan-item">
              <div class="plan-row">
                <span class="dot {e(st)}"></span>
                <span class="plan-text {tc}">{md_inline(text)}</span>
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
    title = e(block.get("title", "Plano"))
    return (
        f'<div class="card"><h3>{title}</h3>'
        f'<div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>'
        f'<ul class="plan-items">{"".join(rows)}</ul>'
        f'<div class="muted small">{done}/{total} concluídos'
        f'{" · " + str(len(items) - total) + " saltados" if len(items) > total else ""}</div></div>'
    )


def apply(block: dict, event: dict) -> bool:
    ev = event.get("event")
    if ev == "plan_edit":
        it = find_item(block, event.get("item"))
        if it is not None:
            it["text"] = event.get("value", "")
        return True
    if ev == "plan_play":
        it = find_item(block, event.get("item"))
        if it is not None:
            it["status"] = "wip"
        return True
    if ev == "plan_skip":
        it = find_item(block, event.get("item"))
        if it is not None:
            it["status"] = "skipped"
        return True
    if ev == "plan_move":
        items = block.get("items", [])
        idx = next((i for i, x in enumerate(items) if str(x.get("id")) == str(event.get("item"))), None)
        if idx is not None:
            j = idx - 1 if event.get("direction") == "up" else idx + 1
            if 0 <= j < len(items):
                items[idx], items[j] = items[j], items[idx]
        return True
    if ev == "plan_comment":
        it = find_item(block, event.get("item"))
        if it is not None:
            it.setdefault("thread", []).append({"from": "user", "text": event.get("value", "")})
            it["seen"] = len(it["thread"])
        return True
    if ev == "plan_seen":
        it = find_item(block, event.get("item"))
        if it is not None:
            it["seen"] = len(it.get("thread", []))
        return True
    return False


def needs_user(block: dict) -> list:
    bid = block.get("id", "")
    out = []
    for it in block.get("items", []):
        th = it.get("thread", [])
        if th and th[-1].get("from") == "agent" and it.get("seen", 0) < len(th):
            out.append((bid, f"Resposta nova em “{it.get('text', '')[:40]}”"))
    return out


SILENT_EVENTS = {"plan_seen"}

JS = """
function planPlay(bid, item) { send({event:'plan_play', block:bid, item}).then(reloadSoon); }
function planSkip(bid, item) { send({event:'plan_skip', block:bid, item}).then(reloadSoon); }
function planMove(bid, item, direction) { send({event:'plan_move', block:bid, item, direction}).then(reloadSoon); }
function planToggleEdit(bid, item) {
  const box = document.getElementById('plan-edit-' + bid + '-' + item);
  box.style.display = (box.style.display === 'none' || !box.style.display) ? 'block' : 'none';
}
function planSaveEdit(bid, item) {
  const v = document.getElementById('plan-ta-' + bid + '-' + item).value;
  send({event:'plan_edit', block:bid, item, value:v}).then(reloadSoon);
}
function _openThreads() {
  try { return new Set(JSON.parse(sessionStorage.getItem('openThreads') || '[]')); }
  catch (e) { return new Set(); }
}
function _saveThreads(s) { sessionStorage.setItem('openThreads', JSON.stringify([...s])); }
function planToggleThread(bid, item) {
  const key = bid + '-' + item;
  const box = document.getElementById('plan-thread-' + key);
  const opening = (box.style.display === 'none' || !box.style.display);
  box.style.display = opening ? 'block' : 'none';
  const open = _openThreads();
  if (opening) open.add(key); else open.delete(key);
  _saveThreads(open);
  if (opening) send({event:'plan_seen', block:bid, item});  // clears the unread badge
}
function planSendComment(bid, item) {
  const ta = document.getElementById('plan-comment-' + bid + '-' + item);
  const v = ta.value;
  if (!v.trim()) return;
  send({event:'plan_comment', block:bid, item, value:v}).then(reloadSoon);
}
// Re-open threads the user had open before the last reload.
for (const key of _openThreads()) {
  const box = document.getElementById('plan-thread-' + key);
  if (box) box.style.display = 'block';
}
"""
