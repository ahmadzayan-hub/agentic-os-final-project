"""The agent answers in the language it was asked to.

The interface can be in Arabic; if the agent kept answering "Happy to
help!" underneath it, the language switch would be a coat of paint. These
tests pin that the agent's own replies — welcome, help, confirmations,
errors and the tone templates — follow the `language` preference, that
the preference accepts the spellings a person is likely to type, and
that English is untouched by default.
"""

import unittest

from agent import Agent, canonical_language, language_code


class SilentBackend:
    """A memory backend whose writes fail, to test the honest suffix."""

    persistent = True

    def load(self):
        return {}

    def save(self, payload):
        return False


def arabic_agent(**preferences):
    return Agent({"agent_name": "Agentic OS", "version": "1.0.0",
                  "preferences": {"language": "Arabic", **preferences}})


class LanguageCodeTestCase(unittest.TestCase):
    def test_the_spellings_a_person_types_are_recognised(self):
        for spelling in ("Arabic", "arabic", "AR", "العربية", "عربي", "عربية"):
            with self.subTest(spelling=spelling):
                self.assertEqual(language_code(spelling), "ar")
        for spelling in ("English", "en", "", None, "French"):
            with self.subTest(spelling=spelling):
                self.assertEqual(language_code(spelling), "en")

    def test_known_names_are_canonicalised_and_unknown_ones_kept(self):
        self.assertEqual(canonical_language("العربية"), "Arabic")
        self.assertEqual(canonical_language("ar"), "Arabic")
        self.assertEqual(canonical_language("english"), "English")
        # A wrong value is shown back, not silently corrected to something
        # the person did not say.
        self.assertEqual(canonical_language("French"), "French")


class ArabicRepliesTestCase(unittest.TestCase):
    def setUp(self):
        self.agent = arabic_agent()

    def test_the_welcome_is_arabic(self):
        welcome = self.agent.get_welcome_message()
        self.assertIn("مرحبًا بك في Agentic OS", welcome)
        self.assertIn("/help", welcome)
        self.assertNotIn("Welcome", welcome)

    def test_help_is_arabic_and_still_lists_every_command(self):
        help_text = self.agent.process_input("/help")
        self.assertIn("الأوامر المتاحة", help_text)
        for command in ("/help", "/remember", "/recall", "/forget", "/set",
                        "/preferences", "/history", "/clear", "/exit"):
            self.assertIn(command, help_text)

    def test_free_text_follows_the_tone_in_arabic(self):
        self.assertIn("يسعدني المساعدة", self.agent.process_input("مرحبا"))
        self.agent.process_input("/set tone concise")
        self.assertIn("استلمت:", self.agent.process_input("مرحبا"))
        self.agent.process_input("/set tone formal")
        self.assertIn("تم استلام طلبك", self.agent.process_input("مرحبا"))

    def test_memory_confirmations_are_arabic(self):
        self.assertEqual(self.agent.process_input("/remember لغتي العربية"),
                         "تم حفظ المعلومة.")
        self.assertIn("المعلومات المحفوظة:", self.agent.process_input("/recall"))
        self.assertEqual(self.agent.process_input("/forget memory_1"),
                         "تمت إزالة memory_1.")
        self.assertIn("لا توجد معلومة محفوظة باسم memory_9",
                      self.agent.process_input("/forget memory_9"))
        self.assertEqual(self.agent.process_input("/recall"),
                         "لم تُحفظ أي معلومات بعد.")

    def test_errors_and_the_empty_input_are_arabic(self):
        # Before anything is sent, so the history really is empty.
        self.assertEqual(self.agent.process_input("/history"),
                         "لا يوجد سجل محادثة متاح.")
        self.assertIn("أمر غير معروف: /teleport",
                      self.agent.process_input("/teleport"))
        self.assertEqual(self.agent.process_input("   "), "يُرجى إدخال أمر أو سؤال.")
        self.assertIn("الاستخدام:", self.agent.process_input("/set tone"))

    def test_a_failed_disk_write_is_reported_in_arabic(self):
        agent = Agent({"agent_name": "Agentic OS", "version": "1.0.0",
                       "preferences": {"language": "Arabic"}},
                      memory_backend=SilentBackend())
        reply = agent.process_input("/remember شيء")
        self.assertTrue(reply.startswith("تم حفظ المعلومة"), reply)
        self.assertIn("تعذّر كتابة التغيير", reply)

    def test_the_command_line_labels_follow_the_language(self):
        self.assertEqual(self.agent.text("you_label"), "أنت")
        self.assertEqual(self.agent.text("agent_label"), "الوكيل")


