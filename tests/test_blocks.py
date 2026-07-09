"""Per-block tests: render-empty, render-filled, apply-each-event,
needs_user-both-states, and an escaping regression test per §8 of SPEC.md."""
import os
import tempfile
import unittest

from painel.blocks import REGISTRY
from painel.blocks import heading, markdown, note, tasks, plan, checklist
from painel.blocks import question, choice, approval, form, log, chat, resources

XSS = '"<script>alert(1)</script>'


class RegistryTest(unittest.TestCase):
    def test_all_documented_types_registered(self):
        expected = {
            "heading", "markdown", "note", "tasks", "plan", "checklist",
            "question", "choice", "approval", "form", "log", "chat", "resources",
        }
        self.assertEqual(expected, set(REGISTRY.keys()))

    def test_template_not_registered(self):
        self.assertNotIn("_template", REGISTRY)
        # _template.py must have no TYPE attribute (or must not be picked up).
        from painel.blocks import _template
        self.assertFalse(hasattr(_template, "TYPE"))


def render_ctx(mod, block, index=0, total=1):
    return mod.render(block, {"index": index, "total": total})


class HeadingTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(heading, {"id": "h1", "type": "heading"})
        self.assertIn("<h2", html)

    def test_render_filled(self):
        html = render_ctx(heading, {"id": "h1", "type": "heading", "text": "Título"})
        self.assertIn("Título", html)

    def test_needs_user_none(self):
        self.assertEqual(heading.needs_user({"text": "x"}), [])

    def test_escaping(self):
        html = render_ctx(heading, {"id": "h1", "type": "heading", "text": XSS})
        self.assertNotIn("<script", html)


class MarkdownTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(markdown, {"id": "m1", "type": "markdown"})
        self.assertIn('class="card md"', html)

    def test_render_filled_inline_md(self):
        html = render_ctx(markdown, {"id": "m1", "type": "markdown", "text": "**bold** `code`"})
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)

    def test_needs_user_none(self):
        self.assertEqual(markdown.needs_user({"text": "x"}), [])

    def test_escaping(self):
        html = render_ctx(markdown, {"id": "m1", "type": "markdown", "text": XSS})
        self.assertNotIn("<script", html)


class NoteTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(note, {"id": "n1", "type": "note"})
        self.assertIn("note-info", html)

    def test_render_filled_tone(self):
        html = render_ctx(note, {"id": "n1", "type": "note", "tone": "danger", "text": "cuidado"})
        self.assertIn("note-danger", html)
        self.assertIn("cuidado", html)

    def test_needs_user_none(self):
        self.assertEqual(note.needs_user({"text": "x"}), [])

    def test_escaping(self):
        html = render_ctx(note, {"id": "n1", "type": "note", "tone": XSS, "text": XSS})
        self.assertNotIn("<script", html)


class TasksTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(tasks, {"id": "t1", "type": "tasks", "items": []})
        self.assertIn("0/0", html)

    def test_render_filled(self):
        b = {"id": "t1", "type": "tasks", "title": "Pipeline",
             "items": [{"text": "a", "status": "done"}, {"text": "b", "status": "pending"}]}
        html = render_ctx(tasks, b)
        self.assertIn("1/2 concluídas", html)
        self.assertIn("width:50%", html)

    def test_needs_user_none(self):
        self.assertEqual(tasks.needs_user({"items": []}), [])

    def test_escaping(self):
        b = {"id": "t1", "type": "tasks", "title": XSS, "items": [{"text": XSS, "status": XSS}]}
        html = render_ctx(tasks, b)
        self.assertNotIn("<script", html)


