---
type: concept
aliases: [Agent runtime, MCP server]
tags: [architecture, ai, extension]
status: active
updated: 2026-10-16
review_every_days: 60
sources: [server/agent_runtime.py, server/tools.py, server/mcp.py, docs/adr/0021-frameworks-measured-adapted-not-adopted.md]
---

# Agent runtimes and MCP

The core of [[Agentic OS]] is framework-free by decision. Three seams let a framework in without widening what a caller may do.

1. **Agent runtime behind the chat.** One method, `run(message, tools, context)`, which returns text or declines with `None`. It sees only sentences the rules cannot place, and calls tools through one tool box: the assistant's catalogue minus chat and every deletion, with arguments checked and at most eight calls per message. LangGraph and Pydantic AI examples ship in `examples/runtimes/`.
2. **MCP server.** The same catalogue over the Model Context Protocol, standard library only, on stdio and in local mode. An editor's agent can start a run and read its status, while publishing still waits at the [[Approval gate]].
3. **A framework inside a stage.** A [[Custom stages|custom stage]] can be built as a LangGraph graph and is audited like any other.

The runtime's model is the [[Model gateway]].

## Related

- [[Decision log]]: decision 0021, frameworks measured, adapted, not adopted.
- [[Analytics OS roadmap]]: the MCP server is a natural way to drive multi-dataset runs from other tools.
