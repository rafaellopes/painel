"""Block-choice lint tests (M16, docs/SPEC.md §20).

The heuristic's contract is §20.1's marker list, and its governing rule is
"prefer false negatives over false positives" -- so the negative tests here
(plain actions, and words that merely *contain* a marker) are as load-bearing
as the positive ones. A linter that cries wolf gets ignored, which would defeat
the whole milestone.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

from painel import lint
from painel import __main__ as cli
from painel.blocks import checklist
from painel.server import save_board

XSS = '"<script>alert(1)</script>'

# The three real incidents from §20, verbatim.
INCIDENT_1 = "Ter pelo menos 2 contas de condutor de teste, associadas à mesma frota/gestor"
INCIDENT_2 = ("COND-1: Login com condutor em Europe/Lisbon — confirmar que "
              "todas as horas exibidas estão corretas")
INCIDENT_3 = ("Responder às perguntas do GitHub profile README "
              "(Draxo numa frase, projetos a listar, email)")

# §20.1's explicit "deliberately NOT flagged" list: plain actions, which are
# exactly what `checklist` is for.
PLAIN_ACTIONS = [
    "Fazer login no portal X",
    "Descarregar o PDF do relatório",
    "Publicar o Show HN",
    "Gravar GIF de demo ~10s",
    "Criar conta Ko-fi",
    "Largar os 5 screenshots em docs/screenshots/",
    "Colocar o ficheiro em ~/Downloads",
]


def _board(*texts):
    return {
        "title": "T",
        "blocks": [{
            "id": "cl", "type": "checklist", "title": "Passos",
            "items": [{"id": f"i{n}", "text": t} for n, t in enumerate(texts, 1)],
        }],
    }


class HeuristicTest(unittest.TestCase):
    def test_incident_3_is_flagged(self):
        self.assertIsNotNone(lint.check_text(INCIDENT_3))

    def test_incidents_1_and_2_are_documented_limitations(self):
        """§20.1's marker list is the contract, and neither incident #1 nor #2
        contains a marker or ends with '?'.

        This is not an oversight in the implementation -- it is what the
        specified heuristic does, pinned deliberately so a future widening is a
        conscious decision with a test change, not an accident:

        - #1 ("Ter pelo menos 2 contas…") fails because *ticking it discards
          the accounts* -- a "this step has a payload the agent needs" problem,
          not an answer-requesting *phrasing*. Nothing in the text asks a
          question.
        - #2 ("…confirmar que todas as horas estão corretas") fails because the
          marker is `confirmar com` ("confirmar com o sócio: X ou Y?"), not a
          bare `confirmar`. Widening it to bare `confirmar` would flag ordinary
          verification steps ("confirmar que o deploy correu bem"), which is
          precisely the false-positive noise §20.1 forbids.
        """
        self.assertIsNone(lint.check_text(INCIDENT_1))
        self.assertIsNone(lint.check_text(INCIDENT_2))

    def test_plain_actions_are_never_flagged(self):
        for text in PLAIN_ACTIONS:
            with self.subTest(text=text):
                self.assertIsNone(lint.check_text(text))

    def test_trailing_question_mark(self):
        self.assertIsNotNone(lint.check_text("Está tudo correto?"))
        self.assertIsNotNone(lint.check_text("Está tudo correto?   "))
        self.assertIsNotNone(lint.check_text("**Está tudo correto?**"))
        self.assertIsNotNone(lint.check_text("Está tudo correto? <br>"))
        self.assertEqual("termina com '?'", lint.check_text("Está tudo correto?"))

    def test_question_mark_mid_text_alone_is_not_enough(self):
        # No marker, '?' not at the end -> not flagged. Conservative on purpose.
        self.assertIsNone(lint.check_text("Ver o ficheiro a?b.txt e apagá-lo"))

    def test_accent_insensitive(self):
        self.assertIsNotNone(lint.check_text("dá-me o IBAN da empresa"))
        self.assertIsNotNone(lint.check_text("da-me o IBAN da empresa"))
        self.assertEqual(lint.check_text("dá-me o IBAN"), lint.check_text("da-me o IBAN"))

    def test_case_insensitive(self):
        for variant in ("RESPONDER ao email do banco", "Responder ao email do banco",
                        "responder ao email do banco"):
            with self.subTest(variant=variant):
                self.assertIsNotNone(lint.check_text(variant))

    def test_every_documented_marker_fires(self):
        for marker in lint.MARKERS:
            with self.subTest(marker=marker):
                self.assertIsNotNone(lint.check_text(f"Passo: {marker} o valor"))

    def test_word_boundaries_prevent_false_positives(self):
        """A marker that merely appears as a *substring* of another word must
        not fire -- this is the single biggest false-positive risk in a
        substring-matching linter."""
        for text in (
            "Verificar a qualidade do build",          # "qual" inside "qualidade"
            "Rever o indicador de performance",        # "indica" inside "indicador"
            "Confirmar que o deploy correu bem",       # bare "confirmar", not "confirmar com"
            "Rever o quantitativo de horas",           # "quanto" inside "quantitativo"
            "Corrigir a informação do rodapé",         # "informa" inside "informação"
            "Arquivar o respondente antigo",           # "responde" inside "respondente"
            "Atualizar a cadameia de testes",          # "da-me" inside a longer word
        ):
            with self.subTest(text=text):
                self.assertIsNone(lint.check_text(text))

    def test_fold_matches_slugify_accent_handling(self):
        from painel.registry import slugify
        self.assertEqual("financas", lint.fold("Finanças"))
        self.assertEqual("financas", slugify("Finanças"))


class LintBoardTest(unittest.TestCase):
    def test_findings_shape(self):
        findings = lint.lint_board(_board(INCIDENT_3))
        self.assertEqual(1, len(findings))
        f = findings[0]
        self.assertEqual("cl", f.block)
        self.assertEqual("i1", f.item)
        self.assertEqual(INCIDENT_3, f.text)
        self.assertEqual("question", f.suggestion)
        self.assertIn("responder", f.reason)

    def test_finding_is_json_serializable(self):
        f = lint.lint_board(_board(INCIDENT_3))[0]
        self.assertEqual(INCIDENT_3, json.loads(json.dumps(f._asdict()))["text"])

    def test_board_order_preserved(self):
        board = _board("Fazer login", "Qual é o IBAN?", "Descarregar o PDF", "Definir o preço")
        self.assertEqual(["i2", "i4"], [f.item for f in lint.lint_board(board)])

    def test_clean_board_has_no_findings(self):
        self.assertEqual([], lint.lint_board(_board(*PLAIN_ACTIONS)))

    def test_board_without_checklist_blocks(self):
        board = {"title": "T", "blocks": [
            {"id": "q1", "type": "question", "prompt": "Qual é o IBAN?"},
            {"id": "n1", "type": "note", "text": "Responder ao banco"},
        ]}
        self.assertEqual([], lint.lint_board(board),
                         "only `checklist` is linted in M16 (§20.3)")

    def test_malformed_input_never_raises(self):
        for board in (None, [], {}, {"blocks": None}, {"blocks": ["oops"]},
                      {"blocks": [{"type": "checklist", "items": None}]},
                      {"blocks": [{"type": "checklist", "items": ["oops"]}]},
                      {"blocks": [{"type": "checklist"}]}):
            with self.subTest(board=board):
                self.assertEqual([], lint.lint_board(board))

    def test_lint_block_matches_lint_board(self):
        board = _board(INCIDENT_3, "Fazer login")
        self.assertEqual(lint.lint_board(board), lint.lint_block(board["blocks"][0]))
        self.assertEqual([], lint.lint_block({"type": "note", "text": "Qual?"}))


class WarnOnceTest(unittest.TestCase):
    def setUp(self):
        lint.reset_warnings()

    def tearDown(self):
        lint.reset_warnings()

    def test_same_finding_logs_once(self):
        f = lint.lint_board(_board(INCIDENT_3))[0]
        out = io.StringIO()
        self.assertTrue(lint.warn_once(f, stream=out))
        self.assertFalse(lint.warn_once(f, stream=out))
        self.assertEqual(1, out.getvalue().count("[painel:lint]"))

    def test_rendering_the_same_board_twice_logs_once(self):
        """render() runs on every 2s poll tick -- one line per render would
        flood ~/.painel/service.log (§20.2)."""
        board = _board(INCIDENT_3)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            checklist.render(board["blocks"][0], {"index": 0, "total": 1})
            checklist.render(board["blocks"][0], {"index": 0, "total": 1})
        self.assertEqual(1, err.getvalue().count("[painel:lint]"))

    def test_edited_text_is_a_new_finding(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            checklist.render(_board(INCIDENT_3)["blocks"][0], {"index": 0, "total": 1})
            checklist.render(_board("Qual é o IBAN?")["blocks"][0], {"index": 0, "total": 1})
        self.assertEqual(2, err.getvalue().count("[painel:lint]"))

    def test_clean_item_logs_nothing(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            checklist.render(_board(*PLAIN_ACTIONS)["blocks"][0], {"index": 0, "total": 1})
        self.assertEqual("", err.getvalue())


class RenderMarkerTest(unittest.TestCase):
    def setUp(self):
        lint.reset_warnings()

    def tearDown(self):
        lint.reset_warnings()

    def _render(self, *texts):
        with contextlib.redirect_stderr(io.StringIO()):
            return checklist.render(_board(*texts)["blocks"][0], {"index": 0, "total": 1})

    def test_flagged_item_renders_the_marker(self):
        html = self._render(INCIDENT_3)
        self.assertIn("lint-warn", html)
        self.assertIn("&#9888;", html)

    def test_marker_copy_points_at_the_per_item_question_button(self):
        html = self._render(INCIDENT_3)
        self.assertIn("❓", html, "the ⚠ copy must point at M12's per-item ❓ (§20.2 layer 3)")

    def test_unflagged_item_renders_no_marker(self):
        html = self._render(*PLAIN_ACTIONS)
        self.assertNotIn("lint-warn", html)

    def test_marker_does_not_disturb_existing_markup(self):
        """Non-blocking (§20.2): the item still renders, checkbox and ❓ intact."""
        html = self._render(INCIDENT_3)
        self.assertIn('type="checkbox"', html)
        self.assertIn("check('cl','i1'", html)
        self.assertIn('id="cr-box-cl-i1"', html)
        self.assertIn("crSendItem('cl','i1')", html)
        self.assertIn(INCIDENT_3.split(" (")[0], html)

    def test_escaping_regression(self):
        html = self._render(f"Responder {XSS}")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("lint-warn", html)

    def test_escaping_regression_in_reason_bearing_text(self):
        # The reason is interpolated into the title attribute; a payload that
        # reaches it must still be escaped.
        html = self._render(f'{XSS} termina assim?')
        self.assertNotIn("<script>alert(1)</script>", html)


class LintCliTest(unittest.TestCase):
    def setUp(self):
        lint.reset_warnings()

    @contextlib.contextmanager
    def _board_file(self, board):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            save_board(path, board)
            yield d, path

    def _run(self, arg):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["lint", arg])
        return code, out.getvalue(), err.getvalue()

    def test_dirty_board_exits_1_and_prints_findings(self):
        with self._board_file(_board("Fazer login no portal X", INCIDENT_3)) as (_, path):
            code, _, err = self._run(path)
        self.assertEqual(1, code)
        self.assertIn("cl/i2", err)
        self.assertIn("question", err)
        self.assertIn("responder", err)
        self.assertNotIn("i1", err.replace("cl/i2", ""))

    def test_clean_board_exits_0(self):
        with self._board_file(_board(*PLAIN_ACTIONS)) as (_, path):
            code, out, _ = self._run(path)
        self.assertEqual(0, code)
        self.assertIn("sem problemas", out)

    def test_board_with_no_checklist_blocks_exits_0(self):
        board = {"title": "T", "blocks": [{"id": "q1", "type": "question", "prompt": "Qual?"}]}
        with self._board_file(board) as (_, path):
            code, out, _ = self._run(path)
        self.assertEqual(0, code)
        self.assertIn("sem problemas", out)

    def test_empty_board_exits_0(self):
        with self._board_file({"title": "T", "blocks": []}) as (_, path):
            self.assertEqual(0, self._run(path)[0])

    def test_directory_argument_resolves_default_board(self):
        with tempfile.TemporaryDirectory() as d:
            save_board(os.path.join(d, cli.DEFAULT_BOARD), _board(INCIDENT_3))
            self.assertEqual(1, self._run(d)[0])

    def test_missing_board_exits_1_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as d:
            code, _, err = self._run(os.path.join(d, "nope.json"))
        self.assertEqual(1, code)
        self.assertIn("não existe", err)

    def test_unreadable_board_exits_1_without_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            code, _, err = self._run(path)
        self.assertEqual(1, code)
        self.assertIn("não consegui ler", err)


if __name__ == "__main__":
    unittest.main()
