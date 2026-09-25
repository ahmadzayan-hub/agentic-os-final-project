"""The other half of the contract: a real LLMRouter router satisfies it.

`tests/test_routing.py` tests this application's side against a fake, so
the suite runs anywhere. This file tests the assumption that fake stands
for — that LLMRouter's routers really do answer
`route_single({"query": ...})` with a `model_name` — by loading two of
them for real.

It skips when LLMRouter is not installed, which is the normal case:
the library brings torch, transformers and CUDA wheels, and a project
whose CLI needs only the standard library cannot require that of anyone.
Skipping is therefore expected, not a gap — but on a machine that has it
(and in any CI job that installs it), the assumption gets checked
instead of assumed.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from server.model_gateway import ModelGateway
from server.routing import RoutedGateway, build_router

LLMROUTER_AVAILABLE = importlib.util.find_spec("llmrouter") is not None

# The candidates this application can actually reach, in the shape
# LLMRouter's DataLoader expects. Sizes are what the heuristic routers
# sort on; prices are what a cost-aware router would.
CANDIDATES = {
    "qwen3:4b": {
        "size": "4B",
        "feature": "Local Ollama model; nothing leaves the machine.",
        "input_price": 0.0, "output_price": 0.0,
        "model": "qwen3:4b", "service": "ollama",
    },
    "claude-sonnet-4-5": {
        "size": "200B",
        "feature": "Hosted Anthropic model for longer, harder summaries.",
        "input_price": 3.0, "output_price": 15.0,
        "model": "claude-sonnet-4-5", "service": "anthropic",
    },
    "gpt-oss-120b": {
        "size": "120B",
        "feature": "Hosted Groq model, fast and inexpensive.",
        "input_price": 0.15, "output_price": 0.6,
        "model": "openai/gpt-oss-120b", "service": "groq",
    },
}


def write_config(root):
    """A router config describing this application's own candidates."""
    candidates = root / "agentic_candidates.json"
    candidates.write_text(json.dumps(CANDIDATES, indent=1), encoding="utf-8")
    config = root / "router.yaml"
    config.write_text(
        "data_path:\n"
        f"  llm_data: '{candidates}'\n"
        "metric:\n  weights:\n    performance: 1\n    cost: 0\n",
        encoding="utf-8")
    return config


@unittest.skipUnless(LLMROUTER_AVAILABLE, "llmrouter is not installed")
class RealRouterTestCase(unittest.TestCase):
    """Two of LLMRouter's heuristic routers, loaded and asked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = write_config(Path(self.tmp.name))

    def gateway(self):
        """Both hosted and local configured, with no call ever made."""
        gateway = ModelGateway(env={"OLLAMA_MODEL": "qwen3:4b",
                                    "ANTHROPIC_API_KEY": "not-a-real-key"})
        gateway.called = []
        for name in ("ollama", "anthropic", "groq"):
            def call(goal, facts, _name=name):
                gateway.called.append(_name)
                return f"Summary from {_name}."
            setattr(gateway, f"_call_{name}", call)
        return gateway

    def test_a_real_router_answers_the_contract_this_project_relies_on(self):
        from llmrouter.models.largest_llm.router import LargestLLM

        router = LargestLLM(str(self.config))
        answer = router.route_single({"query": "Summarise this for a board."})
        self.assertIn("model_name", answer,
                      "LLMRouter's contract changed; server/routing.py rests "
                      "on route_single returning a model_name")
        self.assertIn(answer["model_name"], CANDIDATES)

    def test_the_largest_router_overrules_the_local_first_default(self):
        """The gateway prefers local. A router that judges this report
        worth the stronger model has to be able to say so, and the call
        must actually go there."""
        from llmrouter.models.largest_llm.router import LargestLLM

        gateway = self.gateway()
        self.assertEqual(gateway.provider, "ollama")
        routed = RoutedGateway(gateway, LargestLLM(str(self.config)),
                               "LargestLLM")
        result = routed.narrate("Why did revenue move?",
                                ["Revenue is up 45% over the period."])
        self.assertEqual(result["routing"]["chose"], "claude-sonnet-4-5")
        self.assertEqual(result["routing"]["provider"], "anthropic")
        self.assertTrue(result["routing"]["honoured"])
        self.assertEqual(gateway.called, ["anthropic"])

    def test_the_smallest_router_keeps_the_narration_on_the_local_model(self):
        from llmrouter.models.smallest_llm.router import SmallestLLM

        gateway = self.gateway()
        routed = RoutedGateway(gateway, SmallestLLM(str(self.config)),
                               "SmallestLLM")
        result = routed.narrate("Why did revenue move?",
                                ["Revenue is up 45% over the period."])
        self.assertEqual(result["routing"]["chose"], "qwen3:4b")
        self.assertEqual(result["routing"]["provider"], "ollama")
        self.assertEqual(gateway.called, ["ollama"])

    def test_a_router_choice_this_deployment_cannot_reach_is_refused(self):
        """With nothing configured, the router still chooses — and the
        run says the choice was not used rather than pretending it was."""
        from llmrouter.models.largest_llm.router import LargestLLM

        routed = RoutedGateway(ModelGateway(env={}),
                               LargestLLM(str(self.config)), "LargestLLM")
        result = routed.narrate("Goal", ["A fact."])
        self.assertEqual(result["routing"]["chose"], "claude-sonnet-4-5")
        self.assertFalse(result["routing"]["honoured"])
        self.assertEqual(result["source"], "deterministic")

    def test_it_loads_from_configuration_the_way_an_operator_would(self):
        """The dotted path and the YAML, exactly as the two environment
        variables carry them."""
        router, name, problem = build_router(env={
            "AGENTIC_OS_ROUTER":
                "llmrouter.models.smallest_llm.router.SmallestLLM",
            "AGENTIC_OS_ROUTER_CONFIG": str(self.config),
        })
        self.assertIsNone(problem)
        self.assertEqual(name, "SmallestLLM")
        self.assertEqual(
            router.route_single({"query": "x"})["model_name"], "qwen3:4b")


if __name__ == "__main__":
    unittest.main()
