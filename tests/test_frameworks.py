"""The framework examples, run with fakes in place of any model.

Each class skips when its library is absent — the libraries are
optional and CI does not install them (ADR 0021). Installed, the tests
prove three things: the LangGraph runtime loops, stops, and remembers
its thread; the Pydantic AI runtime drives the same tool box through
the framework's own loop; and a stage built as a LangGraph graph is
audited by the pipeline exactly like a stage written in plain
functions.
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent import Agent
from server.assistant import Assistant
from server.model_gateway import ModelGateway
from server.runs import RunEngine
from server.storage import open_store
from server.tools import ToolBox

try:
    import langgraph  # noqa: F401
    LANGGRAPH = True
except ImportError:  # pragma: no cover
    LANGGRAPH = False

try:
    import pydantic_ai  # noqa: F401
    PYDANTIC_AI = True
except ImportError:  # pragma: no cover
    PYDANTIC_AI = False


class FakeSession:
    def __init__(self, agent):
        self.agent = agent
        self.owner = "local-owner"
        self.transcript = []
        self.id = "thread-1"


def workspace(directory, stages=None):
    store = open_store(None, Path(directory) / "agentic.db")
    engine = RunEngine(store, Path(directory) / "vault", ModelGateway(env={}),
                       stages=stages or {})
    session = FakeSession(Agent({"agent_name": "Agentic OS", "version": "1.0.0"}))
    return engine, Assistant(ModelGateway(env={}), engine), session


def settle(engine, run_id):
    for _ in range(60):
        run = engine.advance(run_id)
        if run["state"] not in ("queued", "running"):
            return run
    raise AssertionError("the run did not settle")


def scripted(*answers):
    """A gateway `ask` that answers from a script and records its prompts."""
    queue = list(answers)
    prompts = []

    def ask(system, user, max_tokens=None):
        prompts.append(user)
        return queue.pop(0) if queue else json.dumps({"reply": ""})

    ask.prompts = prompts
    return ask


@unittest.skipUnless(LANGGRAPH, "langgraph is not installed (optional)")
class LangGraphRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine, self.assistant, self.session = workspace(self.tmp.name)

    def context(self, ask):
        return {"language": "en", "notes": "Context: none", "thread_id": self.session.id,
                "ask": ask}

    def test_it_loops_through_the_tools_and_closes(self):
        from examples.runtimes.langgraph_runtime import LangGraphRuntime
        ask = scripted(
            json.dumps({"tool": "remember", "arguments": {"information": "Q4 review Monday"}}),
            json.dumps({"tool": "start_run", "arguments": {"goal": "Analyse the sample sales",
                                                           "dataset": "sample"}}),
            json.dumps({"reply": "Saved and started."}))
        tools = ToolBox(self.assistant, self.session)
        closing = LangGraphRuntime().run("note the review then analyse sales", tools,
                                         self.context(ask))
        self.assertEqual(closing, "Saved and started.")
        self.assertEqual([s["tool"] for s in tools.steps], ["remember", "start_run"])
        self.assertTrue(all(s["ok"] for s in tools.steps))
        self.assertIn("run_id", tools.last_result)
        self.assertIn("remember → ", ask.prompts[1], "the tool's text was fed back")

    def test_a_thread_remembers_what_the_tools_said(self):
        from examples.runtimes.langgraph_runtime import LangGraphRuntime
        runtime = LangGraphRuntime()
        first = scripted(json.dumps({"tool": "help", "arguments": {}}),
                         json.dumps({"reply": "ok"}))
        runtime.run("first", ToolBox(self.assistant, self.session), self.context(first))
        second = scripted(json.dumps({"reply": "still here"}))
        runtime.run("second", ToolBox(self.assistant, self.session), self.context(second))
        self.assertIn("help → ", second.prompts[0])
        other = scripted(json.dumps({"reply": "new thread"}))
        context = dict(self.context(other), thread_id="thread-2")
        runtime.run("elsewhere", ToolBox(self.assistant, self.session), context)
        self.assertNotIn("help → ", other.prompts[0])

    def test_it_stops_at_its_step_limit_and_on_a_refusal(self):
        from examples.runtimes.langgraph_runtime import LangGraphRuntime
        endless = scripted(*[json.dumps({"tool": "help", "arguments": {}})] * 20)
        tools = ToolBox(self.assistant, self.session)
        LangGraphRuntime(max_steps=3).run("loop", tools, self.context(endless))
        self.assertEqual(len(tools.steps), 3)
        deleter = scripted(json.dumps({"tool": "forget", "arguments": {"key": "all"}}),
                           json.dumps({"tool": "help", "arguments": {}}))
        tools = ToolBox(self.assistant, self.session)
        LangGraphRuntime().run("delete", tools, self.context(deleter))
        self.assertEqual([(s["tool"], s["ok"]) for s in tools.steps], [("forget", False)])

    def test_a_model_that_answers_prose_calls_nothing_and_declines(self):
        from examples.runtimes.langgraph_runtime import LangGraphRuntime
        tools = ToolBox(self.assistant, self.session)
        closing = LangGraphRuntime().run("hi", tools, self.context(scripted("Sure thing!")))
        self.assertIsNone(closing, "nothing called, nothing said: the ordinary path answers")
        self.assertEqual(tools.steps, [])
        tools = ToolBox(self.assistant, self.session)
        closing = LangGraphRuntime().run("hi", tools, self.context(
            scripted(json.dumps({"reply": "Just chatting."}))))
        self.assertEqual(closing, "Just chatting.")


@unittest.skipUnless(PYDANTIC_AI, "pydantic-ai is not installed (optional)")
class PydanticAIRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine, self.assistant, self.session = workspace(self.tmp.name)

    @staticmethod
    def model(turns):
        """A FunctionModel that plays the given responses in order."""
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
        queue = list(turns)

        def respond(messages, info):
            turn = queue.pop(0) if queue else ("text", "done")
            if turn[0] == "text":
                return ModelResponse(parts=[TextPart(turn[1])])
            return ModelResponse(parts=[ToolCallPart(name, args) for name, args in turn[1]])

        return FunctionModel(respond)

    def test_the_frameworks_loop_drives_the_same_tool_box(self):
        from examples.runtimes.pydantic_ai_runtime import PydanticAIRuntime
        model = self.model([
            ("tools", [("remember", {"information": "Q4 review Monday"}), ("recall", {})]),
            ("tools", [("start_run", {"goal": "Analyse the sample sales"})]),
            ("text", "Saved, recalled, started."),
        ])
        tools = ToolBox(self.assistant, self.session)
        closing = PydanticAIRuntime(model).run("do the things", tools,
                                               {"language": "en", "notes": ""})
        self.assertEqual(closing, "Saved, recalled, started.")
        self.assertEqual([s["tool"] for s in tools.steps], ["remember", "recall", "start_run"])
        self.assertIn("memory_1: Q4 review Monday", tools.steps[1]["text"])
        self.assertEqual(self.session.agent.memory, {"memory_1": "Q4 review Monday"})
        self.assertEqual(len(self.engine.list_runs(owner="local-owner")), 1)

    def test_a_refusal_reaches_the_model_and_nothing_is_deleted(self):
        from examples.runtimes.pydantic_ai_runtime import PydanticAIRuntime
        self.session.agent.process_input("remember coffee at 8")
        model = self.model([("tools", [("forget", {"key": "all"})]), ("text", "Could not.")])
        tools = ToolBox(self.assistant, self.session)
        # `forget` is not a registered tool, so the framework itself
        # refuses the call before the box sees it; either way nothing
        # is deleted and the model is told.
        closing = PydanticAIRuntime(model).run("delete it all", tools,
                                               {"language": "en", "notes": ""})
        self.assertEqual(self.session.agent.memory, {"memory_1": "coffee at 8"})
        self.assertNotIn("forget", [s["tool"] for s in tools.steps if s["ok"]])
        self.assertIsInstance(closing, str)

    def test_it_stops_when_the_model_will_not(self):
        from examples.runtimes.pydantic_ai_runtime import PydanticAIRuntime
        model = self.model([("tools", [("help", {})])] * 30)
        tools = ToolBox(self.assistant, self.session)
        closing = PydanticAIRuntime(model, max_steps=3).run("loop", tools,
                                                            {"language": "en", "notes": ""})
        self.assertEqual(closing, "")
        self.assertLessEqual(len(tools.steps), 4)
        self.assertGreater(len(tools.steps), 0)


@unittest.skipUnless(LANGGRAPH, "langgraph is not installed (optional)")
class GraphStageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_with(self, stage):
        engine, _, _ = workspace(self.tmp.name, stages={stage.role: stage})
        run = engine.create_run("Analyse the sample sales dataset")
        return engine, settle(engine, run["id"])

    @staticmethod
    def task(run, role):
        return next(t for t in run["tasks"] if t["role"] == role)

    def test_a_graph_built_stage_is_audited_like_any_other(self):
        from examples.stages.graph_stage import GroupFloor
        engine, run = self.run_with(GroupFloor(floor_share=0.1))
        roles = [t["role"] for t in run["tasks"]]
        self.assertEqual(roles.index("group_floor"), roles.index("sensitivity") + 1)
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertEqual(self.task(run, "group_floor")["state"], "succeeded")
        self.assertIn("at or above the 10% floor", self.task(run, "group_floor")["summary"])
        validator = self.task(run, "validator")
        self.assertTrue(all(c["passed"] for c in validator["quality_checks"]),
                        validator["quality_checks"])
        lineage = next(t for t in engine.store.get_tasks(run["id"]) if t["role"] == "lineage")
        produced = json.loads(lineage["result_json"])["output"]["produced_by_stage"]
        self.assertEqual(produced["group_floor.c_below"], "group_floor")
        report = run["report"]["content"]
        self.assertIn("## Custom stages", report)
        self.assertIn("| segments_below_floor | 0 |", report)
        section = next(s for s in run["reports"] if s["type"] == "group_floor")
        self.assertEqual(section["question"], "Which segments are below the floor?")
        self.assertIn("three-node graph", report)

    def test_it_flags_segments_under_the_floor(self):
        from examples.stages.graph_stage import GroupFloor
        _, run = self.run_with(GroupFloor(floor_share=0.5))
        summary = self.task(run, "group_floor")["summary"]
        self.assertIn("1 of 2 region segments are below the 50% floor", summary)
        self.assertEqual(run["state"], "awaiting_approval")

    def test_a_bad_floor_fails_the_stage_and_only_the_stage(self):
        from examples.stages.graph_stage import GroupFloor
        _, run = self.run_with(GroupFloor(floor_share=7))
        self.assertEqual(self.task(run, "group_floor")["state"], "failed")
        self.assertIn("between 0 and 1", self.task(run, "group_floor")["summary"])
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertIn("- **Group Floor Agent — which segments fall below the floor?:** "
                      "failed — The floor share must be between 0 and 1",
                      run["report"]["content"])


if __name__ == "__main__":
    unittest.main()
