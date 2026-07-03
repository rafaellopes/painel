<div align="center">

# p<span>AI</span>nel

**The second interface for your CLI agent.**

Turn a long, scrolling chat with Claude Code (or any terminal agent) into an
organized, clickable dashboard — checkboxes for the manual steps *you* do,
questions with answer boxes, approval buttons, live progress. One file. No
dependencies. Works with any agent that can write JSON.

</div>

---

## The problem

Agentic coding tools are incredibly capable, but everything lives in one
scrolling conversation. On anything longer than a few steps you lose the thread:
*What's the plan? What did it decide? What is it waiting for me to do?*

Non-technical users feel this most. They can drive an agent, but the chat format
gives them nowhere to **see the state** or **act on it** without typing a reply
into the void.

## The idea

pAInel gives the agent a **second screen** next to the chat. The agent composes
the page out of **typed blocks**, and each block knows how to render itself and
what interaction it hands back:

| Block | What you see | What the agent gets back |
|-------|--------------|--------------------------|
| `checklist` | Checkboxes for **your** manual steps | An event the moment you tick one |
| `plan` | A steerable plan: ▶ play, ✎ edit, ⏭ skip, ▲▼ reorder each step | Jump the queue, rewrite a step, or drop it — live |
| `tasks` | The agent's own progress (done / doing / blocked) | — (read-only) |
| `question` | A prompt with a text box | Your typed answer |
| `choice` | A prompt with option buttons | The option you picked |
| `approval` | A proposal with Approve / Reject | Your decision + comment |
| `form` | Several labelled fields | The filled object |
| `markdown` / `note` / `heading` / `log` | Formatted context | — (read-only) |

The killer case: **the agent needs you to do something by hand** — log into a
portal, download a file, confirm a payment. It drops a `checklist`, keeps
working on everything else, and the instant you tick the box it continues. No
copy-pasting "done" into chat.

## How it works

```
┌─────────────┐   writes    ┌────────────┐   renders   ┌─────────┐
│  the agent  │ ──────────▶ │ board.json │ ──────────▶ │ browser │
└─────────────┘             └────────────┘             └─────────┘
       ▲                          ▲                          │
       │   one JSONL line per     │      you click / type    │
       └──────── interaction ◀────┴──────────────────────────┘
```

- **Input:** a `board.json` — an ordered list of typed blocks.
- **Output:** every interaction is written back into `board.json` **and** printed
  as one JSON line on stdout, so the agent can react in real time.

That's the whole protocol. Any agent that can write a JSON file and read stdout
lines can use pAInel.

## Quick start

Just Python 3 (standard library only, no runtime dependencies).

```bash
pip install -e .          # or: pipx install .  /  see "Installing" below
```

Then, in any project directory, **one command**:

```bash
painel open
```

That's it. First run creates `.painel-board.json` and opens the dashboard in
your browser. Run it again anytime — it's idempotent: if a board is already
running it just re-opens the tab instead of starting a second server. Useful
companions:

```bash
painel status   # is it running? where?
painel stop     # stop the server for this board
painel demo     # see every block type in a showcase board
```

No need to remember ports or ask your agent to start it for you.

Then point your agent at `board.json`. When someone interacts, the server prints
a line like:

```json
{"event":"check","block":"cl","item":"c1","checked":true}
{"event":"answer","block":"q1","value":"send it to ana@acme.com"}
{"event":"approve","block":"ap","decision":"approved","comment":"go ahead"}
```

## Using it inside Claude Code

pAInel ships with a Claude Code **skill** (`.claude/skills/painel/`). Drop it in
your project and the agent learns to:

1. Compose a `board.json` for the session,
2. Serve it and open it next to the chat,
3. Watch for your interactions and react — all on its own.

See [`.claude/skills/painel/SKILL.md`](.claude/skills/painel/SKILL.md).

## Installing

pAInel has zero runtime dependencies, but `pip install` on newer macOS/Homebrew
Python refuses system-wide installs (PEP 668). The clean way:

```bash
python3 -m venv ~/.painel-venv
~/.painel-venv/bin/pip install -e /path/to/painel
mkdir -p ~/.local/bin
ln -sf ~/.painel-venv/bin/painel ~/.local/bin/painel   # make sure ~/.local/bin is on PATH
```

Or, if you have `pipx`: `pipx install /path/to/painel`.

## Board schema

```json
{
  "title": "My session",
  "meta": { "project": "acme", "updated_at": "2026-07-02 21:00" },
  "blocks": [
    { "id": "h1", "type": "heading", "text": "What we're doing" },
    { "id": "m1", "type": "markdown", "text": "Goal: **migrate** the billing job." },
    { "id": "cl", "type": "checklist", "title": "Do these by hand", "items": [
      { "id": "c1", "text": "Log into the billing portal", "checked": false }
    ]},
    { "id": "tk", "type": "tasks", "title": "Progress", "items": [
      { "text": "Read config", "status": "done" },
      { "text": "Run migration", "status": "wip" }
    ]},
    { "id": "q1", "type": "question", "prompt": "Which environment?", "answer": null },
    { "id": "ap", "type": "approval", "prompt": "Deploy now?", "decision": null }
  ]
}
```

Task statuses: `done`, `wip`, `pending`, `blocked`.
Note tones: `info`, `ok`, `warn`, `danger`.

## Design principles

- **Zero dependencies.** One Python file you can read in ten minutes. It should
  run anywhere Python does, forever.
- **Agent-agnostic.** The protocol is just JSON in and JSONL out. Claude Code is
  the first integration, not the only one.
- **The human is a first-class actor.** Most agent UIs assume the agent does
  everything. pAInel is built around the moments a human has to step in.
- **No typing tax.** Ticking a box beats typing "ok done" — especially for
  non-technical users.

## Status

Early but working. v0.1 — the core protocol and all block types are implemented
and tested. Feedback and contributions welcome.

## License

MIT © Rafael Lopes
