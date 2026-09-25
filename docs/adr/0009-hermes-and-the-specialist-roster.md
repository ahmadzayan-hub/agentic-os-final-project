# ADR 0009 — Hermes, and how many specialists is enough

Date: 2026-08-13 · Status: Accepted, superseded in part by ADR 0010

> The counts below are as of this record's date. ADR 0010 added a
> twentieth stage (experiment and causal inference), making it twenty
> stages and twenty-one tasks per run. The numbers are left as written:
> an ADR records what was decided when, and editing it to match a later
> state would destroy the only thing it is for.

## Context

The owner asked for the maximum number of agents, with a named
orchestrator: **Hermes**. The catalog said the opposite — "only four —
no decorative agents" — a line that came from an architecture review
commissioned for this project.

Both positions are defensible and they are not actually in conflict. The
review was not against *many* agents; it was against agents that exist to
be counted. The question a roster has to answer is not "how many?" but
"what does each one compute that nothing else computes?"

## Decision

**Nineteen pipeline stages plus the publish gate — twenty tasks per run —
and one named orchestrator.**

Seven specialists were added, each admitted on the same test: it must
produce calculations a reader can recompute by hand, and it must fail its
own quality checks when the data warrants.

| Stage | Computes | Test that it is not decoration |
| --- | --- | --- |
| Data Contract | per-column type, parse rate, range, nullability | flags a column that is 83% numbers and names the offending values, instead of silently calling it text |
| Data Quality | four dimension ratios and their mean as a 0–100 score | the score drops on a dataset with holes; the weakest dimension is named |
| Privacy | pattern and column-name scan for personal data | detects emails and phone numbers in a synthetic dataset, and stays silent on ordinary business data |
| Segments | share, Pareto coverage, Herfindahl index | HHI of 0.9/0.05/0.03/0.02 computes to 0.8138 |
| Anomaly | residuals from the fitted trend | finds a spike a mean-based outlier check misses, and reports nothing on a clean line |
| Sensitivity | the ranking re-scored at 5%, 10%, 20% | reports the break-even ratio against the runner-up |
| Provenance | snapshot → calculations → claims, both directions | fails when a claim cites evidence that does not exist |

**Hermes is the orchestrator, and is deliberately not a stage.** It is
the run engine: it sequences, enforces the state machine, holds the
approval gate, takes the worker lease, and recovers an interrupted run.
It analyses nothing. Keeping it outside the roster is what makes "no
stage approves its own work" a structural fact rather than a promise —
if Hermes were also an analyst, the separation would be a naming
convention.

## What was rejected, and why

An "Insight Narrator", a "Strategy Agent", a "Quality Assurance
Supervisor", a "Knowledge Synthesizer": each would take another stage's
output, rephrase it, and add a row to the pipeline without adding a fact
to the report. The cost is not compute. It is that every genuine stage
becomes harder to trust when it sits in a list padded with theatre — and
this product's entire claim is that a reader can check the work.

The roster grows again when there is a computation to do, not when there
is a slot to fill.

## Consequences

- A run is 20 tasks instead of 13, so it takes about half again as long
  to reach the approval gate (still seconds). The e2e timeouts moved from
  20s to 40s to keep the margin honest rather than tight.
- The validator gained two checks that only exist because these stages
  do: personal data must reach the approver, and the provenance chain
  must be complete.
- `EVIDENCE_STAGES` now covers fifteen of the nineteen stages — the four
  that produce no claims of their own are the planner, visuals, validator
  and reporter — so the claims table and key metrics in the comprehensive
  report grew accordingly — 39 calculations
  supporting 21 claims on the sample dataset, against 15 claims before.
- Stage order is a dependency order, and a test asserts it: each stage
  may only read what an earlier stage produced.

## Evidence

- 253 Python tests (both dialects, suite run twice), 31 of them in
  `tests/test_analytics.py`.
- Each new specialist is tested on data that makes it fire, not only on
  the tidy sample — a detector that has never detected anything is a
  decoration with a test suite.
- The provenance check was verified to fail: injecting a claim citing
  `c_does_not_exist` makes it report that id and fail its check.
- 23 frontend unit tests, 38 e2e checks including the full 19-stage run
  reaching approval in a real browser.
