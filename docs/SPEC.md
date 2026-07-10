# pAInel — Development Specification (v1)

**Audience:** an AI coding agent (or human) implementing pAInel features
without prior context. This document is self-contained: read it top to bottom
and you can start working. When it conflicts with code comments, this spec
wins; when it conflicts with `docs/PROTOCOL.md` (future), the protocol wins.

---

## 0. Product thesis (why every decision below looks the way it does)

pAInel is a **second interface for AI agents**: the agent composes a local
web dashboard out of **typed blocks** (plan, approval, checklist, question…)
and reacts to the human's clicks. The end user may be non-technical — a
lawyer, an accountant, a manager. The agent picks which blocks appear; the
blocks are a **grammar of human↔agent interactions**, not features.

**The core bet: the block catalog will grow a lot.** Having *the right block
for each need* is how the product fits each user. Therefore the #1
architectural requirement is: **adding a new block type must be trivial,
safe, and self-contained** — one file, one registry entry, no edits to the
HTTP layer, no risk to existing blocks.

Non-negotiable constraints:

1. **Python stdlib only.** No pip dependencies, ever, in the core.
2. **One artifact of state:** `board.json`. Human-readable, agent-editable.
3. **Events out via stdout** (JSONL) and via `<board>.log`. The agent listens
   there; pAInel never calls the agent.
4. **Never interrupt the human typing.** All refresh logic must respect the
   `isBusy()` contract (§6.4).
5. **Graceful degradation:** unknown block types render a visible fallback,
   never crash.

---

## 1. Current state (baseline you inherit)

- `painel/server.py` (~650 lines): monolithic — HTTP handler, HTML/CSS/JS
  template, per-block render functions, event application.
- `painel/__main__.py`: CLI — `open` (idempotent start+browser), `stop`,
  `status`, `serve`, `init`, `demo`.
- 10 block types implemented (§5), including `plan` with play/edit/skip/
  reorder/threads and an "attention bar" (§6.2).
- Distribution: installed via venv + symlink; PyPI pending.
- Tests: none committed yet (ad-hoc so far). You will add them (§8).

Known conventions already in the code that you must preserve:

- All user content is HTML-escaped with `e()`. **When embedding JSON in an
  HTML attribute, always `e(json.dumps(x))`** — a real bug shipped because a
  raw `"` closed the `onclick` attribute early.
- Textareas/inputs carry `data-orig` with their original value so `isBusy()`
  can detect unsent edits.
- Open plan-threads persist across reloads via `sessionStorage`
  (`openThreads` key).
- `plan_seen` events update state but are **not** written to stdout (UI
  housekeeping must not wake the agent).

---

## 2. Target architecture (Milestone M1 is getting here)

```
painel/
  __main__.py          # CLI (unchanged behavior)
  server.py            # HTTP + event dispatch + page shell ONLY
  page.py              # _PAGE template, global CSS, global JS
  blocks/
    __init__.py        # REGISTRY: {type: module}; auto-imports siblings
    base.py            # helpers: e(), md_inline(), shared field rendering
    _template.py       # copy-me skeleton for new blocks (not registered)
    heading.py  markdown.py  note.py  tasks.py  plan.py  checklist.py
    question.py  choice.py  approval.py  form.py  log.py
```

### 2.1 Block module contract

Every block module defines (only `TYPE` and `render` are mandatory):

```python
TYPE = "question"                     # unique, snake_case, stable forever

def render(block: dict, ctx: dict) -> str:
    """Return the block's HTML. ctx = {"index": int, "total": int}.
    Must escape ALL user content with e(). Must not raise on missing
    fields — use .get() with sensible defaults."""

def apply(block: dict, event: dict) -> bool:
    """Mutate `block` in place for an event addressed to it.
    Return True if the event is recognized (even if it changed nothing),
    False if this module doesn't handle that event name."""

def needs_user(block: dict) -> list[str]:
    """Labels (PT) for everything in this block currently waiting on the
    human. Empty list = nothing pending. Drives the attention bar."""

SILENT_EVENTS: set[str] = set()
    """Event names that must NOT be emitted to stdout (UI housekeeping)."""

JS: str = ""
    """Optional JS functions this block needs, appended once to the page.
    Plain string, no f-string braces issues — page.py joins them."""

def watched_paths(block: dict) -> list[str]:
    """Optional (M11, §15). Absolute filesystem paths whose mtime should be
    folded into `/version`'s freshness signal, so the page auto-refreshes
    when a file the board points at changes on disk -- not just when
    board.json itself changes. Return [] (or omit the function entirely) if
    a block has nothing on disk to watch. Missing paths are silently
    ignored by the caller, never raise."""
```

`blocks/__init__.py` builds `REGISTRY` by importing every sibling module
that has a `TYPE` attribute. Dispatch rules in `server.py`:

- **Render:** `REGISTRY[type].render(block, ctx)`; unknown type → fallback
  card `bloco desconhecido: <type>` (keep current behavior).
- **Events:** find the target block by `event["block"]` id, call its
  `apply()`. If the module returns False or block not found, still 200 —
  log to stderr, never crash the server.
- **Attention:** concatenate `needs_user()` across all blocks, in board
  order, as `(block_id, label)` pairs.
- **stdout emission:** skip if event name ∈ that module's `SILENT_EVENTS`.

### 2.2 What must NOT change in M1

The refactor is **behavior-preserving**. Golden test (§8.1) pins the HTML
before/after. CLI, endpoints, board.json format, event names: untouched.

---

## 3. Wire protocol (freeze as v1)

### 3.1 board.json