class PlanTest(unittest.TestCase):
    def _board(self):
        return {"id": "pl", "type": "plan", "title": "Plano", "items": [
            {"id": "p1", "text": "Passo 1", "status": "pending"},
            {"id": "p2", "text": "Passo 2", "status": "pending"},
        ]}

    def test_render_empty(self):
        html = render_ctx(plan, {"id": "pl", "type": "plan", "items": []})
        self.assertIn("0/0 concluídos", html)

    def test_render_filled(self):
        html = render_ctx(plan, self._board())
        self.assertIn("Passo 1", html)
        self.assertIn("planPlay", html)

    def test_apply_play_skip_move_edit_comment_seen(self):
        b = self._board()
        self.assertTrue(plan.apply(b, {"event": "plan_play", "item": "p1"}))
        self.assertEqual(b["items"][0]["status"], "wip")

        self.assertTrue(plan.apply(b, {"event": "plan_skip", "item": "p2"}))
        self.assertEqual(b["items"][1]["status"], "skipped")

        self.assertTrue(plan.apply(b, {"event": "plan_edit", "item": "p1", "value": "novo texto"}))
        self.assertEqual(b["items"][0]["text"], "novo texto")

        self.assertTrue(plan.apply(b, {"event": "plan_move", "item": "p2", "direction": "up"}))
        self.assertEqual(b["items"][0]["id"], "p2")

        self.assertTrue(plan.apply(b, {"event": "plan_comment", "item": "p1", "value": "pergunta"}))
        it = next(i for i in b["items"] if i["id"] == "p1")
        self.assertEqual(it["thread"][-1]["text"], "pergunta")
        self.assertEqual(it["seen"], 1)

        it["thread"].append({"from": "agent", "text": "resposta"})
        self.assertTrue(plan.apply(b, {"event": "plan_seen", "item": "p1"}))
        self.assertEqual(it["seen"], len(it["thread"]))

    def test_apply_unknown_event(self):
        b = self._board()
        self.assertFalse(plan.apply(b, {"event": "nonsense", "item": "p1"}))

    def test_needs_user_both_states(self):
        b = self._board()
        self.assertEqual(plan.needs_user(b), [])
        it = b["items"][0]
        it["thread"] = [{"from": "agent", "text": "resposta"}]
        it["seen"] = 0
        pending = plan.needs_user(b)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][0], "pl")

    def test_plan_seen_is_silent(self):
        self.assertIn("plan_seen", plan.SILENT_EVENTS)

    def test_escaping(self):
        b = {"id": XSS, "type": "plan", "title": XSS, "items": [
            {"id": XSS, "text": XSS, "status": XSS,
             "thread": [{"from": XSS, "text": XSS}]},
        ]}
        html = render_ctx(plan, b)
        self.assertNotIn("<script", html)


class ChecklistTest(unittest.TestCase):
    def _board(self):
        return {"id": "cl", "type": "checklist", "title": "Lista", "items": [
            {"id": "c1", "text": "Fazer isto", "checked": False},
        ]}

    def test_render_empty(self):
        html = render_ctx(checklist, {"id": "cl", "type": "checklist", "items": []})
        self.assertIn("checklist", html)

    def test_render_filled(self):
        html = render_ctx(checklist, self._board())
        self.assertIn("Fazer isto", html)

    def test_apply_check(self):
        b = self._board()
        self.assertTrue(checklist.apply(b, {"event": "check", "item": "c1", "checked": True}))
        self.assertTrue(b["items"][0]["checked"])

    def test_apply_unknown_event(self):
        b = self._board()
        self.assertFalse(checklist.apply(b, {"event": "nope", "item": "c1"}))

    def test_needs_user_both_states(self):
        b = self._board()
        self.assertEqual(len(checklist.needs_user(b)), 1)
        b["items"][0]["checked"] = True
        self.assertEqual(checklist.needs_user(b), [])

    def test_escaping(self):
        b = {"id": XSS, "type": "checklist", "title": XSS,
             "items": [{"id": XSS, "text": XSS, "checked": False}]}
        html = render_ctx(checklist, b)
        self.assertNotIn("<script", html)


class QuestionTest(unittest.TestCase):
    def test_render_empty_prompt(self):
        html = render_ctx(question, {"id": "q1", "type": "question"})
        self.assertIn("Enviar", html)

    def test_render_answered(self):
        html = render_ctx(question, {"id": "q1", "type": "question", "prompt": "?", "answer": "42"})
        self.assertIn("answered", html)
        self.assertIn("42", html)

    def test_apply_answer(self):
        b = {"id": "q1", "type": "question", "prompt": "?", "answer": None}
        self.assertTrue(question.apply(b, {"event": "answer", "value": "resposta"}))
        self.assertEqual(b["answer"], "resposta")

    def test_apply_unknown_event(self):
        b = {"id": "q1", "type": "question"}
        self.assertFalse(question.apply(b, {"event": "nope"}))

    def test_needs_user_both_states(self):
        b = {"id": "q1", "type": "question", "answer": None}
        self.assertEqual(len(question.needs_user(b)), 1)
        b["answer"] = "x"
        self.assertEqual(question.needs_user(b), [])

    def test_escaping(self):
        html = render_ctx(question, {"id": XSS, "type": "question", "prompt": XSS, "answer": XSS})
        self.assertNotIn("<script", html)
        html2 = render_ctx(question, {"id": XSS, "type": "question", "prompt": XSS, "answer": None})
        self.assertNotIn("<script", html2)


class ChoiceTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(choice, {"id": "ch", "type": "choice", "options": []})
        self.assertIn("opts", html)

    def test_render_filled_options(self):
        html = render_ctx(choice, {"id": "ch", "type": "choice", "prompt": "?", "options": ["A", "B"]})
        self.assertIn(">A<", html)
        self.assertIn(">B<", html)

    def test_render_selected(self):
        html = render_ctx(choice, {"id": "ch", "type": "choice", "prompt": "?", "selected": "A"})
        self.assertIn("answered", html)

    def test_apply_choose(self):
        b = {"id": "ch", "type": "choice", "selected": None}
        self.assertTrue(choice.apply(b, {"event": "choose", "value": "B"}))
        self.assertEqual(b["selected"], "B")

    def test_apply_unknown_event(self):
        b = {"id": "ch", "type": "choice"}
        self.assertFalse(choice.apply(b, {"event": "nope"}))

    def test_needs_user_both_states(self):
        b = {"id": "ch", "type": "choice", "selected": None}
        self.assertEqual(len(choice.needs_user(b)), 1)
        b["selected"] = "A"
        self.assertEqual(choice.needs_user(b), [])

    def test_escaping(self):
        b = {"id": XSS, "type": "choice", "prompt": XSS, "options": [XSS], "selected": None}
        html = render_ctx(choice, b)
        self.assertNotIn("<script", html)
        b2 = {"id": XSS, "type": "choice", "prompt": XSS, "selected": XSS}
        html2 = render_ctx(choice, b2)
        self.assertNotIn("<script", html2)


class ApprovalTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(approval, {"id": "ap", "type": "approval"})
        self.assertIn("Aprovar", html)

    def test_render_decided(self):
        html = render_ctx(approval, {"id": "ap", "type": "approval", "prompt": "?",
                                      "decision": "approved", "comment": "ok"})
        self.assertIn("answered", html)
        self.assertIn("ok", html)

    def test_apply_approve(self):
        b = {"id": "ap", "type": "approval", "decision": None}
        self.assertTrue(approval.apply(b, {"event": "approve", "decision": "rejected", "comment": "no"}))
        self.assertEqual(b["decision"], "rejected")
        self.assertEqual(b["comment"], "no")

    def test_apply_unknown_event(self):
        b = {"id": "ap", "type": "approval"}
        self.assertFalse(approval.apply(b, {"event": "nope"}))

    def test_needs_user_both_states(self):
        b = {"id": "ap", "type": "approval", "decision": None}
        self.assertEqual(len(approval.needs_user(b)), 1)
        b["decision"] = "approved"
        self.assertEqual(approval.needs_user(b), [])

    def test_escaping(self):
        b = {"id": XSS, "type": "approval", "prompt": XSS, "decision": XSS, "comment": XSS}
        html = render_ctx(approval, b)
        self.assertNotIn("<script", html)
        b2 = {"id": XSS, "type": "approval", "prompt": XSS, "decision": None}
        html2 = render_ctx(approval, b2)
        self.assertNotIn("<script", html2)


