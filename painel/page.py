"""
Page shell: the _PAGE HTML template, global CSS, and global JS.

Per-block JS (from each block module's JS constant) is joined in and
inserted at the {block_js} placeholder by server.py.

The {cr_global} placeholder holds the M8 global "Pedir alteração" affordance
(docs/SPEC.md §12.3) -- a real board's render() fills it with CR_GLOBAL_HTML;
the directory (M13, painel/directory.py) fills it with "" since it's host-app
chrome, not a board, and change requests don't apply to it.

{base_path_js} / {channel_id_js} (M13, docs/SPEC.md §17.4) are the two values
the unified service must vary per board, and the two the single-board `painel
serve` leaves exactly as they were pre-M13:

- `base_path_js`: '""' for single-board mode (endpoints stay /version and
  /event), '"/<slug>"' under the service.
- `channel_id_js`: the BroadcastChannel identity. Under the service it's the
  board's slug -- M10 keyed it on location.port, and with every board now
  sharing ONE port that would make two *different* boards think they were
  duplicate tabs of each other and close one. Single-board mode keeps the
  port-derived expression verbatim, because there the port genuinely is the
  instance identity (§6.6).

Both are templated server-side rather than derived from location.pathname in
JS (which §17.4 suggests): the client cannot tell `/<slug>` under the service
apart from `/<page>` under `painel serve` -- the same first path segment means
different things in the two modes -- so client-side derivation would silently
break single-board mode's page URLs. The server always knows which mode it is.
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
ul.checklist li {{ padding:.4rem 0; border-bottom:1px solid var(--border);
  display:flex; align-items:flex-start; justify-content:space-between; gap:.4rem; flex-wrap:wrap; }}
ul.checklist li:last-child {{ border-bottom:none; }}
ul.checklist label {{ display:flex; gap:.6rem; align-items:flex-start; cursor:pointer; flex:1; }}
ul.checklist input {{ margin-top:.28rem; width:16px; height:16px; accent-color:var(--accent); flex:none; }}
ul.checklist li.checked span {{ color:var(--muted); text-decoration:line-through; }}
ul.checklist .item-cr-btn {{ flex:none; }}
ul.checklist li .cr-box {{ width:100%; order:3; margin-top:.3rem; }}
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
/* --- Action feedback: "a enviar" spinner + failure state (page.py send()) ---
   Immediate confirmation that a click was received and is in flight, so a
   slow or failed round-trip never looks like a dead button. Works on every
   action button generically (small icon buttons and the wider text ones). */
button.sending {{ position:relative; color:transparent !important; pointer-events:none; }}
button.sending::after {{ content:''; position:absolute; inset:0; margin:auto;
  width:11px; height:11px; border:2px solid var(--border);
  border-top-color:var(--accent); border-radius:50%;
  animation:spin .6s linear infinite; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
button.send-error {{ color:var(--blocked) !important; border-color:var(--blocked) !important;
  animation:shake .3s ease-in-out; }}
@keyframes shake {{ 0%,100% {{ transform:translateX(0); }}
  25% {{ transform:translateX(-2px); }} 75% {{ transform:translateX(2px); }} }}
/* --- Tab hygiene (M10, docs/SPEC.md §14.1) -- duplicate-tab self-close ---
   The surviving/original tab reuses the exact same `pulse` keyframes above
   (not a second, near-duplicate animation) applied to the header, so a
   duplicate-open attempt draws the eye without any new CSS. */
header.dup-pulse {{ animation:pulse 1.6s ease-in-out infinite; border-radius:10px; }}
#dup-notice {{ display:none; position:fixed; top:1rem; left:50%; transform:translateX(-50%);
  background:var(--wip); color:#1a1a1a; padding:.6rem 1.1rem; border-radius:10px;
  font-size:.88rem; font-weight:600; box-shadow:0 4px 14px rgba(0,0,0,.3); z-index:100; }}
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
/* --- Directory (M13, docs/SPEC.md §17.4) -- cards are plain links to each
   registered project; a project whose board.json is gone is shown, not
   dropped (§17.3), just dimmed and not clickable. --- */
a.dir-card {{ display:block; text-decoration:none; color:inherit; }}
a.dir-card:hover {{ border-color:var(--accent); }}
.dir-missing {{ opacity:.7; border-style:dashed; }}
/* --- resources block (M11, docs/SPEC.md §15) --- */
ul.res-list li.res-item {{ display:flex; align-items:center; gap:.7rem;
  padding:.4rem 0; border-bottom:1px solid var(--border); }}
ul.res-list li.res-item:last-child {{ border-bottom:none; }}
.res-thumb {{ width:34px; height:34px; object-fit:cover; border-radius:6px;
  flex:none; background:var(--border); }}
.res-glyph {{ width:34px; height:34px; flex:none; display:flex; align-items:center;
  justify-content:center; font-size:1.2rem; }}
.res-label {{ flex:1; min-width:0; }}
.res-path {{ word-break:break-all; }}
.res-fresh {{ flex:none; text-align:right; }}
.res-warn {{ color:var(--blocked); font-size:.8rem; }}
ul.res-list a {{ color:var(--accent); text-decoration:underline; }}
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
/* --- Navigation shell (M14, docs/SPEC.md §18) -- a breadcrumb on top and a
   persistent left app-shell (project switcher + page list) on every BOARD
   page. Reuses the §11.2 .page-shell/.page-main flex layout and the SAME
   max-width:600px breakpoint below, never a second one. The directory
   (host-app chrome) never gets any of this. --- */
.breadcrumb {{ font-size:.8rem; color:var(--muted); margin-bottom:.9rem; }}
.breadcrumb a {{ color:var(--muted); text-decoration:none; }}
.breadcrumb a:hover {{ color:var(--accent); text-decoration:underline; }}
.breadcrumb .crumb-current {{ color:var(--text); font-weight:600; }}
.breadcrumb .crumb-sep {{ opacity:.5; margin:0 .15rem; }}
.app-shell {{ flex:none; width:200px; display:flex; flex-direction:column; gap:1rem;
  position:sticky; top:1rem; align-self:flex-start; }}
.switcher {{ display:flex; flex-direction:column; gap:.2rem; }}
.switcher-current {{ font-weight:600; font-size:.9rem; padding:.3rem .1rem;
  border-bottom:1px solid var(--border); }}
.switcher details > summary {{ cursor:pointer; font-size:.78rem; color:var(--muted);
  list-style:none; padding:.35rem .1rem; }}
.switcher details > summary::-webkit-details-marker {{ display:none; }}
.switcher details > summary::before {{ content:"▸ "; }}
.switcher details[open] > summary::before {{ content:"▾ "; }}
.switcher details[open] > summary {{ color:var(--text); }}
.switcher-list {{ display:flex; flex-direction:column; gap:.1rem; margin-top:.2rem; }}
.switcher-item {{ display:block; padding:.35rem .5rem; border-radius:8px; color:var(--text);
  text-decoration:none; font-size:.85rem; }}
.switcher-item:hover {{ background:var(--border); }}
.switcher-item.current {{ background:var(--accent); color:var(--accent-ink); font-weight:600; }}
@media (max-width:600px) {{
  .page-shell {{ flex-direction:column; gap:0; }}
  .pages-nav {{ width:100%; }}
  .pages-sidebar {{ display:none; }}
  .pages-dropdown {{ display:block; margin-bottom:1rem; }}
  .app-shell {{ width:100%; position:static; margin-bottom:1rem; }}
}}
</style></head><body{nav_class}>
<div id="dup-notice">👉 já tens este pAInel aberto — a fechar este separador</div>
{attention}
{breadcrumb}
<header id="page-header">
  <h1>{title}</h1>
  <div class="metaline">{metaline}</div>
  <div id="status-chip" class="status-chip">{status_chip}</div>
</header>
{page_shell_open}{nav}{page_main_open}{blocks}{page_main_close}{page_shell_close}
{cr_global}
<footer>p<span style="color:var(--accent)">AI</span>nel · a segunda interface do teu agente</footer>
<script>
// Every endpoint this page talks to hangs off basePath (M13, docs/SPEC.md
// §17.4): '' in single-board mode (`painel serve` -> /event, /version), or
// '/<slug>' under the unified service (-> /<slug>/event, /<slug>/version).
// Templated server-side: only the server knows which mode it's in.
const basePath = {base_path_js};

// The button the human just pressed, captured in the CAPTURE phase so it's
// already set by the time the inline onclick handler runs send() -- this is
// what lets one central send() give every action button (play/skip/answer/
// approve/...) its "a enviar" spinner without touching a single call site.
let _lastActionBtn = null;
document.addEventListener('pointerdown', function (e) {{
  _lastActionBtn = e.target.closest('button');
}}, true);

// send() now does three things the old fire-and-forget version didn't:
//  1. shows an immediate "a enviar" spinner on the pressed button, so a slow
//     round-trip no longer looks like a dead click;
//  2. distinguishes success from failure -- the old catch(e){{}} swallowed
//     every error AND still resolved, so reloadSoon reloaded to the SAME
//     state, making a failed POST indistinguishable from "nothing happened"
//     (the exact confusion this fixes);
//  3. on failure, leaves a visible error state and returns false so the
//     caller's reloadSoon is skipped -- the human sees it did NOT go through
//     instead of a silent reload.
async function send(payload) {{
  const btn = _lastActionBtn;
  if (btn) {{ btn.classList.remove('send-error'); btn.classList.add('sending'); btn.disabled = true; }}
  try {{
    const r = await fetch(basePath + '/event', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return true;   // success -> caller's reloadSoon replaces the whole page
  }} catch (e) {{
    if (btn) {{
      btn.classList.remove('sending'); btn.disabled = false;
      btn.classList.add('send-error');
      btn.title = 'Não foi possível enviar — tenta outra vez';
      setTimeout(() => btn.classList.remove('send-error'), 2500);
    }}
    return false;  // failure -> no reload; the error state stays visible
  }}
}}
function reloadSoon(ok) {{ if (ok === false) return; knownVersion = null; setTimeout(() => location.reload(), 250); }}

// --- Tab hygiene (M10, docs/SPEC.md §14.1) ----------------------------------
// Duplicate-tab self-close via BroadcastChannel. The channel name identifies
// THE BOARD, not the tab: two tabs of the same board must dedupe, two tabs of
// DIFFERENT boards must never touch each other.
//
// M10 keyed this on location.port, which was correct when one board == one
// process == one port (§6.6). Under M13's unified service every board shares
// one port, so a port-keyed channel would make two different boards mutually
// self-closing -- board B's tab would announce, board A's tab would answer
// "already open", and B would close itself. The service therefore templates
// the board's slug into the expression below, while single-board `painel
// serve` keeps the original port-derived one verbatim, since there the port
// genuinely still is the instance identity (docs/SPEC.md §17.4).
(function() {{
  if (typeof BroadcastChannel === 'undefined') return;  // graceful no-op on ancient browsers
  const channelName = 'painel-' + {channel_id_js};
  const bc = new BroadcastChannel(channelName);
  let answered = false;
  bc.onmessage = (ev) => {{
    const msg = ev.data || {{}};
    if (msg.type === 'announce') {{
      // Someone else just opened a tab for this same instance -- I was here
      // first, so I reply to say so, and pulse to draw the eye.
      bc.postMessage({{type: 'already-open'}});
      const hdr = document.getElementById('page-header');
      if (hdr) {{
        hdr.classList.add('dup-pulse');
        setTimeout(() => hdr.classList.remove('dup-pulse'), 3200);
      }}
    }} else if (msg.type === 'already-open' && !answered) {{
      // I'm the newer tab -- someone answered my announce, so I'm the
      // duplicate. Show the notice, then self-close (only works for tabs
      // opened by script, e.g. webbrowser.open() from `painel open`/hub --
      // if the browser refuses for a manually-typed URL, window.close() is
      // a silent no-op and the notice just stays up; no retry/workaround).
      answered = true;
      const notice = document.getElementById('dup-notice');
      if (notice) notice.style.display = 'block';
      setTimeout(() => {{ window.close(); }}, 1500);
    }}
  }};
  bc.postMessage({{type: 'announce'}});
}})();

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
function crToggleItem(bid, iid) {{ _crToggleBox(bid + '-' + iid); }}
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
// Per-item ❓ (M12): same box/key convention as crToggle/crSend, just a
// composite 'block-item' key -- _crToggleBox and the reopen-on-reload loop
// below need zero changes to support this.
function crSendItem(bid, iid) {{
  const key = bid + '-' + iid;
  const ta = document.getElementById('cr-ta-' + key);
  const v = ta.value;
  if (!v.trim()) return;
  send({{event:'change_request', block:bid, item:iid, value:v}}).then(reloadSoon);
}}
// Re-open ✎ boxes the user had open before the last reload.
for (const key of _openCrBoxes()) {{
  const box = document.getElementById('cr-box-' + key);
  if (box) box.style.display = 'block';
}}

// --- Navigation shell (M14, docs/SPEC.md §18) -------------------------------
// The project switcher's expanded/collapsed state survives reloads via
// sessionStorage -- no new SERVER state (§18.5), same discipline as the open
// plan-threads / CR boxes above.
(function() {{
  const det = document.getElementById('switcher-others');
  if (!det) return;
  if (sessionStorage.getItem('switcherOpen') === '1') det.open = true;
  det.addEventListener('toggle', function() {{
    sessionStorage.setItem('switcherOpen', det.open ? '1' : '0');
  }});
}})();
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
    const r = await fetch(basePath + '/version', {{cache:'no-store'}});
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