```jsonc
{
  "protocol": 1,               // ADD in M1. Absent == 1.
  "title": "string",
  "meta": {                    // all optional
    "project": "string",
    "updated_at": "string"     // agent-maintained, free format
  },
  "blocks": [ { "id": "b1", "type": "question", ... }, ... ]
}
```

- `id` unique within the board; required on interactive blocks.
- Order of `blocks` == render order. No nesting in v1.
- **Compatibility rules:** new fields are always additive and optional;
  a renderer must tolerate unknown fields; removing/renaming a field or
  changing its type requires bumping `protocol` (avoid; we intend v1 to
  last).

### 3.2 HTTP endpoints (localhost only, bind 127.0.0.1)

| Method | Path | Behavior |
|---|---|---|
| GET | `/` | Render full page from board.json |
| GET | `/version` | `{"v": <mtime float>, ...}` — poller uses `v`; see §15.2 for M11's freshness extension |
| POST | `/event` | Apply JSON body, persist board, emit JSONL |

### 3.3 Events (JSONL, one per line on stdout and `<board>.log`)

Envelope: `{"event": "<name>", "block": "<block id>", ...payload}`.
Current catalog:

| event | payload | emitted to agent? |
|---|---|---|
| `check` | `item`, `checked: bool` | yes |
| `answer` | `value: str` | yes |
| `choose` | `value: str` | yes |
| `approve` | `decision: "approved"\|"rejected"`, `comment: str` | yes |
| `submit` | `values: {field_id: value}` | yes |
| `plan_play` / `plan_skip` | `item` | yes |
| `plan_move` | `item`, `direction: "up"\|"down"` | yes |
| `plan_edit` | `item`, `value` | yes |
| `plan_comment` | `item`, `value` | yes |
| `plan_seen` | `item` | **no** (silent) |
| `chat_message` | `value: str` | yes |

New blocks add events under their own prefix (`<type>_<verb>`), declared in
the module. Never reuse another block's event names.

---

## 4. UX invariants (apply to every block, present and future)

1. **Answered ≠ deleted.** When an interactive block is resolved, render it
   dimmed (`.answered`) with the outcome visible ("Resposta: …",
   "Escolhido: …"). The board is also the session record.
2. **Attention is derived, never manual.** A block "waits on the human" via
   `needs_user()` only. The sticky yellow bar shows count + anchor links.
   New reply/change indicators use a **seen-counter** pattern
   (`seen: int` = items seen; unread = length > seen), cleared by a silent
   event when the user views it.
3. **Reload discipline.** The page reloads only when `/version` changes AND
   `!isBusy()`. Any block with client-side open/closed state must persist it
   in `sessionStorage` so reloads don't slam it shut.
4. **PT-PT strings** in the UI for now; collect every literal in one place
   per module to ease future i18n (constant `STRINGS` dict at module top).
5. **Dark + light** via the existing CSS custom properties; blocks use the
   variables (`--accent`, `--ok`, `--wip`, `--blocked`, `--border`,
   `--muted`), never hardcoded colors.
6. **Everything keyboard-reachable**; buttons get `title=` tooltips.

---

## 5. Block catalog

### 5.1 Implemented (v1.0) — behavior must be preserved

| type | purpose | key fields | events |
|---|---|---|---|
| `heading` | section title | `text` | — |
| `markdown` | rich text (inline md: bold/italic/code/links) | `text` | — |
| `note` | callout | `text`, `tone: info\|ok\|warn\|danger` | — |
| `tasks` | agent progress, read-only | `title`, `items[{text,status: done\|wip\|pending\|blocked}]` | — |
| `plan` | steerable plan | `title`, `items[{id,text,status(+skipped),thread[],seen}]` | plan_* |
| `checklist` | human manual steps | `title`, `items[{id,text,checked}]` | check |
| `question` | free-text ask | `prompt`, `answer` | answer |
| `choice` | pick one | `prompt`, `options[]`, `selected` | choose |
| `approval` | authorize | `prompt`, `decision`, `comment` | approve |
| `form` | multi-field input | `prompt`, `fields[{id,label,kind: text\|number\|date\|email\|select\|textarea,options?,value}]`, `submitted` | submit |
| `log` | timeline/decisions | `title`, `entries[{ts,text}]` | — |
| `chat` | free-form conversation | `title`, `messages[{from: user\|agent,text}]` | chat_message |

### 5.2 Batch 1 — implement in M2 (in this order)

Each is one module + registry entry + tests. Full field spec here so no
design decisions are needed at build time.

**`countdown`** — deadline pressure for human steps.
```jsonc
{ "id":"cd1","type":"countdown","label":"Submeter IES até",
  "deadline":"2026-07-15T17:00:00","done":false }
```
Render: label + live JS countdown (days/h/m). Past deadline → red, label
"em atraso". `needs_user`: pending if not `done` (label: the block label).
Event `countdown_done {}` when user clicks "Feito".

**`file_drop`** — hand a file to the agent.
```jsonc
{ "id":"f1","type":"file_drop","prompt":"Anexa o extrato de junho (PDF)",
  "accept":".pdf,.csv","dest_dir":"./painel-uploads","files":[] }
```
Render: drag&drop zone + file input. Upload via `POST /upload?block=<id>`
(multipart; **add this endpoint in server.py as part of this block's work**,
max 25 MB, filename sanitized to `[A-Za-z0-9._-]`, saved under `dest_dir`,
path appended to `files[]`). Event `file_added {name, path, size}`.
`needs_user`: pending while `files` empty. Answered-style once ≥1 file.

**`rating`** — quick calibrated feedback.
```jsonc
{ "id":"r1","type":"rating","prompt":"Quão adequado ficou o tom do email?",
  "scale":5,"value":null,"labels":["péssimo","excelente"] }
```
Stars 1..scale (max 10). Event `rate {value:int}`. Pending until `value`.

