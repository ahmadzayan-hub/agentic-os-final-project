"""An agent runtime may drive several tools for one sentence — and nothing else.

Three layers, each with its own tests:

- **The catalogue** (`server/tools.py`) is the assistant's action set
  minus `chat` and the deletions, and a new action must be listed or
  hidden on purpose.
- **The tool box** runs the same executor the chat runs, refuses what
  is not offered, checks arguments by the same rule as a model's, caps
  the number of calls, and records every call, refused or not.
- **The seam** in the assistant: the rules keep every sentence they can
  place; the runtime gets the rest; what it called is on screen
  verbatim above its closing line; if it raises, the rules answer and
  the transcript says why. With nothing configured, nothing changes.
"""

import json
import tempfile
import unittest
from pathlib import Path

import assistant as rules
from agent import Agent
from server import analytics
from server.agent_runtime import build_runtime
from server.assistant import MAX_REPLY_CHARS, Assistant
from server.model_gateway import ModelGateway
from server.runs import RunEngine
from server.storage import open_store
from server.tools import MAX_STEPS, NAMES, TOOLS, ToolBox, describe


def make_agent(language="English"):
    return Agent({"agent_name": "Agentic OS", "version": "1.0.0",
                  "preferences": {"language": language, "tone": "friendly"}})


class FakeSession:
    def __init__(self, agent, owner="local-owner"):
        self.agent = agent
        self.owner = owner
        self.transcript = []
        self.id = "session-1"

    def add_entry(self, role, text, **extra):
        entry = {"role": role, "text": text}
        entry.update({k: v for k, v in extra.items() if v is not None})
        self.transcript.append(entry)
        return entry


def engine_in(directory):
    store = open_store(None, Path(directory) / "agentic.db")
    return RunEngine(store, Path(directory) / "vault", ModelGateway(env={}))


def finish(engine, run_id):
    for _ in range(40):
        run = engine.advance(run_id)
        if run["state"] not in ("queued", "running"):
            return run
    raise AssertionError("the run did not settle")


class ScriptedRuntime:
    """Calls what the test says, then says its closing line."""

    name = "Scripted"

    def __init__(self, calls=(), closing="All done.", trigger=None):
        self.calls = [tuple(c) for c in calls]
        self.closing = closing
        # With a trigger, only a message containing it is handled; any
        # other is declined (None) so the ordinary path answers it.
        self.trigger = trigger
        self.seen = None

    def run(self, message, tools, context):
        self.seen = {"message": message, "context": context,
                     "tools": tools.describe()}
        if self.trigger and self.trigger not in message.lower():
            return None
        for name, arguments in self.calls:
            tools.call(name, arguments)
        return self.closing


class FakeGateway:
    def __init__(self, answer):
        self.answer = answer

    def status(self):
        return {"provider": "ollama", "model": "fake", "configured": True,
                "local_only": True}

    def ask(self, system, user, provider=None, max_tokens=None):
        return self.answer


class RaisingRuntime(ScriptedRuntime):
    def run(self, message, tools, context):
        super().run(message, tools, context)
        raise RuntimeError("boom")


class NoRun:
    pass


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

