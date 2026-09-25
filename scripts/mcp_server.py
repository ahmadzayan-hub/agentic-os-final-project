"""Serve the workspace to an MCP client over standard input and output.

    python scripts/mcp_server.py [--config config.json]

Register it with a client, for example Claude Code:

    claude mcp add agentic-os -- python /path/to/scripts/mcp_server.py

or copy `.mcp.json.example` to `.mcp.json`. The client then sees seven
tools — the assistant's catalogue (ADR 0019/0021) — and every call goes
through the same tool box as the chat, with the same refusals.

Local mode only: standard input carries no identity token, so a
deployment that requires an identity provider is refused here rather
than served as the wrong person. Memory is the workspace's own
(`data/memory.json`, or the database in hosted storage); runs go into
the same store the web interface reads, so an analysis started from an
editor appears in Runs and waits for approval there.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app import PROJECT_ROOT, Session  # noqa: E402
from server.assistant import Assistant  # noqa: E402
from server.auth import build_identity  # noqa: E402
from server.mcp import McpServer  # noqa: E402
from server.model_gateway import ModelGateway  # noqa: E402
from server.quota import load_limits  # noqa: E402
from server.runs import RunEngine  # noqa: E402
from server.stages import load_stages  # noqa: E402
from server.storage import DbMemoryBackend, PostgresStore, open_store  # noqa: E402
from utils import load_config  # noqa: E402


def build(config_path=None, env=None):
    """Everything the server needs, wired the way the web application
    wires it — same store, same engine, same stages, same gateway."""
    env = os.environ if env is None else env
    config = load_config(config_path or PROJECT_ROOT / "config.json")
    identity = build_identity(env)
    if identity.mode != "local":
        raise SystemExit("The MCP server serves local mode only: standard "
                         "input carries no identity token, and this "
                         "deployment requires one.")
    store = open_store(
        env.get("DATABASE_URL") or config.get("database_url"),
        config.get("database_file") or PROJECT_ROOT / "data" / "agentic.db",
    )
    stages, problems = load_stages(env, config)
    for problem in problems:
        print(f"mcp: {problem}", file=sys.stderr)
    gateway = ModelGateway()
    engine = RunEngine(store, config.get("vault_dir") or PROJECT_ROOT / "vault",
                       gateway, limits=load_limits(env), stages=stages,
                       profiles=config.get("profiles") or {})
    memory = (DbMemoryBackend(store, "local-owner")
              if isinstance(store, PostgresStore) else None)
    session = Session(config, memory)
    return McpServer(Assistant(gateway, engine), session,
                     name=str(config.get("agent_name", "Agentic OS"))
                     .lower().replace(" ", "-"),
                     version=str(config.get("version", "1.0.0")))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", default=None, help="path to config.json")
    args = parser.parse_args(argv)
    build(args.config).serve()


if __name__ == "__main__":
    main()