**`table`** — structured data the human can correct.
```jsonc
{ "id":"t1","type":"table","title":"Lançamentos suspeitos",
  "columns":[{"id":"date","label":"Data"},{"id":"desc","label":"Descrição"},
             {"id":"ok","label":"Confirmar?","kind":"checkbox"}],
  "rows":[{"date":"2026-06-03","desc":"FX fee","ok":false}],
  "editable":["ok"],"confirmed":false }
```
Read-only cells as text; `editable` columns render inputs/checkboxes.
"Confirmar tabela" button → event `table_confirm {rows}` (full rows back).
Pending until `confirmed`. Horizontal scroll inside the card on overflow.

**`resources`** — see §15 (M11), full spec, supersedes the earlier
`links` stub (never implemented, name freely reassignable).

**`gauge`** — one number that matters.
```jsonc
{ "id":"g1","type":"gauge","label":"Orçamento usado","value":7350,
  "max":10000,"unit":"€","warn_at":0.8 }
```
Bar + big number. ≥ `warn_at`·max → warning color. Read-only.

### 5.3 Batch 2 — specified later, reserved names now

`diff` (before/after approval), `signature` (draw-to-sign),
`image_annotate`, `date_pick`, `multi_choice`, `evidence`
(photo/screenshot proof for a checklist step), `timer` (agent-set reminder),
`chart` (simple SVG series). **Do not implement without a spec section.**
Reserved = the names may not be used for anything else.

### 5.5 `chat` block — full spec (implement in M7)

Free-form conversation as a first-class block, so the human never needs a
separate terminal for the day-to-day dialogue. It generalizes the pattern
already proven by `plan`'s per-item threads (§5.1) to a top-level block.

```jsonc
{ "id": "chat", "type": "chat", "title": "Conversa",
  "messages": [
    {"from": "user", "text": "Porque escolheste esta abordagem?"},
    {"from": "agent", "text": "Porque X evita Y — ver decisão em Decisões."}
  ] }
```

- Render: message list as bubbles (reuse `.thread-msg`/`.thread-msg.user`/
  `.thread-msg.agent` styles from `plan`'s thread CSS — do not duplicate
  the rule, extract to a shared class both use), newest at the bottom,
  auto-scrolled into view; a fixed textarea + "Enviar" button below.
- Only ONE `chat` block per board makes sense (top-level, agent-agnostic
  free text) — render fine either way, but the skill should only ever
  compose one.
- Event `chat_message {value}` → append `{"from":"user","text":value}`.
  **Not silent** — this is the whole point, the agent must be woken.
- `needs_user()`: pending (label "Nova mensagem" — actually: only report
  pending if the last message is from `user` with no agent reply yet AND
  more than ~5s has passed, to avoid flagging "pending" the instant the
  user hits send, before the agent had a chance to answer. Simplest
  correct rule: pending iff `messages` is non-empty and `messages[-1]["from"]
  == "user"`. Same semantics as the plan-thread unread logic in reverse.)
- No `seen` counter needed at first (unlike plan threads) — the block is
  always visible at the top, not tucked behind a toggle.
- Depends on **M5's `meta.agent_status`** (see §11) to show a small state
  chip inside the chat card header ("🟢 a ouvir" / "🟡 a trabalhar…" /
  "⚪ agente offline") — without it, a message sent while the agent isn't
  running just sits unanswered with no explanation. Build M5 before M7,
  or at minimum before M7 ships to real (non-technical) users.

### 5.4 How to add a block (the recipe a simple model follows)

1. Copy `blocks/_template.py` → `blocks/<type>.py`; fill `TYPE`, `STRINGS`.
2. Write `render()` — every user string through `e()`; JSON-in-attribute
   through `e(json.dumps(…))`; colors via CSS vars only.
3. Write `apply()` for your events; add UI-housekeeping names to
   `SILENT_EVENTS`.
4. Write `needs_user()` — think "what would the yellow bar say?".
5. Add JS (if any) to module `JS` constant; functions namespaced
   `<type>Verb()` e.g. `ratingSet()`.
6. Tests (§8): render-empty, render-filled, apply-each-event,
   needs_user-both-states, escaping test with `"<script>"` in every field.
7. Add one example to `python -m painel demo`'s board.
8. Update the table in §5.1/5.2 and `.claude/skills/painel/SKILL.md`
   (the agent must learn when to reach for the new block).

Definition of done for any block PR: all 8 steps, `python -m painel demo`
shows it, golden test updated deliberately (never accidentally).

---

## 6. Page shell details (for page.py extraction)

### 6.1 Layout
Max-width 780px, centered; sticky attention bar above the header when
pending items exist; footer brand. Cards: existing `.card` style.

### 6.2 Attention bar
`_needs_user(board)` → `[(block_id, label)]`. Bar: count chip + labels as
`#blk-<id>` anchor links. Every block is wrapped in `<div id="blk-<id>">`.

### 6.3 Polling
2s interval; `GET /version`; reload iff version changed and `!isBusy()`.

### 6.4 isBusy() contract
True if: focused element is TEXTAREA/INPUT/SELECT, **or** any
textarea/input's `value !== data-orig`. Every new block with inputs must set
`data-orig` on render.

### 6.5 The generic "needs-user" wrapper (shipped ad hoc after M7, retrofit here)

