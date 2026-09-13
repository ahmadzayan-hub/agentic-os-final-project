# Agent Catalog

The analytics run executes a governed pipeline of specialist agents. Each
is a typed, deterministic stage (`server/analytics.py`) — not a persona in
a chat loop — returning a structured result:

```
status · summary · claims[] · calculations[] · quality_checks[] · output
```

Claims carry `evidence` (calculation ids) and a `status`; the Validation
Expert independently re-verifies them. Pattern selection is recorded by
the Planner (sequential governed pipeline — the simplest sufficient
pattern for a repeatable analytics workflow, with a fixed bounded stage
list as the stopping rule).

| # | Agent | Responsibility | Can fail the run |
| --- | --- | --- | --- |
| 1 | **Hermes** — Orchestrator (run engine) | Sequences every stage, enforces the state machine and the approval gate, holds the worker lease, recovers an interrupted run. **Analyses nothing itself** — it is `server/runs.py`, not a pipeline stage, so accountability for sequencing is separate from accountability for findings | — |
| 2 | Planner Agent | Records the plan, pattern choice, and stopping rule | no |
| 3 | Data Source Agent | CSV ingestion, size/row limits, snapshot hash | yes |
| 4 | Data Contract Agent | Per-column type, nullability, distinctness, range, parse rate; names values that break the column they sit in | no |
| 5 | Data Profiling Agent | Completeness, duplicates, types, numeric detection | yes (no numeric data) |
| 6 | Data Quality Agent | Scorecard over four ratios (completeness, uniqueness, validity, consistency) with a stated formula and a grade | no |
| 7 | Privacy Agent | Scans column names and values for personal data before anything can be published; reports, never redacts silently | no |
| 8 | Data Cleaning Agent | Trim, dedupe, coercion — row loss always reported | yes |
| 9 | Metric Governance Agent | Decides which column the run analyses and states why: a certified glossary metric, an uncertified one, a column name, or the first numeric column. Names the metric's owner and definition, and where the definition is arithmetic over other columns present in the data, checks every row against it and reports the ones that do not match | no |
| 10 | Data Preparation Agent | Measure/dimension selection, aggregates, trend | yes |
| 11 | Segment Concentration Agent | Share per segment, Pareto coverage, Herfindahl index — the fact a total hides | no |
| 12 | **Descriptive Analytics Agent** — *what happened?* | Totals, typical values, spread, period change, largest segment, unusual records | yes (no usable values) |
| 13 | **Diagnostic Analytics Agent** — *why did it happen?* | Decomposes the change by segment (parts must sum to the whole) and measures which columns move together — association, never cause | no |
| 14 | **Experiment and Causal Inference Agent** — *can we claim a cause?* | Decides whether the dataset supports a causal claim at all. With an assignment column: compares arms against a baseline, reports each difference as a range that stays valid however often the test was checked while it ran (ADR 0016) with the narrower fixed-size reading beside it, widens every range when several arms are compared, and flags a split too lopsided for random assignment. Without one: refuses the causal claim and computes the experiment that would settle it — observations needed per group, and the smallest change the existing rows could already detect | no |
| 15 | **Predictive Analytics Agent** — *what will happen?* | Trend fitted to history and extended, with accuracy measured by backtesting against held-out periods; declines to forecast below 4 periods | no |
| 16 | Anomaly Detection Agent | Periods that break the fitted pattern (residuals beyond two standard deviations of the residuals) — distinct from an outlier against the average | no |
| 17 | **Prescriptive Analytics Agent** — *what should I do?* | Enumerates options the data supplies, scores each under one stated assumption, recommends one and says what would change the answer | no |
| 18 | Sensitivity Agent | Re-scores every option at 5%, 10% and 20% uplift and reports whether the recommendation survives, plus the break-even ratio against the runner-up | no |
| 19 | Visualization Expert | Truthful chart specs (zero-based axes, alt text): totals by segment, trend, who-moved-it, history-and-forecast | no |
| 20 | Provenance Agent | Builds snapshot → calculations → claims and checks it holds both ways: no claim citing missing evidence, and uncited calculations named | no |
| 21 | Validation Expert | Reconciles totals and the change decomposition, row accounting, claim-evidence coverage, forecast accuracy declared, recommendations carry assumptions, claims free of statistical jargon; may reject, never rewrites | rejects → partially_completed |
| 22 | Reporting Expert | One report per analytics type plus a comprehensive report embedding all four, with the claims-evidence matrix and limitations | no |
| 23 | Knowledge Curator (vault publish) | Approval-gated write-back to the Obsidian vault with provenance frontmatter | approval required |

