---
name: painel
description: >
  Show a live, clickable dashboard (pAInel) next to the chat for any non-trivial,
  multi-step task. Use it to give the human checkboxes for manual steps, ask
  questions with answer boxes, request approvals, and show live progress — instead
  of burying everything in scrolling chat. Trigger when the work has several steps,
  requires the user to do something by hand, or when the user asks for a plan,
  dashboard, checklist, or "second interface".
---

# pAInel — the second interface

pAInel renders a `board.json` as an interactive web page next to the chat. You
compose typed blocks; the human clicks/types; each interaction is written back to
the board **and** printed as one JSON line on stdout, which you watch to react.

Use it for any non-trivial, multi-step task — **especially** when the user must
do something manually (log in somewhere, download a file, confirm a payment).
Don't use it for one-shot answers or quick chats.

## Setup (once per task)

1. **Write** a `board.json` in the working directory (see schema below). Start
   with a heading, a markdown goal, a `tasks` block for your own progress, and —
   if you need the user to do or decide anything — the relevant interactive
   blocks.

2. **Open** it — one idempotent command, no port bookkeeping needed:
   ```bash
   painel open              # creates the board if missing, starts the server, opens the browser
   ```
   Calling it again just re-opens the tab if a server is already running for
   that board — safe to call from anywhere, including directly by the user.
   Check `painel status` / stop with `painel stop`. If `painel` isn't on PATH,
   fall back to `python3 -m painel serve board.json --port <N> --open`
   (foreground) or vendor the single `painel/server.py` into the project.

   `painel open` also silently ensures a **hub** is running at the fixed
   address `http://localhost:8765/` — a page listing every board currently
   running on the machine, with pending badges and status chips, click-through
   to each. It's a convenience for the human to bookmark once; you don't need
   to do anything extra to keep it running or mention it unless asked.

3. **Watch** for interactions. `painel open` logs the server's stdout to
   `<board>.log` in the project — attach a background monitor to that file,
   filtering to JSON lines (they start with `{`). Each line is one interaction
   event.

## React to events

Events look like:
```json
{"event":"check",     "block":"cl", "item":"c1", "checked":true}
{"event":"answer",    "block":"q1", "value":"..."}
{"event":"choose",    "block":"ch", "value":"PDF"}
{"event":"approve",   "block":"ap", "decision":"approved", "comment":"..."}
{"event":"submit",    "block":"fm", "values":{"nome":"Ana"}}
{"event":"plan_play", "block":"pl", "item":"p2"}
{"event":"plan_edit", "block":"pl", "item":"p3", "value":"new text"}
{"event":"plan_skip", "block":"pl", "item":"p1"}
{"event":"plan_move", "block":"pl", "item":"p3", "direction":"up"}
{"event":"change_request", "block":"regras", "value":"o prazo passa a 12h"}
{"event":"change_request", "block":null, "value":"adiciona uma fase de testes com utilizadores"}
```

