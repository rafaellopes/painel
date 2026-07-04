"""
Page shell: the _PAGE HTML template, global CSS, and global JS.

Per-block JS (from each block module's JS constant) is joined in and
inserted at the {block_js} placeholder by server.py.
"""
from __future__ import annotations

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