class FormTest(unittest.TestCase):
    def _board(self):
        return {"id": "fm", "type": "form", "prompt": "Dados:", "fields": [
            {"id": "nome", "label": "Nome", "kind": "text", "value": ""},
        ], "submitted": False}

    def test_render_empty_fields(self):
        html = render_ctx(form, {"id": "fm", "type": "form", "fields": []})
        self.assertIn("Enviar", html)

    def test_render_filled(self):
        html = render_ctx(form, self._board())
        self.assertIn("Nome", html)

    def test_render_submitted(self):
        b = self._board()
        b["submitted"] = True
        b["fields"][0]["value"] = "Rafael"
        html = render_ctx(form, b)
        self.assertIn("answered", html)
        self.assertIn("Rafael", html)

    def test_apply_submit(self):
        b = self._board()
        self.assertTrue(form.apply(b, {"event": "submit", "values": {"nome": "Rafael"}}))
        self.assertEqual(b["fields"][0]["value"], "Rafael")
        self.assertTrue(b["submitted"])

    def test_apply_unknown_event(self):
        b = self._board()
        self.assertFalse(form.apply(b, {"event": "nope"}))

    def test_needs_user_both_states(self):
        b = self._board()
        self.assertEqual(len(form.needs_user(b)), 1)
        b["submitted"] = True
        self.assertEqual(form.needs_user(b), [])

    def test_escaping(self):
        b = {"id": XSS, "type": "form", "prompt": XSS, "fields": [
            {"id": XSS, "label": XSS, "kind": XSS, "value": XSS, "options": [XSS]},
        ], "submitted": False}
        html = render_ctx(form, b)
        self.assertNotIn("<script", html)
        b2 = dict(b, submitted=True)
        html2 = render_ctx(form, b2)
        self.assertNotIn("<script", html2)


class LogTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(log, {"id": "lg", "type": "log", "entries": []})
        self.assertIn("Registo", html)

    def test_render_filled(self):
        html = render_ctx(log, {"id": "lg", "type": "log", "entries": [{"ts": "10:00", "text": "início"}]})
        self.assertIn("início", html)

    def test_needs_user_none(self):
        self.assertEqual(log.needs_user({"entries": []}), [])

    def test_escaping(self):
        b = {"id": XSS, "type": "log", "title": XSS, "entries": [{"ts": XSS, "text": XSS}]}
        html = render_ctx(log, b)
        self.assertNotIn("<script", html)


class ChatTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(chat, {"id": "chat", "type": "chat", "messages": []})
        self.assertIn("chat-card", html)
        self.assertIn("chatSend", html)

    def test_render_filled_order_and_classes(self):
        b = {"id": "chat", "type": "chat", "title": "Conversa", "messages": [
            {"from": "user", "text": "Olá"},
            {"from": "agent", "text": "Olá! Em que posso ajudar?"},
            {"from": "user", "text": "Explica X"},
        ]}
        html = render_ctx(chat, b)
        self.assertIn('class="thread-msg user"', html)
        self.assertIn('class="thread-msg agent"', html)
        # Newest-at-bottom: messages must render in original (chronological) order.
        self.assertLess(html.index("Olá!"), html.index("Explica X"))
        self.assertLess(html.index("Olá<"), html.index("Olá!"))

    def test_render_shows_status_chip_when_ctx_has_agent_status(self):
        b = {"id": "chat", "type": "chat", "messages": []}
        html = chat.render(b, {"index": 0, "total": 1, "agent_status": "working"})
        self.assertIn("chat-chip", html)
        self.assertIn("a trabalhar", html)

    def test_render_no_chip_when_agent_status_absent(self):
        html = render_ctx(chat, {"id": "chat", "type": "chat", "messages": []})
        self.assertNotIn("chat-chip", html)

    def test_apply_chat_message(self):
        b = {"id": "chat", "type": "chat", "messages": []}
        self.assertTrue(chat.apply(b, {"event": "chat_message", "value": "Olá agente"}))
        self.assertEqual(b["messages"], [{"from": "user", "text": "Olá agente"}])
        # A second message appends, doesn't replace.
        self.assertTrue(chat.apply(b, {"event": "chat_message", "value": "segunda"}))
        self.assertEqual(len(b["messages"]), 2)
        self.assertEqual(b["messages"][-1]["text"], "segunda")

    def test_apply_unknown_event(self):
        b = {"id": "chat", "type": "chat", "messages": []}
        self.assertFalse(chat.apply(b, {"event": "nonsense"}))
        self.assertEqual(b["messages"], [])

    def test_chat_message_not_silent(self):
        self.assertNotIn("chat_message", chat.SILENT_EVENTS)

    def test_needs_user_always_empty(self):
        # Judgment call (docs/SPEC.md §5.5, see chat.needs_user docstring):
        # a chat awaiting an agent reply is NOT something the human is
        # waiting on, so it must never populate the human-facing attention
        # bar (§6.2) -- regardless of who sent the last message.
        self.assertEqual(chat.needs_user({"id": "chat", "messages": []}), [])
        b_user_last = {"id": "chat", "messages": [
            {"from": "agent", "text": "oi"},
            {"from": "user", "text": "responde-me"},
        ]}
        self.assertEqual(chat.needs_user(b_user_last), [])
        b_agent_last = {"id": "chat", "messages": [
            {"from": "user", "text": "oi"},
            {"from": "agent", "text": "resposta"},
        ]}
        self.assertEqual(chat.needs_user(b_agent_last), [])

    def test_escaping(self):
        b = {"id": XSS, "type": "chat", "title": XSS,
             "messages": [{"from": XSS, "text": XSS}]}
        html = render_ctx(chat, b)
        self.assertNotIn("<script", html)


