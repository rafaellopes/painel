"""
Page shell: the _PAGE HTML template, global CSS, and global JS.

Per-block JS (from each block module's JS constant) is joined in and
inserted at the {block_js} placeholder by server.py.

The {cr_global} placeholder holds the M8 global "Pedir alteração" affordance
(docs/SPEC.md §12.3) -- a real board's render() fills it with CR_GLOBAL_HTML;
the hub (M9, painel/hub.py) fills it with "" since it's host-app chrome, not
a board, and change requests don't apply to it.
"""
from __future__ import annotations

CR_GLOBAL_HTML = """<div class="cr-global">
  <button class="ico" title="Pedir alteração, nova tarefa, ou rever algo" onclick="crToggleGlobal()">&#10133; Pedir alteração, nova tarefa, ou rever algo</button>
  <div id="cr-box-global" class="cr-box" style="display:none">
    <textarea id="cr-ta-global" data-orig="" placeholder="O que precisas de pedir?"></textarea>
    <button onclick="crSendGlobal()">Enviar pedido</button>
  </div>
</div>"""

_PAGE = """<!doctype html>
<html lang="pt"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="icon" id="favicon" href="">
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
/* A block currently waiting on the human (server-computed from the same
   _needs_user() the attention bar uses) must be visually unmistakable among
   plain info cards (markdown/note/log) -- not just linked-to from the bar
   above. Lives entirely on the generic wrapper div so every block type,
   present and future, gets it for free with zero per-block-module code. */
.needs-user {{ position:relative; }}
.needs-user > .card {{ border-left:4px solid var(--wip); }}
.needs-user::before {{
  content:"⏳ à tua espera"; position:absolute; top:-.65rem; right:.9rem;
  background:var(--wip); color:#1a1a1a; font-size:.68rem; font-weight:700;
  letter-spacing:.02em; padding:.15rem .55rem; border-radius:999px; z-index:1;
}}
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
.status-chip {{ display:inline-block; margin-top:.35rem; padding:.2rem .6rem; border-radius:999px;
  background:var(--border); color:var(--text); font-size:.78rem; font-weight:500; }}
/* --- Change requests (M8, docs/SPEC.md §12) -- generic per-block ✎ button
   + inline box injected by render() itself (not by any blocks/*.py module),
   plus the global affordance and the "Pedidos em aberto" card. --- */
.block-actions {{ display:flex; justify-content:flex-end; gap:.15rem; margin-bottom:.3rem; }}
.cr-box {{ margin-bottom:.6rem; }}
.cr-card ul.log a {{ color:var(--accent); text-decoration:underline; font-size:.82rem; }}
.cr-global {{ margin:1.5rem 0; text-align:center; }}
.cr-global button.ico {{ font-size:.8rem; padding:.4rem .8rem; }}
.cr-global .cr-box {{ text-align:left; max-width:520px; margin:.5rem auto 0; }}
/* --- chat block (M7, docs/SPEC.md §5.5) -- reuses .thread-msg(s) above --- */
.chat-card h3 {{ display:flex; align-items:center; justify-content:space-between; gap:.5rem; }}
.chat-chip {{ margin-top:0; font-size:.7rem; padding:.15rem .5rem; text-transform:none;
  letter-spacing:normal; }}
.chat-msgs {{ max-height:340px; overflow-y:auto; margin-bottom:.5rem; }}
/* --- Hub (M9, docs/SPEC.md §13) -- cards are plain links to each board --- */
a.hub-card {{ display:block; text-decoration:none; color:inherit; }}
a.hub-card:hover {{ border-color:var(--accent); }}
/* --- Multi-page nav (M6, docs/SPEC.md §11) --- */
body.has-nav {{ max-width:1040px; }}
.page-shell {{ display:flex; gap:2rem; align-items:flex-start; }}
.page-main {{ flex:1; min-width:0; }}
.pages-nav {{ flex:none; width:190px; }}
.pages-sidebar {{ display:flex; flex-direction:column; gap:.15rem; position:sticky; top:1rem; }}
.pages-sidebar .nav-item {{ display:block; padding:.45rem .7rem; border-radius:8px; color:var(--text);
  text-decoration:none; font-size:.88rem; }}
.pages-sidebar .nav-item:hover {{ background:var(--border); }}
.pages-sidebar .nav-item.active {{ background:var(--accent); color:var(--accent-ink); font-weight:600; }}
.pages-dropdown {{ display:none; }}
.pages-dropdown select {{ margin-top:0; }}
@media (max-width:600px) {{
  .page-shell {{ flex-direction:column; gap:0; }}
  .pages-nav {{ width:100%; }}
  .pages-sidebar {{ display:none; }}
  .pages-dropdown {{ display:block; margin-bottom:1rem; }}
}}
</style></head><body{nav_class}>
{attention}
<header>
  <h1>{title}</h1>
  <div class="metaline">{metaline}</div>
  <div id="status-chip" class="status-chip">{status_chip}</div>
</header>
{page_shell_open}{nav}{page_main_open}{blocks}{page_main_close}{page_shell_close}
{cr_global}
<footer>p<span style="color:var(--accent)">AI</span>nel · a segunda interface do teu agente</footer>
<script>
async function send(payload) {{
  try {{
    await fetch('/event', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify(payload)}});
  }} catch (e) {{}}
}}
function reloadSoon() {{ knownVersion = null; setTimeout(() => location.reload(), 250); }}

// --- Change requests (M8, docs/SPEC.md §12) ---------------------------------
// Generic per-block ✎ box (server-injected wrapper markup, not per-block-
// module) + the global "Pedir alteração" affordance. Open/closed state
// persists across polls/reloads via sessionStorage, same pattern as plan's
// open-threads (§1 / planToggleThread above).
function _openCrBoxes() {{
  try {{ return new Set(JSON.parse(sessionStorage.getItem('openCrBoxes') || '[]')); }}
  catch (e) {{ return new Set(); }}
}}
function _saveCrBoxes(s) {{ sessionStorage.setItem('openCrBoxes', JSON.stringify([...s])); }}
function _crToggleBox(key) {{
  const box = document.getElementById('cr-box-' + key);
  if (!box) return;
  const opening = (box.style.display === 'none' || !box.style.display);
  box.style.display = opening ? 'block' : 'none';
  const open = _openCrBoxes();
  if (opening) open.add(key); else open.delete(key);
  _saveCrBoxes(open);
}}
function crToggle(bid) {{ _crToggleBox(bid); }}
function crToggleGlobal() {{ _crToggleBox('global'); }}
function crSend(bid) {{
  const ta = document.getElementById('cr-ta-' + bid);
  const v = ta.value;
  if (!v.trim()) return;
  send({{event:'change_request', block:bid, value:v}}).then(reloadSoon);
}}
function crSendGlobal() {{
  const ta = document.getElementById('cr-ta-global');
  const v = ta.value;
  if (!v.trim()) return;
  send({{event:'change_request', block:null, value:v}}).then(reloadSoon);
}}
// Re-open ✎ boxes the user had open before the last reload.
for (const key of _openCrBoxes()) {{
  const box = document.getElementById('cr-box-' + key);
  if (box) box.style.display = 'block';
}}
{block_js}
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

// --- Whose-turn signal (M5, docs/SPEC.md §10) -------------------------------
// The server renders the initial title/favicon/chip; this section keeps them
// live on every poll tick (not just page load), and fires a Notification on
// a 0->N pending transition while the tab is hidden.
const boardTitle = {board_title_js};
let pendingCount = {pending_count};
let agentStatus = {agent_status_js};
let hasResolved = {has_resolved};
let notifyAsked = false;

const FAVICONS = {{
  red: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"%3E%3Ccircle cx="8" cy="8" r="7" fill="%23f87171"/%3E%3C/svg%3E',
  yellow: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"%3E%3Ccircle cx="8" cy="8" r="7" fill="%23facc15"/%3E%3C/svg%3E',
  green: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"%3E%3Ccircle cx="8" cy="8" r="7" fill="%234ade80"/%3E%3C/svg%3E',
  gray: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"%3E%3Ccircle cx="8" cy="8" r="7" fill="%239aa0aa"/%3E%3C/svg%3E'
}};
function setFavicon(color) {{
  const link = document.getElementById('favicon');
  if (link) link.href = FAVICONS[color] || FAVICONS.gray;
}}
function titleFor(pending, status) {{
  if (pending > 0) return '🔴 ' + pending + ' à tua espera — ' + boardTitle;
  if (status === 'working') return '🟡 ' + boardTitle;
  return '⚪ ' + boardTitle;
}}
function chipFor(pending, status, resolved) {{
  if (pending > 0) return '🔴 À espera de ti (' + pending + ')';
  if (status === 'working') return '🟡 O agente está a trabalhar…';
  if (resolved) return '✅ Tudo feito';
  return '⚪ Agente offline';
}}
function faviconColorFor(pending, status, resolved) {{
  if (pending > 0) return 'red';
  if (status === 'working') return 'yellow';
  if (resolved) return 'green';
  return 'gray';
}}
function updateWhoseTurn(pending, status, resolved) {{
  document.title = titleFor(pending, status);
  const chip = document.getElementById('status-chip');
  if (chip) chip.textContent = chipFor(pending, status, resolved);
  setFavicon(faviconColorFor(pending, status, resolved));
}}
async function maybeNotify(newPending) {{
  if (newPending <= pendingCount || !document.hidden) return;
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default' && !notifyAsked) {{
    notifyAsked = true;
    try {{ await Notification.requestPermission(); }} catch (e) {{ return; }}
  }}
  if (Notification.permission !== 'granted') return;
  try {{
    const n = new Notification(titleFor(newPending, agentStatus));
    n.onclick = () => {{
      window.focus();
      // Attention links are absolute paths+fragments (e.g. "/Estratégia#blk-x"),
      // not bare "#blk-x" fragments, since the friendly path-based page routing
      // landed -- navigate via href, not location.hash (which would only work
      // for same-page fragments).
      const first = document.querySelector('.attention a');
      if (first) location.href = first.getAttribute('href');
    }};
  }} catch (e) {{}}
}}
updateWhoseTurn(pendingCount, agentStatus, hasResolved);

let knownVersion = null;
async function poll() {{
  try {{
    const r = await fetch('/version', {{cache:'no-store'}});
    const data = await r.json();
    if (knownVersion === null) {{ knownVersion = data.v; }}
    else if (data.v !== knownVersion && !isBusy()) {{ location.reload(); return; }}
    // Re-evaluate the whose-turn signal every tick (§10.2), independent of
    // whether the board content changed enough to warrant a reload.
    maybeNotify(data.pending);
    pendingCount = data.pending;
    agentStatus = data.agent_status;
    hasResolved = data.has_resolved;
    updateWhoseTurn(pendingCount, agentStatus, hasResolved);
  }} catch (e) {{}}
}}
setInterval(poll, 1500);
</script>
</body></html>"""
