"""Board export tests (M3, docs/SPEC.md §24).

Pins every acceptance clause from the M3 milestone row:
- `GET /export` returns HTML with `Content-Disposition: attachment`;
- the exported HTML contains NO `<script>` and NO external URL (no
  `http(s)` src/href to a network resource; `data:` is fine) -- i.e. zero
  network requests when opened from disk;
- a multi-page board exports all pages in order;
- answered question states, open change-request threads and the event-log
  table are all present;
- a `collapsed` block appears expanded in the export;
- no interactive control (✎, submit button, upload zone, request-change
  affordance) appears in the export output;
- a project-relative image is inlined as a `data:` URI; an image escaping
  the project dir or of a non-image extension is NOT embedded (alt fallback);
- a board using none of image/collapsed/pages still exports and is well-formed;
- backward-compat: the LIVE (non-export) page renders exactly as before.

Served by a real handler on a random loopback port over a temp-dir board,
same style as tests/test_m18.py -- never touches the user's real state.
"""
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from painel import server as srv

# A minimal but valid 1x1 PNG (same bytes test_m18 uses).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da6360000002000155a2b4ec00000000"
    "49454e44ae426082"
)
_SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='4' height='4'/></svg>"

XSS = '"<script>alert(1)</script>'


def _body(html: str) -> str:
    """Markup region only (after </style>), so the shared CSS doesn't confound
    content assertions -- the export shell has no <script> region at all."""
    return html.split("</style>", 1)[1]


def _write_board(d: str, board: dict, log_lines=None) -> str:
    path = os.path.join(d, "board.json")
    srv.save_board(path, board)
    if log_lines:
        import json
        with open(path + ".log", "w", encoding="utf-8") as fh:
            for ev in log_lines:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def _rich_board() -> dict:
    """A board exercising every export-relevant feature: two pages, an answered
    question, an open question, a collapsed block, a checklist, an upload with
    a listed file, an inline data: image and a project-relative image."""
    return {
        "title": "My Session",
        "meta": {"project": "demo", "updated_at": "2026-07-31"},
        "change_requests": [
            {"id": "cr1", "block": "q1", "item": None,
             "text": "please revisit the estimate", "status": "open", "ts": ""},
            {"id": "cr2", "block": None, "item": None,
             "text": "already handled", "status": "closed", "ts": ""},
        ],
        "blocks": [
            {"id": "q1", "type": "question", "prompt": "Ship it?",
             "answer": "yes, on Friday"},
            {"id": "q2", "type": "question", "prompt": "Second call?",
             "answer": None},
            {"id": "col", "type": "markdown", "text": "hidden detail body",
             "title": "Notes", "collapsed": True},
            {"id": "cl", "type": "checklist", "title": "Manual steps", "items": [
                {"id": "i1", "text": "login done", "checked": True},
                {"id": "i2", "text": "download report", "checked": False},
            ]},
            {"id": "up1", "type": "upload", "prompt": "drop the file",
             "files": [{"name": "a.png", "path": "/x/a.png", "size": 10}]},
            {"id": "imgd", "type": "image",
             "src": "data:image/svg+xml;base64,PHN2Zy8+", "alt": "inline fig"},
            {"id": "imgf", "type": "image", "src": "painel-assets/chart.svg",
             "alt": "the chart", "page": "Details"},
            {"id": "md2", "type": "markdown", "text": "second page body",
             "page": "Details"},
        ],
    }


