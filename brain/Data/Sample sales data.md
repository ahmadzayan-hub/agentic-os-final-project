---
type: dataset
aliases: [Bundled sample, Sample dataset]
tags: [data]
status: active
updated: 2026-10-16
review_every_days: 90
sources: [server/analytics.py]
---

# Sample sales data

The dataset [[Agentic OS]] analyses when nobody uploads one. It is generated deterministically in code, so every test and demo gets the same numbers.

- **Shape:** 72 rows: 12 months of 2025 × 2 regions (North, South) × 3 categories (Hardware, Software, Services).
- **Columns:** `month`, `region`, `category`, `revenue`, `units`.
- **Built-in pattern:** 3% monthly growth plus a 12% lift in November and December, so trends, seasonality and forecasts have something real to find.

It runs through the [[Governed pipeline]] like any upload, and it is what the end-to-end tests analyse.

## Related

- [[Team 3 maintenance dataset]]: the far larger course dataset, which is not bundled.
- [[Analytics OS roadmap]]: multi-dataset runs will need more samples than this one.