class SwitchingMidSessionTestCase(unittest.TestCase):
    def test_the_confirmation_is_already_in_the_new_language(self):
        agent = Agent({"agent_name": "Agentic OS", "version": "1.0.0"})
        self.assertIn("Happy to help", agent.process_input("hello"))
        reply = agent.process_input("/set language العربية")
        self.assertIn("تم تحديث التفضيل", reply)
        self.assertEqual(agent.preferences["language"], "Arabic")
        self.assertIn("يسعدني المساعدة", agent.process_input("hello"))

        reply = agent.process_input("/set language English")
        self.assertIn("Preference updated", reply)
        self.assertIn("Happy to help", agent.process_input("hello"))

    def test_an_unknown_language_falls_back_to_english_and_says_what_it_kept(self):
        agent = Agent({"agent_name": "Agentic OS", "version": "1.0.0"})
        self.assertIn("language = French", agent.process_input("/set language French"))
        self.assertEqual(agent.preferences["language"], "French")
        self.assertIn("Happy to help", agent.process_input("hello"))

    def test_english_is_the_default_and_unchanged(self):
        agent = Agent({"agent_name": "Agentic OS", "version": "1.0.0"})
        self.assertTrue(agent.get_welcome_message().startswith("Welcome to Agentic OS"))
        self.assertEqual(agent.process_input("/remember x"), "Information saved.")
        self.assertEqual(agent.text("you_label"), "You")


try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - CLI-only environments
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class SessionLanguageTestCase(unittest.TestCase):
    """The API carries the language: a session can be born in it, the
    command catalogue follows it, and switching it mid-session switches
    the welcome text and the next reply together."""

    def setUp(self):
        import json
        import tempfile
        from pathlib import Path

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        config_path = root / "config.json"
        config_path.write_text(json.dumps({
            "agent_name": "Agentic OS", "version": "1.0.0",
            "memory_file": str(root / "memory.json"),
            "database_file": str(root / "agentic.db"),
            "vault_dir": str(root / "vault"),
        }), encoding="utf-8")
        self.client = TestClient(create_app(config_path),
                                 raise_server_exceptions=False)

    def test_a_session_can_be_created_in_arabic(self):
        response = self.client.post("/api/sessions", json={"language": "Arabic"})
        self.assertEqual(response.status_code, 201)
        state = response.json()
        self.assertEqual(state["preferences"]["language"], "Arabic")
        self.assertIn("مرحبًا بك في Agentic OS", state["welcome"])
        descriptions = {c["command"]: c["description"] for c in state["commands"]}
        self.assertEqual(descriptions["/help"], "عرض الأوامر المتاحة")
        # The command itself is what a person types: unchanged.
        self.assertEqual(state["commands"][0]["usage"], "/help")

    def test_a_session_created_without_a_body_is_english_as_before(self):
        response = self.client.post("/api/sessions")
        self.assertEqual(response.status_code, 201)
        state = response.json()
        self.assertEqual(state["preferences"]["language"], "English")
        self.assertTrue(state["welcome"].startswith("Welcome to Agentic OS"))
        self.assertEqual(state["commands"][0]["description"], "Show available commands")

    def test_switching_the_preference_switches_welcome_commands_and_replies(self):
        state = self.client.post("/api/sessions").json()
        session_id = state["session_id"]
        response = self.client.put(f"/api/sessions/{session_id}/preferences",
                                   json={"key": "language", "value": "العربية"})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIn("تم تحديث التفضيل", result["reply_text"])
        self.assertEqual(result["state"]["preferences"]["language"], "Arabic")
        self.assertIn("مرحبًا بك", result["state"]["welcome"])
        self.assertEqual(result["state"]["commands"][0]["description"],
                         "عرض الأوامر المتاحة")

        reply = self.client.post(f"/api/sessions/{session_id}/messages",
                                 json={"text": "مرحبا"}).json()
        self.assertIn("يسعدني المساعدة", reply["reply"]["text"])

    def test_arabic_input_round_trips_through_the_transcript_intact(self):
        state = self.client.post("/api/sessions", json={"language": "Arabic"}).json()
        session_id = state["session_id"]
        text = "تذكّر أن الاجتماع الساعة الثامنة صباحًا"
        reply = self.client.post(f"/api/sessions/{session_id}/messages",
                                 json={"text": "/remember " + text[len("تذكّر "):]}).json()
        self.assertEqual(reply["reply"]["text"], "تم حفظ المعلومة.")
        entries = reply["state"]["memory_entries"]
        self.assertEqual(entries[0]["text"], "أن الاجتماع الساعة الثامنة صباحًا")


if __name__ == "__main__":
    unittest.main()
