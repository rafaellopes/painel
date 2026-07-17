"""The unified service (M13, docs/SPEC.md §17): one process serving every
registered project, addressed by slug.

Follows the same fake-HOME pattern as tests.test_main so real ~/.painel state
(and the author's real running service) is never touched.

The most important test in this file -- arguably in the suite -- is
PerBoardLogContractTest: §17.2.2's contract that an event posted to one board
lands in THAT board's own <board>.log and in no other's. If that breaks, every
agent tailing a board is silently broken, which is the whole product.
"""
import json
import os
import socket
import tempfile
import threading
import unicodedata
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from painel import __main__ as cli
from painel import directory as dir_mod
from painel import registry
from painel import server as srv
from painel.server import save_board


class _FakeHomeMixin:
    def setUp(self):
        self._tmp_home = tempfile.TemporaryDirectory()
        self._orig_expanduser = os.path.expanduser
        home = self._tmp_home.name

        def fake_expanduser(path):
            return path.replace("~", home, 1) if path.startswith("~") else self._orig_expanduser(path)

        os.path.expanduser = fake_expanduser
        self.addCleanup(setattr, os.path, "expanduser", self._orig_expanduser)
        self.addCleanup(self._tmp_home.cleanup)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _project(self, dirname, project=None, blocks=None, title=None):
        """Create a real project directory with a real board, return its path."""
        d = os.path.join(self._tmp.name, dirname)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, ".painel-board.json")
        save_board(path, {
            "title": title or dirname,
            "meta": {"project": project if project is not None else dirname},
            "blocks": blocks if blocks is not None else [],
        })
        return path


