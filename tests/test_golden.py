"""Golden page test: render the demo board and compare byte-for-byte against
tests/golden/demo.html. Update the golden file only via
`python -m tests.regen_golden` -- never by hand."""
import os
import unittest

from painel.__main__ import _demo_board
from painel.server import render

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden", "demo.html")


class GoldenPageTest(unittest.TestCase):
    def test_demo_board_matches_golden(self):
        with open(GOLDEN_PATH, "r", encoding="utf-8") as fh:
            expected = fh.read()
        actual = render(_demo_board())
        self.assertEqual(
            actual, expected,
            "Rendered demo board no longer matches tests/golden/demo.html. "
            "If this change is intentional, regenerate with: "
            "python -m tests.regen_golden",
        )


if __name__ == "__main__":
    unittest.main()
