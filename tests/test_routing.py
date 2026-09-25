"""Choosing the narrator, and saying who chose it.

These tests never import LLMRouter. That is the point of the contract
being one method wide: the integration is tested against
`route_single({"query": ...}) -> {"model_name": ...}`, so the suite stays
runnable on a machine with no torch, no CUDA wheels and no network —
which is every machine CI runs on.

`tests/test_llmrouter_integration.py` covers the other half: that a real
LLMRouter router satisfies this contract. It skips when the library is
absent, which is most of the time and deliberately so.
"""

import unittest

from server.model_gateway import ModelGateway
from server.routing import RoutedGateway, build_router, provider_for


class FakeRouter:
    """Whatever LLMRouter router you like, minus three gigabytes."""

    def __init__(self, answer, explode=False):
        self.answer = answer
        self.explode = explode
        self.seen = []

    def route_single(self, query):
        self.seen.append(query)
        if self.explode:
            raise RuntimeError("the router fell over")
        return {"model_name": self.answer}


def gateway_with(**env):
    """A gateway configured for providers, wired to call none of them.

    The keys below are fake, and a test that lets `narrate` reach for
    api.groq.com with a fake key is a test that is slow, flaky offline,
    and knocking on somebody's door for no reason. Stubbing the callers
    also makes the assertion sharper: it records which provider was
    actually invoked, not merely which one was chosen.
    """
    gateway = ModelGateway(env=env)
    gateway.called = []

    def caller(name):
        def call(goal, facts):
            gateway.called.append(name)
            return f"Summary from {name}."
        return call

    gateway._call_ollama = caller("ollama")
    gateway._call_anthropic = caller("anthropic")
    gateway._call_groq = caller("groq")
    return gateway


class ProviderMappingTestCase(unittest.TestCase):
    """A router names a model; this application knows providers."""

    def setUp(self):
        self.all = [{"provider": "ollama", "model": "llama3.1"},
                    {"provider": "anthropic", "model": "claude-sonnet-4-5"},
                    {"provider": "groq", "model": "openai/gpt-oss-120b"},
                    {"provider": "deterministic", "model": None}]

    def test_names_a_router_is_likely_to_produce_are_understood(self):
        for name, expected in (("claude-3-5-sonnet", "anthropic"),
                               ("gpt-4o", "groq"),
                               ("llama3.1:8b", "ollama"),
                               ("qwen3:4b", "ollama"),
                               ("mixtral-8x7b", "groq")):
            with self.subTest(name=name):
                self.assertEqual(provider_for(name, self.all), expected)

    def test_the_longest_matching_alias_wins(self):
        """"claude-sonnet-4-5" contains both "claude" and "claude-sonnet".
        They agree here, but a name that matched two different providers
        on a short alias would be resolved by luck of dict order."""
        aliases = [{"provider": "anthropic", "model": "x"},
                   {"provider": "groq", "model": "y"},
                   {"provider": "deterministic", "model": None}]
        self.assertEqual(provider_for("claude-sonnet-4-5", aliases), "anthropic")

    def test_an_unreachable_provider_is_not_a_match(self):
        """The router may be trained on a catalogue this deployment has
        never heard of. Returning it anyway would send the narration to
        a provider with no key."""
        only_local = [{"provider": "ollama", "model": "llama3.1"},
                      {"provider": "deterministic", "model": None}]
        self.assertIsNone(provider_for("claude-3-5-sonnet", only_local))

    def test_an_unknown_name_is_none_rather_than_a_guess(self):
        self.assertIsNone(provider_for("some-model-nobody-has", self.all))
        self.assertIsNone(provider_for("", self.all))
        self.assertIsNone(provider_for(None, self.all))


