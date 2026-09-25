# ADR 0011 — A metric glossary that can be wrong out loud

**Status:** Accepted
**Date:** 2026-08-15

## Context

Every figure this system produces is about one column. Until now the
choice of column was made here, inside the preparation stage:

```python
measure = next((c for c in numeric_columns if c.lower() in
                ("revenue", "sales", "amount", "value", "total")),
               numeric_columns[0])
```

That line is usually right and always unaccountable. It picks a column
because of its name, silently, and nothing downstream ever says which
column was chosen or why. If a dataset carries both `revenue` and
`net_revenue`, one of them is analysed and the report never mentions the
other. If nothing matches, the first numeric column wins — and a report
about `units` is presented in exactly the same voice as a report about
audited revenue.

This is the mechanism behind a familiar organisational failure. Two
reports both say "revenue", both are internally consistent, and they
disagree — so the meeting becomes an argument about the number instead of
a decision about the business. The pipeline had strong guarantees about
arithmetic (every claim traces to a calculation), about language (no
jargon in a headline), and now about causality (ADR 0010) — but no
guarantee at all about *meaning*.

## Decision

A **metric glossary**, and a stage that enforces it.

`metrics.json`, beside `config.json`, defines metrics: a name, a
definition in words, an owner, a certification flag, the columns the
metric may appear as, and optionally the arithmetic it is supposed to
satisfy. A new **Metric Governance Agent** runs between cleaning and
preparation and:

1. **Chooses the measure, and says why.** Order of authority: a certified
   glossary metric, then any metric somebody wrote down, then a column
   whose name looks like a measure, then the first numeric column. The
   preparer no longer guesses; it reads the decision. Every report states
   which of those four applied — "chosen by first numeric column" is a
   fact the reader is entitled to.
2. **Names the owner and the definition** whenever one exists, in the
   report the approver reads.
3. **Checks the column against its own definition.** Where the formula's
   inputs are present in the data, every row is recomputed and compared.
   A `revenue` column that does not equal `unit_price × units` is
   reported with the offending rows and the size of each gap.
4. **Names the road not taken.** When more than one column answers to a
   glossary metric, the report says which was analysed and which was not.
5. **Reports a broken glossary rather than ignoring it.** A malformed
   entry never fails the run — but it produces a failed quality check and
   a warning claim, because the dangerous state is a glossary someone
   believes is in force when it is not.

The validator gains `measure_is_certified_or_declared_uncertified`.
Uncertified is allowed; uncertified and unsaid is not.

## Why a file, and why no glossary ships

**A file, not a database table.** Certifying a metric is a governance
act, and a reviewed commit is a stronger control than an edit box: it has
an author, a date, a diff, and a reviewer. The cost is that the glossary
is process-wide — a hosted install cannot give each tenant its own — and
that it is read once at startup, so editing it does not change a run
already in flight. Both are stated in `docs/KNOWN_LIMITATIONS.md`. The
store-backed, per-owner version is the follow-up when multi-tenant
editing is actually needed; building it now would be inventing a
requirement.

**No glossary in the repository.** Shipping a `metrics.json` that
certifies "revenue" as owned by "Finance" would be fabricating an
organisational fact — the same failure as a fabricated screenshot or an
invented test count. An install with no glossary is genuinely
uncertified, every run says so, and `metrics.example.json` shows the
format. The honest default is the one that admits it knows nothing.

## The formula language, and why it is tiny

One operation over column names: `sum`, `multiply` (two or more),
`subtract`, `divide` (exactly two). No nesting, no expression parser, no
`eval`.

This is deliberately less than a metric layer like dbt's or LookML's. The
reason is not effort: an expression evaluator over user-supplied strings
is an attack surface and an auditing problem, and a definition a reader
cannot check by hand is not much of a definition. `unit_price × units`
appears in the report exactly like that, and anyone can verify a row with
a calculator. When a definition genuinely needs more than one operation,
that is a signal it needs a derived column upstream, computed and tested
where such things belong.

Rounding is tolerated at half a percent or one hundredth of a unit.
Exact equality would flag ordinary currency rounding, and a check that
cries wolf is a check people learn to skip.

## Consequences

- A run is 22 tasks instead of 21. The stage is arithmetic over rows
  already in memory.
- The comprehensive report gains a **What this report measures** section,
  above data quality, because it is the more fundamental question.
- The `measure` heuristic now lives in `server/metrics.py` alongside the
  glossary lookup, so every way of choosing a measure sits in one file
  and each is reported as a decision with a reason.
- A dataset whose `revenue` column disagrees with its own definition now
  produces a warning and a failed quality check on that stage — but does
  **not** fail the run. The breach is a finding about the data, and
  killing the run would hide the report that explains it. The approval
  gate is where a human decides what to do about it.

## Alternatives considered

**Infer definitions from the data.** Rejected. A system that guesses that
`revenue ≈ price × units` and then reports that guess as a definition has
manufactured governance, which is worse than none.

**Fail the run on a definition breach.** Rejected. The report is the
artifact that explains the breach; suppressing it to signal severity
would be counterproductive. The failed quality check and the warning
claim carry the signal, and publication still requires a human.

**Put the glossary in the database with a CRUD interface.** Deferred, not
rejected — see above. Nothing in the design prevents it: the stage reads
a list of validated dicts, and where that list comes from is one
function.

**Let the glossary override the measure silently.** Rejected. The point
of the stage is that the choice becomes visible. A glossary that changed
the answer without saying so would be the same failure as the hard-coded
name list, with better provenance.
