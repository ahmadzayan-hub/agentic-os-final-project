# ADR 0010 — Experiment and causal inference as a governed stage

**Status:** Accepted, amended in part by ADR 0016
**Date:** 2026-08-15

> The "what this is not" section below lists sequential testing as
> absent and warns that peeking invalidates these ranges. ADR 0016 acted
> on that warning: an always-valid range now carries the verdict. The
> text is left as written — a record says what was decided when.
**Supersedes in part:** ADR 0009 (roster count: nineteen stages → twenty)

## Context

The diagnostic agent (ADR 0007) answers "why did it happen?" by
decomposing a change across segments and measuring which columns move
together. Both are association. The report says so, twice, in the stage's
own words and again in the limitations section.

That was not enough, and the reason is worth writing down rather than
patching around. A report that contains the sentence *"revenue moves
closely with discount depth, which is where to look first"* has, in
practice, already been read as *"discounting raises revenue"* by the time
it reaches a decision. The disclaimer sits in a paragraph the reader
skips; the finding sits in the headline they act on. Putting a caveat
next to a claim does not make the claim safe — the caveat and the claim
compete for attention, and the claim wins.

The four types are a maturity ladder, and every rung on it is
associational. Nothing in the pipeline was accountable for the question
"is this dataset entitled to a causal claim at all?" — so nothing
answered it, and the answer defaulted to whatever the reader assumed.

## Decision

Add a twentieth stage, **Experiment and Causal Inference**, immediately
after the diagnostic stage, with its own report and its own tab. It is
not a fifth analytics type: the four types answer *what does the data
say*, and this one answers *what is this data entitled to claim*. It is
kept in a separate list (`REPORT_SECTIONS`) for exactly that reason, so
that "all four analytics types" keeps meaning four everywhere it is
asserted, including in the validator.

The stage takes one of two paths, and the dataset chooses.

**A controlled comparison is recorded.** Detection is deliberately
narrow: a non-numeric, non-date column with two to six distinct values,
whose *name* contains an assignment word (`variant`, `treatment`, `arm`,
`test_group`, `bucket`, `assignment`, …) or whose *values* contain one
(`control`, `treatment`, `holdout`, `baseline`, `variant`). Bare "A"/"B"
values are not accepted alone — a column of grades would qualify.
`cohort` is deliberately excluded from the name list: a cohort is defined
by something that already happened, never by assignment, so accepting it
would let an observational split be read as a controlled one.

Then, for each arm against a baseline:

- the difference in means, reported as a **range**, not a point. A single
  number implies a precision the sample does not have; the range is what
  the data can actually support, and the verdict is whether it includes
  no-change;
- **Bonferroni** widening when more than one arm is compared, because
  comparing more groups gives chance more chances;
- a **sample-ratio-mismatch** check at three standard errors of the
  expected split. Beyond that, the run says so and warns that the
  comparison may be measuring the assignment rather than the change;
- an **assumption claim, always**: this difference is an effect only if
  assignment was random. The column proves an assignment was recorded,
  never that it was random;
- a **limitation claim, always**: each row is treated as one independent
  observation, and where rows are aggregates the ranges are narrower than
  the truth.

**No controlled comparison is recorded** — which is most business data.
The stage refuses the causal claim, and then prices the experiment that
would settle it:

- observations needed per group to detect a 5%, 10% and 20% change, from
  the observed variance, at two-sided 5% and 80% power;
- the **smallest change the existing rows could already detect**, if
  split evenly into two groups. This is the number that changes
  decisions: "anything under 27% would be invisible in a sample this
  size" is worth knowing *before* commissioning a test, not after.

All arithmetic is standard library (`statistics.NormalDist`, `math`), and
every figure carries a method string precise enough to recompute by hand.

## Business language, again

The conventional vocabulary of this stage is the most jargon-dense in
analytics, and the project's rule (ADR 0007) is that claims and headlines
are business language while method strings stay technical. That split did
real work here:

| Not said in a claim | Said instead |
| --- | --- |
| p < 0.05 | the range does not include no-change, so this is unlikely to be chance alone |
| 80% statistical power | a test that size catches a real change of that size about four times in five |
| 95% confidence interval | the plausible range: 7.87 to 16.18 |
| Bonferroni correction | comparing more groups gives chance more chances, so each range was widened |
| sample ratio mismatch | the groups are unevenly sized — random assignment rarely lands that far apart |

The technical terms appear in the calculation table, where an auditor
needs them. `claims_avoid_statistical_jargon` fails the build if they
leak into a claim or a headline, and that check now covers this stage's
headline as well.

## Consequences

- A run is 21 tasks instead of 20. The stage is arithmetic over rows
  already in memory; it adds no measurable time.
- Every report now states, in one line under the four-question table,
  whether a cause may be claimed. On observational data that line is a
  refusal — which is the honest answer and, for most datasets, the
  permanent one.
- The interface gains a fifth report tab. It is generic over
  `REPORT_SECTIONS`, so no per-type code was added.
- `EVIDENCE_STAGES` covers sixteen of the twenty stages; the causal
  stage's claims are audited by the validator like any other.

## What this is not

"We do causal inference" is the kind of claim that gets believed, so the
boundary is stated precisely. What ships: fixed-horizon comparison of
recorded arms, multiple-comparison control, ratio-mismatch detection, and
power arithmetic. What does **not** ship: any method for extracting a
causal effect from observational data — no propensity scores, no
difference-in-differences, no instrumental variables, no synthetic
control. Where the data records no assignment, the answer is "no", not an
estimate with a wider range. Sequential testing and always-valid
inference are also absent; the ranges here assume the sample size was
fixed in advance, and peeking at a running experiment invalidates them.

## Alternatives considered

**Extend the diagnostic agent instead.** Rejected. The disclaimer already
lives there and is already ignored; the whole point is that this question
needs a stage that is accountable for it, with a report a reader opens on
purpose.

**Make it a fifth analytics type.** Rejected. It answers a different kind
of question, and folding it in would have quietly falsified "the four
types of business analytics" in every document and the validator check
that enforces it.

**Estimate effects from observational data.** Rejected for now. Every
method in that family (propensity scores, difference-in-differences,
instrumental variables) carries assumptions that cannot be verified from
a CSV and are routinely violated in practice. Shipping one would produce
a number where the honest output is a refusal — the exact failure this
stage exists to prevent.

**Report a p-value.** Rejected. It answers a question nobody asked
("how surprising is this data if nothing were happening?") and is read as
the answer to the one they did ("how likely is this real?"). A range in
the units of the measure is both more honest and more useful.