class PassThroughTestCase(unittest.TestCase):
    """With no router, nothing about the application changes."""

    def test_no_router_means_the_priority_order_still_applies(self):
        routed = RoutedGateway(gateway_with())
        result = routed.narrate("Goal", ["A fact."])
        self.assertEqual(result["source"], "deterministic")
        self.assertIsNone(result["routing"]["router"])
        self.assertIsNone(result["routing"]["provider"])

    def test_the_status_still_answers_what_it_always_answered(self):
        routed = RoutedGateway(gateway_with())
        status = routed.status()
        self.assertEqual(status["provider"], "deterministic")
        self.assertTrue(status["local_only"])
        self.assertIsNone(status["router"])


class RoutingDecisionTestCase(unittest.TestCase):
    def test_the_router_gets_the_facts_and_never_the_dataset(self):
        """The rule does not relax because the recipient runs locally."""
        router = FakeRouter("claude-3-5-sonnet")
        routed = RoutedGateway(gateway_with(ANTHROPIC_API_KEY="k"), router)
        routed.narrate("Why did revenue move?",
                       ["Revenue is up 45%.", "North is the biggest region."])
        sent = router.seen[0]["query"]
        self.assertIn("Revenue is up 45%", sent)
        self.assertIn("Why did revenue move?", sent)
        self.assertNotIn("month,region", sent)

    def test_an_honoured_choice_is_recorded_with_its_reason(self):
        gateway = gateway_with(GROQ_API_KEY="k")
        routed = RoutedGateway(gateway, FakeRouter("gpt-4o"))
        result = routed.narrate("Goal", ["A fact."])
        decision = result["routing"]
        self.assertTrue(decision["honoured"])
        self.assertEqual(decision["provider"], "groq")
        self.assertEqual(decision["chose"], "gpt-4o")
        self.assertIn("gpt-4o", decision["why"])
        self.assertEqual(gateway.called, ["groq"],
                         "the chosen provider is not the one that narrated")

    def test_the_router_can_overrule_the_priority_order(self):
        """Local-first is the gateway's default. A router that knows this
        report needs the stronger model has to be able to say so — and
        the call must actually go there."""
        gateway = gateway_with(OLLAMA_MODEL="qwen3:4b", ANTHROPIC_API_KEY="k")
        self.assertEqual(gateway.provider, "ollama")   # the default
        routed = RoutedGateway(gateway, FakeRouter("claude-sonnet-4-5"))
        result = routed.narrate("Goal", ["A fact."])
        self.assertEqual(gateway.called, ["anthropic"])
        self.assertTrue(result["routing"]["honoured"])

    def test_a_choice_this_deployment_cannot_reach_is_refused_not_substituted(self):
        """Silently narrating with a different model than the one chosen
        would make the report's "narrated by" line a lie."""
        routed = RoutedGateway(gateway_with(), FakeRouter("claude-3-5-sonnet"))
        decision = routed.narrate("Goal", ["A fact."])["routing"]
        self.assertFalse(decision["honoured"])
        self.assertEqual(decision["chose"], "claude-3-5-sonnet")
        self.assertIsNone(decision["provider"])
        self.assertIn("cannot reach", decision["why"])

    def test_a_router_that_fails_costs_a_decision_not_a_report(self):
        routed = RoutedGateway(gateway_with(), FakeRouter("x", explode=True))
        result = routed.narrate("Goal", ["A fact."])
        self.assertTrue(result["text"], "the report lost its summary")
        self.assertFalse(result["routing"]["honoured"])
        self.assertIn("failed", result["routing"]["why"])

    def test_a_router_that_answers_nothing_is_handled(self):
        class Silent:
            def route_single(self, query):
                return {}

        routed = RoutedGateway(gateway_with(), Silent())
        decision = routed.narrate("Goal", ["A fact."])["routing"]
        self.assertFalse(decision["honoured"])
        self.assertIsNone(decision["chose"])

    def test_the_status_names_the_router_and_what_it_may_choose_from(self):
        routed = RoutedGateway(gateway_with(OLLAMA_MODEL="qwen3:4b",
                                            GROQ_API_KEY="k"),
                               FakeRouter("qwen3:4b"))
        status = routed.status()
        self.assertEqual(status["router"], "FakeRouter")
        self.assertIn("ollama:qwen3:4b", status["candidates"])
        self.assertIn("groq:openai/gpt-oss-120b", status["candidates"])
        self.assertIn("deterministic", status["candidates"])


