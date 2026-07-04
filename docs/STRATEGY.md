# pAInel — strategy: from dev tool to the interface for non-technical AI work

*Last revised: 2026-07-04. Companion to [MONETIZATION.md](../MONETIZATION.md).*

## 1. Where the project actually stands

Honest inventory, one week in:

- **Working core** (~650 lines, stdlib only): 10 block types, steerable plan
  (play/edit/skip/reorder), per-step discussion threads, unread badges, a
  sticky "waiting on you" attention bar, smart auto-refresh that never eats
  your typing.
- **CLI**: `painel open` — one idempotent command; pid/log bookkeeping done.
- **Integrations**: Claude Code skill + Cursor and Aider guides.
- **Distribution**: public on GitHub, demo GIF, MIT. Zero users beyond the
  author. That's not a weakness to hide — it's the stage where positioning is
  still free to change.

## 2. The strategic insight nobody in this space is acting on

Every tool in the "agent dashboard" niche (Conductor, Claudia, the kanban
boards, Claude Code Remote Control) serves **developers watching code**. The
fastest-growing population of agent users is the opposite: lawyers, managers,
accountants, researchers — people using Claude Code / Cowork for *work that
isn't code*. For them:

- The **terminal is a cliff**, not a tool. They can climb it once (install)
  but won't live there.
- The **chat log is where context goes to die**. They think in checklists,
  approvals and progress — exactly pAInel's block vocabulary.
- **Trust is the product.** They need to see what the agent plans to do,
  approve it in their words, and keep a record of what happened.

pAInel's block protocol is accidentally the right abstraction for this
audience: it speaks *task language* (plan, approve, do-this-manually), not
*tool language* (diff, tool-call, token). The strategic move is to stop
positioning pAInel as "a dashboard for your CLI agent" and start positioning
it as **"the way people who don't code work with AI agents."**

## 3. Strategic assets to build (moats, in priority order)

1. **The protocol as a mini-standard.** `board.json` + JSONL events is a
   task-level human-in-the-loop spec. Version it (`"v": 1`), document it as
   *the Board Protocol*, and ship adapters (Claude Code, Cursor, Aider, ACP →
   OpenCode/anything). If the format becomes how agents ask humans for
   task-level input, every client that renders it grows pAInel — even
   competitors'.
2. **Recipes (templates), localized.** A blank board is a dev tool; a recipe
   ("prepare my tax return", "vendor due-diligence", "month-end close",
   "plan a relocation") is a *product*. Recipes are just JSON — cheap to
   author, easy to community-source, and the natural marketplace later.
   Ship them in the user's language from day one (PT + EN first — the author
   is a native PT speaker; PT-BR alone is 200M+ people underserved by
   English-first AI tooling).
3. **The session record as an artifact.** Non-technical work needs proof:
   who approved what, what was decided, what the agent did. The board *is*
   that record. One-click export ("board → PDF/HTML report") turns every
   session into a shareable deliverable — and a viral loop (every exported
   report advertises pAInel).
