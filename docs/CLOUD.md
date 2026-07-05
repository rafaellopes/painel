# pAInel Cloud — design (not yet built)

**Status: design only.** This document specifies the paid wedge described in
[MONETIZATION.md](../MONETIZATION.md) (Stage B) and
[STRATEGY.md](STRATEGY.md) §6 Phase 3. Do not implement until the Phase 2
go/no-go gate is met (§6 of STRATEGY.md: ≥500 stars OR ≥50 weekly active
boards OR ≥20 founding supporters). Written now, on request, so the design
work doesn't block on the gate — only the build does.

## 1. The one job it does

*"I stepped away from my desk. The agent hit something only I can decide.
I want to see it and answer from my phone, right now, without SSH-ing back
in."*

Nothing else. Cloud is not a rewrite, not a new UI, not a hosted agent
runtime. It is a **relay** that makes the exact same local `board.json` +
event protocol reachable from a phone, plus a push notification so the
human doesn't have to keep the tab open.

## 2. Why this, not something else

- The local pAInel already computes *everything needed*: `_needs_user()`,
  `meta.agent_status`, the whose-turn signal (M5). Cloud doesn't add
  product surface — it adds **reach** to product surface that exists.
- Claude Code's own Remote Control (see STRATEGY.md §3) proves demand for
  "control from phone" but works at tool-call level (approve every
  command). pAInel Cloud stays at **task level** (approve the plan, tick
  the checklist item, answer the question) — different, complementary,
  not a feature race with Anthropic.
- Keeping it a relay (not a rewrite) means the free local core stays
  exactly as-is; Cloud is additive infrastructure, not a fork.

## 3. Architecture

```
┌─────────────┐        outbound WSS         ┌──────────────────┐        HTTPS         ┌────────────┐
│ painel serve │ ───────────────────────────▶│  relay (hosted)   │◀──────────────────── │  phone PWA │
│ (localhost)  │◀───────────────────────────  │  1 process/board  │ ──────────────────▶ │            │
└─────────────┘   events + board snapshots    └──────────────────┘   commands + polls    └────────────┘
                                                       │
                                                       ▼
                                              Web Push (VAPID)
```

- **Local side (`painel cloud` subcommand, new):** the existing `serve`
  process gains an optional outbound WebSocket connection to the relay.
  No inbound port opens on the user's machine — this is the same trust
  model as ngrok/Tailscale Funnel/Cloudflare Tunnel: outbound-only,
  nothing to firewall, nothing for a non-technical user to configure.
  Reuses the exact same `render()`/`_apply()` functions already in
  `server.py` — the relay just forwards bytes, it does not re-implement
  block rendering.
- **Relay (the one piece of new infrastructure):** a small stateless
  process (could be a single Cloudflare Worker + Durable Object per
  active board, or a tiny Fly.io/Hetzner box — infra choice deferred to
  build time) that:
  1. Authenticates the local `painel serve` connection with a per-board
     token (generated locally on first `painel cloud` run, never
     transmitted in plaintext, rotated on demand via `painel cloud
     rotate-token`).
  2. Authenticates the phone via a short-lived signed link (magic link,
     no password — matches "zero friction" ethos) or a paired PWA
     install (QR code shown by `painel cloud`, scanned once).
  3. Relays `/event` POSTs from phone → local process, and rendered
     board HTML / `/version` payloads local → phone.
  4. Sends a Web Push notification when the local process reports a
     `pending: 0 → N` transition (the exact same signal M5 already
     computes for the browser `Notification` — Cloud just also fires it
     server-side so it works even with the PWA closed).
- **Phone side:** an installable PWA (not a native app — no App
  Store review cycle, no per-platform build). Renders the same HTML
  the local server would, fetched through the relay. Push notifications
  via the standard Web Push API (works installed-to-homescreen on iOS
  16.4+ and Android Chrome).

## 4. Why WebSocket relay over the alternatives