def _occupy_port():
    """Returns (socket, port) -- caller must keep the socket alive to keep the
    port occupied, and close it when done."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(16)
    return s, s.getsockname()[1]


class _RunningServiceMixin(_FakeHomeMixin):
    """A real _ServiceHandler on a real socket -- these are HTTP-level tests,
    not handler-unit tests, because routing is exactly what M13 changed."""

    def _start_service(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._ServiceHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(httpd.shutdown)
        return port

    def _get(self, port, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def _post(self, port, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def _post_upload(self, port, path, files, boundary="pAInelBOUNDARY123"):
        """POST a hand-built multipart body; files = [(field, filename, bytes)]."""
        b = boundary.encode()
        body = b""
        for field, filename, content in files:
            body += b"--" + b + b"\r\n"
            body += (f'Content-Disposition: form-data; name="{field}"; '
                     f'filename="{filename}"').encode() + b"\r\n"
            body += b"Content-Type: application/octet-stream\r\n\r\n"
            body += content + b"\r\n"
        body += b"--" + b + b"--\r\n"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()


# --------------------------------------------------------------------------- #
# §17.2.2 -- THE contract                                                      #
# --------------------------------------------------------------------------- #
class PerBoardLogContractTest(_RunningServiceMixin, unittest.TestCase):
    """docs/SPEC.md §17.2.2, pinned.

    Pre-M13, each board had its own process whose stdout the CLI redirected
    into <board>.log; the agent tails that file per project. The unified
    service has one stdout for all boards, so it must write each event
    DIRECTLY into that board's own log. If events were merged into one shared
    stream instead, every project's agent would see every other project's
    events -- "you have broken the entire product" territory."""

    def test_event_lands_in_its_own_boards_log_and_not_the_others(self):
        a = self._project("proj-a", blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": None}])
        b = self._project("proj-b", blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": None}])
        slug_a, slug_b = registry.register(a), registry.register(b)
        port = self._start_service()

        status, _ = self._post(port, f"/{slug_a}/event",
                               {"event": "answer", "block": "q1", "value": "só para o A"})
        self.assertEqual(status, 200)

        # It landed in A's own log...
        with open(a + ".log", encoding="utf-8") as fh:
            a_lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(a_lines), 1)
        self.assertEqual(a_lines[0], {"event": "answer", "block": "q1", "value": "só para o A"})

        # ...and B's log does not exist at all: B saw nothing, not even an
        # empty file. B's agent must never have to filter A's events out.
        self.assertFalse(os.path.exists(b + ".log"))

        # And the board itself was mutated -- A's, not B's.
        self.assertEqual(srv.load_board(a)["blocks"][0]["answer"], "só para o A")
        self.assertIsNone(srv.load_board(b)["blocks"][0]["answer"])
        self.assertNotEqual(slug_a, slug_b)

    def test_each_board_accumulates_only_its_own_events(self):
        a = self._project("proj-a", blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": None}])
        b = self._project("proj-b", blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": None}])
        slug_a, slug_b = registry.register(a), registry.register(b)
        port = self._start_service()

        self._post(port, f"/{slug_a}/event", {"event": "answer", "block": "q1", "value": "a1"})
        self._post(port, f"/{slug_b}/event", {"event": "answer", "block": "q1", "value": "b1"})
        self._post(port, f"/{slug_a}/event", {"event": "answer", "block": "q1", "value": "a2"})

        def values(board_path):
            with open(board_path + ".log", encoding="utf-8") as fh:
                return [json.loads(line)["value"] for line in fh if line.strip()]

        self.assertEqual(values(a), ["a1", "a2"])
        self.assertEqual(values(b), ["b1"])

    def test_log_is_jsonl_appended_and_flushed_per_line(self):
        """The agent's command is `tail -n0 -F <board>.log | grep '^{'`: one
        complete JSON object per line, readable the instant it's written (no
        buffering until process exit -- there is no process exit any more)."""
        a = self._project("proj-a", blocks=[{"id": "c1", "type": "checklist", "items": [
            {"id": "i1", "text": "passo", "checked": False}]}])
        slug = registry.register(a)
        port = self._start_service()
        self._post(port, f"/{slug}/event", {"event": "check", "block": "c1", "item": "i1", "checked": True})
        with open(a + ".log", encoding="utf-8") as fh:
            content = fh.read()
        self.assertTrue(content.endswith("\n"))
        self.assertEqual(len(content.strip().split("\n")), 1)
        self.assertTrue(content.startswith("{"))  # survives the agent's grep '^{'
        json.loads(content)

    def test_pre_existing_log_is_appended_to_never_truncated(self):
        a = self._project("proj-a", blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": None}])
        with open(a + ".log", "w", encoding="utf-8") as fh:
            fh.write('{"event": "answer", "block": "q1", "value": "de ontem"}\n')
        slug = registry.register(a)
        port = self._start_service()
        self._post(port, f"/{slug}/event", {"event": "answer", "block": "q1", "value": "de hoje"})
        with open(a + ".log", encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual([x["value"] for x in lines], ["de ontem", "de hoje"])

    def test_silent_events_still_never_reach_the_boards_log(self):
        """SILENT_EVENTS (§2.1) is UI housekeeping that must not wake the
        agent. The log is now the agent's channel, so the rule applies to the
        file exactly as it applied to stdout."""
        a = self._project("proj-a", blocks=[{"id": "pl", "type": "plan", "items": [
            {"id": "p1", "text": "x", "thread": [{"from": "agent", "text": "hi"}], "seen": 0}]}])
        slug = registry.register(a)
        port = self._start_service()
        self._post(port, f"/{slug}/event", {"event": "plan_seen", "block": "pl", "item": "p1"})
        self.assertFalse(os.path.exists(a + ".log"))
        # ...but the state change still happened.
        self.assertEqual(srv.load_board(a)["blocks"][0]["items"][0]["seen"], 1)

    def test_board_json_stays_at_its_registered_path_in_the_project_dir(self):
        """§17.2.1: no central board store. The board is mutated in place,
        next to the work, and nothing board-shaped appears under ~/.painel."""
        a = self._project("proj-a", blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": None}])
        slug = registry.register(a)
        port = self._start_service()
        self._post(port, f"/{slug}/event", {"event": "answer", "block": "q1", "value": "x"})
        self.assertEqual(srv.load_board(a)["blocks"][0]["answer"], "x")
        painel_home = os.path.join(os.path.expanduser("~"), ".painel")
        self.assertEqual(
            sorted(os.listdir(painel_home)), ["projects.json"],
            "the registry stores a pointer to the board, never a copy of it",
        )


# --------------------------------------------------------------------------- #
# §19 -- the upload block endpoint, under the unified service                  #
# --------------------------------------------------------------------------- #
class UploadServiceTest(_RunningServiceMixin, unittest.TestCase):
    """M15 (docs/SPEC.md §19.2): /<slug>/upload writes files under the block's
    dest_dir and emits a NON-silent file_added event into THAT board's own
    <board>.log -- the same per-board-log contract as /event (§17.2.2)."""

    def test_upload_writes_file_and_emits_file_added_to_its_own_log(self):
        a = self._project("proj-a", blocks=[
            {"id": "up1", "type": "upload", "prompt": "?", "dest_dir": "docs/shots", "files": []}])
        slug = registry.register(a)
        port = self._start_service()

        status, _ = self._post_upload(port, f"/{slug}/upload?block=up1",
                                      [("file", "shot.png", b"PNGDATA")])
        self.assertEqual(status, 200)

        project_dir = os.path.dirname(a)
        dest = os.path.join(project_dir, "docs", "shots", "shot.png")
        self.assertTrue(os.path.exists(dest))

        # files[] updated on the board in place (§19.1).
        files = srv.load_board(a)["blocks"][0]["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "shot.png")
        self.assertEqual(files[0]["path"], dest)
        self.assertEqual(files[0]["size"], 7)

        # file_added landed in THIS board's own log, and is NOT silent (§19.2).
        with open(a + ".log", encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], {"event": "file_added", "block": "up1",
                                    "name": "shot.png", "path": dest, "size": 7})

    def test_global_upload_block_null_lands_in_painel_uploads(self):
        a = self._project("proj-a", blocks=[])
        slug = registry.register(a)
        port = self._start_service()

        status, _ = self._post_upload(port, f"/{slug}/upload",
                                      [("file", "hand.txt", b"hi")])
        self.assertEqual(status, 200)
        dest = os.path.join(os.path.dirname(a), "painel-uploads", "hand.txt")
        self.assertTrue(os.path.exists(dest))
        with open(a + ".log", encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIsNone(lines[0]["block"])  # block:null, mirroring global CR

    def test_upload_to_board_a_never_touches_board_b_log(self):
        """Per-board isolation (mirrors PerBoardLogContractTest): an upload to A
        writes A's log and A's disk only; B sees nothing, not even a file."""
        a = self._project("proj-a", blocks=[
            {"id": "up1", "type": "upload", "dest_dir": "up", "files": []}])
        b = self._project("proj-b", blocks=[
            {"id": "up1", "type": "upload", "dest_dir": "up", "files": []}])
        slug_a, slug_b = registry.register(a), registry.register(b)
        port = self._start_service()

        self._post_upload(port, f"/{slug_a}/upload?block=up1", [("file", "a.png", b"A")])
        with open(a + ".log", encoding="utf-8") as fh:
            self.assertEqual(len([l for l in fh if l.strip()]), 1)
        self.assertFalse(os.path.exists(b + ".log"))
        self.assertEqual(srv.load_board(b)["blocks"][0]["files"], [])

    def test_dest_dir_escape_is_refused_and_writes_nothing(self):
        a = self._project("proj-a", blocks=[
            {"id": "up1", "type": "upload", "dest_dir": "../../escape", "files": []}])
        slug = registry.register(a)
        port = self._start_service()
        status, _ = self._post_upload(port, f"/{slug}/upload?block=up1",
                                      [("file", "x.png", b"DATA")])
        self.assertEqual(status, 400)
        self.assertFalse(os.path.exists(a + ".log"))  # nothing emitted either
        self.assertEqual(srv.load_board(a)["blocks"][0]["files"], [])

    def test_get_on_upload_path_404s(self):
        registry.register(self._project("proj", project="P", blocks=[]))
        port = self._start_service()
        status, _ = self._get(port, "/p/upload")
        self.assertEqual(status, 404)


# --------------------------------------------------------------------------- #
# §17.3 -- the registry                                                        #
# --------------------------------------------------------------------------- #
class SlugTest(unittest.TestCase):
    def test_normalization_rules(self):
        self.assertEqual(registry.slugify("Livrete"), "livrete")
        self.assertEqual(registry.slugify("rececao.pt"), "rececao-pt")
        self.assertEqual(registry.slugify("My Cool Project"), "my-cool-project")
        self.assertEqual(registry.slugify("some_snake_case"), "some-snake-case")
        self.assertEqual(registry.slugify("a---b"), "a-b")  # repeats collapse
        self.assertEqual(registry.slugify("  spaced  out  "), "spaced-out")
        self.assertEqual(registry.slugify("!!!weird***chars!!!"), "weirdchars")
        self.assertEqual(registry.slugify("-leading-and-trailing-"), "leading-and-trailing")

    def test_accents_are_folded_not_stripped(self):
        self.assertEqual(registry.slugify("Finanças"), "financas")
        self.assertEqual(registry.slugify("Estratégia"), "estrategia")

    def test_unusable_input_falls_back_rather_than_producing_an_empty_slug(self):
        self.assertEqual(registry.slugify(""), "projeto")
        self.assertEqual(registry.slugify("***"), "projeto")
        self.assertEqual(registry.slugify(None), "projeto")


class RegistryTest(_FakeHomeMixin, unittest.TestCase):
    def test_register_derives_the_slug_from_meta_project(self):
        path = self._project("whatever-dir", project="Livrete")
        self.assertEqual(registry.register(path), "livrete")

    def test_register_falls_back_to_the_parent_directory_name(self):
        path = self._project("rececao.pt", project="")
        self.assertEqual(registry.register(path), "rececao-pt")

    def test_registering_the_same_board_twice_is_idempotent(self):
        path = self._project("proj", project="Proj")
        self.assertEqual(registry.register(path), "proj")
        self.assertEqual(registry.register(path), "proj")
        self.assertEqual(len(registry.load_projects()), 1)

    def test_same_path_in_nfc_and_nfd_is_one_project(self):
        """Real bug, caught during the M13 migration on a real project.
        macOS returns NFD from the filesystem ("Finanças" as c + U+0327)
        while the same path typed in a shell is NFC (ç as U+00E7) -- they
        print identically. `painel add "<NFC path>"` then `painel open` from
        inside the directory (cwd -> NFD) registered the board twice and
        minted a spurious "financas-2". Nearly every real board here lives
        under "Meu Drive/Finanças/"."""
        path = self._project("Finanças", project="Finanças")
        nfc = unicodedata.normalize("NFC", path)
        nfd = unicodedata.normalize("NFD", path)
        self.assertNotEqual(nfc, nfd)  # genuinely different strings
        slug_a = registry.register(nfc)
        slug_b = registry.register(nfd)
        self.assertEqual(slug_a, slug_b)
        self.assertEqual(len(registry.load_projects()), 1)

    def test_registry_stores_the_path_verbatim_not_normalized(self):
        """Normalization is for *comparison* only. On Linux, NFC and NFD
        filenames are genuinely different files -- rewriting the stored path
        to a normalized form could point the service at a path that doesn't
        exist. We compare normalized, we store (and open) what we were
        given."""
        path = self._project("Finanças", project="Finanças")
        nfd = unicodedata.normalize("NFD", path)
        slug = registry.register(nfd)
        stored = registry.load_projects()[slug]["path"]
        self.assertTrue(os.path.exists(stored))
        self.assertEqual(
            unicodedata.normalize("NFC", os.path.realpath(stored)),
            unicodedata.normalize("NFC", os.path.realpath(path)),
        )

    def test_path_key_folds_symlinks(self):
        path = self._project("real-dir", project="Proj")
        link_dir = os.path.join(self._tmp.name, "link-dir")
        os.symlink(os.path.dirname(path), link_dir)
        via_link = os.path.join(link_dir, os.path.basename(path))
        self.assertEqual(registry.path_key(path), registry.path_key(via_link))
        self.assertEqual(registry.register(path), registry.register(via_link))
        self.assertEqual(len(registry.load_projects()), 1)

    def test_collision_gets_a_numeric_suffix(self):
        a = self._project("dir-a", project="Cliente")
        b = self._project("dir-b", project="Cliente")
        c = self._project("dir-c", project="Cliente")
        self.assertEqual(registry.register(a), "cliente")
        self.assertEqual(registry.register(b), "cliente-2")
        self.assertEqual(registry.register(c), "cliente-3")

    def test_reserved_slugs_are_suffixed_never_left_unreachable(self):
        """§17.3: a project called "version" must not shadow /<slug>/version
        semantics -- but it must still be reachable, so it's suffixed."""
        for name in ("version", "event"):
            path = self._project(f"dir-{name}", project=name)
            slug = registry.register(path)
            self.assertEqual(slug, f"{name}-2")
            self.assertNotIn(slug, registry.RESERVED_SLUGS)

    def test_slug_is_stable_across_a_board_retitle(self):
        """§17.3's load-bearing rule: the slug is generated ONCE and stored.
        Retitling a board must not silently change its URL and break the
        bookmark the human just made."""
        path = self._project("proj", project="Antigo")
        self.assertEqual(registry.register(path), "antigo")

        board = srv.load_board(path)
        board["meta"]["project"] = "Nome Completamente Novo"
        board["title"] = "Outro Título"
        srv.save_board(path, board)

        self.assertEqual(registry.register(path), "antigo")  # re-register: same slug
        self.assertEqual(registry.get("antigo")["path"], os.path.abspath(path))
        self.assertIsNone(registry.get("nome-completamente-novo"))
        # The display title DOES follow the board -- it addresses nothing.
        self.assertEqual(registry.get("antigo")["title"], "Outro Título")

    def test_missing_path_entry_is_still_listed_visibly_not_dropped(self):
        path = self._project("gone", project="Desaparecido")
        slug = registry.register(path)
        os.remove(path)
        entries = registry.entries()
        self.assertEqual([x["slug"] for x in entries], [slug])
        self.assertTrue(entries[0]["missing"])

    def test_unregister_never_deletes_the_board_file(self):
        path = self._project("proj", project="Proj")
        slug = registry.register(path)
        self.assertTrue(registry.unregister(slug))
        self.assertEqual(registry.load_projects(), {})
        self.assertTrue(os.path.exists(path), "the board belongs to the project, not to us")
        self.assertFalse(registry.unregister(slug))  # second call: not registered

    def test_registry_stores_a_pointer_with_an_absolute_path(self):
        path = self._project("proj", project="Proj")
        slug = registry.register(path)
        entry = registry.load_projects()[slug]
        self.assertTrue(os.path.isabs(entry["path"]))
        self.assertEqual(sorted(entry), ["path", "title"])

    def test_corrupt_registry_file_reads_as_empty_rather_than_crashing(self):
        with open(registry.projects_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        self.assertEqual(registry.load_projects(), {})
        self.assertEqual(registry.entries(), [])

    def test_service_json_roundtrip(self):
        self.assertIsNone(registry.read_service())
        registry.write_service(1234, 8765)
        self.assertEqual(registry.read_service(), {"pid": 1234, "port": 8765, "host": "127.0.0.1"})
        registry.clear_service()
        self.assertIsNone(registry.read_service())

    def test_legacy_instances_dir_is_cleaned_up(self):
        """§17.7: pre-M13 per-port process files describe processes that no
        longer exist. Ignored, and dropped on first run of the new service."""
        legacy = os.path.join(registry.painel_dir(), "instances")
        os.makedirs(legacy, exist_ok=True)
        with open(os.path.join(legacy, "8771.json"), "w", encoding="utf-8") as fh:
            fh.write('{"pid": 1, "port": 8771, "board": "/tmp/x.json"}')
        registry.clean_legacy_instances()
        self.assertFalse(os.path.exists(legacy))
        registry.clean_legacy_instances()  # idempotent, must not raise


# --------------------------------------------------------------------------- #
# §17.4 -- routing                                                             #
# --------------------------------------------------------------------------- #
class RoutingTest(_RunningServiceMixin, unittest.TestCase):
    def test_root_lists_every_registered_project_including_ones_with_no_process(self):
        """§17.1's whole complaint: 7 boards on disk, 2 processes, the hub
        listed 2. Post-M13 NO project has a process of its own -- so if
        anything is listed at all, this works."""
        registry.register(self._project("proj-a", project="Projeto A", title="Projeto A"))
        registry.register(self._project("proj-b", project="Projeto B", title="Projeto B"))
        port = self._start_service()
        status, body = self._get(port, "/")
        self.assertEqual(status, 200)
        self.assertIn("Projeto A", body)
        self.assertIn("Projeto B", body)
        self.assertIn('href="/projeto-a"', body)
        self.assertIn('href="/projeto-b"', body)

    def test_empty_directory_is_empty_but_not_broken(self):
        port = self._start_service()
        status, body = self._get(port, "/")
        self.assertEqual(status, 200)
        self.assertIn("Nenhum projeto registado", body)
        self.assertIn("</html>", body)

    def test_missing_project_renders_visibly_missing_in_the_directory(self):
        path = self._project("gone", project="Desaparecido", title="Desaparecido")
        registry.register(path)
        os.remove(path)
        port = self._start_service()
        status, body = self._get(port, "/")
        self.assertEqual(status, 200)
        self.assertIn("Desaparecido", body)  # listed, not silently dropped
        self.assertIn("board não encontrado", body)  # and visibly so
        self.assertNotIn('href="/desaparecido"', body)  # nothing to open

    def test_slug_renders_that_boards_home(self):
        registry.register(self._project("proj-a", project="A", title="Board A", blocks=[
            {"id": "h1", "type": "heading", "text": "Só do A"}]))
        registry.register(self._project("proj-b", project="B", title="Board B", blocks=[
            {"id": "h1", "type": "heading", "text": "Só do B"}]))
        port = self._start_service()
        status, body = self._get(port, "/a")
        self.assertEqual(status, 200)
        self.assertIn("Só do A", body)
        self.assertNotIn("Só do B", body)

    def test_slug_page_renders_that_page(self):
        registry.register(self._project("proj", project="P", blocks=[
            {"id": "h1", "type": "heading", "text": "Bloco da Home"},
            {"id": "h2", "type": "heading", "text": "Bloco Financeiro", "page": "Financeiro"},
        ]))
        port = self._start_service()
        status, body = self._get(port, "/p/Financeiro")
        self.assertEqual(status, 200)
        self.assertIn("Bloco Financeiro", body)
        self.assertNotIn("Bloco da Home", body)

    def test_page_links_are_prefixed_with_the_slug(self):
        registry.register(self._project("proj", project="P", blocks=[
            {"id": "h1", "type": "heading", "text": "Home"},
            {"id": "h2", "type": "heading", "text": "Fin", "page": "Financeiro"},
        ]))
        port = self._start_service()
        _, body = self._get(port, "/p")
        self.assertIn('href="/p/Financeiro"', body)
        self.assertIn('href="/p"', body)  # Home, not "/"

    def test_query_page_param_still_accepted_on_a_boards_home(self):
        """§17.4: old bookmarked ?page= links keep working."""
        registry.register(self._project("proj", project="P", blocks=[
            {"id": "h1", "type": "heading", "text": "Bloco da Home"},
            {"id": "h2", "type": "heading", "text": "Bloco Financeiro", "page": "Financeiro"},
        ]))
        port = self._start_service()
        status, body = self._get(port, "/p?page=Financeiro")
        self.assertEqual(status, 200)
        self.assertIn("Bloco Financeiro", body)
        self.assertNotIn("Bloco da Home", body)

    def test_trailing_slash_on_a_slug_is_that_boards_home(self):
        registry.register(self._project("proj", project="P", blocks=[
            {"id": "h1", "type": "heading", "text": "Bloco da Home"}]))
        port = self._start_service()
        status, body = self._get(port, "/p/")
        self.assertEqual(status, 200)
        self.assertIn("Bloco da Home", body)

    def test_unknown_slug_404s_and_lists_what_is_registered(self):
        """§17.4: not a bare 404 -- the human mistyped or the project was
        removed, and the page should say which projects DO exist."""
        registry.register(self._project("proj-a", project="Projeto A", title="Projeto A"))
        port = self._start_service()
        status, body = self._get(port, "/nao-existe")
        self.assertEqual(status, 404)
        self.assertIn("nao-existe", body)
        self.assertIn("Projeto A", body)
        self.assertIn('href="/projeto-a"', body)

    def test_version_returns_the_right_payload_per_board(self):
        a = self._project("proj-a", project="A", blocks=[
            {"id": "q1", "type": "question", "prompt": "?", "answer": None}])
        b = self._project("proj-b", project="B", blocks=[
            {"id": "q1", "type": "question", "prompt": "?", "answer": "respondida"},
            {"id": "q2", "type": "question", "prompt": "?", "answer": "também"},
        ])
        board_b = srv.load_board(b)
        board_b["meta"]["agent_status"] = "working"
        srv.save_board(b, board_b)
        registry.register(a)
        registry.register(b)
        port = self._start_service()

        _, body_a = self._get(port, "/a/version")
        payload_a = json.loads(body_a)
        self.assertEqual(payload_a["pending"], 1)
        self.assertEqual(payload_a["agent_status"], "working")  # default when absent
        self.assertFalse(payload_a["has_resolved"])

        _, body_b = self._get(port, "/b/version")
        payload_b = json.loads(body_b)
        self.assertEqual(payload_b["pending"], 0)
        self.assertTrue(payload_b["has_resolved"])
        # Different boards, genuinely different payloads.
        self.assertNotEqual(payload_a["v"], payload_b["v"])

    def test_version_still_folds_in_watched_paths_mtimes(self):
        """M11/§15.2's freshness extension must survive the move into the
        service: a resources block's watched file changing on disk still bumps
        `v`, with no board.json edit at all."""
        watched = os.path.join(self._tmp.name, "mockup.png")
        with open(watched, "w") as fh:
            fh.write("v1")
        registry.register(self._project("proj", project="P", blocks=[
            {"id": "res1", "type": "resources", "title": "Docs",
             "items": [{"label": "Mockup", "kind": "file", "path": watched}]}]))
        port = self._start_service()

        _, body = self._get(port, "/p/version")
        v_before = json.loads(body)["v"]

        os.utime(watched, (v_before + 1000, v_before + 1000))
        _, body = self._get(port, "/p/version")
        v_after = json.loads(body)["v"]
        self.assertGreater(v_after, v_before)
        self.assertEqual(v_after, v_before + 1000)

    def test_version_on_an_unknown_slug_404s(self):
        port = self._start_service()
        status, _ = self._get(port, "/nao-existe/version")
        self.assertEqual(status, 404)

    def test_get_on_an_event_path_404s(self):
        """/<slug>/event is POST-only, exactly as /event was pre-M13."""
        registry.register(self._project("proj", project="P"))
        port = self._start_service()
        status, _ = self._get(port, "/p/event")
        self.assertEqual(status, 404)

    def test_post_to_an_unknown_slug_404s(self):
        port = self._start_service()
        status, _ = self._post(port, "/nao-existe/event", {"event": "answer", "block": "q1", "value": "x"})
        self.assertEqual(status, 404)

    def test_directory_reflects_registry_changes_without_caching(self):
        port = self._start_service()
        _, before = self._get(port, "/")
        self.assertNotIn("Aparece Depois", before)

        registry.register(self._project("later", project="Aparece Depois", title="Aparece Depois"))
        _, during = self._get(port, "/")
        self.assertIn("Aparece Depois", during)

        registry.unregister("aparece-depois")
        _, after = self._get(port, "/")
        self.assertNotIn("Aparece Depois", after)

    def test_served_board_page_points_its_js_at_the_slug_scoped_endpoints(self):
        registry.register(self._project("proj", project="P"))
        port = self._start_service()
        _, body = self._get(port, "/p")
        self.assertIn('const basePath = "/p";', body)
        self.assertIn("fetch(basePath + '/version'", body)
        self.assertIn("fetch(basePath + '/event'", body)


class DirectoryRenderTest(_FakeHomeMixin, unittest.TestCase):
    """The directory is host-app chrome fed by the registry, not a block type
    (§13.2's rule survives M13) -- it reuses page.py's _PAGE directly."""

    def test_pending_badge_and_status_chip_reuse_the_shared_helpers(self):
        registry.register(self._project(
            "com", project="Com Pendentes", title="Com Pendentes",
            blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": None}]))
        registry.register(self._project(
            "sem", project="Sem Pendentes", title="Sem Pendentes",
            blocks=[{"id": "q1", "type": "question", "prompt": "?", "answer": "sim"}]))
        html = dir_mod.render_directory(registry.entries())
        self.assertIn("À espera de ti", html)
        self.assertIn("Agente offline", html)

    def test_agent_status_chip_shown_per_project(self):
        path = self._project("proj", project="meu-projeto", title="O Meu Board")
        board = srv.load_board(path)
        board["meta"]["agent_status"] = "working"
        srv.save_board(path, board)
        registry.register(path)
        html = dir_mod.render_directory(registry.entries())
        self.assertIn("O Meu Board", html)
        self.assertIn("meu-projeto", html)
        self.assertIn("a trabalhar", html)

    def test_directory_adds_no_block_type_to_the_public_catalog(self):
        from painel.blocks import REGISTRY
        for name in ("directory", "hub", "project", "dir"):
            self.assertNotIn(name, REGISTRY)


# --------------------------------------------------------------------------- #
# §17.5 / §17.6 -- CLI: port handling and exposure safety                      #
# --------------------------------------------------------------------------- #
class ForeignServiceOnServicePortTest(_FakeHomeMixin, unittest.TestCase):
    """Real bug, caught during dogfooding (2026-07-06): 8765 was already
    occupied by an unrelated service on the author's machine. M13 raises the
    stakes -- the port is now THE ADDRESS, in every bookmark -- so the
    response is a hard failure suggesting --port, never a silent wander
    (§17.5). This is §13's _is_our_hub check, adapted."""

    def _serve_real_service_in_thread(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._ServiceHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(httpd.shutdown)
        return port

    def test_is_our_service_true_for_a_genuine_service(self):
        port = self._serve_real_service_in_thread()
        self.assertTrue(cli._is_our_service(port))

    def test_is_our_service_false_for_a_non_http_occupant(self):
        s, port = _occupy_port()
        try:
            self.assertFalse(cli._is_our_service(port))
        finally:
            s.close()

    def test_is_our_service_false_for_an_http_server_with_different_content(self):
        from http.server import BaseHTTPRequestHandler

        class _OtherService(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                body = b"<html><title>Pulsia</title>Not pAInel at all</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _OtherService)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertFalse(cli._is_our_service(port))
        finally:
            httpd.shutdown()
            thread.join()
            httpd.server_close()

    def test_ensure_service_fails_clearly_and_never_wanders_to_another_port(self):
        import contextlib
        import io
        s, port = _occupy_port()
        spawn_calls = []
        orig = cli._spawn_service
        cli._spawn_service = lambda p, host="127.0.0.1": spawn_calls.append(p)
        try:
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                result = cli._ensure_service_running(port=port)
            self.assertIsNone(result)                 # failed...
            self.assertEqual(spawn_calls, [])         # ...without binding anything
            err = captured.getvalue()
            self.assertIn("já está ocupada", err)
            self.assertIn("--port", err)              # and told the human what to do
        finally:
            cli._spawn_service = orig
            s.close()

    def test_ensure_service_adopts_a_genuine_service_already_on_the_port(self):
        port = self._serve_real_service_in_thread()
        spawn_calls = []
        orig = cli._spawn_service
        cli._spawn_service = lambda p, host="127.0.0.1": spawn_calls.append(p)
        try:
            self.assertEqual(cli._ensure_service_running(port=port), port)
            self.assertEqual(spawn_calls, [])  # never starts a second one
        finally:
            cli._spawn_service = orig


class ExposureSafetyTest(unittest.TestCase):
    """§17.6, fail closed. Boards routinely hold plaintext credentials; pAInel
    has no auth by design. A non-loopback bind reachable by typo is a defect."""

    def test_loopback_hosts_need_no_acknowledgement(self):
        for host in ("127.0.0.1", "localhost", "::1", ""):
            self.assertTrue(cli._check_exposure(host, ack=False))

    def test_non_loopback_without_the_ack_flag_is_refused(self):
        import contextlib
        import io
        for host in ("0.0.0.0", "192.168.1.10", "::"):
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                self.assertFalse(cli._check_exposure(host, ack=False))
            err = captured.getvalue()
            self.assertIn("recusei arrancar", err)
            self.assertIn("credenciais", err)  # says WHY, not just "no"
            self.assertIn(cli.EXPOSE_ACK_FLAG, err)  # says how, if you mean it

    def test_non_loopback_with_the_ack_flag_is_allowed(self):
        self.assertTrue(cli._check_exposure("0.0.0.0", ack=True))

    def test_service_command_refuses_a_non_loopback_bind_without_the_flag(self):
        import contextlib
        import io
        served = []
        orig = cli.serve_service
        cli.serve_service = lambda **kw: served.append(kw)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                rc = cli.main(["service", "--host", "0.0.0.0"])
            self.assertEqual(rc, 1)
            self.assertEqual(served, [], "must never bind before the human acknowledges")
        finally:
            cli.serve_service = orig

    def test_service_command_binds_non_loopback_once_acknowledged(self):
        served = []
        orig = cli.serve_service
        cli.serve_service = lambda **kw: served.append(kw)
        try:
            rc = cli.main(["service", "--host", "0.0.0.0", cli.EXPOSE_ACK_FLAG, "--port", "9999"])
            self.assertEqual(rc, 0)
            self.assertEqual(served, [{"port": 9999, "host": "0.0.0.0"}])
        finally:
            cli.serve_service = orig

    def test_service_defaults_to_loopback(self):
        served = []
        orig = cli.serve_service
        cli.serve_service = lambda **kw: served.append(kw)
        try:
            cli.main(["service"])
            self.assertEqual(served, [{"port": cli.SERVICE_PORT, "host": "127.0.0.1"}])
        finally:
            cli.serve_service = orig

    def test_hub_is_an_alias_for_service(self):
        """§17.5: kept so existing habits and scripts don't break."""
        served = []
        orig = cli.serve_service
        cli.serve_service = lambda **kw: served.append(kw)
        try:
            self.assertEqual(cli.main(["hub", "--port", "8765"]), 0)
            self.assertEqual(served, [{"port": 8765, "host": "127.0.0.1"}])
        finally:
            cli.serve_service = orig


class CliCommandsTest(_FakeHomeMixin, unittest.TestCase):
    def test_add_registers_without_starting_anything(self):
        path = self._project("proj", project="Proj")
        spawn_calls = []
        orig = cli._spawn_service
        cli._spawn_service = lambda p, host="127.0.0.1": spawn_calls.append(p)
        try:
            self.assertEqual(cli.cmd_add(os.path.dirname(path)), 0)
            self.assertIn("proj", registry.load_projects())
            self.assertEqual(spawn_calls, [])
        finally:
            cli._spawn_service = orig

    def test_add_refuses_a_directory_with_no_board(self):
        import contextlib
        import io
        empty = os.path.join(self._tmp.name, "vazio")
        os.makedirs(empty)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.cmd_add(empty), 1)
        self.assertEqual(registry.load_projects(), {})

    def test_add_accepts_a_board_path_as_well_as_a_directory(self):
        """M13 reshaped these to take a directory, but the author's fingers
        have typed board paths for months -- both must work."""
        path = self._project("proj", project="Proj")
        self.assertEqual(cli.cmd_add(path), 0)
        self.assertEqual(registry.load_projects()["proj"]["path"], os.path.abspath(path))

    def test_remove_unregisters_and_leaves_the_board_alone(self):
        path = self._project("proj", project="Proj")
        cli.cmd_add(path)
        self.assertEqual(cli.cmd_remove("proj"), 0)
        self.assertEqual(registry.load_projects(), {})
        self.assertTrue(os.path.exists(path))

    def test_remove_of_an_unregistered_slug_is_an_error_not_a_crash(self):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.cmd_remove("nunca-existiu"), 1)

    def test_open_creates_registers_and_points_the_browser_at_the_slug(self):
        """§17.2.3: `painel open` in a fresh dir still Just Works end to end."""
        opened, spawned = [], []
        orig_open, orig_spawn = cli.webbrowser.open, cli._spawn_service
        orig_wait = cli._wait_until_listening
        cli.webbrowser.open = lambda url: opened.append(url)
        cli._spawn_service = lambda p, host="127.0.0.1": spawned.append(p) or 111
        cli._wait_until_listening = lambda port, tries=50: None
        try:
            fresh = os.path.join(self._tmp.name, "novo-projeto")
            os.makedirs(fresh)
            self.assertEqual(cli.cmd_open(fresh, port=9876), 0)
            self.assertTrue(os.path.exists(os.path.join(fresh, ".painel-board.json")))
            self.assertIn("novo-projeto", registry.load_projects())
            self.assertEqual(spawned, [9876])
            self.assertEqual(opened, ["http://localhost:9876/novo-projeto"])
        finally:
            cli.webbrowser.open, cli._spawn_service = orig_open, orig_spawn
            cli._wait_until_listening = orig_wait

    def test_open_starter_board_is_named_after_its_own_dir_not_the_cwd(self):
        orig_open, orig_spawn = cli.webbrowser.open, cli._spawn_service
        orig_wait = cli._wait_until_listening
        cli.webbrowser.open = lambda url: None
        cli._spawn_service = lambda p, host="127.0.0.1": 111
        cli._wait_until_listening = lambda port, tries=50: None
        try:
            fresh = os.path.join(self._tmp.name, "outro-sitio")
            os.makedirs(fresh)
            cli.cmd_open(fresh, port=9876)
            board = srv.load_board(os.path.join(fresh, ".painel-board.json"))
            self.assertEqual(board["meta"]["project"], "outro-sitio")
        finally:
            cli.webbrowser.open, cli._spawn_service = orig_open, orig_spawn
            cli._wait_until_listening = orig_wait

    def test_open_is_idempotent_and_does_not_start_a_second_service(self):
        path = self._project("proj", project="Proj")
        opened, spawned = [], []
        orig_open, orig_spawn = cli.webbrowser.open, cli._spawn_service
        orig_running = cli._service_running
        cli.webbrowser.open = lambda url: opened.append(url)
        cli._spawn_service = lambda p, host="127.0.0.1": spawned.append(p)
        cli._service_running = lambda port: True
        try:
            registry.write_service(999, 8765)
            cli.cmd_open(os.path.dirname(path), port=None)
            cli.cmd_open(os.path.dirname(path), port=None)
            self.assertEqual(spawned, [])
            self.assertEqual(opened, ["http://localhost:8765/proj"] * 2)
            self.assertEqual(len(registry.load_projects()), 1)
        finally:
            cli.webbrowser.open, cli._spawn_service = orig_open, orig_spawn
            cli._service_running = orig_running

    def test_status_reports_the_service_and_the_project_count(self):
        import contextlib
        import io
        self._project("proj", project="Proj")
        cli.cmd_add(os.path.join(self._tmp.name, "proj"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.cmd_status()
        self.assertIn("parado", out.getvalue())
        self.assertIn("1 projeto registado", out.getvalue())

        registry.write_service(os.getpid(), 8765)
        orig = cli._service_running
        cli._service_running = lambda port: True
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.cmd_status()
            self.assertIn("http://localhost:8765/", out.getvalue())
            self.assertIn("1 projeto registado", out.getvalue())
        finally:
            cli._service_running = orig

    def test_stop_clears_the_service_record(self):
        import contextlib
        import io
        registry.write_service(999999999, 8765)  # a pid that isn't alive
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_stop(), 0)
        self.assertIsNone(registry.read_service())

    def test_stop_when_nothing_is_running_is_not_an_error(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_stop(), 0)

    def test_restart_all_restarts_the_one_service_on_the_same_port(self):
        """§17.5: the NAME stays (it's in the author's post-upgrade muscle
        memory and documented workflow); it just has one thing to restart now.
        Same port, so every bookmark survives."""
        import contextlib
        import io
        spawned = []
        orig_spawn, orig_alive = cli._spawn_service, cli._pid_alive
        orig_wait, orig_free = cli._wait_until_listening, cli._wait_until_listening_free
        cli._spawn_service = lambda p, host="127.0.0.1": spawned.append((p, host)) or 4242
        cli._pid_alive = lambda pid: False
        cli._wait_until_listening = lambda port, tries=50: None
        cli._wait_until_listening_free = lambda port, tries=50: None
        try:
            registry.write_service(999, 8765)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.cmd_restart_all(), 0)
            self.assertEqual(spawned, [(8765, "127.0.0.1")])
            self.assertIn("reiniciado", out.getvalue())
        finally:
            cli._spawn_service, cli._pid_alive = orig_spawn, orig_alive
            cli._wait_until_listening, cli._wait_until_listening_free = orig_wait, orig_free

    def test_restart_all_with_no_service_is_not_an_error(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.cmd_restart_all(), 0)
        self.assertIn("nenhum pAInel a correr", out.getvalue())


# --------------------------------------------------------------------------- #
# §17.5 -- `painel serve` is unchanged (regression guard)                      #
# --------------------------------------------------------------------------- #
class SingleBoardServeUnchangedTest(unittest.TestCase):
    """`painel serve <board>` survives M13 untouched (§17.5): one board,
    foreground, no registry, board at the server root. It's the right tool for
    tests and for a vendored single-board use -- and keeping it working is
    what keeps every pre-M13 test in this suite meaningful.

    Deliberately does NOT use the fake-HOME mixin: single-board mode must not
    read or write ~/.painel at all."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board_path = os.path.join(self.tmp.name, "board.json")
        save_board(self.board_path, {
            "title": "Sozinho",
            "meta": {},
            "blocks": [
                {"id": "h1", "type": "heading", "text": "Bloco da Home"},
                {"id": "q1", "type": "question", "prompt": "Pergunta?", "answer": None},
                {"id": "h2", "type": "heading", "text": "Bloco Financeiro", "page": "Financeiro"},
            ],
        })
        srv._Handler.board_path = self.board_path
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv._Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.httpd.shutdown)

    def _get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_board_is_served_at_the_root_not_under_a_slug(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("Bloco da Home", body)

    def test_pages_are_served_at_the_root_too(self):
        status, body = self._get("/Financeiro")
        self.assertEqual(status, 200)
        self.assertIn("Bloco Financeiro", body)
        self.assertNotIn("Bloco da Home", body)

    def test_version_stays_at_slash_version(self):
        status, body = self._get("/version")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["pending"], 1)
        self.assertIn("v", payload)
        self.assertIn("agent_status", payload)

    def test_js_endpoints_stay_unprefixed(self):
        _, body = self._get("/")
        self.assertIn('const basePath = "";', body)
        self.assertIn("fetch(basePath + '/version'", body)

    def test_links_stay_unprefixed(self):
        _, body = self._get("/")
        self.assertIn('href="/Financeiro"', body)

    def test_event_posts_to_slash_event_and_emits_on_stdout_only(self):
        """Single-board mode's agent channel has always been this process's
        stdout, which the CLI redirects into <board>.log. The service writes
        the file itself instead -- doing BOTH here would double every line."""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/event",
            data=json.dumps({"event": "answer", "block": "q1", "value": "42"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)
        self.assertEqual(srv.load_board(self.board_path)["blocks"][1]["answer"], "42")
        self.assertFalse(os.path.exists(self.board_path + ".log"))

    def test_unknown_path_still_falls_back_to_home(self):
        status, body = self._get("/favicon.ico")
        self.assertEqual(status, 200)
        self.assertIn("Bloco da Home", body)


if __name__ == "__main__":
    unittest.main()
