"""The workspace over MCP: the same tools, the same refusals, a real client.

- **Dispatch**: every JSON-RPC shape the tools-only subset must handle —
  initialize and version negotiation, ping, tools/list, tools/call for
  a tool that runs and one that is refused, notifications, batches,
  parse errors, invalid requests, unknown methods, bad params, and a
  bug inside a tool (an internal error, not a dead transport).
- **Stdio**: the real script as a subprocess, a run started from it,
  and the same store the web interface would read.
- **The official client**, when `mcp` is installed: the SDK's own
  ClientSession initialises against this server, lists the tools and
  calls one. That is the interoperability claim, and it is skipped, not
  faked, when the SDK is absent.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent import Agent
from server.assistant import Assistant
from server.mcp import (INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST,
                        METHOD_NOT_FOUND, PARSE_ERROR, PROTOCOL_VERSIONS, McpServer)
from server.model_gateway import ModelGateway
from server.runs import RunEngine
from server.storage import open_store
from server.tools import NAMES, describe

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "mcp_server.py"


class FakeSession:
    def __init__(self, agent):
        self.agent = agent
        self.owner = "local-owner"
        self.transcript = []
        self.id = "mcp"


def request(request_id, method, params=None):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def write_config(root):
    config = root / "config.json"
    config.write_text(json.dumps({
        "agent_name": "Agentic OS", "version": "1.0.0",
        "memory_file": str(root / "memory.json"),
        "database_file": str(root / "agentic.db"),
        "vault_dir": str(root / "vault"),
    }), encoding="utf-8")
    return config


class DispatchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = open_store(None, Path(self.tmp.name) / "agentic.db")
        self.engine = RunEngine(store, Path(self.tmp.name) / "vault", ModelGateway(env={}))
        self.session = FakeSession(Agent({"agent_name": "Agentic OS", "version": "1.0.0"}))
        self.server = McpServer(Assistant(ModelGateway(env={}), self.engine), self.session,
                                name="agentic-os", version="1.0.0")

    def send(self, message):
        text = self.server.handle_text(json.dumps(message))
        return None if text is None else json.loads(text)

    def test_initialize_negotiates_a_version_and_declares_tools_only(self):
        result = self.send(request(1, "initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}}))["result"]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["serverInfo"], {"name": "agentic-os", "version": "1.0.0"})
        self.assertIn("nothing here can delete", result["instructions"])
        newer = self.send(request(2, "initialize", {"protocolVersion": "2099-01-01"}))
        self.assertEqual(newer["result"]["protocolVersion"], PROTOCOL_VERSIONS[-1])
        self.assertIsNone(self.send({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertTrue(self.server.initialized)

    def test_ping_and_tools_list(self):
        self.assertEqual(self.send(request(1, "ping"))["result"], {})
        tools = self.send(request(2, "tools/list"))["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], list(NAMES))
        self.assertEqual(tools, describe())

    def test_a_tool_call_runs_the_same_executor_and_a_refusal_is_an_error_result(self):
        saved = self.send(request(1, "tools/call", {
            "name": "remember", "arguments": {"information": "coffee at 8"}}))["result"]
        self.assertFalse(saved["isError"])
        self.assertEqual(saved["content"][0]["type"], "text")
        self.assertEqual(self.session.agent.memory, {"memory_1": "coffee at 8"})
        started = self.send(request(2, "tools/call", {
            "name": "start_run", "arguments": {"goal": "Analyse the sample sales"}}))["result"]
        self.assertFalse(started["isError"])
        self.assertEqual(len(self.engine.list_runs(owner="local-owner")), 1)
        refused = self.send(request(3, "tools/call", {
            "name": "forget", "arguments": {"key": "all"}}))["result"]
        self.assertTrue(refused["isError"])
        self.assertIn("not offered", refused["content"][0]["text"])
        self.assertEqual(self.session.agent.memory, {"memory_1": "coffee at 8"})
        unknown = self.send(request(4, "tools/call", {"name": "launch_rockets"}))["result"]
        self.assertTrue(unknown["isError"])
        self.assertIn("no tool called", unknown["content"][0]["text"])

    def test_each_call_has_its_own_step_budget(self):
        for i in range(12):
            result = self.send(request(i, "tools/call", {"name": "help"}))["result"]
            self.assertFalse(result["isError"])

    def test_bad_params_are_protocol_errors(self):
        self.assertEqual(self.send(request(1, "tools/call", {}))["error"]["code"], INVALID_PARAMS)
        self.assertEqual(self.send(request(2, "tools/call", {
            "name": "help", "arguments": "yes"}))["error"]["code"], INVALID_PARAMS)

    def test_unknown_methods_bad_json_and_bad_requests(self):
        self.assertEqual(self.send(request(1, "resources/list"))["error"]["code"], METHOD_NOT_FOUND)
        self.assertEqual(json.loads(self.server.handle_text("{nope"))["error"]["code"], PARSE_ERROR)
        self.assertEqual(self.send({"id": 1, "method": "ping"})["error"]["code"], INVALID_REQUEST)
        self.assertEqual(self.send({"jsonrpc": "2.0", "id": 2})["error"]["code"], INVALID_REQUEST)
        # A response to a request we never sent is ignored, as the protocol says.
        self.assertIsNone(self.send({"jsonrpc": "2.0", "result": {}}))
        self.assertIsNone(self.send({"jsonrpc": "2.0", "method": "notifications/cancelled"}))

    def test_a_batch_is_answered_as_a_batch(self):
        text = self.server.handle_text(json.dumps([
            request(1, "ping"), {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request(2, "tools/list")]))
        responses = json.loads(text)
        self.assertEqual([r["id"] for r in responses], [1, 2])
        self.assertIsNone(self.server.handle_text(json.dumps([
            {"jsonrpc": "2.0", "method": "notifications/initialized"}])))

    def test_a_bug_inside_a_tool_is_an_internal_error_not_a_dead_server(self):
        class Broken:
            def _execute(self, *args, **kwargs):
                raise ZeroDivisionError("bug")
        server = McpServer(Broken(), self.session)
        response = self.send_to(server, request(1, "tools/call", {"name": "help"}))
        self.assertEqual(response["error"]["code"], INTERNAL_ERROR)
        self.assertIn("ZeroDivisionError", response["error"]["message"])
        self.assertEqual(self.send_to(server, request(2, "ping"))["result"], {})

    @staticmethod
    def send_to(server, message):
        return json.loads(server.handle_text(json.dumps(message)))


class StdioTestCase(unittest.TestCase):
    """The real script, as a client would run it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = write_config(self.root)

    def run_server(self, messages):
        lines = "\n".join(json.dumps(m) for m in messages) + "\n"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("AGENTIC_OS_", "DATABASE_URL", "SUPABASE"))}
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(self.config)],
            input=lines, capture_output=True, text=True, timeout=120, cwd=str(ROOT), env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]

    def test_a_client_can_initialise_list_and_start_a_run(self):
        responses = self.run_server([
            request(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "test", "version": "0"}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request(2, "tools/list"),
            request(3, "tools/call", {"name": "start_run",
                                      "arguments": {"goal": "Analyse the sample sales"}}),
            request(4, "tools/call", {"name": "run_status"}),
        ])
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4])
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual([t["name"] for t in responses[1]["result"]["tools"]], list(NAMES))
        started = responses[2]["result"]["content"][0]["text"]
        self.assertIn("Started analysis", started)
        self.assertIn("Analyse the sample sales", responses[3]["result"]["content"][0]["text"])
        # The run went into the same store the web interface reads.
        store = open_store(None, self.root / "agentic.db")
        engine = RunEngine(store, self.root / "vault", ModelGateway(env={}))
        self.assertEqual(len(engine.list_runs(owner="local-owner")), 1)

    def test_a_hosted_deployment_is_refused_over_stdio(self):
        env = dict(os.environ, SUPABASE_JWT_SECRET="x" * 40)
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(self.config)],
            input="", capture_output=True, text=True, timeout=120, cwd=str(ROOT), env=env)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("local mode only", completed.stderr)