Every block's outer `<div id="blk-<id>">` wrapper (§6.2) additionally gets
`class="needs-user"` when that block's id appears in `_needs_user(board)`'s
pending set. This is computed once in `render()` (a `pending_ids` set built
*before* the blocks are joined) and is the reason a pending block visually
stands out (colored left border + a small "⏳ à tua espera" ribbon, in
page.py's CSS) from plain info cards (markdown/note/log) — not just linked
to from the attention bar. **Zero per-block-module code**: any block type,
present or future, gets this for free purely from the wrapper + CSS. §12's
`change_request` UI (M8) reuses this exact same generic-wrapper pattern for
its own per-block ✎ button — read this section before building M8.

### 6.6 The instance registry (shipped ad hoc for `restart-all`, retrofit here)

`~/.painel/instances/<port>.json` — one small file per *currently running*
instance, written by the CLI's `_spawn()` on every launch and removed by
`cmd_stop`: `{"pid": int, "port": int, "board": "<absolute path>"}`. This
exists so `painel restart-all` can find every live instance on the machine
without parsing `ps` output (an earlier attempt at that broke on any board
path containing a space, e.g. Google Drive's "Meu Drive" — printed command
lines can't reliably distinguish "a space inside one argument" from "a
space between two arguments" once the kernel's original argv is gone).
Stale entries (pid dead, or port free again) are deleted the next time
anything reads the directory — self-healing, no manual cleanup. **§13's
hub (M9) is this registry with a UI on top** — read this section before
building M9.

---

## 7. CLI (unchanged surface, document only)

`painel open [board] [--port N]` idempotent (pidfile `<board>.pid`,
log `<board>.log`) · `stop` · `status` · `restart-all` (§6.6) · `serve`
(foreground) · `init` · `demo`. Default board `.painel-board.json`. Auto
port from 8765.

---

## 8. Testing (new — part of M1)

Framework: `unittest` (stdlib only). Layout: `tests/test_blocks.py`,
`tests/test_server.py`, `tests/test_golden.py`.

1. **Golden page test:** render the demo board, compare against
   `tests/golden/demo.html`. Update file only via
   `python -m tests.regen_golden` (script prints a diff and asks nothing —
   the diff appearing in the PR is the review).
2. **Per-block tests** as in §5.4 step 6.
3. **Event dispatch tests:** unknown event → 200 + no mutation; event to
   missing block id → 200 + no crash; `plan_seen` absent from stdout capture.
4. **Escaping regression:** a board where every string field is
   `'"<script>alert(1)</script>'` renders with zero raw `<script` in output.
5. CI: single GitHub Action, `python -m unittest discover`, py3.10–3.14.

---

## 10. Whose-turn signal (M5) — full spec

**Problem this solves:** the human splits attention between the agent's own
surface (terminal/chat) and the pAInel tab, with no ambient signal for who
should act next. Solved without the human having to look at either screen
directly.

### 10.1 Protocol addition

```jsonc
{ "meta": { "agent_status": "working" } }   // "working" | "waiting" | "idle"
```

- `working` — agent is actively doing something (default assumption when
  the field is absent, for backward compatibility with existing boards).
- `waiting` — agent has nothing left to do until the human acts (i.e.
  `_needs_user(board)` is non-empty AND the agent has no other in-flight
  work — in practice: the agent sets this explicitly right before it goes
  idle/blocks on Monitor).
- `idle` — agent process isn't running / isn't watching this board at all
  (set by the CLI, not the agent — see 10.3).

The agent updates `meta.agent_status` the same way it updates any other
board field: read, mutate, `save_board()`. No new event type needed for the
agent→board direction (it's not a human interaction).

### 10.2 Rendering

- **`<title>`**: dynamic via JS based on `_needs_user()` count AND
  `agent_status`, re-evaluated on every poll tick (§6.3), not just on load:
  - pending > 0 → `🔴 N à tua espera — <board title>`
  - pending == 0 and status == working → `🟡 <board title>`
  - pending == 0 and status == idle → `⚪ <board title>`
  - pending == 0 and status == waiting (rare: agent waiting but nothing
    flagged — treat as idle for display) → `⚪ <board title>`
- **Favicon**: a tiny inline SVG data-URI dot (red/yellow/green/gray),
  swapped via JS by rewriting the `<link rel="icon">` href — no image
  asset, keeps zero-dependency promise. Function `setFavicon(color)`.
- **Header chip**: small pill next to the title, same four states, text
  version of the above ("🟡 O agente está a trabalhar…", "🔴 À espera de
  ti (N)", "⚪ Agente offline", "✅ Tudo feito" when status idle/waiting
  and pending == 0 and board has ≥1 resolved interactive block — reuse
  `_needs_user` plumbing, don't add new state tracking).
- **Browser notification**: when `pending` transitions from 0 to >0 (or
  increases) AND the document is hidden (`document.hidden`), call
  `Notification` API (request permission lazily, once, on first qualifying
  transition — never on page load, that's an anti-pattern that gets
  ignored/blocked by users). Title: the same 🔴 string; click → focuses
  the tab and scrolls to the first pending anchor.

### 10.3 CLI responsibility

`painel open`/`serve` should set `meta.agent_status = "idle"` when the
board file doesn't already have the key (first run) and there's no evidence
of a live agent (this is best-effort, not authoritative — the agent is the
source of truth once it's running and updating the field itself). Do not
over-engineer process-liveness detection here; the simple default plus the
agent setting `"working"`/`"waiting"` as it goes is sufficient for M5.

### 10.4 Deep links from the agent's own surface

When the agent (in Claude Code, or whatever is driving the board) composes
a block that needs the human, it should mention the direct anchor URL in
its own chat output, e.g. `👉 http://127.0.0.1:PORT/#blk-<id>`. This is a
**convention for the skill/integration docs to teach**, not new code in
pAInel itself — no spec work needed beyond documenting it in
`.claude/skills/painel/SKILL.md` and the Cursor/Aider guides.

---

## 11. Multi-page navigation (M6) — full spec

**Problem this solves:** large boards (many blocks) become an undifferentiated
scroll, reproducing the "lost in the chat" problem inside pAInel itself.

### 11.1 Protocol addition

```jsonc
{ "id": "b1", "type": "plan", "page": "Financeiro", ... }
```

- `page` is optional on every block. Absent → block renders on the
  implicit **Home** page (page name `null`/omitted, displayed as the board
  title, always first in the nav).
- Page order = **order of first appearance** in `blocks[]` (no separate
  page-list to maintain — avoids the two-sources-of-truth trap).
- Boards with zero blocks carrying a `page` value render exactly as today:
  **no nav UI appears at all.** This must be verified by a test — multi-page
  is purely additive, must not add visual noise to small/existing boards.

### 11.2 Rendering

- When ≥2 distinct `page` values (including implicit Home) exist: render a
  left sidebar nav (collapses to a top dropdown under ~600px viewport —
  reuse existing responsive patterns if any, otherwise plain CSS
  `@media`). Each nav item: page name + a badge = count of pending
  `_needs_user()` items whose block lives on that page (e.g. `Financeiro ③`).
  Zero pending → no badge (not "0").
- Only blocks belonging to the active page render in the main column;
  others are omitted from the DOM entirely (not just hidden) — keeps pages
  fast and avoids id collisions across pages mattering.
- **The attention bar (§6.2) becomes global**, spanning pages: its anchor
  links must navigate to the right page AND scroll to the block — i.e.
  `href="?page=<page>#blk-<id>"`. Switching page via query param is a full
  reload (simplicity over SPA complexity — this is still a stdlib-only
  server-rendered app); `?page=` persists across the existing `/version`
  poll-reload (JS must preserve `location.search` on `location.reload()`,
  which it does by default — just don't rewrite the URL elsewhere).
- Current page persists across reloads the same way open-threads do
  (§ "Open threads persist" precedent) — but simpler: it's already in the
  URL, so a normal reload naturally keeps it. No sessionStorage needed here.

### 11.3 Non-goals for M6

No drag-to-reorder pages, no nested pages, no per-page permissions. If a
future need appears, extend additively; do not redesign the `page` field.

---

## 12. Change requests (M8) — full spec

**Problem this solves:** the board today only lets the human answer what
the agent already asked (questions, choices, approvals). There is no way
to *initiate* something — "the SLA is now 12h, not 24h", "add a testing
phase", "push this deadline back a week" — without leaving the board and
typing it into the chat, which is exactly the "which surface do I use"
confusion this project exists to remove (see the session's whole M5/M6/M7
arc). The fix generalizes the pattern already proven twice: `plan`'s
per-item 💬 threads (§5.1) and the ✎ inline-edit box already on `plan`
items — lift both into a **generic, per-block mechanism** every block type
gets for free, plus one global entry point for requests that don't belong
to any specific block.

### 12.1 Protocol addition — one universal event, no new block-level fields

```jsonc
{"event": "change_request", "block": "<id or null>", "value": "<free text>"}
```

- `block` is the id of the card the ✎ was clicked on, or `null`/absent for
  the global "➕ Pedir alteração" affordance (§12.3).
- This event is **not silent** (must reach the agent) — the entire point.
- No new fields are added to any block's own schema. The request is not
  stored *on* the block; it's appended to a board-level list so it survives
  even if the block it referenced is later removed/changed:
  ```jsonc
  { "change_requests": [
      {"id": "cr1", "block": "regras", "text": "o prazo passa a 12h",
       "status": "open", "ts": "..."}
  ] }
  ```
  (`ts` is a free-format string the *server* does not generate — see §12.4
  on why timestamps are the agent's job, not pAInel's.)
- `status`: `"open"` (default) until the agent resolves it, then
  `"done"` or `"declined"` (agent sets this by editing the board, same as
  any other state change — no new event needed for the resolution side).

### 12.2 The generic ✎ button (reuses §6.5's wrapper pattern exactly)

Every block wrapper (`<div id="blk-<id>" class="needs-user">...`, §6.5)
gets one more small icon button injected by `render()` itself — **not by
any block module** — same reasoning as the needs-user ribbon: this must
work for every block type without touching `blocks/*.py`. On click, reveals
an inline textarea + "Enviar pedido" button (same show/hide + `data-orig`
conventions as `plan`'s ✎ edit box, §5.1), posts `change_request` with that
block's id, clears/collapses on success.

Open questions the previous two features already answered, reused here:
- Persisting "this box is open" across polls/reloads → same `sessionStorage`
  pattern as plan-thread open state (§1's "Open plan-threads persist").
- Where the button sits among the others → same `.plan-actions`-style icon
  row concept, generalized to a shared `.block-actions` row that `render()`
  injects into the wrapper (not into each block's own card markup, so it
  doesn't fight with a block's own internal layout).

### 12.3 The global entry point

A small persistent affordance at the bottom of the page (footer area, above
the `<footer>` brand line): "➕ Pedir alteração, nova tarefa, ou rever algo"
— same inline textarea+button pattern, posts `change_request` with
`block: null`. Exists precisely for requests that don't belong to one card
("adiciona uma fase de testes com utilizadores" isn't about any single
existing block).

### 12.4 Rendering open change requests

A `change_requests` array with any `status: "open"` entries renders as its
own small card (reuse `log`-style rows, §5.1's `log` block, but this is
server/page-level rendering, not a `blocks/*.py` module — it's board-level
state, not a block) titled "Pedidos em aberto", each row showing the text
and (if `block` is set) a link to that block. This card's presence also
feeds `_needs_user()` — **from the agent's perspective**, not the human's:
an open change request is something *the agent* owes a resolution to, so
per the same reasoning M7 (§5.5) used for unanswered chat messages,
**open change requests do NOT appear in the human-facing attention bar**
(§6.2's bar is only for what's waiting on the human). They're visible on
the board as a standing record, and the agent is expected to notice them
via the same event-stream mechanism as everything else (stdout/`<board>.log`).

### 12.5 Skill guidance (update `.claude/skills/painel/SKILL.md`)

Add explicit instructions: on receiving `change_request`, the agent must
(a) actually apply the requested change to the board if it's clear enough
to act on immediately, or (b) ask one clarifying question (as a normal
`question`/`choice` block, not chat) if not, and (c) mark the corresponding
`change_requests` entry `"done"`/`"declined"` with a one-line reason once
resolved, and (d) log the outcome in the board's `log` block. Never resolve
a change request by only replying in chat — the resolution belongs on the
board, exactly like every other interaction this project stands for.

---

## 13. The hub (M9) — full spec

**Problem this solves:** every board lives on its own ad-hoc port; there is
no single, memorable address. The human either remembers N different
`localhost:PORT` numbers or asks the agent each time. §6.6's instance
registry already tracks every live board — the hub is a thin UI on top of
data that already exists, not new tracking infrastructure.

### 13.1 What it is

A tiny built-in page, served on a **fixed, well-known port** (8765 — already
the CLI's default starting port, so no new number to remember), listing
every board currently in `~/.painel/instances/` (§6.6) as a clickable card:
board title, project (from `meta.project`), a pending-count badge (reusing
`_needs_user()` the same way page-nav badges do, §11.2), and the
`agent_status` chip (§10.2). Clicking a card navigates to that board's own
`http://localhost:<its-port>/`.

### 13.2 How it's served — reuse `serve()`, don't fork a second server

Do **not** write a second HTTP server implementation. Instead:
- `painel hub [--port 8765]` is a new CLI command that starts a `serve()`
  instance whose "board" is synthesized on every request directly from
  `_discover_running_boards()` (§6.6) — each live instance becomes one
  `heading`+`markdown`+`links`-style entry (or a small new internal render
  path if that doesn't fit cleanly; **do not add a new block type to the
  public catalog for this** — the hub's listing is host-app chrome, not a
  board a human composes, so it can live entirely in `painel/__main__.py`
  or a small `painel/hub.py`, calling `page.py`'s existing template/CSS
  directly rather than going through the block registry).
- The hub re-reads the registry on every request (like `_needs_user` is
  recomputed on every render) — no caching, no staleness, boards
  starting/stopping are reflected immediately on refresh.
- `painel open` should, in addition to opening the specific board, ensure
  the hub is running too (idempotent, same `_spawn`-family pattern as any
  other instance) so the human always has the fixed address available —
  but the hub itself never needs a browser tab opened automatically; it's
  the thing you bookmark once, not something that appears unprompted.

### 13.3 Friendly host, one extra step

`http://localhost:8765/` is the guaranteed-works address (works in every
browser, zero config) and is the one to print/document as canonical. As a
bonus, **document** (README/SKILL.md, not new code) that Chrome/Firefox
users can bookmark `http://<slug>.localhost:8765/`-style addresses if they
want per-project vanity URLs — browsers resolve arbitrary `*.localhost`
subdomains to loopback with zero configuration (living standard, no
`/etc/hosts` edit, no sudo). This is documentation only; do not attempt to
make pAInel bind to or recognize custom hostnames — the port is what
actually routes the request, the hostname is cosmetic.

### 13.4 Non-goals for M9

No auth, no remote access (still 127.0.0.1-only, same as every other
instance) — the hub is a local convenience, not pAInel Cloud (see
`docs/CLOUD.md`) wearing a costume. No renaming/managing boards from the
hub UI — it's read-only navigation, not a board manager.

---

## 14. Tab hygiene and the chat-pointer convention (M10) — full spec

Two small, independent fixes for the same underlying complaint: repeated
`painel open` calls accumulate duplicate browser tabs, and the agent's own
chat output tends to duplicate everything already on the board instead of
just pointing at it.

### 14.1 Duplicate-tab self-close via BroadcastChannel

Every board page, on load, opens a `BroadcastChannel` named
`painel-<port>` (stable per instance, not per board path, since the port
*is* the instance identity — §6.6). It announces its presence; if another
tab for the same channel responds "I'm already here", the newer tab closes
itself after briefly flashing a "👉 já tens este pAInel aberto — a fechar
este separador" notice (long enough to read, short enough to not be
annoying — ~1.5s), and the original tab gets a transient visual pulse (CSS
animation reusing the same `pulse` keyframes already defined for the
plan-thread reply dot, §5.1) so the human's eye is drawn to the tab that's
staying open. `window.close()` only works on tabs opened by script (which
is exactly the `webbrowser.open()` case from `painel open` — the common
case this fixes); if the browser refuses to close a manually-opened tab,
fall back to just showing the "already open elsewhere" notice without
attempting to close, rather than erroring.

### 14.2 The chat-pointer convention (documentation only, no new code)

Update `.claude/skills/painel/SKILL.md` with an explicit rule: once
something is represented on the board, the agent's own chat reply about it
should be **one line plus the deep link** (§10.4's convention), not a
restated copy of the board's content. The board is the single source of
truth for state; the chat is for conversation and for work that doesn't
have a board representation yet. This directly targets the failure mode
observed in this project's own dogfooding (the `rececao.pt` session
described three pending decisions in full prose in chat *and* had them as
proper `choice`/`question` blocks — the duplication is what made the board
feel optional).

---

## 15. The `resources` block (M11) — full spec

**Problem this solves:** several of Rafael's real projects each accumulate a
handful of documents/mockups/reference links (a design mockup, a generated
report, a Figma prototype, a spec doc) that the human needs quick access to
— and that keep changing as work progresses. A static list requires the
agent to re-describe it every time something changes, which both wastes
chat turns and drifts out of sync (§14.2's whole point — the board should
be the thing that's current, not a snapshot the agent narrates around).

### 15.1 Board shape

```jsonc
{ "id": "res1", "type": "resources", "title": "Documentos e mockups",
  "items": [
    { "label": "Mockup landing v3", "kind": "file",
      "path": "/Users/rafael/Desktop/mockup-v3.png" },
    { "label": "Pasta de entregáveis", "kind": "folder",
      "path": "/Users/rafael/projects/acme/deliverables" },
    { "label": "Protótipo Figma", "kind": "url",
      "url": "https://figma.com/file/..." }
  ] }
```

- `kind`: `"file"` | `"folder"` | `"url"`. `file`/`folder` carry an absolute
  local `path`; `url` carries an external `url`. Never both on one item.
- No `id` needed per item (read-only block, no events target individual
  items) — but keep items order-stable (it's a plain list, order = board
  order, no reordering UI in v1).

### 15.2 Live freshness (the "sempre atualizados" requirement)

Two layers, both server-side, both computed fresh on every request (no
caching, matching every other freshness mechanism already in this codebase
— `_needs_user()`, the hub's registry re-read, etc.):

1. **Per-item freshness text.** For `kind in ("file", "folder")`, `render()`
   calls `os.stat(path)` at render time and shows a relative "atualizado há
   Xm/h/d" (or an absolute date beyond ~7 days — reuse whatever relative-time
   helper already exists in the codebase if there is one, otherwise write a
   small one in `blocks/base.py` so future blocks can reuse it too). A
   missing path renders a clear inline warning ("⚠ ficheiro não encontrado")
   instead of crashing or silently omitting the item — graceful degradation
   per §0's constraint 5, and useful signal (a moved/deleted mockup should
   be visible, not silently stale). `kind: "url"` items never show
   freshness (external, not ours to stat) — just the link with an
   external-link icon, `target="_blank"`.
2. **Page-level auto-refresh on file change.** This is the piece that makes
   the block *actually* stay current without the human refreshing manually:
   `watched_paths(block)` (the new optional module hook, §2.1) returns every
   `file`/`folder` item's `path`. The `/version` endpoint's `v` value
   becomes `max(board.json's own mtime, every registered block's
   watched_paths() mtimes)` — computed by having `server.py`'s `/version`
   handler iterate all blocks, call `REGISTRY[type].watched_paths(block)`
   when the module defines it (skip silently if not — most blocks won't),
   `os.path.getmtime()` each returned path inside a try/except (missing
   path → ignored, not an error), and take the max alongside the board's
   own mtime. The existing poll/reload machinery (§6.3) needs zero changes
   — it already reloads whenever `v` changes; it just now changes for a
   wider set of reasons. A `folder`'s mtime only reflects changes to the
   folder's own immediate directory entries (files added/removed), not
   arbitrary nested file edits — document this as a known, acceptable
   limitation in a code comment rather than implementing recursive
   directory watching (that's real complexity for a niche need; if it turns
   out to matter, revisit later — don't build it preemptively).

### 15.3 Thumbnails

For `kind: "file"` items whose path has a common image extension (`.png`,
`.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, case-insensitive), render a small
inline thumbnail via `<img src="file://<path>">`. This is safe and simple:
loading an image resource (unlike `fetch`/XHR, and unlike *navigating* to a
`file://` link) is not subject to the same-origin restrictions that make
`file://` awkward elsewhere in browsers, so this works with zero server-side
image-serving code. Non-image files just show a small icon-by-extension (or
a generic file glyph — keep this simple, don't build a MIME-type icon set).
Folders never get a thumbnail. Local paths (`file`/`folder`) are shown as
monospace text, not a clickable navigation link — clicking a `file://` href
to *navigate* is unreliable across browsers/OSes for security reasons; only
`url` items are real clickable links. This is a deliberate, documented
limitation, not a bug to fix later.

### 15.4 Non-goals for M11

No upload/edit of items from the UI (composed by the agent only, like every
other read-only block — `tasks`, `log`, etc.). No recursive folder watching
(§15.2). No remote/network paths (local filesystem only — this block only
makes sense for a human and agent sharing the same machine, which is
pAInel's whole model anyway, §0). No new public API beyond the
`watched_paths()` hook, which is generically useful to any *future* block
that points at something on disk — do not special-case `resources` inside
`server.py`'s `/version` handler beyond calling the generic hook.

---

## 16. Per-item change requests (M12)

**Problem this solves:** the block-level ✎ (§12) covers "something about
this whole card needs to change", but a `checklist` with several steps often
has exactly one item the human doesn't understand or can't act on (a real
example: "Correr no terminal: bash scripts/set_tasty.sh (colar client
secret + refresh token, ocultos)" — unclear which secret, from where). The
human's only prior recourse was leaving it unchecked forever or asking in
chat, both of which defeat the board.

### 16.1 Mechanism

A small ❓ button next to each item of a block that opts in, posting the
*same* `change_request` event (§12.1) with an added `item` field:
```json
{"event":"change_request", "block":"prep", "item":"p2", "value":"não sei onde arranjar isto"}
```
Handled by the exact same generic path as the block-level/global ✎ — never
dispatched through the block's own `apply()`. The stored
`change_requests` entry gains `"item"` (`None` when absent, i.e. every
change request from before M12 or from the block-level/global affordance —
fully backward compatible). The "Pedidos em aberto" card resolves the
item's own `text` for display when possible, so the open-requests list is
readable without opening the board to figure out which of N items the human
meant. Still excluded from the human-facing attention bar, same reasoning
as §12.4 (it's the agent's turn, not the human's).

### 16.2 Shared helper, not a bespoke mechanism per block

`blocks.base.item_change_request_html(block_id, item_id)` renders the
button + inline box, reusing the *exact* `cr-box-<key>`/`cr-ta-<key>` DOM id
convention and `page.py`'s existing `_crToggleBox`/sessionStorage
persistence from §12.2 — the key is just `<block>-<item>` instead of
`<block>`, so open/closed state across reloads works for free, no new
client-side persistence logic. Only `crToggleItem(bid,iid)`/
`crSendItem(bid,iid)` needed adding to page.py's JS. `checklist.py` is the
first (and, as of M12, only) consumer — any future item-bearing block
(`table`, once M2 ships) should call the same helper rather than inventing
its own per-item ask-a-question mechanism.

### 16.3 Non-goals

Not a full conversation thread like `plan`'s per-item 💬 (§5.1) — that
pattern stays bespoke to `plan` where a back-and-forth about *reprioritizing
a step* is the common case. The change-request ❓ is a single ask, resolved
the same way any change request is resolved (§12's existing 4-step flow).
No new block-module contract hook — `item_change_request_html` is a shared
render-time helper a module calls from inside its own `render()`, not a
`§2.1`-style optional attribute the registry auto-discovers.

---

## 9. Milestones for the implementing model

| # | Deliverable | Acceptance |
|---|---|---|
| **M1** | Refactor to `blocks/` registry + `page.py`; add `"protocol": 1`; test suite + CI | Golden HTML identical (modulo the protocol field); all §8 tests green; `painel demo` unchanged to the eye |
| **M2** | Batch-1 blocks: countdown, file_drop, rating, table, links, gauge (+ `/upload`) | Each passes §5.4 DoD; demo board shows all six; skill updated |
| **M3** | Board export: `GET /export` → single-file HTML report (inline CSS, no JS, print-friendly); "Exportar" link in footer | Opens standalone in a browser from disk; includes answered states + threads + log |
| **M4** | PyPI release `painel` 0.2.0 (`pipx install painel`) | Fresh machine: `pipx install painel && painel demo` works |
| **M5** | Whose-turn signal (§10): dynamic `<title>`, favicon, header chip, browser notification, `meta.agent_status` protocol field | Title/favicon change correctly across all 4 states in a manual + scripted check; notification fires only on 0→N transition while hidden; existing boards without `agent_status` still render (defaults to `working`) |
| **M6** | Multi-page navigation (§11): `page` field, sidebar/dropdown nav with pending badges, attention bar spans pages | Board with no `page` fields renders identically to pre-M6 (no nav at all) — pinned by test; board with 2+ pages shows nav, badges match `_needs_user()` counts, anchor links cross pages correctly |
| **M7** | `chat` block (§5.5) | Passes §5.4 DoD; requires M5 merged first (status chip dependency); demo board includes a chat example |
| **M8** | Change requests (§12): universal `change_request` event, generic ✎ per-block button + global "➕ Pedir alteração" affordance, `change_requests` board-level array, skill guidance | ✎ button appears on every block type without touching any `blocks/*.py` module; global affordance works with `block: null`; open requests render as their own card and do NOT appear in the human-facing attention bar (§12.4); skill updated |
| **M9** | The hub (§13): `painel hub` on a fixed port (default 8765) listing every live instance from the §6.6 registry with pending badges + status chip, click-through to that board | Hub reflects registry changes on every refresh, no caching; a board with zero registry entries shows an empty-but-not-broken hub; no new public block type added for this |
| **M10** | Tab hygiene + chat-pointer convention (§14): BroadcastChannel duplicate-tab self-close, skill rule that chat replies point at the board instead of restating it | Opening the same board twice in two tabs results in one tab closing itself with a visible notice, the other pulsing; skill doc updated with the one-line-plus-link convention |
| **M11** | `resources` block (§15): file/folder/url items, live per-item freshness text, thumbnails for images, generic `watched_paths()` hook + `/version` freshness extension so the page auto-refreshes when a linked file changes on disk | Passes §5.4 DoD; a board with a `resources` block auto-reloads when a watched file's mtime changes, without any board.json edit; missing paths render a visible warning, never crash; `watched_paths()` being absent on every other block type causes zero behavior change (backward compatible) |
| **M12** | Per-item change requests (§16): ❓ next to each `checklist` item, shared `item_change_request_html()` helper, `item` field on `change_requests` entries | `change_requests` entries carry `item` (None when absent, backward compatible); resolved item text shown in "Pedidos em aberto"; still excluded from the attention bar; open/closed box state persists across reloads via the existing generic mechanism, no new client-side persistence code |

**Suggested build order for a growing catalog:** M1 (already the
foundation) → M5 and M6 can proceed in **either order relative to each
other** (independent), but **M7 depends on M5** landing first. M2/M3/M4 are
independent of M5/M6/M7 and may interleave freely. **M8 is independent of
M5-M7** (build any time after M1). **M9 depends on §6.6's registry**
(already shipped, ad hoc, ahead of this table — safe to build any time).
**M10.1 (tab dedup) is independent; M10.2 (chat-pointer convention) is
docs-only and can land any time.**

Work one PR per milestone (M2 may be one PR per block). Conventional commit
messages. Ask nothing that this spec already answers; where the spec is
silent on cosmetics, match existing style.