class RenderExportUnitTest(unittest.TestCase):
    """render_export() over a temp-dir board -- no HTTP."""

    def _prep(self, d):
        path = _write_board(
            d, _rich_board(),
            log_lines=[
                {"event": "answer", "block": "q1", "value": "yes, on Friday"},
                {"event": "check", "block": "cl", "item": "i1", "value": True},
            ],
        )
        os.makedirs(os.path.join(d, "painel-assets"))
        with open(os.path.join(d, "painel-assets", "chart.svg"), "wb") as fh:
            fh.write(_SVG)
        return path

    def test_no_script_and_no_external_url(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._prep(d)
            html = srv.render_export(srv.load_board(path), path)
            self.assertNotIn("<script", html)
            # No network-triggering URL: data: is fine, a namespace string
            # buried inside a data: URI is not a fetch.
            self.assertNotIn('src="http', html)
            self.assertNotIn('href="http', html)
            self.assertNotIn('src="//', html)
            self.assertNotIn("url(http", html)

    def test_all_pages_in_order(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._prep(d)
            body = _body(srv.render_export(srv.load_board(path), path))
            self.assertIn("My Session", body)   # Home heading (board title)
            self.assertIn("Details", body)       # second page heading
            self.assertLess(body.index("My Session"), body.index("Details"))
            # A block on the second page appears after that heading.
            self.assertLess(body.index("Details"), body.index("second page body"))

    def test_answered_state_and_open_thread_and_log_present(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._prep(d)
            body = _body(srv.render_export(srv.load_board(path), path))
            self.assertIn("yes, on Friday", body)          # answered question
            self.assertIn("Awaiting answer", body)          # open question state
            self.assertIn("please revisit the estimate", body)  # open change req
            self.assertNotIn("already handled", body)       # closed one excluded
            self.assertIn("Event log", body)                # log section
            self.assertIn("<table", body)                   # log table

    def test_collapsed_block_is_expanded(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._prep(d)
            body = _body(srv.render_export(srv.load_board(path), path))
            self.assertNotIn('details class="blk-collapse"', body)  # not folded
            self.assertIn("hidden detail body", body)               # content shown

    def test_no_interactive_control(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._prep(d)
            body = _body(srv.render_export(srv.load_board(path), path))
            for token in ("onclick", "onchange", "ondrop", "<textarea", "<input",
                          "<button", "<select", "crToggle", "upload-zone",
                          "cr-box", "Request a change"):
                self.assertNotIn(token, body, f"interactive token leaked: {token}")

    def test_project_relative_image_inlined_as_data_uri(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._prep(d)
            body = _body(srv.render_export(srv.load_board(path), path))
            # The .svg file is embedded as a base64 data: URI, not an /asset URL.
            self.assertIn("src=\"data:image/svg+xml;base64,", body)
            self.assertNotIn("/asset?p=", body)
            # And the pre-supplied data: image passes through.
            self.assertIn("data:image/svg+xml;base64,PHN2Zy8+", body)

    def test_escaping_and_non_image_not_embedded_alt_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            board = {"title": "t", "blocks": [
                {"id": "esc", "type": "image", "src": "../../etc/passwd",
                 "alt": "escapes the project"},
                {"id": "txt", "type": "image", "src": "painel-assets/notes.txt",
                 "alt": "not an image"},
            ]}
            path = _write_board(d, board)
            os.makedirs(os.path.join(d, "painel-assets"))
            with open(os.path.join(d, "painel-assets", "notes.txt"), "wb") as fh:
                fh.write(b"secret")
            body = _body(srv.render_export(srv.load_board(path), path))
            self.assertIn("img-fallback", body)             # alt fallback shown
            self.assertIn("escapes the project", body)
            self.assertIn("not an image", body)
            self.assertNotIn("data:", body)                 # nothing embedded
            self.assertNotIn("passwd", body)
            self.assertNotIn("secret", body)                # out-of-scope bytes never in

    def test_minimal_board_exports_well_formed(self):
        """A board using none of image/collapsed/pages still exports."""
        with tempfile.TemporaryDirectory() as d:
            board = {"title": "Plain", "blocks": [
                {"id": "m", "type": "markdown", "text": "just text"},
                {"id": "n", "type": "note", "tone": "info", "text": "a note"},
            ]}
            path = _write_board(d, board)
            html = srv.render_export(srv.load_board(path), path)
            self.assertTrue(html.startswith("<!doctype html>"))
            self.assertTrue(html.rstrip().endswith("</html>"))
            self.assertNotIn("<script", html)
            self.assertIn("just text", html)
            self.assertIn("Plain", html)


class BackwardCompatTest(unittest.TestCase):
    def test_live_page_unchanged_by_export_branches(self):
        """The interactive-block export branches must never leak into the LIVE
        render: a live page keeps its inputs/buttons exactly as before."""
        board = {"title": "t", "blocks": [
            {"id": "q", "type": "question", "prompt": "why?", "answer": None},
            {"id": "cl", "type": "checklist", "items": [
                {"id": "i1", "text": "do it", "checked": False}]},
            {"id": "up", "type": "upload", "prompt": "drop"},
        ]}
        html = srv.render(board)
        self.assertIn('onclick="answer(', html)       # question submit intact
        self.assertIn('type="checkbox"', html)         # checklist input intact
        self.assertIn("upload-zone", html)             # upload drop zone intact
        self.assertIn("/export", html)                 # footer export link added


class ExportEndpointTest(unittest.TestCase):
    def _serve(self, board_path):
        srv._Handler.board_path = board_path
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd, t, port

    def _get(self, port, path):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read(), ex.headers

    def test_export_endpoint_downloads_html(self):
        with tempfile.TemporaryDirectory() as d:
            proj = os.path.join(d, "myproject")
            os.makedirs(os.path.join(proj, "painel-assets"))
            path = _write_board(
                proj, _rich_board(),
                log_lines=[{"event": "answer", "block": "q1", "value": "yes"}])
            with open(os.path.join(proj, "painel-assets", "chart.svg"), "wb") as fh:
                fh.write(_SVG)
            httpd, t, port = self._serve(path)
            try:
                status, body, headers = self._get(port, "/export")
            finally:
                httpd.shutdown(); t.join(); httpd.server_close()
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Content-Type"), "text/html; charset=utf-8")
            self.assertIn("attachment", headers.get("Content-Disposition", ""))
            # Filename is the project dirname (single-board, §24.1).
            self.assertIn('filename="myproject.html"', headers.get("Content-Disposition", ""))
            text = body.decode("utf-8")
            self.assertNotIn("<script", text)
            self.assertNotIn('src="http', text)
            self.assertIn("data:image/svg+xml;base64,", text)  # asset inlined


if __name__ == "__main__":
    unittest.main()
