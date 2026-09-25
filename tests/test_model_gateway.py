"""The model gateway: provider selection, and the limits on what a model
is allowed to do.

No test here touches the network. Provider calls are exercised by
substituting the one HTTP method, which is also the only place a
credential is ever used.
"""

import unittest

from server.model_gateway import ModelGateway


class ProviderSelectionTestCase(unittest.TestCase):
    def test_no_configuration_means_deterministic_and_offline(self):
        gateway = ModelGateway(env={})
        self.assertEqual(gateway.status(),
                         {"provider": "deterministic", "model": None,
                          "configured": False, "local_only": True})
        result = gateway.narrate("the goal", ["Revenue is up 45%."])
        self.assertEqual(result["source"], "deterministic")
        self.assertIn("Revenue is up 45%.", result["text"])

    def test_ollama_wins_because_nothing_leaves_the_machine(self):
        gateway = ModelGateway(env={"OLLAMA_MODEL": "llama3.1",
                                    "ANTHROPIC_API_KEY": "k", "GROQ_API_KEY": "k"})
        self.assertEqual(gateway.provider, "ollama")
        self.assertTrue(gateway.status()["local_only"])

    def test_anthropic_is_used_when_no_local_model_is_configured(self):
        gateway = ModelGateway(env={"ANTHROPIC_API_KEY": "k", "GROQ_API_KEY": "k"})
        self.assertEqual(gateway.provider, "anthropic")
        self.assertEqual(gateway.model, "claude-sonnet-4-5")
        self.assertFalse(gateway.status()["local_only"])

    def test_groq_remains_available(self):
        gateway = ModelGateway(env={"GROQ_API_KEY": "k", "GROQ_MODEL": "m"})
        self.assertEqual((gateway.provider, gateway.model), ("groq", "m"))

    def test_the_status_never_exposes_a_credential(self):
        gateway = ModelGateway(env={"ANTHROPIC_API_KEY": "secret-key-value"})
        self.assertNotIn("secret-key-value", repr(gateway.status()))


class ProviderCallTestCase(unittest.TestCase):
    """Each provider's request shape and response parsing, without a network."""

    def gateway_with(self, env, response):
        gateway = ModelGateway(env=env)
        self.sent = {}

        def fake_post(url, headers, payload):
            self.sent = {"url": url, "headers": headers, "payload": payload}
            return response

        gateway._post = fake_post
        return gateway

    def test_ollama_posts_to_the_local_host_and_reads_its_reply(self):
        gateway = self.gateway_with(
            {"OLLAMA_MODEL": "llama3.1", "OLLAMA_HOST": "http://127.0.0.1:11434"},
            {"message": {"content": "  Costs are rising.  "}})
        result = gateway.narrate("goal", ["Costs rose 12%."])
        self.assertEqual(result, {"text": "Costs are rising.", "source": "model"})
        self.assertEqual(self.sent["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(self.sent["headers"], {})  # no credential, none needed
        self.assertFalse(self.sent["payload"]["stream"])

    def test_anthropic_sends_the_versioned_header_and_reads_its_reply(self):
        gateway = self.gateway_with({"ANTHROPIC_API_KEY": "k"},
                                    {"content": [{"text": "Costs are rising."}]})
        result = gateway.narrate("goal", ["Costs rose 12%."])
        self.assertEqual(result["source"], "model")
        self.assertEqual(self.sent["headers"]["x-api-key"], "k")
        self.assertIn("anthropic-version", self.sent["headers"])

    def test_the_narrator_is_told_to_write_in_business_language(self):
        gateway = self.gateway_with({"OLLAMA_MODEL": "m"},
                                    {"message": {"content": "ok"}})
        gateway.narrate("goal", ["A fact."])
        system = self.sent["payload"]["messages"][0]["content"]
        self.assertIn("plain business language", system)
        self.assertIn("standard deviations", system)  # named as what NOT to write

    def test_only_verified_facts_are_sent__never_the_dataset(self):
        gateway = self.gateway_with({"OLLAMA_MODEL": "m"},
                                    {"message": {"content": "ok"}})
        gateway.narrate("Analyze sales", ["Total revenue is 3,583,440."])
        payload = repr(self.sent["payload"])
        self.assertIn("Total revenue is 3,583,440.", payload)
        # The prompt is the goal plus the fact list, and nothing else.
        user = self.sent["payload"]["messages"][1]["content"]
        self.assertEqual(user, "Goal: Analyze sales\nVerified facts:\n"
                               "- Total revenue is 3,583,440.")

    def test_a_reasoning_model_s_scratchpad_never_reaches_the_report(self):
        """qwen3, deepseek-r1 and friends think out loud in <think> tags.
        That is not an executive summary."""
        gateway = self.gateway_with(
            {"OLLAMA_MODEL": "qwen3:4b"},
            {"message": {"content":
                         "<think>The user wants a summary. Revenue rose 45%, so I "
                         "should lead with that. Let me check the numbers again…"
                         "</think>\n\nRevenue is up sharply, led by the North region."}})
        result = gateway.narrate("goal", ["Revenue rose 45%."])
        self.assertEqual(result["text"], "Revenue is up sharply, led by the North region.")
        self.assertNotIn("<think>", result["text"])
        self.assertNotIn("check the numbers again", result["text"])

    def test_a_reply_cut_off_mid_thought_falls_back_rather_than_leaking(self):
        gateway = self.gateway_with(
            {"OLLAMA_MODEL": "qwen3:4b"},
            {"message": {"content": "<think>Let me work through this. First the total"}})
        result = gateway.narrate("goal", ["Revenue rose 45%."])
        self.assertEqual(result["source"], "deterministic")
        self.assertNotIn("<think>", result["text"])

    def test_local_models_get_a_bigger_token_budget_to_think_with(self):
        gateway = self.gateway_with({"OLLAMA_MODEL": "qwen3:4b"},
                                    {"message": {"content": "ok"}})
        gateway.narrate("goal", ["A fact."])
        self.assertEqual(self.sent["payload"]["options"]["num_predict"], 600)

    def test_a_provider_failure_degrades_to_deterministic_and_says_so(self):
        for response in (None, {}, {"content": []}, {"message": {"content": "   "}}):
            with self.subTest(response=response):
                gateway = self.gateway_with({"OLLAMA_MODEL": "m"}, response)
                result = gateway.narrate("goal", ["A verified fact."])
                self.assertEqual(result["source"], "deterministic")
                self.assertIn("A verified fact.", result["text"])


if __name__ == "__main__":
    unittest.main()