`plan_play` is a priority override: the user is telling you to drop what's queued and
start that specific step now. The server already flips its status to `wip` for you —
your job is to actually act on it. `plan_move`/`plan_edit`/`plan_skip` are already
applied to the board by the server; just notice them and adjust your own work
accordingly (e.g. don't keep working on a step the user just skipped).

When an event arrives:
- Do the thing it unblocks (continue the pipeline, use the answer, honor the
  decision).
- **Update `board.json`** to reflect new state: flip task statuses, add a `log`
  entry, add the next question, append next steps. The page auto-refreshes when
  the file changes (and never while the user is mid-typing).

Keep the board as the single source of truth for "where are we". The user should
be able to glance at it and know the plan, the progress, and what's waiting on
them — without re-reading the chat.

## Tell the human whose turn it is

Set `meta.agent_status` whenever you know it — the page's `<title>`, favicon dot,
and header chip all reflect it live, so the human can tell at a glance (tab bar,
even from another window) whether they need to act:

- `"working"` — you're actively doing something. Default assumption if you never
  set it, for backward compatibility with older boards.
- `"waiting"` — you have nothing left to do until the human acts. Set this right
  before you go idle/block on watching the log for events.
- `"idle"` — nobody is driving the board. `painel open`/`serve` set this
  automatically on first run if the key is absent; you don't need to set it
  yourself for "not started yet", only for "I'm done for now".

```json
{ "meta": { "agent_status": "waiting" } }
```

When you post something in the board that needs the human's attention, also
**mention the direct link in your own chat output** so they don't have to go
hunting for it — pAInel underlines this by generating an anchor id per block
(`#blk-<id>`):

```
👉 http://127.0.0.1:8765/#blk-ap
```

This is just a convention (no special pAInel endpoint) — build the URL from the
port `painel open`/`serve` printed and the block's `id`.

## Change requests — the human initiates something

Every block gets a small ✎ button for free (you never add this yourself —
pAInel injects it into every card), plus a persistent "➕ Pedir alteração,
nova tarefa, ou rever algo" affordance near the bottom of the page. Both
post the same event:

```json
{"event":"change_request", "block":"regras", "value":"o prazo passa a 12h"}
{"event":"change_request", "block":null,     "value":"adiciona uma fase de testes"}
```

`block` is the id of the card the ✎ was clicked on, or `null`/absent for the
global affordance. pAInel appends every one of these to a board-level
`change_requests` array for you — `{"id":"cr1","block":"regras","text":"...",
"status":"open","ts":"..."}` — you don't create this array yourself, just
read and resolve it. **This is not silent** — it reaches you the same way
every other event does, and it does **not** show up in the human-facing
attention bar (that bar is only for what's waiting on the human; an open
change request is something *you* owe a resolution to).

On receiving `change_request`:
1. If the request is clear enough to act on immediately, **apply it** —
   edit the relevant block(s), or add/adjust whatever it's asking for.
2. If it's ambiguous, **ask one clarifying question** as a proper
   `question`/`choice` block (never just in chat).
3. Once resolved, edit that entry in `change_requests` directly: set
   `"status"` to `"done"` or `"declined"` and add a one-line reason (there's
   no separate event for this — you resolve it the same way you resolve any
   other board state, by editing `board.json`).
4. Log the outcome in the `log` block.

Never resolve a change request purely by replying in chat — the resolution
belongs on the board, exactly like every other interaction.

## Board schema

```json
{
  "title": "Session title",
  "meta": { "project": "name", "updated_at": "2026-07-02 21:00", "agent_status": "working" },
  "blocks": [ /* ordered, each with a unique "id" and a "type" */ ],
  "change_requests": [ /* pAInel appends here on every change_request event; you resolve status */ ]
}
```

Block types:

- `heading` — `{ "type":"heading", "text":"..." }`
- `markdown` — `{ "type":"markdown", "text":"supports **bold**, \`code\`, line breaks" }`
- `note` — `{ "type":"note", "tone":"info|ok|warn|danger", "text":"..." }`
- `tasks` — your progress, read-only. `{ "type":"tasks", "title":"...", "items":[{"text":"...","status":"done|wip|pending|blocked"}] }`
- `plan` — a plan the user can steer, not just watch. Each item needs a stable `id`. `{ "type":"plan", "title":"...", "items":[{"id":"p1","text":"...","status":"pending|wip|done|blocked|skipped"}] }`. Per item the user can: ▶ **play** (jump the queue — tells you to work on it now), ✎ **edit** the text, ⏭ **skip**, ▲▼ **reorder**. Prefer `plan` over `tasks` whenever the user might want to reprioritize or rewrite a step; use plain `tasks` only for steps that are purely internal bookkeeping.
- `checklist` — the user's manual steps. `{ "type":"checklist", "title":"...", "items":[{"id":"c1","text":"...","checked":false}] }`
- `question` — `{ "type":"question", "prompt":"...", "answer":null }`
- `choice` — `{ "type":"choice", "prompt":"...", "options":["A","B"], "selected":null }`
- `approval` — `{ "type":"approval", "prompt":"...", "decision":null }`
- `form` — `{ "type":"form", "prompt":"...", "fields":[{"id":"f1","label":"...","kind":"text|number|date|email|textarea|select","options":[...],"value":""}], "submitted":false }`
- `log` — `{ "type":"log", "title":"...", "entries":[{"ts":"HH:MM","text":"..."}] }`
- `chat` — free-form conversation, a substitute for a separate terminal for day-to-day dialogue. `{ "type":"chat", "title":"Conversa", "messages":[{"from":"user","text":"..."},{"from":"agent","text":"..."}] }`. The human's replies arrive as a **non-silent** `chat_message` event (append `{"from":"user","text":value}` to `messages` and reply by appending your own `{"from":"agent","text":...}` before saving the board). Only compose one `chat` block per board (top-level). It never contributes to the attention bar — a message awaiting your reply is *your* turn, not the human's, so it's surfaced via `meta.agent_status` (the same 🟢/🟡/⚪ chip shown in the page header) rather than the yellow "à tua espera" bar.

## Multi-page boards

Boards past ~15-20 blocks turn into an undifferentiated scroll — the same
"lost in the chat" problem pAInel exists to solve, just one level down. Fix
it by tagging blocks with `"page": "Financeiro"` (any string). Blocks with
no `page` stay on the implicit **Home** page (always first, shown as the
board title). Page order = the order pages first show up in `blocks[]` —
there's no separate page list to keep in sync.

```json
{ "id": "b1", "type": "plan", "page": "Financeiro", "title": "..." }
```

- 0 or 1 distinct pages → nothing changes, no nav appears.
- ≥2 distinct pages → a left sidebar nav appears (collapses to a dropdown on
  narrow screens), one entry per page, with a badge showing how many pending
  items (per `needs_user()`) live on that page.
- The attention bar still spans every page — its links jump straight to the
  right page and block (`?page=Financeiro#blk-b1`).
- Switching page is a normal link/full reload — there's no page you need to
  "leave open"; just link to `?page=<name>` in your own chat output the same
  way you already link to `#blk-<id>`.

Use it to group by theme/workstream (e.g. "Financeiro", "Legal", "Operações")
once a single board is doing double or triple duty. Don't reach for it on
small boards — it adds visual structure only once there's enough content to
justify it.

## Rules of thumb

- Every interactive block needs a stable, unique `id` — you match events by it.
- Prefer a `checklist` over asking the user to type "done" in chat.
- Prefer `choice`/`approval` over open questions when the options are known.
- After every meaningful step, update the board — stale boards defeat the point.
- Leave the board in its final state at the end; it's the session's record.
- Set `meta.agent_status` ("working"/"waiting"/"idle") so the tab title/favicon/chip
  tell the human whose turn it is without them switching tabs to check.
- When something needs the human, echo the direct anchor link (`👉 URL#blk-<id>`)
  in your own chat output too — don't make them scroll pAInel to find it.
- Never leave a `change_request` unresolved — always flip its `status` to
  `"done"`/`"declined"` with a one-line reason once handled, and log the
  outcome. Resolving it only in chat doesn't count.
