---
type: concept
aliases: [Confusion matrix, Recall floors, Blind holdout, Reviewer benchmark]
tags: [measurement, quality]
status: active
updated: 2026-10-17
review_every_days: 30
sources: [docs/adr/0027-agents-are-measured.md, scripts/evaluate_agents.py, scripts/score_review.py, evals/floors.json, evals/reviewers/README.md, evals/reviewers/summary.json]
---

# Agent evaluation

How [[Agentic OS]] knows how often each of its agents is right: labelled synthetic cases, a confusion matrix per agent, recall floors, and holdouts written blind. It is what turns "the agent works" into a number a reader can check.

## Facts

- **Method (ADR 0027):**
    - Fixes come from dev misses only. Holdouts judge them.
    - For the text classifiers, each holdout is written blind by an independent agent from the label definitions alone, then joins dev after the round.
    - Floors in `evals/floors.json` fail the tests on any regression.
- **Overfitting shows:** chat intent scored 100% on dev and 68% on a blind set. After another round it scored 80% on a new blind set of 60 cases.
- **Blind recall on 2026-10-17 (round 5, blind set v4), before → after:**
    - intent 68% → 72%;
    - jargon 83% → 92%;
    - causal wording 69% → 69% (precision 92%).
    - The rules scored 80% on intent on the previous blind set. One blind set overstates how far hand-written rules generalise.
    - Privacy, the raw-data guard and the figures checker each scored 100% on their holdouts.
- **Reviewer benchmark:** three seeded memos.
    - Dev A; B held out, from the same author; C written blind.
    - The Tier 0 figures checker went from 0% to 75% lane recall on C, with no false alarms.
    - The Haiku figures auditor caught every planted figure defect with either prompt. The Sonnet analytics reviewer went from 83% to 100% on A, and stayed at 80% on B and 100% on C.
    - The memos were nearly too easy for the language models.
- **Two lessons from the checker:**
    - A rule that derives figures must keep to prose. The capstone dashboard's data table broke it.
    - It must count one quantity once, which the figures holdout showed.
- **Controlled comparison:** an edited subagent loads only in a new session. So prompt versions are compared by giving a general-purpose agent on the same model each version's instructions, and changing nothing else.

## Related

- [[Home]]
- [[Soul]]: no fabricated numbers, so the honest number is the blind one.
- [[Agent team]]: the reviewers this measures.
- [[Weighted KPIs]]: the denominator category in the reviewer benchmark tests this rule.