try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    MCP_SDK_AVAILABLE = False


@unittest.skipUnless(MCP_SDK_AVAILABLE, "the mcp SDK is not installed (optional)")
class OfficialClientTestCase(unittest.TestCase):
    """The SDK's client against this standard-library server."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = write_config(Path(self.tmp.name))

    def test_the_official_client_initialises_lists_and_calls(self):
        import asyncio

        async def drive():
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("AGENTIC_OS_", "DATABASE_URL", "SUPABASE"))}
            params = StdioServerParameters(
                command=sys.executable, args=[str(SCRIPT), "--config", str(self.config)],
                env=env, cwd=str(ROOT))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    listed = await session.list_tools()
                    helped = await session.call_tool("help", {})
                    refused = await session.call_tool("forget", {"key": "all"})
                    return init, listed, helped, refused

        init, listed, helped, refused = asyncio.run(drive())
        # Wire names, whatever the SDK's Python attribute names are.
        init, helped, refused = (m.model_dump(by_alias=True) for m in (init, helped, refused))
        self.assertEqual(init["serverInfo"]["name"], "agentic-os")
        self.assertIn(init["protocolVersion"], PROTOCOL_VERSIONS)
        self.assertEqual([t.name for t in listed.tools], list(NAMES))
        self.assertFalse(helped["isError"])
        self.assertIn("Here is what I can do", helped["content"][0]["text"])
        self.assertTrue(refused["isError"])
        self.assertIn("not offered", refused["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
