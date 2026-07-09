"""
Regenerate tests/golden/demo.html from the current code.

Run with:  python -m tests.regen_golden

Prints a diff against the previous golden file (if any) and writes the new
one -- no interactive prompt. The diff appearing in the PR is the review:
never update the golden file "accidentally", only deliberately.
"""
from __future__ import annotations

import difflib
import os

from painel.__main__ import _demo_board
from painel.server import render

from ._golden_normalize import normalize

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden", "demo.html")


def main() -> int:
    # Normalized (see _golden_normalize.py): the M11 resources example bakes
    # in this machine's absolute repo path and a wall-clock-dependent
    # freshness string, neither of which belongs in a file committed to a
    # public repo or compared byte-for-byte days/months after regeneration.
    new_html = normalize(render(_demo_board()))

    old_html = None
    if os.path.exists(GOLDEN_PATH):
        with open(GOLDEN_PATH, "r", encoding="utf-8") as fh:
            old_html = fh.read()

    if old_html is not None and old_html != new_html:
        diff = difflib.unified_diff(
            old_html.splitlines(keepends=True),
            new_html.splitlines(keepends=True),
            fromfile="golden/demo.html (old)",
            tofile="golden/demo.html (new)",
        )
        print("".join(diff))
    elif old_html is None:
        print(f"no previous golden file -- writing {GOLDEN_PATH} for the first time")
    else:
        print("no change.")

    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as fh:
        fh.write(new_html)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