class ResourcesTest(unittest.TestCase):
    def test_render_empty(self):
        html = render_ctx(resources, {"id": "res1", "type": "resources", "items": []})
        self.assertIn("res-list", html)

    def test_render_file_shows_recent_freshness(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mockup.png")
            with open(path, "w") as fh:
                fh.write("x")
            b = {"id": "res1", "type": "resources", "items": [
                {"label": "Mockup", "kind": "file", "path": path},
            ]}
            html = render_ctx(resources, b)
            self.assertIn("atualizado", html)
            self.assertNotIn("não encontrado", html)

    def test_render_missing_path_shows_warning_not_crash(self):
        b = {"id": "res1", "type": "resources", "items": [
            {"label": "Ficheiro perdido", "kind": "file", "path": "/no/such/path.pdf"},
        ]}
        html = render_ctx(resources, b)
        self.assertIn("ficheiro não encontrado", html)

    def test_render_url_item_no_freshness_target_blank(self):
        b = {"id": "res1", "type": "resources", "items": [
            {"label": "Figma", "kind": "url", "url": "https://figma.com/x"},
        ]}
        html = render_ctx(resources, b)
        self.assertNotIn("atualizado", html)
        self.assertNotIn("não encontrado", html)
        self.assertIn('target="_blank"', html)
        self.assertIn('href="https://figma.com/x"', html)

    def test_render_image_file_gets_thumbnail(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shot.png")
            with open(path, "w") as fh:
                fh.write("x")
            b = {"id": "res1", "type": "resources", "items": [
                {"label": "Screenshot", "kind": "file", "path": path},
            ]}
            html = render_ctx(resources, b)
            self.assertIn(f'src="file://{path}"', html)

    def test_render_non_image_file_no_thumbnail(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "report.pdf")
            with open(path, "w") as fh:
                fh.write("x")
            b = {"id": "res1", "type": "resources", "items": [
                {"label": "Relatório", "kind": "file", "path": path},
            ]}
            html = render_ctx(resources, b)
            self.assertNotIn("<img", html)
            self.assertIn("res-glyph", html)

    def test_render_folder_never_gets_thumbnail(self):
        with tempfile.TemporaryDirectory() as d:
            b = {"id": "res1", "type": "resources", "items": [
                {"label": "Pasta", "kind": "folder", "path": d},
            ]}
            html = render_ctx(resources, b)
            self.assertNotIn("<img", html)

    def test_apply_unknown_event(self):
        self.assertFalse(resources.apply({"id": "res1"}, {"event": "nonsense"}))

    def test_needs_user_always_empty(self):
        self.assertEqual(resources.needs_user({"items": [{"kind": "file", "path": "/x"}]}), [])

    def test_watched_paths_excludes_url(self):
        b = {"id": "res1", "type": "resources", "items": [
            {"label": "a", "kind": "file", "path": "/tmp/a.png"},
            {"label": "b", "kind": "folder", "path": "/tmp/b"},
            {"label": "c", "kind": "url", "url": "https://example.com"},
        ]}
        self.assertEqual(resources.watched_paths(b), ["/tmp/a.png", "/tmp/b"])

    def test_watched_paths_empty_when_no_items(self):
        self.assertEqual(resources.watched_paths({"items": []}), [])

    def test_escaping(self):
        b = {"id": XSS, "type": "resources", "title": XSS, "items": [
            {"label": XSS, "kind": "file", "path": XSS},
            {"label": XSS, "kind": "url", "url": XSS},
        ]}
        html = render_ctx(resources, b)
        self.assertNotIn("<script", html)


if __name__ == "__main__":
    unittest.main()