## The four types form a ladder

Each level consumes the one below it, which is why they run in this order
and why the pipeline is sequential rather than parallel:

```
Descriptive → Diagnostic → Predictive → Prescriptive
(what?)       (why?)       (what next?)  (what to do?)
                  │
                  └── Experiment and Causal Inference
                      (may any of this be called a cause?)
```

The prescriptive agent's options come from the diagnostic decomposition
and the predictive forecast; a recommendation with nothing underneath it
would be an opinion.

The causal agent is **not a fifth type**. It hangs off the diagnostic
step because that is where the temptation appears: the moment a run says
"revenue moves with discount depth", somebody is going to read it as
"discounts raise revenue". It answers a different kind of question —
not *what does the data say* but *what is this data entitled to claim* —
and its usual answer is "not a cause, and here is the experiment that
would settle it". It gets its own report and its own tab for the same
reason it exists: a limitation buried at the bottom of somebody else's
report is a limitation nobody reads.

## What a number is allowed to mean

Every figure in every report is about one column, and until ADR 0011 the
choice of column was a guess made silently inside the preparation stage —
a name from a hard-coded list, or the first numeric column. The Metric
Governance Agent turns that into a decision with a reason attached, and
where a glossary is configured, the glossary decides.

`metrics.json` (see `metrics.example.json`) gives each metric a
definition in words, an owner, and optionally the arithmetic it is
supposed to satisfy. That last part is what separates this from a
document: where the formula's inputs are in the data, every row is
checked against it, and a `revenue` column that does not equal
`unit_price × units` is reported with the offending rows.

No glossary ships with the repository. Certifying a metric is a statement
that an organisation agrees on a definition and that a named person owns
it, so a default owner would be a fabricated one. Runs without a glossary
say plainly that their measure is undefined, and the validator fails a
run that stays quiet about it.

## Business language is a contract, not a style

Every type answers its question in one plain sentence — the headline —
which is the stage's summary, the top of its report, and the row in the
comprehensive report's summary table. "Costs are rising", not "the mean
increased by 2.3 standard deviations". This is enforced, not encouraged:
`claims_avoid_statistical_jargon` fails validation if a claim or headline
contains statistical vocabulary, and the narrator's system prompt carries
the same rule. Method strings keep their technical precision, because
that is what makes a figure auditable — the distinction is between what
the reader is told and what the reader can check.

## Independence rules implemented

- The Validation Expert receives artifacts and acceptance criteria, not
  hidden reasoning, and re-computes checks deterministically.
- Publishing (the only side-effecting stage) is server-enforced behind an
  approval bound to the exact artifact hash.
- The model narrator never contributes numbers; its text is labelled with
  its source (`model` or `deterministic`) in the report.

## Why twenty-one stages and not more

Each stage above computes something no other stage computes, and each
emits calculations a reader can recompute by hand from the method string
beside them. That is the entry test, and it is the reason the list stops
where it does: a "Insight Narrator", a "Strategy Agent", or a "Quality
Assurance Supervisor" would consume another stage's output, rephrase it,
and add a row to the pipeline without adding a fact to the report. The
cost of a decorative agent is not compute — it is that every genuine
stage becomes harder to trust when it sits in a list padded with
theatre.

Hermes is deliberately **not** one of the twenty-one. It sequences, gates,
leases and recovers; it never produces a finding. Keeping the
orchestrator out of the analysis list is what makes "no stage may
approve its own work" a structural fact rather than a promise.

## Not implemented (honest scope)

Seasonality models, true optimization, red-team, and cost agents are not
implemented — they require capabilities (inference libraries, LLM
evaluation, billing relationships) that would be placeholders today.

Causal inference is now **partly** implemented and the boundary is worth
stating precisely, because "we do causal inference" is the kind of claim
that gets believed. What ships (ADR 0010): a two-arm or multi-arm
comparison with an uncertainty range, a multiple-comparison correction, a
sample-ratio-mismatch check, and power/minimum-detectable-effect
arithmetic — all from the standard library, all recomputable by hand from
the method strings. What does **not** ship: any method for extracting a
causal effect from observational data. No propensity scores, no
difference-in-differences, no instrumental variables, no synthetic
control. Where the data records no assignment, the agent's answer is
"no", not an estimate with a wider range.

The forecasting and recommendation now shipped are deliberately modest and
say so in their own reports: a straight-line trend with backtested error,
and an option ranking under one stated assumption. Calling either of them
"machine learning" or "optimization" would be a marketing claim, not a
description. The pipeline's typed stage contract is the extension point
when the real thing is warranted.
