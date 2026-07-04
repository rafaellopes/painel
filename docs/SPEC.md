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
| GET | `/version` | `{"v": <mtime float>}` — poller uses it |
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

**`links`** — curated resources/outputs.
```jsonc
{ "id":"l1","type":"links","title":"Documentos gerados",
  "items":[{"label":"Minuta v2 (PDF)","url":"file:///…","kind":"file"},
           {"label":"Portal AT","url":"https://…","kind":"external"}] }
```
Render as list with kind icon. No events, never pending. `target=_blank`.

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

---

## 7. CLI (unchanged surface, document only)

`painel open [board] [--port N]` idempotent (pidfile `<board>.pid`,
log `<board>.log`) · `stop` · `status` · `serve` (foreground) · `init` ·
`demo`. Default board `.painel-board.json`. Auto port from 8765.

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

**Suggested build order for a growing catalog:** M1 (already the
foundation) → M5 and M6 can proceed in **either order relative to each
other** (independent), but **M7 depends on M5** landing first. M2/M3/M4 are
independent of M5/M6/M7 and may interleave freely.

Work one PR per milestone (M2 may be one PR per block). Conventional commit
messages. Ask nothing that this spec already answers; where the spec is
silent on cosmetics, match existing style.
