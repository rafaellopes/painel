"""The `image` block tests (M18, docs/SPEC.md §22).

Pins every acceptance clause from the M18 milestone row:
- additive: a board with no `image` renders byte-identically to before;
- a project-relative `src` renders through the contained `…/asset?p=` endpoint
  with the correct image Content-Type (real handler, random loopback port,
  temp-dir board);
- a `src` escaping the project dir → 404, NO bytes;
- a non-image extension → 404 (not a generic file server);
- a remote `http(s)` `src` is refused and shows the alt fallback, never fetched;
- a `data:` src renders inline with no endpoint hit;
- an `image` nested in a `group:columns` renders and its alt/caption are
  `e()`-escaped (M17 integration);
- SVG served as `image/svg+xml`.
"""
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from painel import server as srv
from painel.blocks import image

XSS = '"<script>alert(1)</script>'

# A minimal but valid 1x1 PNG (the smallest real bytes worth serving).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da6360000002000155a2b4ec00000000"
    "49454e44ae426082"
)


def _body_markup(html: str) -> str:
    """Markup region only (after <style>, before <script>), so CSS/JS mentions
    of the generic class names don't confound content assertions."""
    return html.split("</style>", 1)[1].split("<script>")[0]


# --------------------------------------------------------------------------- #
# Additive / backward-compat guard                                             #
# --------------------------------------------------------------------------- #
class BackwardCompatTest(unittest.TestCase):
    def test_board_without_image_is_byte_identical(self):
        """A board that uses no `image` block must render exactly as it would
        have before M18 -- the whole additive contract. Compared against a
        render produced with the `image` type removed from the registry."""
        board = {"title": "t", "blocks": [
            {"id": "m1", "type": "markdown", "text": "hello"},
            {"id": "n1", "type": "note", "tone": "info", "text": "world"},
            {"id": "q1", "type": "question", "prompt": "why?", "answer": None},
        ]}
        with_image = srv.render(board)
        saved = srv.REGISTRY.pop("image")
        try:
            without_image = srv.render(board)
        finally:
            srv.REGISTRY["image"] = saved
        self.assertEqual(with_image, without_image)


# --------------------------------------------------------------------------- #
# Rendering (§22.4) -- pure block-level, no endpoint                           #
# --------------------------------------------------------------------------- #
class RenderTest(unittest.TestCase):
    def test_project_relative_src_becomes_asset_url(self):
        html = image.render(
            {"id": "i", "type": "image", "src": "painel-assets/chart.svg",
             "alt": "a chart"}, {"base_path": ""})
        self.assertIn('src="/asset?p=painel-assets%2Fchart.svg"', html)
        self.assertIn('alt="a chart"', html)
        self.assertIn('loading="lazy"', html)
        self.assertIn('<figure class="card img-block">', html)

    def test_asset_url_respects_base_path_under_service(self):
        html = image.render(
            {"id": "i", "type": "image", "src": "painel-assets/x.png", "alt": "x"},
            {"base_path": "/myproj"})
        self.assertIn('src="/myproj/asset?p=painel-assets%2Fx.png"', html)

    def test_data_uri_is_inlined_verbatim_escaped(self):
        data = "data:image/svg+xml;utf8,<svg></svg>"
        html = image.render(
            {"id": "i", "type": "image", "src": data, "alt": "d"}, {"base_path": ""})
        # No endpoint URL; the data: URI is inlined (escaped as an attribute).
        self.assertNotIn("/asset?p=", html)
        self.assertIn("data:image/svg+xml", html)
        self.assertIn("&lt;svg&gt;", html)  # angle brackets escaped in attr

    def test_remote_http_src_is_refused_with_alt_fallback(self):
        html = image.render(
            {"id": "i", "type": "image", "src": "https://evil.example/pixel.png",
             "alt": "should show as text"}, {"base_path": ""})
        self.assertNotIn("evil.example", html)       # never emitted, never fetched
        self.assertNotIn("<img", html)               # no <img> that would load it
        self.assertIn("img-fallback", html)
        self.assertIn("should show as text", html)
        self.assertIn("remote src refused", html)

    def test_protocol_relative_remote_src_is_refused(self):
        html = image.render(
            {"id": "i", "type": "image", "src": "//evil.example/x.png", "alt": "a"},
            {"base_path": ""})
        self.assertNotIn("evil.example", html)
        self.assertIn("img-fallback", html)

    def test_missing_src_shows_alt_fallback_not_broken_glyph(self):
        html = image.render(
            {"id": "i", "type": "image", "alt": "no source"}, {"base_path": ""})
        self.assertIn("img-fallback", html)
        self.assertIn("no source", html)
        self.assertNotIn("<img", html)

    def test_max_width_and_fit_applied(self):
        html = image.render(
            {"id": "i", "type": "image", "src": "painel-assets/x.png", "alt": "x",
             "max_width": "300px", "fit": "cover"}, {"base_path": ""})
        self.assertIn("max-width:300px", html)
        self.assertIn("object-fit:cover", html)

    def test_caption_rendered_as_inline_md(self):
        html = image.render(
            {"id": "i", "type": "image", "src": "painel-assets/x.png", "alt": "x",
             "caption": "**bold** cap"}, {"base_path": ""})
        self.assertIn("<figcaption", html)
        self.assertIn("<strong>bold</strong>", html)

    def test_alt_and_caption_escaped(self):
        html = image.render(
            {"id": "i", "type": "image", "src": "painel-assets/x.png",
             "alt": XSS, "caption": XSS}, {"base_path": ""})
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_read_only_contract(self):
        b = {"id": "i", "type": "image", "src": "x.png", "alt": "x"}
        self.assertFalse(image.apply(b, {"event": "anything"}))
        self.assertEqual(image.needs_user(b), [])
        self.assertEqual(image.SILENT_EVENTS, set())
        self.assertEqual(image.JS, "")


