# ADR 0021 — Agent frameworks: measured, adapted, not adopted

**Status:** Accepted
**Date:** 2026-09-23
**Extends:** ADR 0019 (the assistant), ADR 0020 (custom stages);
follows the pattern of ADR 0017 (an optional library, loaded by dotted
path, absent by default)

## Context

The question was which agent framework this "Agentic OS" is built on —
LangGraph, CrewAI, AutoGen, the OpenAI Agents SDK, Google's ADK,
Pydantic AI, LlamaIndex, smolagents, the Claude Agent SDK — and, if
none, which one it should adopt.

The honest answer to the first half is *none*, and it is a decision,
not an omission. The pipeline is a fixed, deterministic sequence of
21 stages under three auditors and an approval gate. What agent
frameworks chiefly sell — a model deciding the next step, a loop of
tool calls, several model personas conferring — is exactly what the
governance forbids inside a stage: a model narrates, it never decides
what is calculated (ADR 0009, MATURITY_ASSESSMENT "Two things not to
do"). The orchestrator, Hermes, already has what LangGraph would bring
to the pipeline — a state, checkpoints, an interrupt for a human — with
a typed result contract and a provenance chain no framework provides.

The second half deserves a better answer than a preference. There is
one place where a loop earns its keep: the conversational assistant
(ADR 0019), whose rules turn one sentence into one action and cannot
serve a sentence that asks for several. And there are two things that
matter more than which loop: that the loop cannot widen what a caller
may do, and that the workspace is reachable *from* other agents
without adopting any of their frameworks.

## Decision

### The core stays framework-free

`agent.py`, `server/analytics.py` and `server/runs.py` import nothing
but the standard library. This is what keeps the CLI's promise, keeps
every figure recomputable by hand, and keeps the governance in one
file that no dependency can change under it.

### The assistant gets a runtime seam, and the runtime gets a tool box

`server/agent_runtime.py` loads one optional runtime by dotted path —
`AGENTIC_OS_AGENT_RUNTIME`, or `config.json`'s `agent_runtime` with
options — exactly as a router (ADR 0017) or a stage (ADR 0020) is
loaded. A runtime is one method:

    run(message, tools, context) -> str

Three rules make the seam safe whichever framework sits behind it:

- **Rules first.** A sentence the rules can place as one exact action
  is that action, and the runtime never sees it. The runtime gets what
  the rules would otherwise answer with "not understood" — and may
  decline it (return `None`, having called nothing), in which case the
  ordinary path answers: the rules, or the configured model's chat
  reply. A runtime is an addition to the assistant, never a replacement
  for it.
- **One tool box** (`server/tools.py`). The runtime calls tools only
  through it. The catalogue is the assistant's action set minus `chat`
  and minus the deletions — a deletion is asked for directly and
  confirmed in the next message, and no loop can do it. Arguments are
  checked by the same rule as a model's; calls per message are capped
  at eight; unknown tools, refused tools and bad arguments come back as
  sentences in the person's language, never as exceptions.
- **The record is the tools' own text.** What the person sees is every
  tool's own sentence, verbatim and in order, and then the runtime's
  closing line — the one piece of text of its making, labelled as
  such on screen ("run by LangGraph · 2 tool calls"). If the runtime
  raises, the rules answer, the transcript says why, and whatever ran
  before the failure is still on the record: those actions happened.

The context a runtime receives is the assistant's own: verified
sentences and settings, never a dataset row, plus `ask` — the model
gateway — so a runtime that wants the deployment's model gets it with
every key server-side and every fallback intact.

### Two runtimes, as examples, each under a minute to read

- **LangGraph** (`examples/runtimes/langgraph_runtime.py`): a plan → act
  graph with a checkpoint per session thread, so the next message on
  the same thread remembers what the tools said. The model is the
  gateway. This is the runtime to reach for when the loop should stay
  on the deployment's own providers.
- **Pydantic AI** (`examples/runtimes/pydantic_ai_runtime.py`): the
  framework's native tool loop, with each catalogue entry registered
  from its JSON schema. It talks to its provider directly — its own
  keys, its own environment variables — which is the trade-off against
  the first example, and the reason both exist.

Neither is installed by default; neither is in `requirements.txt`; CI
does not install them, and their tests skip rather than fake.

### The workspace as MCP tools, in the standard library

`server/mcp.py` and `scripts/mcp_server.py` serve the same catalogue
over the Model Context Protocol — JSON-RPC over stdio: `initialize`,
`ping`, `tools/list`, `tools/call`, notifications ignored. Every call
goes through the same tool box, so an editor's agent may start a run
and read its status, and may not delete a memory, exactly like a
runtime. The official SDK's client is what the tests drive it with
when the SDK is installed; the server itself needs no dependency.
Local mode only: standard input carries no identity token, and a
hosted deployment is refused rather than served as the wrong person.

### A framework may live inside a stage

`examples/stages/graph_stage.py` is a custom stage (ADR 0020) built as
a three-node LangGraph graph — rank, flag, write — with no model in
any node. It returns the contract; provenance, validation and the
report treat it exactly as they treat a stage in plain functions. The
framework changes how the stage is structured and nothing about how it
is governed. That is the whole of what "using a framework with this
system" should mean.

## What it costs

Measured on this machine (`pip install --target`), including each
library's dependencies:

| Library | Version | Disk | Packages |
| --- | --- | --- | --- |
| langgraph | 1.2.12 | 72 MB | 38 |
| pydantic-ai-slim | 2.48.0 | 35 MB | 17 |
| mcp (SDK; not needed to serve) | 2.2.0 | 44 MB | 28 |
| LLMRouter (ADR 0017, for comparison) | — | 5.3 GB | — |

Each figure includes `pydantic`, which FastAPI already requires, so the
marginal cost is somewhat smaller. None of the three is a cost the CLI
should impose, which is why all three are optional.

## Verification

- `tests/test_agent_runtime.py` (29): the catalogue is the action set
  minus `chat` and the deletions; the tool box runs the chat's own
  executor, refuses deletions and unknown tools, checks arguments,
  drops what the schema does not list, caps steps, records every call,
  and refuses in the person's language; the seam keeps exact sentences
  for the rules, shows every tool's text verbatim then the closing
  line, falls back with a reason when the runtime raises, cannot be
  made to delete, is shown notes and never a row, caps the closing
  line, may decline so the ordinary path answers, cannot decline after
  calling something, changes nothing when unconfigured, and leaves
  confirmations to the rules; the loader; and the API — health, a reply with steps, a
  broken runtime reported.
- `tests/test_mcp.py` (11): every JSON-RPC shape of the tools-only
  subset; the real script over stdio, a run started from it in the
  same store the web interface reads; a hosted deployment refused; and
  the official SDK client initialising, listing and calling (skipped
  when the SDK is absent).
- `tests/test_frameworks.py` (10): the LangGraph runtime loops, feeds
  results back, remembers its thread, stops at its limit and on a
  refusal, and calls nothing for prose; the Pydantic AI runtime drives
  the same box, cannot delete, and stops when the model will not; the
  graph stage is audited, flags what it should, and fails only itself.
  All skipped when the libraries are absent — as in CI.
- One end-to-end test on desktop and mobile: the label and the
  verbatim texts, and an exact sentence never reaching the runtime.
- Three mutations by hand, each restored: offering the deletions to
  drivers fails nine tests (the box, the seam, the MCP dispatcher and
  the official client); removing the step cap fails one; letting the
  runtime see every sentence fails three, including the API test.
- Totals after this change: 584 Python tests (573 run in CI, where the
  11 needing an optional library skip), 37 unit tests, 52 end-to-end
  checks on desktop and mobile.

## What is still absent

- **No live model has driven either runtime from this environment.**
  Both were exercised with scripted models; the egress policy here
  blocks the providers, as for the narrator (ADR 0007).
- **A runtime cannot approve or publish.** Nothing in the catalogue
  touches the approval gate, on purpose.
- **MCP is stdio and local.** No HTTP transport, no authentication, no
  resources or prompts; a hosted deployment has no MCP surface.
- **A plugin is trusted code.** A runtime, like a stage, runs in this
  process; the tool box bounds what it may *do*, not what it may
  *import*.
- **Framework versions move.** The examples were verified against the
  versions in the table, whose APIs were probed rather than assumed;
  a later major version may need the examples adjusted.
