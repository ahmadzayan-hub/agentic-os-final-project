# ADR 0016 — A range that survives being looked at

**Status:** Accepted
**Date:** 2026-09-13
**Amends:** ADR 0010, which listed sequential testing as absent

## Context

ADR 0010 shipped a fixed-horizon comparison and, in its own "what this
is not" section, wrote:

> Sequential testing and always-valid inference are also absent; the
> ranges here assume the sample size was fixed in advance, and peeking at
> a running experiment invalidates them.

That was honest, and it was in the wrong place. It was in a decision
record. It was not in the report anyone reads.

It needed to be, because the assumption is almost always false. Nobody
running a test on their own data fixes the sample size in advance and
then looks exactly once at the end. They look on Tuesday, again on
Thursday, and they stop when the number looks good — and stopping when
the number looks good is precisely the thing that breaks a fixed-horizon
interval.

The size of the break is not a rounding error. Simulated: two groups
drawn from the same distribution, no effect at all, checked every five
observations up to 600. **A fixed-horizon interval calls the difference
real in 31.5% of those experiments.** Nearly a third of tests where
nothing whatsoever is happening.

A tool that hands a business analyst that interval, in a product built
around not overclaiming, is handing them a 1-in-3 chance of acting on
noise.

## Decision

Report an **always-valid range** — a confidence sequence — as the range
the verdict rests on, with the fixed-horizon range kept beside it for the
reader who genuinely did fix their sample size.

The construction is the normal-mixture confidence sequence (Robbins 1970;
Howard et al., *Time-uniform Chernoff bounds*, 2021), whose radius at
sample size *n* is

    σ · √( 2(nρ² + 1) / (n²ρ²) · ln( √(nρ² + 1) / α ) )

with ρ tuned to the sample size where the sequence should be tightest.
Expressed as a multiple of the ordinary standard error it is a drop-in
replacement for the 1.96 in a fixed-horizon interval — one factor, one
substitution, and nothing else about the comparison changes. The
Bonferroni split across arms applies to both.

Measured against the same simulation: **1.0% false alarms**, inside the
5% budget, against the fixed-horizon interval's 31.5%. It still finds a
one-standard-deviation effect in 100% of runs, so the width buys safety
without buying uselessness.

**Why the wider one is the verdict.** The tool cannot know whether the
horizon was fixed — it receives a CSV. The safe assumption is the common
case, and the common case is that somebody is watching a test as it runs.
The narrower reading is printed in its own table, labelled with exactly
the assumption that earns it.

## The price, stated

The always-valid range is about **1.55× wider** at the tuning point
(1,000 observations per arm), and wider still far from it. Two
consequences worth naming rather than discovering:

- **Small samples now say no.** Four observations against four, perfectly
  separated, used to be reported as a result. It no longer is, and it
  should not have been: the fixed-horizon reading at n=4 was already
  over-confident — it used a normal approximation where a t-distribution
  belongs — and the sequence is simply honest about it. There is a test
  that pins this.
- **The report has to explain itself.** A wider number with no reason
  beside it reads as a worse answer rather than a more honest one, so the
  causal section now carries a short section on why — including the
  simulated one-third figure, because that is the fact that makes the
  width obviously worth paying.

## Verification

The formula is transcribed from the literature, and a transcribed
formula is one that might be transcribed wrong. `tests/test_sequential.py`
therefore measures the property rather than asserting it: 400 seeded
null experiments, checked every five observations, counting alarms. The
suite also pins that the *fixed-horizon* rate stays above 20% — if that
ever drops toward 5%, the harness has stopped simulating peeking and the
headline test means nothing.

A mistake worth recording: the power test was first written with its
assertion inverted — it computed `1 - alarm_rate` for an experiment with
a real effect, called it `found`, and asserted it was *small*. It passed,
while checking the opposite of the sentence in its own failure message.
The helper is now named for what it counts (`alarm_rate`) rather than
what that counts as, which is what made the error visible.

## Consequences

- Runs report two ranges. The interface shows the primary one; the
  markdown carries both.
- `beyond_chance` is now the conservative verdict, and a second field
  records what a fixed-horizon reading would have said — so nothing is
  hidden, it is only labelled.
- 414 Python tests, of which the simulation adds a third of a second.

## What is still absent

- **No early-stopping recommendation.** The range is valid to look at; the
  tool does not tell anyone when to stop. That is a decision about cost
  and risk, not a statistic.
- **Still nothing from observational data.** ADR 0010's refusal stands:
  no propensity scores, no difference-in-differences, no instrumental
  variables, no synthetic control.
- **One tuning point, not chosen by the user.** A test aimed at 50
  observations per arm and one aimed at 50,000 would ideally tune
  differently. Getting that wrong costs width, never validity, and
  exposing a statistical tuning knob in a product that refuses to print
  the words "p-value" would be a strange place to start.
