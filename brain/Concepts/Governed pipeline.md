---
type: concept
aliases: [Specialist pipeline, Analytics pipeline]
tags: [architecture]
status: active
updated: 2026-10-16
review_every_days: 30
sources: [server/analytics.py, docs/AGENT_CATALOG.md, docs/adr/0009-hermes-and-the-specialist-roster.md]
---

# Governed pipeline

How [[Agentic OS]] analyses a dataset: twenty-one specialist stages in a fixed order, each computing something no other stage computes. The [[Hermes orchestrator]] sequences them, and the [[Approval gate]] closes the run.

## The stages, in order

1. **Preparing the data:** planner, data source, data contract, profiling, quality, privacy, cleaning, metric governance, preparation, and segment concentration.
2. **The four analytics types:** descriptive (what happened?), diagnostic (why?), predictive (what will happen?) and prescriptive (what should I do?). They run as a maturity ladder, with experiment and causal inference, anomaly detection and sensitivity testing between them.
3. **Making it trustworthy:** visualisation, provenance, independent validation and reporting.
4. **Publishing:** an approval-gated task that writes to the vault.

## Rules that make it governed

- A claim without evidence, or written in statistical jargon, fails validation.
- Association is never reported as cause; causal claims need a control and a treatment group.
- Every figure names its measure and its owner through the metric glossary, and follows [[Weighted KPIs]].
- Runs are durable: they can be paused, cancelled and resumed after a crash.

## Limits

One CSV dataset per run, with a single measure, group and date. These are the gaps in the [[Analytics OS roadmap]].

## Related

- [[Custom stages]]: how a domain stage joins the same audit.
- [[Decision log]]: decisions 0007, 0009, 0010 and 0011 shaped the pipeline.
