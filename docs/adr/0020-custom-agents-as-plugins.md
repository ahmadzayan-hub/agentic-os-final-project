# ADR 0020 — Custom agents as plugins

**Status:** Accepted
**Date:** 2026-09-23
**Amends:** ADR 0009, whose roster was a closed list; the roadmap's
"Pluggable Domain Expert Agent", which this replaces with a mechanism
rather than an agent

## Context

The pipeline was a literal list in `server/analytics.py`. Every stage
in it was admitted on a test — *it computes something no other stage
computes* (ADR 0009) — and every one of them lives under the same three
auditors: the provenance stage that walks claims back to calculations,
the validator that can reject the run, and the reporter that embeds
everything in the artifact the approval gate binds to.

That is a good pipeline and a closed one. Pointing the system at a new
domain — a target the business set, a seasonality the sector knows, a
margin rule an operator cares about — meant editing `analytics.py`,
which means editing the file that holds the governance. The maturity
assessment named this the second of the two gaps between the product
and its name: no customisation surface.

The obvious fix is also the wrong one. A registry that lets a plugin
run *anywhere* — after the validator, say, or in place of it — would
turn "add a file" into "opt out of the governance". A plugin that
returns whatever shape it likes cannot be audited. A plugin that can
rewrite the context can rewrite what the built-in stages found. Any of
those would buy extensibility at the price of the one property the
reports have that is worth having.

## Decision

### A stage is a file, and a file is admitted under the same governance

`server/stages.py` loads stages by dotted path — from
`AGENTIC_OS_STAGES` or `config.json`'s `stages`, with options, and a
`stages_path` that makes a plain folder importable — exactly the way a
router is registered (ADR 0017). A plugin is a class or instance with:

    role          a slug, unique, not a built-in stage's name
    title         what the pipeline list and the run log call it
    after         which built-in stage it follows (default: sensitivity)
    question      optional; set, the stage gets its own report section
    can_fail_run  optional; True means its failure fails the run
    run(ctx)      the stage: a dict in, a result dict out

`examples/stages/target_attainment.py` is a complete one, sixty lines,
standard library only.

### The governed tail cannot be placed after

`after` must name a built-in stage before provenance, validation,
reporting and publishing. There is no placement after them, so every
custom stage runs before the auditors and is audited by them. The
mechanism that makes this hold is small: the three auditors used to
read a fixed tuple of evidence stages; they now read the run's own
declaration of its stages (`analytics.evidence_stages(ctx)`), which
the engine writes from the task list. A custom stage's claims are
checked for evidence and for jargon by the same validator, its
calculations appear in the same provenance chain and the same "Key
metrics" table, its claims in the same "Every claim" table, and its
section — if it wrote one — in the same comprehensive report.

Removing that one line, so the auditors read the fixed tuple again,
fails the tests that put a bad custom claim through the validator.
That is the test that matters: a plugin cannot be admitted any other
way.

### The contract is enforced, not trusted

A result is validated field by field before anything is recorded:
status, summary, claims, calculations, quality checks, output — the
shape every built-in stage returns. Two rules are stricter than the
built-ins need:

- **Ids carry the role.** A custom calculation is `target_attainment.c_gap`,
  never `c_gap`. A plugin cannot collide with a built-in id and make an
  unsupported claim look supported, and the provenance table says where
  every figure came from.
- **Sizes are capped** (50 claims, 200 calculations, 50 checks, and
  text lengths), so a runaway plugin cannot bloat a report or a row.

A malformed result fails the stage with the reason in the task summary.

### The stage cannot rewrite anything, and its failure is its own

A custom stage reads everything the built-in stages produced and
changes none of it, for two different reasons that are worth keeping
apart. What the built-in stages found is safe because of the durability
design (ADR 0006, 0012): a stage is a pure function of the stored
results before it, and every stage's context is rebuilt from the store,
so a write to the dict reaches no later stage. A test registers a stage
that zeroes the prepared total and empties the descriptive claims,
places a second stage after it, and asserts the second stage — and the
validator — saw the original. That test passes with or without any
copying, and says so in its comment.

The copy is for the one live object in the context: the metric glossary
(ADR 0011), read once per process and shared by every run and every
tenant. Without a copy, a stage could append its own certified
definition of revenue and every later report in the process would state
it. The stage is therefore handed a deep copy, and a test registers a
stage that plants exactly that, runs twice, and asserts the second run's
governance stage and report never saw it. Removing the copy fails that
test and only that test — which is the honest measure of what the copy
buys.

A failure — an exception, a contract violation, a `failed` status — marks
the stage failed and the run continues, unless the stage declared
`can_fail_run`. The report then says, under "Custom stages", that the
stage failed and why. A report that silently lacked a stage would be a
report the reader could not tell was incomplete.

### Profiles choose; the picker appears only when they exist

`profiles` in `config.json` name subsets of the registered stages; a run
may name one. With no profile, the `default` profile applies, or every
registered stage when none is defined. An unknown profile is refused
before anything is written. The interface shows a picker only when
profiles are configured, so a default install looks exactly as it did.

### What this is not

**A sandbox.** A plugin is Python in this process, trusted the way the
router and the metric glossary are. The contract catches mistakes; it
does not contain malice. The operator decides what to register, and the
registry is per process — a hosted install cannot give each tenant its
own stages, for the same reason it cannot give each its own glossary
(ADR 0011).

## Verification

- 28 tests in `tests/test_stages.py`. Loading: options, the environment
  variable, an unloadable path as a sentence, a shadowed built-in role,
  every governed-tail placement, a duplicate, a missing title or `run`,
  a refused stage beside a loaded one, a plain folder through
  `stages_path`. The contract: a good result, normalisation, role
  prefixes, and ten ways a result can be wrong. Governance, with the real
  engine: placement and audit of the example stage; a custom claim
  without evidence rejected by the validator; a custom claim in jargon
  rejected; the built-in findings unreachable; the shared glossary
  unreachable; a failure the stage's own; a failure that may fail the
  run; a malformed result; a stage reporting failure; profiles; a
  profile naming a ghost; a run whose stage was unregistered. The API:
  the catalogue, health, and a profile on a run.
- One end-to-end test on desktop and mobile: the picker, the stage in
  the pipeline list between sensitivity and provenance, its own tab and
  question, and its ids in the comprehensive report.
- Two mutations by hand, each restored afterwards. The auditors reading
  the fixed tuple instead of the run's declaration fails the tests that
  put a bad custom claim through the validator. Removing the copy handed
  to the stage fails the glossary test — and, before that test existed,
  failed nothing, which is why it exists.

## Consequences

- "Edit analytics.py" is now "add a file": the built-in roster is
  unchanged at 21 stages, and a domain stage lives outside the file that
  holds the governance.
- The background worker loads the same registry, so a run advanced in
  the background has the stages the browser has.
- `/api/pipelines` lists stages, profiles, the default, and every load
  problem; `/api/health` carries the problems too.
- 534 Python tests, 37 unit tests, 50 end-to-end checks.

## What is still absent

- **A custom stage cannot narrate.** It does not receive the model
  gateway. That is deliberate — a model narrates, it never calculates,
  and a plugin is a calculation — and it is also a limit: a stage that
  wanted to phrase its own finding cannot.
- **A custom stage cannot chart.** Charts come from the visualisation
  stage over the prepared data; a plugin's figures appear in tables.
- **Per-tenant registries**, as above.
- **Hot reload.** The registry is read at start-up; a new stage needs a
  restart, like the glossary and the router.
