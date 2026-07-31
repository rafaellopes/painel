# Changelog

All notable changes to pAInel are recorded here. Versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased

- **Board export (M3, §24)** — every live board page gains an **Export** link
  (footer) that downloads a self-contained static HTML snapshot: `GET /export`
  (single-board) / `GET /<slug>/export` (service). One file, opens from disk
  with **zero network requests** — inline CSS, no JS, all pages flattened,
  images inlined as `data:` URIs through the same §22.3 containment, plus a
  report section with open change requests and the event log. Print-friendly
  (`@media print`). It is a render *mode* reusing the live block pipeline, never
  a second renderer; zero dependencies.

## 0.2.0 — first PyPI release

- **Published to PyPI** — `pipx install painel` / `pip install painel` now work
  (previously clone + editable install only). Publishing uses PyPI Trusted
  Publishing (GitHub Actions OIDC) with no stored token.
- `painel --version` prints the installed version.
- Requires Python 3.10+ (matching the supported/tested matrix).
- Bundles everything since 0.1.0 — blocks and features **M13–M18**: the unified
  service, navigation shell, `upload` block, block-choice lint, adaptive layout
  & phase-awareness, and the `image` block.

## 0.1.0

- Initial version: core protocol and all block types implemented and tested.