# --------------------------------------------------------------------------- #
# M17 integration: an image inside a group:columns                             #
# --------------------------------------------------------------------------- #
class GroupIntegrationTest(unittest.TestCase):
    def test_image_in_columns_group_renders_and_escapes(self):
        board = {"blocks": [
            {"id": "g", "type": "group", "layout": "columns", "title": "fig", "blocks": [
                {"id": "img", "type": "image", "src": "painel-assets/c.png",
                 "alt": XSS, "caption": XSS},
                {"id": "txt", "type": "markdown", "text": "reads the figure"},
            ]},
        ]}
        html = srv.render(board)
        body = _body_markup(html)
        self.assertIn("group-cols", body)
        self.assertIn('<div id="blk-img">', body)          # nested wrapper present
        self.assertIn("img-block", body)
        self.assertIn("/asset?p=painel-assets%2Fc.png", body)
        self.assertNotIn("<script>alert(1)</script>", html)  # alt/caption escaped

    def test_image_block_css_present_in_page(self):
        css = srv.render({"blocks": []}).split("<style>")[1].split("</style>")[0]
        self.assertIn(".img-block", css)
        self.assertIn(".group-cols .img-block img", css)


# --------------------------------------------------------------------------- #
# read_asset() unit — the containment core (§22.3), no HTTP                     #
# --------------------------------------------------------------------------- #
class ReadAssetUnitTest(unittest.TestCase):
    def _board(self, d):
        path = os.path.join(d, "board.json")
        srv.save_board(path, {"blocks": []})
        return path

    def test_reads_contained_image(self):
        with tempfile.TemporaryDirectory() as d:
            board = self._board(d)
            os.makedirs(os.path.join(d, "painel-assets"))
            with open(os.path.join(d, "painel-assets", "x.png"), "wb") as fh:
                fh.write(_PNG_1x1)
            content, ctype = srv.read_asset(board, "painel-assets/x.png")
            self.assertEqual(content, _PNG_1x1)
            self.assertEqual(ctype, "image/png")

    def test_escaping_path_refused_no_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            board = self._board(d)
            content, ctype = srv.read_asset(board, "../../etc/passwd")
            self.assertIsNone(content)
            self.assertIsNone(ctype)

    def test_non_image_extension_refused(self):
        with tempfile.TemporaryDirectory() as d:
            board = self._board(d)  # board.json exists and IS inside the project
            content, ctype = srv.read_asset(board, "board.json")
            self.assertIsNone(content)  # exists + contained, but not an image
            self.assertIsNone(ctype)

    def test_svg_content_type(self):
        with tempfile.TemporaryDirectory() as d:
            board = self._board(d)
            with open(os.path.join(d, "d.svg"), "wb") as fh:
                fh.write(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
            content, ctype = srv.read_asset(board, "d.svg")
            self.assertEqual(ctype, "image/svg+xml")

    def test_missing_file_refused(self):
        with tempfile.TemporaryDirectory() as d:
            board = self._board(d)
            self.assertEqual(srv.read_asset(board, "painel-assets/nope.png"), (None, None))


# --------------------------------------------------------------------------- #
# The served endpoint over a real handler on a random loopback port            #
# --------------------------------------------------------------------------- #
class AssetEndpointTest(unittest.TestCase):
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
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_serves_png_with_content_type_and_no_store(self):
        with tempfile.TemporaryDirectory() as d:
            board = os.path.join(d, "board.json")
            srv.save_board(board, {"blocks": []})
            os.makedirs(os.path.join(d, "painel-assets"))
            with open(os.path.join(d, "painel-assets", "x.png"), "wb") as fh:
                fh.write(_PNG_1x1)
            httpd, t, port = self._serve(board)
            try:
                status, body, headers = self._get(port, "/asset?p=painel-assets%2Fx.png")
            finally:
                httpd.shutdown(); t.join(); httpd.server_close()
            self.assertEqual(status, 200)
            self.assertEqual(body, _PNG_1x1)
            self.assertEqual(headers.get("Content-Type"), "image/png")
            self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_svg_served_as_svg_xml(self):
        with tempfile.TemporaryDirectory() as d:
            board = os.path.join(d, "board.json")
            srv.save_board(board, {"blocks": []})
            svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>x()</script></svg>"
            with open(os.path.join(d, "fig.svg"), "wb") as fh:
                fh.write(svg)
            httpd, t, port = self._serve(board)
            try:
                status, body, headers = self._get(port, "/asset?p=fig.svg")
            finally:
                httpd.shutdown(); t.join(); httpd.server_close()
            self.assertEqual(status, 200)
            # Served as image/svg+xml -- as an <img> subresource the browser
            # neuters the script (§22.3.3); we pin the Content-Type here.
            self.assertEqual(headers.get("Content-Type"), "image/svg+xml")
            self.assertEqual(body, svg)

    def test_escape_returns_404_no_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            board = os.path.join(d, "board.json")
            srv.save_board(board, {"blocks": []})
            httpd, t, port = self._serve(board)
            try:
                status, body, _ = self._get(port, "/asset?p=..%2F..%2F..%2Fetc%2Fpasswd")
            finally:
                httpd.shutdown(); t.join(); httpd.server_close()
            self.assertEqual(status, 404)
            self.assertNotIn(b"root:", body)  # no /etc/passwd bytes leaked

    def test_non_image_extension_returns_404(self):
        with tempfile.TemporaryDirectory() as d:
            board = os.path.join(d, "board.json")
            srv.save_board(board, {"blocks": []})
            httpd, t, port = self._serve(board)
            try:
                # board.json exists and is contained, but is not an image.
                status, _, _ = self._get(port, "/asset?p=board.json")
            finally:
                httpd.shutdown(); t.join(); httpd.server_close()
            self.assertEqual(status, 404)

    def test_missing_asset_returns_404(self):
        with tempfile.TemporaryDirectory() as d:
            board = os.path.join(d, "board.json")
            srv.save_board(board, {"blocks": []})
            httpd, t, port = self._serve(board)
            try:
                status, _, _ = self._get(port, "/asset?p=painel-assets%2Fnope.png")
            finally:
                httpd.shutdown(); t.join(); httpd.server_close()
            self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