class ReportNoteTestCase(unittest.TestCase):
    """The sentence in the report that names the narrator."""

    def note(self, routing, source=None):
        from server.analytics import _routing_note

        return _routing_note(routing, source)

    def test_no_router_adds_nothing(self):
        self.assertEqual(self.note(None), "")
        self.assertEqual(self.note({"router": None}), "")

    def test_an_honoured_choice_that_answered_names_the_chooser(self):
        note = self.note({"router": "SmallestLLM", "honoured": True,
                          "chose": "qwen3:4b"}, source="model")
        self.assertIn("chosen by SmallestLLM", note)
        self.assertIn("qwen3:4b", note)

    def test_an_honoured_choice_that_did_not_answer_says_that_instead(self):
        """Otherwise the line reads "the deterministic narrator was
        chosen by SmallestLLM", which is not what happened."""
        note = self.note({"router": "SmallestLLM", "honoured": True,
                          "chose": "qwen3:4b"}, source="deterministic")
        self.assertIn("did not answer", note)
        self.assertNotIn("chosen by", note)

    def test_a_refused_choice_carries_the_reason(self):
        note = self.note({"router": "LargestLLM", "honoured": False,
                          "chose": "claude-sonnet-4-5",
                          "why": "The router chose it and it is unreachable."},
                         source="deterministic")
        self.assertIn("was not used", note)
        self.assertIn("unreachable", note)


class BuildRouterTestCase(unittest.TestCase):
    """Loading one is configuration, and configuration goes wrong."""

    def test_nothing_configured_is_not_an_error(self):
        router, name, problem = build_router(env={})
        self.assertIsNone(router)
        self.assertIsNone(problem)

    def test_a_missing_class_is_reported_as_a_sentence_not_an_exception(self):
        router, _name, problem = build_router(
            env={"AGENTIC_OS_ROUTER": "llmrouter.nope.NotARouter"})
        self.assertIsNone(router)
        self.assertIn("could not be loaded", problem)
        self.assertIn("falls back", problem)

    def test_a_path_that_is_not_a_dotted_class_says_so(self):
        router, _name, problem = build_router(
            env={"AGENTIC_OS_ROUTER": "SmallestLLM"})
        self.assertIsNone(router)
        self.assertIn("dotted path", problem)

    def test_a_loadable_router_is_returned_with_its_name(self):
        router, name, problem = build_router(
            env={"AGENTIC_OS_ROUTER": "tests.test_routing.AlwaysGroq"})
        self.assertIsNone(problem)
        self.assertEqual(name, "AlwaysGroq")
        self.assertEqual(router.route_single({"query": "x"})["model_name"],
                         "gpt-4o")


class MisconfigurationIsVisibleTestCase(unittest.TestCase):
    """A router that did not load has to be findable.

    The API answers this in /api/health. A worker is a bare process with
    no endpoint to ask, so the only place a typo in the dotted path can
    surface is its output — and a silent fallback to the priority order
    looks exactly like a working router that happens to agree with it.
    """

    def test_the_worker_says_so_rather_than_falling_back_in_silence(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr
        from pathlib import Path

        from server.worker import build_worker

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({
                "database_file": str(Path(tmp) / "worker.db"),
                "vault_dir": str(Path(tmp) / "vault"),
            }), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                build_worker(env={"AGENTIC_OS_ROUTER": "nope.NotARouter"},
                             config_path=str(config))

        said = stderr.getvalue()
        self.assertIn("nope.NotARouter", said)
        self.assertIn("could not be loaded", said)


class AlwaysGroq:
    """A router in four lines, which is the point of the narrow contract."""

    def route_single(self, query):
        return {"model_name": "gpt-4o"}


if __name__ == "__main__":
    unittest.main()
