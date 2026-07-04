"""Free-form conversation, first-class top-level block (M7, docs/SPEC.md §5.5).

Generalizes the message-bubble pattern already proven by `plan`'s per-item
threads to a top-level, always-visible block, so the human never needs a
separate terminal for day-to-day dialogue with the agent.
"""
from __future__ import annotations

from .base import e, md_inline, status_chip_text

TYPE = "chat"

STRINGS = {
    "title": "Conversa",
    "you": "Tu",
    "agent": "Agente",
    "placeholder": "Escreve uma mensagem...",
    "send": "Enviar",
}


def render(block: dict, ctx: dict) -> str:
    bid = e(block.get("id", ""))
    title = e(block.get("title", STRINGS["title"]))
    messages = block.get("messages", [])

    # Show the same M5 whose-turn chip used in the page header (docs/SPEC.md
    # §10.2) right inside the card, so a message sent while the agent isn't
    # running has a visible explanation instead of just sitting unanswered.
    # We don't know the board-wide pending count or "has resolved" state from
    # inside a single block's render(block, ctx) -- both are board-level, not
    # block-level -- so the chip here only reflects agent_status, passed in
    # via ctx by the caller (server.py) when available. Absent ctx info
    # (e.g. in isolated unit tests) falls back to a status-less card: no chip
    # rendered rather than guessing.
    status = ctx.get("agent_status") if isinstance(ctx, dict) else None
    chip_html = ""
    if status is not None:
        chip_text = status_chip_text(0, status, False)
        chip_html = f'<span class="status-chip chat-chip">{e(chip_text)}</span>'

    msgs_html = "".join(
        f'<div class="thread-msg {e(m.get("from", ""))}">'
        f'<b>{STRINGS["you"] if m.get("from") == "user" else STRINGS["agent"]}:</b> '
        f'{md_inline(e(m.get("text", "")))}</div>'
        for m in messages
    )

    # No inline <script> tag here by design: keeping script logic entirely in
    # the shared JS constant (below) means the escaping regression test
    # ('"<script>alert(1)</script>' payload, docs/SPEC.md §8.4) can assert
    # "no raw <script" in a block's rendered markup without a block-level
    # false positive from the app's own (non-user) markup.
    return (
        f'<div class="card chat-card">'
        f'<h3>{title}{chip_html}</h3>'
        f'<div class="thread-msgs chat-msgs" id="chat-msgs-{bid}">{msgs_html}</div>'
        f'<textarea id="chat-ta-{bid}" data-orig="" placeholder="{e(STRINGS["placeholder"])}"></textarea>'
        f'<button onclick="chatSend(\'{bid}\')">{e(STRINGS["send"])}</button>'
        f'</div>'
    )


def apply(block: dict, event: dict) -> bool:
    if event.get("event") != "chat_message":
        return False
    block.setdefault("messages", []).append(
        {"from": "user", "text": event.get("value", "")}
    )
    return True


def needs_user(block: dict) -> list:
    """Per docs/SPEC.md §5.5, the literal rule offered is "pending iff
    messages non-empty and last message is from user" -- mirroring the
    plan-thread unread logic in reverse.

    Judgment call: we deliberately do NOT surface that state via the
    attention bar. §6.2 defines the attention bar as everything currently
    waiting on the HUMAN. When the last message is from the user, the human
    has already acted -- it's the AGENT that owes a reply. Putting that in
    the yellow "à tua espera" bar would tell the human they need to act when
    they just did; the correct signal for "agent owes a reply" is the
    existing M5 whose-turn machinery (meta.agent_status / the header + this
    card's own chip), not the human-facing attention bar. The unanswered
    message is still visibly sitting there in the chat card itself (no
    seen-counter is needed per the spec -- the block is always on-screen),
    so nothing is lost; it just isn't double-counted as something for the
    human to do. Hence: always return [] here.
    """
    return []


SILENT_EVENTS: set = set()  # chat_message must wake the agent -- never silent

JS = """
function chatSend(bid) {
  const ta = document.getElementById('chat-ta-' + bid);
  const v = ta.value;
  if (!v.trim()) return;
  send({event:'chat_message', block:bid, value:v}).then(reloadSoon);
}
// Auto-scroll every chat card's message list to the bottom (newest message)
// on every page load/reload -- run for all chat blocks on the page at once.
document.querySelectorAll('.chat-msgs').forEach(function (el) { el.scrollTop = el.scrollHeight; });
"""