class CatalogueTestCase(unittest.TestCase):
    def test_the_catalogue_is_the_action_set_minus_chat_and_deletions(self):
        self.assertEqual(set(NAMES), set(rules.ACTIONS) - {"chat"} - rules.DESTRUCTIVE)
        for tool in TOOLS:
            with self.subTest(tool=tool["name"]):
                schema = tool["inputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                self.assertTrue(set(schema["properties"]) <= set(rules.ACTIONS[tool["name"]]))
                self.assertTrue(set(schema["required"]) <= set(schema["properties"]))
                self.assertTrue(tool["description"].strip())

    def test_describe_hands_out_copies(self):
        described = describe()
        described[0]["name"] = "tampered"
        self.assertEqual(TOOLS[0]["name"], "help")


# ---------------------------------------------------------------------------
# The tool box
# ---------------------------------------------------------------------------

class ToolBoxTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = engine_in(self.tmp.name)
        self.assistant = Assistant(ModelGateway(env={}), self.engine)
        self.session = FakeSession(make_agent())
        self.tools = ToolBox(self.assistant, self.session)

    def test_a_tool_runs_the_same_executor_as_the_chat(self):
        saved = self.tools.call("remember", {"information": "coffee at 8"})
        self.assertTrue(saved["ok"])
        self.assertEqual(self.session.agent.memory, {"memory_1": "coffee at 8"})
        self.assertEqual(saved["text"], self.session.agent.process_input(
            "/remember coffee at 8").replace("memory_2", "memory_1"),
            "the tool's text is the slash command's own sentence")
        recalled = self.tools.call("recall", {})
        self.assertIn("memory_1: coffee at 8", recalled["text"])

    def test_start_run_creates_a_governed_run_and_status_reports_it(self):
        started = self.tools.call("start_run", {"goal": "Analyse the sample sales",
                                                "dataset": "sample"})
        self.assertTrue(started["ok"])
        run_id = started["result"]["run_id"]
        self.assertIn(run_id, started["text"])
        self.assertEqual(self.engine.get_run(run_id)["goal"], "Analyse the sample sales")
        self.assertEqual(self.tools.last_result, {"run_id": run_id})
        status = self.tools.call("run_status", {})
        self.assertIn(run_id, status["text"])

    def test_a_deletion_is_not_offered(self):
        self.session.agent.process_input("remember coffee at 8")
        for name, arguments in (("forget", {"key": "all"}), ("forget", {"key": "memory_1"}),
                                ("clear_history", {})):
            with self.subTest(tool=name):
                outcome = self.tools.call(name, arguments)
                self.assertFalse(outcome["ok"])
                self.assertIn("not offered", outcome["text"])
        self.assertEqual(self.session.agent.memory, {"memory_1": "coffee at 8"})
        self.assertEqual([s["ok"] for s in self.tools.steps], [False, False, False])

    def test_an_unknown_tool_is_named_and_the_catalogue_listed(self):
        outcome = self.tools.call("launch_rockets", {"target": "moon"})
        self.assertFalse(outcome["ok"])
        self.assertIn("no tool called “launch_rockets”", outcome["text"])
        self.assertIn("start_run", outcome["text"])

    def test_bad_arguments_are_refused_before_anything_runs(self):
        cases = (
            ("remember", {"information": "   "}),
            ("set_preference", {"key": "tone", "value": "shouty"}),
            ("set_preference", {"key": "colour", "value": "blue"}),
            ("start_run", {"goal": ["not", "text"]}),
            ("start_run", {}),
        )
        for name, arguments in cases:
            with self.subTest(tool=name, arguments=arguments):
                outcome = self.tools.call(name, arguments)
                self.assertFalse(outcome["ok"])
                self.assertIn("not valid", outcome["text"])
        self.assertEqual(self.session.agent.memory, {})
        self.assertEqual(self.engine.list_runs(owner="local-owner"), [])

    def test_arguments_outside_the_schema_are_dropped_not_passed(self):
        outcome = self.tools.call("remember", {"information": "coffee at 8",
                                               "category": "work", "priority": 9,
                                               "run_it": True})
        self.assertTrue(outcome["ok"])
        self.assertEqual(self.tools.steps[-1]["arguments"],
                         {"information": "coffee at 8", "category": "work"})

    def test_the_step_limit_holds(self):
        for _ in range(MAX_STEPS):
            self.assertTrue(self.tools.call("help", {})["ok"])
        extra = self.tools.call("start_run", {"goal": "one more"})
        self.assertFalse(extra["ok"])
        self.assertIn("step limit", extra["text"])
        self.assertEqual(len(self.tools.steps), MAX_STEPS + 1)
        self.assertEqual(self.engine.list_runs(owner="local-owner"), [])

    def test_refusals_follow_the_persons_language(self):
        arabic = ToolBox(self.assistant, FakeSession(make_agent("Arabic")))
        self.assertIn("غير متاح", arabic.call("forget", {"key": "all"})["text"])
        self.assertIn("لا توجد أداة", arabic.call("nothing", {})["text"])

    def test_every_call_is_on_the_record(self):
        self.tools.call("remember", {"information": 42})
        self.tools.call("forget", {"key": "all"})
        self.assertEqual([s["tool"] for s in self.tools.steps], ["remember", "forget"])
        self.assertEqual(self.tools.steps[0]["arguments"], {"information": "42"})
        self.assertTrue(self.tools.steps[0]["ok"])
        self.assertFalse(self.tools.steps[1]["ok"])
        for step in self.tools.steps:
            self.assertEqual(set(step), {"tool", "arguments", "ok", "text"})


# ---------------------------------------------------------------------------
# The seam in the assistant
# ---------------------------------------------------------------------------

class AssistantRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = engine_in(self.tmp.name)
        self.session = FakeSession(make_agent())

    def with_runtime(self, runtime):
        return Assistant(ModelGateway(env={}), self.engine, runtime=runtime,
                         runtime_name=runtime.name)

    def say(self, assistant, text):
        self.session.add_entry("user", text)
        outcome = assistant.handle(text, self.session)
        self.session.add_entry("agent", outcome["text"], source=outcome.get("source"),
                               action=outcome.get("action"), result=outcome.get("result"),
                               pending=outcome.get("pending"), steps=outcome.get("steps"))
        return outcome

    def test_the_rules_keep_what_they_can_place_and_the_runtime_gets_the_rest(self):
        runtime = ScriptedRuntime([("help", {})])
        assistant = self.with_runtime(runtime)
        outcome = self.say(assistant, "remember that coffee is at 8")
        self.assertEqual(outcome["source"], "rules")
        self.assertIsNone(runtime.seen, "an exact action must not reach the runtime")
        outcome = self.say(assistant, "please sort out the three things we discussed")
        self.assertEqual(outcome["source"], "runtime")
        self.assertEqual(runtime.seen["message"], "please sort out the three things we discussed")
        self.assertEqual([t["name"] for t in runtime.seen["tools"]], list(NAMES))

    def test_the_reply_shows_every_tools_text_verbatim_then_the_closing_line(self):
        runtime = ScriptedRuntime([
            ("remember", {"information": "the Q4 review is on Monday"}),
            ("start_run", {"goal": "Analyse the sample sales", "dataset": "sample"}),
        ], closing="Saved and started.")
        outcome = self.say(self.with_runtime(runtime),
                           "please sort out the two things we discussed")
        self.assertEqual(outcome["action"], "runtime")
        self.assertEqual(outcome["provider"], "Scripted")
        self.assertEqual([s["tool"] for s in outcome["steps"]], ["remember", "start_run"])
        run_id = outcome["result"]["run_id"]
        expected = "\n\n".join([outcome["steps"][0]["text"], outcome["steps"][1]["text"],
                                "Saved and started."])
        self.assertEqual(outcome["text"], expected)
        self.assertIn(run_id, outcome["text"])
        self.assertEqual(self.session.agent.memory, {"memory_1": "the Q4 review is on Monday"})

    def test_a_runtime_that_raises_falls_back_to_the_rules_and_keeps_the_record(self):
        runtime = RaisingRuntime([("remember", {"information": "coffee at 8"})])
        outcome = self.say(self.with_runtime(runtime), "do a few things for me")
        self.assertEqual(outcome["source"], "rules")
        self.assertIn("RuntimeError: boom", outcome["why"])
        self.assertIn("rules answered instead", outcome["why"])
        self.assertIn("not sure what", outcome["text"].lower())
        self.assertEqual([s["tool"] for s in outcome["steps"]], ["remember"])
        self.assertEqual(self.session.agent.memory, {"memory_1": "coffee at 8"},
                         "what ran before the failure happened, and is on record")

    def test_a_runtime_cannot_delete_even_when_it_tries(self):
        self.session.agent.process_input("remember coffee at 8")
        runtime = ScriptedRuntime([("forget", {"key": "all"}), ("clear_history", {}),
                                   ("forget", {"key": "memory_1"})], closing="Deleted everything.")
        outcome = self.say(self.with_runtime(runtime), "tidy up my stuff please")
        self.assertEqual(self.session.agent.memory, {"memory_1": "coffee at 8"})
        self.assertEqual([s["ok"] for s in outcome["steps"]], [False, False, False])
        self.assertIn("not offered", outcome["text"])
        self.assertIsNone(outcome.get("pending"))

    def test_the_runtime_is_shown_notes_but_never_a_row(self):
        self.session.agent.process_input("remember the Q4 review is on Monday")
        plain = Assistant(ModelGateway(env={}), self.engine)
        finish(self.engine, plain.handle("analyse the sample sales data",
                                         self.session)["result"]["run_id"])
        runtime = ScriptedRuntime()
        self.say(self.with_runtime(runtime), "tell me about things generally")
        context = runtime.seen["context"]
        self.assertEqual(context["language"], "en")
        self.assertEqual(context["thread_id"], "session-1")
        self.assertTrue(callable(context["ask"]))
        self.assertIn("the Q4 review is on Monday", context["notes"])
        self.assertIn("Latest analysis", context["notes"])
        for line in analytics.sample_dataset().splitlines()[:5]:
            self.assertNotIn(line, context["notes"], "a dataset row reached the runtime")

    def test_the_closing_line_is_capped_and_an_empty_one_is_the_fallback(self):
        long = ScriptedRuntime(closing="x" * (MAX_REPLY_CHARS * 3))
        outcome = self.say(self.with_runtime(long), "ramble for me")
        self.assertEqual(len(outcome["text"]), MAX_REPLY_CHARS)
        silent = ScriptedRuntime(closing="")
        outcome = self.say(self.with_runtime(silent), "say nothing useful")
        self.assertEqual(outcome["source"], "runtime")
        self.assertIn("not sure what", outcome["text"].lower())

    def test_a_runtime_may_decline_and_the_ordinary_path_answers(self):
        runtime = ScriptedRuntime([("help", {})], trigger="sort out")
        assistant = self.with_runtime(runtime)
        outcome = self.say(assistant, "tell me a joke")
        self.assertEqual(runtime.seen["message"], "tell me a joke")
        self.assertEqual(outcome["source"], "rules")
        self.assertEqual(outcome["action"], "chat")
        self.assertNotIn("steps", outcome)
        self.assertNotIn("why", outcome)
        self.assertIn("not sure what", outcome["text"].lower())
        outcome = self.say(assistant, "please sort out the three things")
        self.assertEqual(outcome["source"], "runtime")
        # Declining hands the sentence to the model when one is configured.
        gateway = FakeGateway(json.dumps({"action": "chat", "reply": "A model's joke."}))
        modelled = Assistant(gateway, self.engine, runtime=runtime, runtime_name="Scripted")
        outcome = self.say(modelled, "tell me a joke")
        self.assertEqual(outcome["source"], "model")
        self.assertEqual(outcome["text"], "A model's joke.")

    def test_a_runtime_that_called_something_cannot_decline(self):
        class CallsThenDeclines(ScriptedRuntime):
            def run(self, message, tools, context):
                tools.call("help", {})
                return None
        outcome = self.say(self.with_runtime(CallsThenDeclines()), "do a thing")
        self.assertEqual(outcome["source"], "runtime")
        self.assertEqual([s["tool"] for s in outcome["steps"]], ["help"])
        self.assertIn("Here is what I can do", outcome["text"])

    def test_with_no_runtime_nothing_changes(self):
        outcome = self.say(Assistant(ModelGateway(env={}), self.engine),
                           "please sort out the three things we discussed")
        self.assertEqual(outcome["source"], "rules")
        self.assertEqual(outcome["action"], "chat")
        self.assertNotIn("steps", outcome)

    def test_a_pending_confirmation_still_belongs_to_the_rules(self):
        self.session.agent.process_input("remember coffee at 8")
        runtime = ScriptedRuntime([("help", {})])
        assistant = self.with_runtime(runtime)
        self.assertEqual(self.say(assistant, "forget everything")["action"], "confirm")
        outcome = self.say(assistant, "yes")
        self.assertEqual(outcome["source"], "rules")
        self.assertEqual(self.session.agent.memory, {})
        self.assertIsNone(runtime.seen)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class LoaderTestCase(unittest.TestCase):
    def test_nothing_configured_loads_nothing(self):
        self.assertEqual(build_runtime(env={}, config={}), (None, None, None))

    def test_loads_by_dotted_path_with_options_from_config(self):
        runtime, name, problem = build_runtime(env={}, config={"agent_runtime": {
            "path": "tests.test_agent_runtime.ScriptedRuntime",
            "options": {"calls": [["help", {}]], "closing": "hi"}}})
        self.assertIsNone(problem)
        # By name, not isinstance: under discovery this module is imported
        # once as `test_agent_runtime` and once, by the loader, as
        # `tests.test_agent_runtime`, and those are two class objects.
        self.assertEqual(type(runtime).__name__, "ScriptedRuntime")
        self.assertEqual(name, "Scripted")
        self.assertEqual(runtime.calls, [("help", {})])
        self.assertEqual(runtime.closing, "hi")

    def test_loads_from_the_environment_variable(self):
        runtime, name, problem = build_runtime(
            env={"AGENTIC_OS_AGENT_RUNTIME": "tests.test_agent_runtime.ScriptedRuntime"},
            config={"agent_runtime": "ignored.when.env.is.set"})
        self.assertIsNone(problem)
        self.assertEqual(type(runtime).__name__, "ScriptedRuntime")
        self.assertEqual(name, "Scripted")

    def test_an_unloadable_runtime_is_a_sentence_not_a_crash(self):
        runtime, name, problem = build_runtime(env={"AGENTIC_OS_AGENT_RUNTIME": "nowhere.Nothing"},
                                               config={})
        self.assertIsNone(runtime)
        self.assertIn("could not be loaded", problem)
        self.assertIn("the rules answer every message", problem)

    def test_a_runtime_without_run_is_refused(self):
        runtime, name, problem = build_runtime(
            env={"AGENTIC_OS_AGENT_RUNTIME": "tests.test_agent_runtime.NoRun"}, config={})
        self.assertIsNone(runtime)
        self.assertIn("no run(message, tools, context)", problem)


# ---------------------------------------------------------------------------
# Over the API
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi not installed")
class RuntimeApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config_path = root / "config.json"
        self.config_path.write_text(json.dumps({
            "agent_name": "Agentic OS", "version": "1.0.0",
            "memory_file": str(root / "memory.json"),
            "database_file": str(root / "agentic.db"),
            "vault_dir": str(root / "vault"),
            "agent_runtime": {"path": "tests.test_agent_runtime.ScriptedRuntime",
                              "options": {"calls": [["help", {}]], "closing": "Over to you."}},
        }), encoding="utf-8")
        self.client = TestClient(create_app(self.config_path), raise_server_exceptions=False)

    def test_health_names_the_runtime(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["agent_runtime"], "Scripted")
        self.assertIsNone(body["runtime_problem"])

    def test_a_message_the_rules_cannot_place_comes_back_with_its_steps(self):
        sid = self.client.post("/api/sessions").json()["session_id"]
        reply = self.client.post(f"/api/sessions/{sid}/messages",
                                 json={"text": "please sort out the three things"}).json()["reply"]
        self.assertEqual(reply["source"], "runtime")
        self.assertEqual(reply["provider"], "Scripted")
        self.assertEqual(reply["action"], "runtime")
        self.assertEqual([s["tool"] for s in reply["steps"]], ["help"])
        self.assertTrue(reply["text"].endswith("Over to you."))
        self.assertIn("Here is what I can do", reply["text"])
        # And an exact sentence still never reaches it.
        reply = self.client.post(f"/api/sessions/{sid}/messages",
                                 json={"text": "remember that coffee is at 8"}).json()["reply"]
        self.assertEqual(reply["source"], "rules")
        self.assertNotIn("steps", reply)

    def test_a_broken_runtime_is_reported_and_the_rules_answer(self):
        root = Path(self.tmp.name)
        broken = root / "broken.json"
        broken.write_text(json.dumps({
            "agent_name": "Agentic OS", "version": "1.0.0",
            "memory_file": str(root / "memory2.json"),
            "database_file": str(root / "agentic2.db"),
            "vault_dir": str(root / "vault2"),
            "agent_runtime": "nowhere.Nothing"}), encoding="utf-8")
        client = TestClient(create_app(broken), raise_server_exceptions=False)
        health = client.get("/api/health").json()
        self.assertIsNone(health["agent_runtime"])
        self.assertIn("could not be loaded", health["runtime_problem"])
        sid = client.post("/api/sessions").json()["session_id"]
        reply = client.post(f"/api/sessions/{sid}/messages",
                            json={"text": "please sort out the three things"}).json()["reply"]
        self.assertEqual(reply["source"], "rules")


if __name__ == "__main__":
    unittest.main()
