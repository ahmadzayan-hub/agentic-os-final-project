---
type: concept
aliases: [KPI register, Ratio of sums]
tags: [measurement]
status: active
updated: 2026-10-16
review_every_days: 60
sources: [server/metrics.py, project-progress.md, docs/adr/0026-uneven-periods-are-read-per-record.md, docs/AGENT_TEAM.md]
---

# Weighted KPIs

Every rate is computed as a summed numerator over a summed denominator, never as an average of row rates. Averaging rows gives a small record the same weight as a large one, and it averages placeholders as if they were measurements.

## The example, corrected

On the [[Team 3 maintenance dataset]], the register values are right: first-time fix 76.6%, repeat repair 23.4%, MTBF 313.3 h, SLA met 46.1%. The first comparison with row averages was not like for like.

| KPI | Row average, all 5,000 records | Row average where the rate is defined | Ratio of sums |
| --- | --- | --- | --- |
| First-time fix | 64.7% | 80.6% (4,015 corrective records) | 76.6% |
| Repeat repair | 15.6% | 19.4% | 23.4% |
| MTBF | 342.5 h | 310.8 h (records with a failure) | 313.3 h |

The 985 preventive records store placeholder rates: a first-time-fix rate of 0, and MTBF equal to operating hours. They made the gaps look about three times larger than weighting alone does. The stored SLA score (75.8% on average) is min(1, target ÷ actual), a different measure from the share of targets met, so it is not a weighting example at all. The analytics reviewer found this in the first review loop, and a recomputation confirmed it ([[Agent team]]).

Two lessons:

- Check what a row's rate means before averaging or comparing it. A placeholder is not a zero.
- The same care applies to counts. A total over periods or groups of different sizes moves with the number of records, so read it per record (ADR 0026).

## In the product

The metric glossary (`metrics.json`) gives each metric a definition, an owner and optional arithmetic checks. The [[Governed pipeline]] fails a run that stays silent about an undefined measure.

## Related

- [[Soul]]: evidence before claims starts with measuring correctly.
- [[Team 3 Capstone]]: where the register was first written.
- [[Analytics OS roadmap]]: dashboard measures must follow the same rule.
- [[Agent team]]: the review that corrected this note.
