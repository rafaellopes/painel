# Changelog

All notable changes to pAInel are recorded here. Versions follow
[Semantic Versioning](https://semver.org/).

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
