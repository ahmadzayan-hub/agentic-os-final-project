# ADR 0007 — The four business-analytics types as governed agents

Date: 2026-08-12 · Status: Accepted

## Context

The pipeline had one analysis stage (`analyst`) and one interpretation
stage (`business`). Between them they answered "what happened?" well and
gestured at "what should I do?" through a single concentration-risk rule.
Business analytics is not one question, though — it is four, in a maturity
ladder where each level needs the one below it:

```
Descriptive → Diagnostic → Predictive → Prescriptive
(what?)       (why?)       (what next?)  (what to do?)
```

## Decision

Four typed agents, one per question, replacing `analyst` and `business`.
Each owns its question, produces **its own standalone report**, and
consumes the stages above it. The comprehensive report embeds all four in
full — not links to them — because the approval gate binds to that
artifact's hash: what a human approves for publication must be exactly
what they were shown.

**Descriptive** — totals, typical value, spread, period change, largest
segment, unusual records.

**Diagnostic** — decomposes the change between the first and last period
by segment, and measures which other columns move with the measure. The
decomposition is exact arithmetic whose parts are validated to sum to the
whole. Correlation is reported as association and labelled as such in the
same sentence, never in a footnote.

**Predictive** — a least-squares trend fitted to the historical periods
and extended three forward. **Accuracy is measured, not asserted**: the
model is refit on all but the last few periods and scored against those
held-out actuals, and that error is what the report quotes as a range.
Below 4 periods it refuses to forecast; below 6 it forecasts and declares
that its accuracy is unmeasured. A forecast nobody has checked is a guess
with a decimal point.

**Prescriptive** — enumerates options the dataset itself supplies (protect
the leader, grow the smallest segment, reverse a decline, hold course),
scores each under one improvement assumption applied equally, recommends
the largest, and says how close the call was. Holding course scores zero
by construction: that is what makes it the bar the others must clear.

### Why not a real forecasting or optimization library

DuckDB, statsmodels, Prophet, or an LP solver would each be defensible,
and each would add a dependency, a build surface, and a class of failure
this project cannot currently test end-to-end. More importantly, none of
them would change the honest answer for a 2 MB CSV with twelve monthly
periods: a straight line with a measured error is the right size of claim
for the data available. The stage contract is the seam to swap when the
data justifies more — that is a deliberately narrow interface, and this
ADR is the record that the choice was made, not overlooked.

## Business language is enforced, not encouraged

The professional skill in the brief is translating findings into language
an executive acts on. That was implemented as a mechanism rather than a
convention:

- Each type produces a **headline**: one plain sentence that is the
  stage's summary, the first line of its report, and its row in the
  comprehensive report's summary table.
- `claims_avoid_statistical_jargon` **fails validation** when a claim or a
  headline contains statistical vocabulary ("p < 0.05", "coefficient of
  determination", "standard deviations", "statistically significant", …).
  The test suite proves the check can fail, so it cannot rot into a check
  that only ever passes.
- The narrator's system prompt carries the same rule, and the narrator is
  still forbidden from producing numbers.

Method strings keep full technical precision — "least-squares slope of
revenue against period order" — because that is what makes a figure
auditable. The distinction is between what the reader is *told* and what
the reader can *check*.

Visualisation is treated the same way. The diagnostic answer now has a
chart of its own (change by segment, negatives below the axis), and the
forecast chart names the boundary between measurement and projection in
its alt text.

## Model providers

The gateway gained **Ollama** (local, no credential) and **Anthropic**,
alongside Groq. Priority is ollama → anthropic → groq, with local first
because it is the only option where nothing leaves the machine; `status()`
reports `local_only` so the answer to "does anything leave this host?" is
one field, not an inference. The standing rule is unchanged and tested:
**the model never receives the dataset**, only the already-verified facts,
and it never produces a number.

## Compatibility

Runs created by the previous pipeline have tasks whose roles no longer
exist. Advancing one now fails it with an explicit message naming the
missing stage and telling the user to start a new run; its stored results
stay readable. Previously this raised a `KeyError` that the API surfaced
as a 404 — a run that appeared to vanish.

## Evidence

- 220 Python tests (both dialects, suite run twice), including 18 in
  `tests/test_analytics.py` and 13 in `tests/test_model_gateway.py`.
- Every headline figure was recomputed independently — total, period
  change, forecast, backtest error, and the segment decomposition — and
  matched to the cent.
- Honest-refusal paths are tested: three periods produces no forecast;
  five periods produces one explicitly marked unmeasured; a dataset with
  no segments and no trend produces no recommendation.
- The Ollama and Anthropic paths were exercised **over a real socket**
  against local servers speaking each wire protocol: one request, correct
  headers, only verified facts in the body, and the dataset absent from
  it. No live provider call has been made from this environment — its
  egress policy blocks the model hosts.
- Reasoning models are handled explicitly. `qwen3:4b` and its relatives
  answer with a `<think>` scratchpad before the summary; that block is
  stripped, a reply truncated mid-thought falls back to the deterministic
  narrator rather than printing reasoning as a summary, and local models
  get a larger token budget because thinking would otherwise consume it
  all. Verified end to end against a server that replies the way qwen3
  does: the scratchpad appears nowhere in the 12,937-character report.
