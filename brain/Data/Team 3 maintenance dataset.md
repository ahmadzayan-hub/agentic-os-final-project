---
type: dataset
aliases: [Maintenance dataset, Group_9226_Team_3_Enterprise_Dataset]
tags: [data, course]
status: active
updated: 2026-10-16
review_every_days: 30
sources: [project-progress.md]
---

# Team 3 maintenance dataset

The course-supplied dataset behind the [[Team 3 Capstone]]: synthetic maintenance records for five asset classes. It is a course file, so it is **not** in this repository and must not be committed.

## Facts verified in the analysis

- 5,000 records, 60 variables, January 2024 to December 2026. No missing values and no duplicate record IDs.
- Thirteen KPI formulas recompute exactly from their parts.
- **Asset IDs are not assets:** they repeat every 180 rows and change class, site and criticality, so the record is the unit of analysis.
- Risk_Category is just Condition_Risk_Score cut at 18 and 32, and the five composite scores fit other columns with R² from 0.82 to 0.98, so they are benchmarks, not model inputs.
- Loss is 4.5 times maintenance spend: $228.9M against $50.4M. Loss per downtime hour is about $2,500 in every criticality band.
- Age is the strongest gradient: MTBF falls from 460 h to 204 h, and loss per record rises from $26,501 to $83,610.
- There is no trend across the 12 quarters.
- No failure mode dominates: each causes 18.9% to 20.6% of downtime.
- Stockouts double the outage: 44.5 h against 22.2 h of downtime per corrective record, from 84 records. Lead time has no link to downtime (r = 0.04).
- Reactive maintenance is worst at the same average age of 8.1 years: MTBF 219 h against 363 h for condition-based maintenance, and 57% more loss per record.
- Critical equipment meets its SLA in 29.1% of records, against about 49% for other levels. Team A's night shift is the weakest team-shift cell, at 42.9%.

## Why it matters beyond the course

At 2.1 MB it was just over the old 2 MB limit of [[Agentic OS]]; since ADR 0024 it fits the 4 MB upload limit, and its 60 columns are well under the 500-column cap. It needs exactly what the [[Analytics OS roadmap]] adds: [[Column mapping]], a dashboard and classification models. Mapping arrived first (ADR 0025): mapped, its `Record_Date` column trends by month over 36 periods, where the old name rule found no date at all. It is the obvious test case for these features, used locally and never committed.

## Related

- [[Weighted KPIs]]: first proved on this data.
- [[Sample sales data]]: the small bundled dataset.
