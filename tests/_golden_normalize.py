"""
Shared normalization for the golden-page test (tests/test_golden.py) and its
regeneration script (tests/regen_golden.py).

M11 (docs/SPEC.md §15) introduced the first genuinely machine- and
time-dependent content into the demo board: the `resources` block example
points at this repo's own absolute path (§15.2's live-freshness example, see
painel/__main__.py's `_demo_board()`), and its freshness text ("atualizado
há Xd") drifts with wall-clock time. Both would make the golden file either
leak a local filesystem path (this is a public repo) or flake on every CI
run once enough time passes since regeneration. Normalize both away before
writing the golden file and before comparing against it, so everything else
in the page shell is still pinned byte-for-byte.
"""
from __future__ import annotations

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FRESH_RE = re.compile(r"atualizado (agora mesmo|h[áa] [^<]+|em \d{4}-\d{2}-\d{2})")


def normalize(html: str) -> str:
    html = html.replace(REPO_ROOT, "<REPO_ROOT>")
    html = _FRESH_RE.sub("atualizado <FRESH>", html)
    return html