| Option | Verdict |
|---|---|
| Expose local server directly (port-forward) | Rejected — the whole point is zero networking setup for non-technical users, and it's a security hazard by default |
| Generic tunnel (ngrok/Tailscale/Cloudflare Tunnel) the user runs themselves | Viable **stopgap** for technical users right now (document as a manual recipe in the meantime — zero code needed), but not the product: still requires an account + CLI setup, defeats "zero friction" |
| Full server-side board hosting (relay stores/owns board state) | Rejected — breaks "local is the source of truth"; also turns a lean relay into a database+auth+billing system prematurely |
| **Outbound-only relay, local process stays authoritative** (chosen) | Matches existing trust model, smallest new surface, board.json never leaves the user's machine except as relayed bytes in transit |

## 5. Protocol additions (additive to SPEC.md v1, no breaking changes)

```jsonc
// New CLI-managed file, sibling to <board>.json, never committed:
// <board>.json.cloud  — { "relay_url": "...", "board_token": "...", "paired_at": "..." }
```

- No changes to `board.json` itself or the event envelope (§3.3 of
  SPEC.md). The relay is transport, not protocol — same events, same
  block contract, same `needs_user()`/`agent_status` semantics travel
  over it unchanged.
- New CLI surface (implement only at build time, spec'd here for
  continuity with SPEC.md's milestone style):
  - `painel cloud` — pair this board (prints QR/link), starts relaying.
  - `painel cloud status` — connected? relay URL? paired devices?
  - `painel cloud unpair` — revoke a device/token.

## 6. Security & trust (non-negotiable before shipping, not before designing)

- Board content is **not** stored server-side beyond in-flight relay
  buffering — no board database. If the relay process restarts, it just
  reconnects; the local process remains the source of truth.
- Per-board token, not per-user account, for v1 — lower friction, smaller
  attack surface (compromise of one token exposes one board, not an
  account). Revocable any time via `painel cloud unpair`.
- TLS everywhere (relay↔local, relay↔phone). No custom crypto — standard
  WSS/HTTPS.
- Rate limits on the relay (per-token) to prevent abuse of someone else's
  relayed board if a token leaks.
- Explicit non-goal for v1: multi-user boards / roles / SSO. That's the
  **Teams** tier (STRATEGY.md §4 Stage C), a separate, later design.

## 7. What Cloud does NOT change

- No new block types required for Cloud itself (existing blocks render
  fine on a phone viewport — the page shell is already responsive per
  SPEC.md §11's mobile nav collapse from M6).
- No change to the free local experience. `painel open`/`serve` behave
  identically with or without `painel cloud` ever having been run.
- No server-side agent execution. The agent (Claude Code or whatever)
  keeps running locally; Cloud only relays the human's side of the
  conversation.

## 8. Pricing tie-in (from STRATEGY.md §4, restated for build reference)

Solo tier ~€6–9/mo: one paired phone, unlimited boards, push notifications.
Teams tier (later, not v1): shared boards, roles, audit log, ~€15–20/user/mo.
Free tier keeps zero Cloud features — this is the entire paid product
surface for the "reach" wedge; nothing about the local experience is ever
gated.

## 9. Build plan (do not start until the Phase 2 gate is met)

1. Relay MVP: single-tenant WebSocket relay (Cloudflare Worker or small
   VPS process), one board, one paired device. No billing yet.
2. `painel cloud` CLI command wired to it; QR pairing flow.
3. PWA shell: service worker for push, manifest, installable, renders the
   relayed board (can literally reuse `page.py`'s HTML/CSS — no separate
   frontend codebase).
4. Web Push wiring on the pending-transition signal (reuse M5's exact
   detection logic server-side instead of client-side `document.hidden`
   check).
5. Billing (Stripe or Polar, matching the Founding Supporter mechanism
   already in place) gate on the relay once the MVP is validated with a
   handful of real users (friends/family, same cohort as STRATEGY.md's
   Phase 2 non-technical user tests).
6. Security review pass (token rotation, rate limits, TLS config) before
   any public announcement of the paid tier.

## 10. Open questions to resolve at build time (not now)

- Exact relay hosting choice (Cloudflare Workers+DO vs. small VPS) —
  depends on real load patterns once there are users, not guessable now.
- Whether the magic-link or QR-pairing auth flow tests better with actual
  non-technical users (Phase 2's 10-user cohort is the right place to
  learn this, not a design-desk decision).
- Whether iOS PWA push reliability (historically spottier than Android)
  forces an earlier-than-planned native wrapper (Capacitor) — watch this,
  don't pre-solve it.
