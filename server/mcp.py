"""The workspace as MCP tools, over stdio, in the standard library.

The Model Context Protocol is JSON-RPC 2.0 over newline-delimited
standard input and output. A tools-only server needs four methods —
`initialize`, `ping`, `tools/list`, `tools/call` — and must ignore
notifications. That is what this module serves, and nothing else:
no resources, no prompts, no sampling, no streaming.

Why not the official SDK: measured here, `mcp` is 44 MB across 28
packages (ADR 0021), for a protocol whose tools-only subset fits in this
file. The SDK's *client* is the right thing to test against, though,
and `tests/test_mcp.py` drives this server with it when it is installed.

What a client gets is exactly what an agent runtime gets: the catalogue
in `server/tools.py`, through the same `ToolBox`, with the same
refusals — no deletions, arguments checked, the tool's own text as the
result. The protocol adds nothing to what a caller may do.
"""

import json
import sys

from server.tools import ToolBox, describe

# Revisions of the protocol whose tools-only subset this server
# implements. A client asking for a newer one is answered with the
# newest of these; the client then decides, as the protocol says.
PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

INSTRUCTIONS = (
    "Agentic OS is a governed business-analytics workspace. Its tools save "
    "and recall the person's memory, change reply preferences, start a "
    "deterministic analytics run, report its status and quote its report's "
    "verified headlines. Publishing a report always waits for the person's "
    "approval in the workspace; nothing here can delete anything."
)


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class McpServer:
    def __init__(self, assistant, session, name="agentic-os", version="1.0.0"):
        self.assistant = assistant
        self.session = session
        self.name = name
        self.version = version
        self.initialized = False

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def serve(self, stdin=None, stdout=None):
        """Read requests until standard input closes. Never raises: a bad
        line is answered with a JSON-RPC error, and anything the log has
        to say goes to standard error, because standard output is the
        protocol."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle_text(line)
            if response is not None:
                stdout.write(response + "\n")
                stdout.flush()

    def handle_text(self, line):
        """One line in, one line out (or None for a notification)."""
        try:
            message = json.loads(line)
        except ValueError:
            return json.dumps(_error(None, PARSE_ERROR, "Parse error"))
        if isinstance(message, list):
            responses = [r for r in (self.handle(m) for m in message) if r is not None]
            return json.dumps(responses) if responses else None
        response = self.handle(message)
        return None if response is None else json.dumps(response)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def handle(self, message):
        """A parsed JSON-RPC message → a response dict, or None."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "Invalid Request")
        method = message.get("method")
        request_id = message.get("id")
        if not isinstance(method, str):
            if request_id is None:
                return None  # a response to something we never sent
            return _error(request_id, INVALID_REQUEST, "Invalid Request")
        if request_id is None or method.startswith("notifications/"):
            if method == "notifications/initialized":
                self.initialized = True
            return None
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        try:
            result = self._dispatch(method, params)
        except RpcError as error:
            return _error(request_id, error.code, str(error))
        except Exception as error:  # a bug must not kill the transport
            print(f"mcp: {method} failed: {type(error).__name__}: {error}",
                  file=sys.stderr)
            return _error(request_id, INTERNAL_ERROR,
                          f"{type(error).__name__}: {error}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method, params):
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": describe()}
        if method == "tools/call":
            return self._call(params)
        raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _initialize(self, params):
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-1]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
            "instructions": INSTRUCTIONS,
        }

    def _call(self, params):
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, "tools/call needs a tool name")
        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")
        # One box per call: the step limit is per message, and over MCP
        # every call is its own message.
        outcome = ToolBox(self.assistant, self.session).call(name, arguments or {})
        return {"content": [{"type": "text", "text": outcome["text"]}],
                "isError": not outcome["ok"]}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}