4. **Manual-steps-as-first-class.** No competitor models "the human does
   step 3". This is the emotional hook of the demo and the feature to keep
   deepening (reminders, mobile ticks, evidence attachments: "photo of the
   signed form").
5. **pAInel Desktop (later, decisive).** For true non-tech reach the terminal
   must disappear: a double-clickable app that embeds an agent engine
   (Claude Agent SDK, or OpenCode via ACP for BYOK) where the board is the
   *only* interface. That's the "worldwide" unlock — and the piece that makes
   acquisition interesting (see §5). Build it only after the interface layer
   has proven demand.

## 4. Monetization — one certain path, staged

**Principle:** the open core (local server, all blocks, all integrations)
stays MIT forever. Money comes from *convenience and reach*, never from
gating the protocol.

### Stage A — from v1, this month, zero infrastructure
**GitHub Sponsors + a one-time "Founding supporter" license (€19–29) via
Polar/Lemon Squeezy.** What it buys today: early access to recipes as they
ship, name in SUPPORTERS.md, a vote on the roadmap. This is deliberately
small money — its real function is **signal**: every paying supporter is
evidence of willingness-to-pay you can show later (to yourself, and to
acquirers). No servers, no support burden, cancellable any time.

### Stage B — at traction (~500 stars or ~50 WAU), the real wedge
**pAInel Cloud, €6–9/mo solo:** a secure tunnel + PWA so the human can
answer/approve/tick **from their phone**, with push notifications when the
agent is blocked waiting. This is the feature the free local version
constantly advertises by its absence ("I left my desk and the agent sat
waiting for 2 hours"). Claude Code's Remote Control validates the demand but
does it at tool-call level (approve every command) — pAInel does it at task
level (approve the plan, tick the step). Teams tier (€15–20/user/mo: shared
boards, roles, audit) follows only if solo Cloud converts.

### Stage C — compounding
Recipe marketplace (rev-share on paid recipes), pro blocks (file upload,
signature, rich tables), enterprise (SSO, self-host support contract).

### Explicitly rejected
- Ads, telemetry-as-product: kills trust, kills acquisition value.
- Paywalling block types or integrations: kills the standard play.
- Per-token resale (running the models for users) at this stage: turns a
  lean project into a billing+abuse company overnight.

## 5. Being attractive for acquisition (Anthropic, OpenAI, Cursor, Zed…)

Acquirers won't buy 650 lines of Python — they'd rebuild it in a week. What
they *can't* rebuild cheaply, and therefore what to maximize:

1. **Adoption of the protocol.** If thousands of boards exist and other
   clients render the format, buying pAInel = buying the standard and its
   community. Keep the spec versioned, documented, and used by ≥3 agent
   integrations.
2. **The audience nobody has.** Document non-technical use cases obsessively
   (case studies, testimonials, the "recipes" people actually run). Every AI
   lab is trying to cross from developers to everyone; a project that already
   owns that bridge — however small — is strategic evidence.
3. **Usage insight.** Opt-in, privacy-respecting aggregate metrics (blocks
   used, recipe categories, approval latency). This is product intelligence
   about how normal humans supervise agents — genuinely scarce data. Opt-in
   only; the trust story is worth more than the data.
4. **Clean IP & brand.** Single copyright holder (you), MIT license, DCO for
   external contributions, trademark on "pAInel" name/logo, own GitHub org
   (move from personal repo when there's traction). An acquirer's lawyers
   should find nothing to untangle.
5. **A person worth hiring.** Acqui-hires are half of small acquisitions.
   Public building (posts, demos, the launch story "I built the missing
   interface for my own lost-in-chat problem") makes the founder legible.

**Positioning sentence for that audience:** *pAInel is the task-level
human-in-the-loop layer — the standard way agents ask humans for decisions,
manual steps and approvals, born where the users already are.*

## 6. Development plan

### Phase 0 — Foundations for the story (this week)
- [ ] Version the protocol: `"protocol": 1` in board.json, `docs/PROTOCOL.md`
      spec (blocks, events, extension rules).
- [ ] `pipx install painel` / publish to PyPI.
- [ ] README repositioning: lead with the non-technical story, comparison
      table vs Remote Control / Conductor / AG-UI.
- [ ] GitHub Sponsors + Polar "Founding supporter". (Stage A money on.)

### Phase 1 — Launch to the existing beachhead (weeks 2–3)
- [ ] Publish the Claude Code plugin/skill to the marketplace.
- [ ] Show HN + r/ClaudeAI + X thread; the GIF is the hero. Ship the same
      week the marketplace listing goes live.
- [ ] 5 starter recipes, EN + PT (tax prep checklist, contract review,
      month-end close, home move, content pipeline).
- [ ] Board → HTML/PDF report export (the artifact loop).

### Phase 2 — Prove the non-tech thesis (weeks 4–8)
- [ ] 10 real non-technical users observed (friends/family/network count).
      Measure: can they go from `painel open` to a completed recipe without
      help? Fix every stumble.
- [ ] Recipes gallery page (static site, links from README).
- [ ] ACP adapter experiment: drive a board from OpenCode headless. (This is
      the desktop-engine feasibility spike, timeboxed to a week.)
- **Go/no-go:** ≥500 stars or ≥50 weekly active boards or ≥20 founding
  supporters by end of month 2. If no signal: keep as OSS portfolio piece,
  stop investing beyond maintenance.

### Phase 3 — The wedge (months 3–4, only on go)
- [ ] pAInel Cloud MVP: tunnel + PWA + push. Solo tier only.
- [ ] pAInel Desktop prototype: Tauri/Electron shell, embedded engine
      (Agent SDK or OpenCode/ACP), board-only UX, recipes as the home screen.
- [ ] Move to GitHub org, trademark filing, DCO.

### Phase 4 — Scale what worked (months 5+)
- [ ] Whichever of Cloud/Desktop showed pull gets the focus; the other waits.
- [ ] Recipe marketplace beta; teams tier if pulled by users.

## 7. Risks, plainly

| Risk | Mitigation |
|------|------------|
| Anthropic ships a native task panel | Be agnostic (Cursor/Aider/ACP), own manual steps + recipes + the record — places a lab won't go soon |
| AG-UI becomes the HITL standard | AG-UI is for builders embedding agents in apps; pAInel is for *end users*. Different buyer. Bridge, don't fight: an AG-UI adapter is possible later |
| Non-tech users can't install Python | Phase 2 measures this honestly; Desktop (Phase 3) is the real answer; `pipx`/installer script is the interim |
| One-person bus factor | Small, boring codebase (stdlib!), DCO + docs from day 1 make adoption survivable |
| Motivation dies before signal | Phase gates are cheap and dated; Stage A money + public building create external accountability |
