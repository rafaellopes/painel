"""CLI-level tests: M5 (SPEC.md §10.3) -- painel open/serve set
meta.agent_status="idle" on first run when the key is absent, best-effort --
plus M13's board-path argument handling (§17.5).

The service lifecycle, the project registry and `painel serve`'s regression
guard live in tests/test_service.py."""
import os
import tempfile
import unittest

from painel import __main__ as cli
from painel.server import load_board, save_board


class DefaultAgentStatusTest(unittest.TestCase):
    def test_sets_idle_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            save_board(path, {"title": "T", "meta": {}, "blocks": []})
            cli._default_agent_status_if_absent(path)
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")

    def test_does_not_overwrite_existing_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            save_board(path, {"title": "T", "meta": {"agent_status": "working"}, "blocks": []})
            cli._default_agent_status_if_absent(path)
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "working")

    def test_missing_meta_key_entirely(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            save_board(path, {"title": "T", "blocks": []})
            cli._default_agent_status_if_absent(path)
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")

    def test_best_effort_missing_board_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "does-not-exist.json")
            # load_board creates the file on demand, so this should succeed
            # and set idle -- not crash. Guards the "best-effort" contract.
            cli._default_agent_status_if_absent(path)
            self.assertTrue(os.path.exists(path))
            board = load_board(path)
            self.assertEqual(board["meta"]["agent_status"], "idle")

    def test_best_effort_malformed_json_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not valid json")
            # Should not raise -- best-effort per SPEC.md §10.3.
            cli._default_agent_status_if_absent(path)

    def test_demo_board_has_explicit_agent_status(self):
        board = cli._demo_board()
        self.assertIn("agent_status", board["meta"])


class BoardPathResolutionTest(unittest.TestCase):
    """M13 (docs/SPEC.md §17.5) reshaped `open`/`add` to take a project
    DIRECTORY rather than a board path. The board path form has been in the
    author's fingers for months, so both are accepted."""

    def test_a_directory_resolves_to_its_default_board(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cli._resolve_board_arg(d), os.path.join(d, cli.DEFAULT_BOARD))

    def test_a_board_path_is_taken_as_is(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".painel-board.json")
            save_board(path, {"title": "T", "meta": {}, "blocks": []})
            self.assertEqual(cli._resolve_board_arg(path), path)

    def test_a_nonexistent_path_is_taken_as_a_board_to_be_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "custom-board.json")
            self.assertEqual(cli._resolve_board_arg(path), path)


class InstallSkillTest(unittest.TestCase):
    """painel install-skill (symlink, never a copy -- there must only ever
    be one real copy of the skill, so there is nothing to keep in sync)."""

    def test_symlinks_into_a_project_with_no_existing_skill_dir(self):
        with tempfile.TemporaryDirectory() as d:
            rc = cli.cmd_install_skill(d)
            self.assertEqual(rc, 0)
            dest = os.path.join(d, ".claude", "skills", "painel")
            self.assertTrue(os.path.islink(dest))
            self.assertTrue(os.path.isfile(os.path.join(dest, "SKILL.md")))
            self.assertEqual(os.path.realpath(dest), os.path.realpath(cli._skill_source_dir()))

    def test_idempotent_when_already_correctly_linked(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cli.cmd_install_skill(d), 0)
            self.assertEqual(cli.cmd_install_skill(d), 0)  # second call, same result, no error

    def test_replaces_a_stale_link_pointing_elsewhere(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as elsewhere:
            dest_parent = os.path.join(d, ".claude", "skills")
            os.makedirs(dest_parent)
            stale = os.path.join(dest_parent, "painel")
            os.symlink(elsewhere, stale)
            rc = cli.cmd_install_skill(d)
            self.assertEqual(rc, 0)
            self.assertEqual(os.path.realpath(stale), os.path.realpath(cli._skill_source_dir()))

    def test_refuses_to_clobber_a_real_directory(self):
        with tempfile.TemporaryDirectory() as d:
            dest_parent = os.path.join(d, ".claude", "skills")
            dest = os.path.join(dest_parent, "painel")
            os.makedirs(dest)
            with open(os.path.join(dest, "SKILL.md"), "w") as fh:
                fh.write("hand-written copy, not a symlink")
            rc = cli.cmd_install_skill(d)
            self.assertEqual(rc, 1)
            self.assertFalse(os.path.islink(dest))  # untouched
            with open(os.path.join(dest, "SKILL.md")) as fh:
                self.assertEqual(fh.read(), "hand-written copy, not a symlink")

    def test_skill_source_dir_resolves_to_a_real_existing_directory(self):
        src = cli._skill_source_dir()
        self.assertIsNotNone(src)
        self.assertTrue(os.path.isfile(os.path.join(src, "SKILL.md")))


if __name__ == "__main__":
    unittest.main()
