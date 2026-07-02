# pAInel — fame & monetization strategy

The goal: become known for a **simple** tool that helps ordinary people run
complex work with coding agents in an organized, productive way. Monetization
should never compromise that story — the open core stays free, forever, MIT.

## Why this can spread

- **One sentence pitch:** *"a second screen for your AI agent — checkboxes for
  what you do, live progress for what it does."* People immediately get it.
- **Zero install friction.** One Python file, standard library only. That's the
  difference between "I'll try it later" and "it's running now."
- **Demo sells itself.** `python -m painel demo` → a screen recording of ticking
  a box and watching the agent continue is a great 20-second video for X /
  LinkedIn / Reddit r/ClaudeAI. Fame comes from the *clip*, not the README.
- **Rides the agent wave.** Claude Code, Cursor, Codex, Aider all have the same
  "lost in the chat" problem. Being agent-agnostic means every one of those
  communities is a potential audience.

## Growth plan (free core)

1. **Ship the repo** with a killer README, a GIF, and the `demo` command.
2. **Post the clip** where agent users hang out (r/ClaudeAI, X, HN "Show HN",
   the Claude Code / Cursor Discords). Lead with the manual-checkbox moment.
3. **Publish the Claude Code plugin/skill** to the marketplace as the reference
   integration — a second, warmer acquisition channel.
4. **Write the integration guides** (Cursor, Aider, plain shell) so other
   communities can adopt it without you.
5. **Encourage block contributions.** A healthy "here's a new block type" PR
   flow is what turns a tool into a project.

## Where the money is (without breaking the free promise)

The free tool is local, single-user, one board. The paid layer is everything a
**team** or **power user** needs once they rely on it:

| Tier | What you sell | Why people pay |
|------|---------------|----------------|
| **Free / OSS** | Local server, all block types, all integrations | Adoption engine. Never gated. |
| **pAInel Cloud** | Hosted boards with a shareable URL, so the human can approve/answer from their **phone** while the agent runs on a server or in CI | Removes "must be at my machine". Huge for long/remote runs. |
| **Teams** | Multiple people on one board, roles, who-approved-what audit log, SSO | Agencies & teams running agents for clients. |
| **Pro blocks** | Richer blocks: file upload/preview, image annotate, signature, payment confirm, rich tables, charts | Real workflows need real inputs. |
| **Templates marketplace** | Curated board templates for common jobs (month-end close, migration runbook, content pipeline) + a cut on paid ones | Non-technical users want a starting point, not a blank board. |
| **Notifications** | Push/SMS/WhatsApp when the agent is blocked on you | "Tell me on my phone when it needs me" is worth paying for. |

Pricing intuition: free forever locally; **Cloud** ~$8–12/mo solo, **Teams**
~$15–20/user/mo. Sponsorship (GitHub Sponsors) from day one for goodwill.

## The wedge

Start narrow and sharp: **"the agent asks you to do a manual step, and you tick
it off from your phone."** That single flow — remote, mobile, checkbox — is the
paid feature people will reach for first, and it's the natural upsell from the
free local checklist. Everything else (teams, marketplace, pro blocks) is
expansion once that wedge lands.

## What to protect

- Keep the **protocol open and documented** (board.json + JSONL). If the format
  is a de-facto standard, pAInel wins even where someone else builds a client.
- Keep the **local experience excellent and unlimited.** The moment free feels
  crippled, the fame story dies. Monetize *reach* (cloud, mobile, team), not the
  core capability.
