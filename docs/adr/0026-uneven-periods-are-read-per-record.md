# ADR 0026: Uneven periods are read per record

**Status:** Accepted
**Date:** 2026-10-16
**Keeps:** the descriptive stage's total change (`c_change`), the column mapping (ADR 0025), claims that trace to calculations, raw data never sent to a model

## Context

The descriptive stage compares a measure's total in the first period with its total in the last. That answers "how much more or less in all", but it misleads when periods hold different numbers of records.

The dashboards skill found this on the capstone dataset:

- **The data:** production loss, by month. In 2024 and 2025 there are 167 records a month; in 2026, 83.
- **What the stage said:** the headline read "down 39% over the period".
- **What happened:** per record, loss rose 23% from the first month to the last. The total fell because the last year holds half as many records, not because loss fell.

A sales file with a partial last month, or a log that gained sources over time, would mislead the same way. The trend chart and the forecast read the same totals.

## Decision

1. **The preparer counts the records behind each total.** Its output gains `group_counts` and `trend_counts`, the number of records with a value in each group and each period. They are counts, not rows, so they may leave the run (`scripts/analyse.py` exports them).
2. **Uneven periods are named.** Periods are uneven when the quietest holds under three quarters of the busiest's records (`UNEVEN_PERIODS = 0.75`). The descriptive stage then adds:
    - three calculations: `c_period_records_min`, `c_period_records_max` and `c_change_per_record` (each period's total divided by its records, first against last);
    - a `limitation` claim, `cl_uneven_periods`, in English and Arabic. It says the periods hold from N to M records, that the change in the total partly reflects that, and what the change is per record;
    - a sentence in the headline: "Periods hold different numbers of records; per record it is up 23%."
3. **Nothing else changes.** The total change, its claim and the forecast stay as they were. A reader sees both numbers and the reason they differ. Even periods produce exactly the report they did before.

## Consequences

- A total and a per-record change can point in opposite directions in one headline. That is the honest reading, and the claim explains it.
- The threshold is a judgement. A quarter fewer records is enough to move a total by a quarter, which is the size of change a headline reports. It is one constant, and the tests pin its behaviour on both sides.
- Group totals can be uneven too: a region with more stores has a larger total. `group_counts` makes per-record breakdowns possible in a dashboard (`.claude/skills/dashboards/render.py`), but this decision does not change the segment or diagnostic stages.
- The validator's lineage check covers the new calculations like any other.

## Tests

`tests/test_analytics.py`, `DirectionOfChangeTestCase`:

- totals keep their counts;
- even periods add nothing;
- a period with fewer records is read per record: a total down 40% is up 20% per record;
- the warning is written in Arabic too.
