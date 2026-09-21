# ADR 0017 — Choosing the narrator, and saying who chose it

**Status:** Accepted
**Date:** 2026-09-21
**Amends:** ADR 0007, which fixed the provider order and left it there

## Context

The model gateway picks a narrator by a fixed priority: local Ollama if
configured, else Anthropic, else Groq, else the deterministic template.
That order is a good default — local first means nothing leaves the
machine — and it is also a guess. The same guess, for every report, made
once at start-up, with no reason attached and no way to disagree with it.

This is the shape of problem ADR 0011 found in the choice of measure: a
silent default standing in for a decision. There the fix was to make the
decision explicit, let something else make it, and print what was chosen.
The same three moves apply here.

There is also a reason to want the decision made *per report* rather than
per deployment. A one-paragraph summary of a clean descriptive run and a
summary of a causal comparison with a contested verdict are not the same
job. A deployment with both a 4-billion-parameter local model and a
hosted frontier model has a real choice to make each time, and "whatever
was first in the list at start-up" is not making it.

## Decision

Introduce an optional **router**: something that is asked, per narration,
which model should write this summary. The contract is deliberately one
method wide:

    route_single({"query": str, ...}) -> {"model_name": str, ...}

That is LLMRouter's interface (ulab-uiuc), whose whole subject is picking
a model per query under a cost and quality budget. Taking exactly one
method of it, and nothing else, buys two things: LLMRouter's KNN, MLP,
graph and heuristic routers all work here unmodified, and so does four
lines of your own — `tests/test_routing.py` contains such a router, and
it is four lines.

`server/routing.py` wraps the existing gateway rather than replacing it,
so every fallback, timeout and honest-degradation path in `ModelGateway`
still applies. Configuration is two environment variables, because a
third would be a framework:

    AGENTIC_OS_ROUTER         dotted path to a router class
    AGENTIC_OS_ROUTER_CONFIG  the config file that class wants

### LLMRouter is not a dependency

It is optional, it is never imported at module scope, and with nothing
configured this module changes no behaviour whatsoever — the priority
order applies exactly as before.

That is not politeness. LLMRouter pulls in torch, transformers and CUDA
wheels. Measured on this machine, those dependencies occupy **5.3 GB**
(`nvidia` 3.2 GB, `torch` 1.2 GB, `triton` 897 MB, `transformers`
118 MB, the rest smaller). This project's headline promise is that the
CLI needs only the standard library, and a research library of that
weight has no business being required by it.
`requirements.txt` therefore does not list it, and CI does not install
it.

### A choice this deployment cannot reach is refused, not substituted

A router trained on a public model catalogue will say `gpt-4o` long
before it says "the ollama one", and it has no idea which keys this
deployment holds. So the router's answer is mapped to a provider that is
actually reachable, and if it maps to nothing, **the choice is not
honoured and the report says so**. Silently narrating with a different
model than the one chosen would make the report's "narrated by" line a
lie, and that line is the entire point of having one.

Mapping is by the longest matching alias, so `claude-sonnet-4-5` resolves
through `claude-sonnet` rather than stopping at `claude`. An unrecognised
name returns nothing rather than a guess.

### The router gets the facts, never the dataset

ADR 0007's rule does not relax because the recipient is a local
scikit-learn model rather than a hosted API. The router receives the
narration prompt — goal and verified facts — because that is what it must
judge; it receives no rows. There is a test that asserts the dataset is
absent from what the router sees.

## Verification

Two files, deliberately split:

- `tests/test_routing.py` (22 tests) never imports LLMRouter. It tests
  this application's side against the one-method contract, so the suite
  stays runnable on a machine with no torch and no network — which is
  every machine CI runs on. It stubs the gateway's provider callers, so
  the assertions say *which provider actually narrated*, not merely which
  one was chosen.
- `tests/test_llmrouter_integration.py` (5 tests) loads two real
  LLMRouter routers and checks the assumption the fake stands for. It
  skips when the library is absent, which in CI is always.

Both halves were run for this ADR. With LLMRouter installed: **441 tests,
none skipped**. With it uninstalled, which is what CI sees: **441 tests,
5 skipped**.

Live, through the running server, with the two heuristic routers:

    LargestLLM   chose claude-sonnet-4-5  -> anthropic  honoured
    SmallestLLM  chose qwen3:4b           -> ollama     honoured

**A defect this found.** The first version of the report line read:

> Narrative source: deterministic, chosen by SmallestLLM

which says the router chose the deterministic narrator. It had not — it
chose a model that then failed to answer, and the gateway fell back. The
sentence was true about two separate facts and false about the one it
appeared to assert. The wording now distinguishes *honoured and
answered*, *honoured and did not answer*, and *not honoured*, and
`ReportNoteTestCase` pins all three. Worth recording because the routing
logic was correct throughout; only the sentence about it was wrong, and a
report nobody can trust the prose of is not improved by correct
internals.

## Consequences

- The report names the narrator **and why that one**, or says plainly
  that the router's choice was not used and what happened instead.
- `/api/health` names the router inside `model_provider` and carries
  `router_problem` beside it, so a router that failed to load is visible
  without reading logs. A worker has no endpoint to ask, so it prints the
  same sentence to stderr at start-up; there is a test for that, because
  a silent fallback to the priority order looks exactly like a router
  that happens to agree with it.
- A router that raises costs a routing decision, never a report: the
  priority order applies and the failure is recorded in `why`.
- 441 Python tests.

## What is still absent

- **No cost or latency feedback.** The router chooses; nothing measures
  what the choice cost and nothing tells the router it was wrong. The
  learned routers in LLMRouter are trained offline against benchmark
  data, and this project has no billing relationship to measure against
  (ADR 0008).
- **The learned routers are untested here.** KNN, MLP and graph routers
  need embedding models and checkpoint downloads that this environment's
  egress policy blocks. The contract they satisfy is the same one, and
  the two heuristic routers exercise it, but "it works with SmallestLLM"
  is not "it works with the MLP router".
- **One router per process, chosen at start-up.** Per-owner routing in a
  hosted install would need the router in the database, and that is the
  metric-glossary problem (ADR 0011) again, unsolved for the same reason.
- **No live hosted call has been made from here.** Unchanged from ADR
  0007: the provider wire contracts are tested against a local HTTP
  server, and this environment cannot reach the real ones.
