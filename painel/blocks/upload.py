"""
The human hands files to the agent (M15, docs/SPEC.md §19).

The inverse of `resources` (M11, §15): where `resources` lets the agent *show*
files to the human, `upload` lets the human *drop* files/images/a folder into a
destination the AGENT chooses (`dest_dir`, relative to the project). This kills
the "where do I put these?" question the human otherwise has to ask in chat.

Read-side / write-side stay single-purpose: this block never previews or
thumbnails what was dropped (§19.5) -- if the agent wants to show the files
back, it composes a `resources` block, which already does thumbnails.

Note on the event flow: the `file_added` event is applied SERVER-SIDE by the
/upload endpoint (server.py), which writes the file, appends {name,path,size}
to this block's `files`, and emits the JSONL event directly -- exactly like the
change_request endpoint handles its own event rather than routing it through a
block's apply(). So apply() here is a deliberate no-op: this module never sees
file_added through the /event path.
"""
from __future__ import annotations

from .base import e, md_inline

TYPE = "upload"

STRINGS = {
    "prompt_default": "Arrasta ficheiros para aqui",
    "drop_hint": "Arrasta ficheiros para aqui ou clica para escolher",
    "drop_hint_dir": "Arrasta uma pasta para aqui ou clica para escolher",
    "uploaded": "Ficheiros enviados",
    "pending_label": "Ficheiros por enviar",
}


def _files_html(block: dict) -> str:
    """Answered-style listing of what's already been uploaded (§19.1), so the
    block reads like a resolved interaction and the human sees the drop landed."""
    files = block.get("files", [])
    if not files:
        return ""
    rows = "".join(
        f'<li class="res-item">'
        f'<span class="res-glyph">📎</span>'
        f'<span class="res-label">{e(f.get("name", ""))}<br>'
        f'<code class="res-path small muted">{e(f.get("path", ""))}</code></span>'
        f'<span class="res-fresh muted small">{e(_human_size(f.get("size", 0)))}</span>'
        f'</li>'
        for f in files
    )
    return (
        f'<div class="upload-done"><div class="answer">{e(STRINGS["uploaded"])}:</div>'
        f'<ul class="res-list">{rows}</ul></div>'
    )


def _human_size(n) -> str:
    try:
        size = float(int(n))
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    prompt = block.get("prompt") or STRINGS["prompt_default"]
    accept = block.get("accept", "")
    multiple = block.get("multiple", True)
    directory = block.get("directory", False)
    files = block.get("files", [])

    attrs = []
    if multiple:
        attrs.append("multiple")
    if directory:
        attrs.append("webkitdirectory")
    if accept:
        attrs.append(f'accept="{e(accept)}"')
    input_attrs = " ".join(attrs)

    hint = STRINGS["drop_hint_dir"] if directory else STRINGS["drop_hint"]
    # `answered`-style dim once at least one file has landed (UX invariant §4.1:
    # answered != deleted -- the drop zone stays usable, but the block visibly
    # carries its outcome).
    card_cls = "card upload-card answered" if files else "card upload-card"
    return (
        f'<div class="{card_cls}">'
        f'<p>{md_inline(e(prompt))}</p>'
        f'<div class="upload-zone" id="up-zone-{bid}" '
        f'ondragover="uploadDragOver(event)" ondragleave="uploadDragLeave(event)" '
        f'ondrop="uploadDrop(event,\'{bid}\')" '
        f'onclick="document.getElementById(\'up-input-{bid}\').click()">'
        f'<span class="upload-hint">{e(hint)}</span>'
        f'<input type="file" id="up-input-{bid}" style="display:none" {input_attrs} '
        f'onchange="uploadPick(this,\'{bid}\')">'
        f'</div>'
        f'{_files_html(block)}'
        f'</div>'
    )


def apply(block: dict, event: dict) -> bool:
    """No-op: file_added is applied server-side by the /upload endpoint
    (server.py), never dispatched here through /event (see module docstring)."""
    return False


def needs_user(block: dict) -> list:
    """Pending while `files` is empty: an upload block the agent composed is
    something it's waiting on the human to feed, so it belongs in the attention
    bar until at least one file has landed (unlike a change request, which is
    the agent's turn). Once ≥1 file is uploaded it's resolved (§19)."""
    if not block.get("files"):
        label = block.get("prompt") or STRINGS["pending_label"]
        return [(block.get("id", ""), label)]
    return []


SILENT_EVENTS: set = set()

# All upload JS lives here (always emitted into the page via _block_js, whether
# or not a board uses an upload block) so the GLOBAL 📎 affordance in page.py
# can reuse the same helpers. Endpoints hang off basePath (M13, §17.4): the
# block id goes in the query string; the global affordance names no block, so
# the server defaults dest_dir to painel-uploads/ (§19.3).
JS = """
function _uploadPost(url, files, zone) {
  if (!files || !files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('file', f, f.name);
  if (zone) { zone.classList.remove('upload-error'); zone.classList.add('uploading'); }
  fetch(url, {method:'POST', body: fd})
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); reloadSoon(true); })
    .catch(function (e) {
      if (zone) {
        zone.classList.remove('uploading');
        zone.classList.add('upload-error');
        setTimeout(function () { zone.classList.remove('upload-error'); }, 2500);
      }
    });
}
function uploadDragOver(ev) { ev.preventDefault(); ev.currentTarget.classList.add('dragover'); }
function uploadDragLeave(ev) { ev.currentTarget.classList.remove('dragover'); }
function uploadDrop(ev, bid) {
  ev.preventDefault();
  const zone = ev.currentTarget; zone.classList.remove('dragover');
  _uploadPost(basePath + '/upload?block=' + encodeURIComponent(bid), ev.dataTransfer.files, zone);
}
function uploadPick(input, bid) {
  _uploadPost(basePath + '/upload?block=' + encodeURIComponent(bid), input.files,
              document.getElementById('up-zone-' + bid));
}
function uploadDropGlobal(ev) {
  ev.preventDefault();
  const zone = ev.currentTarget; zone.classList.remove('dragover');
  _uploadPost(basePath + '/upload', ev.dataTransfer.files, zone);
}
function uploadPickGlobal(input) {
  _uploadPost(basePath + '/upload', input.files, document.getElementById('up-zone-global'));
}
"""
