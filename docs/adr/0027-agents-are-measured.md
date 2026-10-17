# ADR 0027: Agents are measured

**Status:** Accepted
**Date:** 2026-10-17
**Keeps:** raw data never sent to a model, claims that trace to calculations, the review loop (`docs/AGENT_TEAM.md` §5), deterministic tools before models (Tier 0 first)

## Context

The project has many agents that classify: rules that read a chat sentence, the column mapper, the privacy check, the model router, the raw-data guard, the jargon and causal-wording checks, the figures checker, and the reviewer subagents in the review loop. Until now, each was tested on a handful of examples. Nobody knew how often each one was right, which mistakes it made, or whether a change made it better or only fitted the examples.

## Decision

### 1. Every classifying agent has a labelled suite and a confusion matrix

`scripts/evaluate_agents.py` runs the suites in `evals/` (all synthetic) and prints, for each one:

- a confusion matrix (rows are the true label, columns the prediction);
- per-class precision, recall, F1 and support;
- the headline: positive-class recall for a detector (the share of real cases it catches), macro recall for a multi-class agent.

`--html` writes the report page and `--check` exits 1 below a floor.

| Suite | Agent (module) | Headline |
| --- | --- | --- |
| `intent` | Assistant: what a chat sentence asks for (`assistant.understand`) | macro recall, 10 actions |
| `column_roles` | Column mapping: each column's role (`server/mapping.suggest`) | macro recall |
| `personal_data` | Privacy: columns holding direct identifiers (`server/analytics.personal_data_findings`) | recall |
| `router` | Model routing: which provider a model name means (`server/routing.provider_for`) | macro recall |
| `raw_guard` | Consultation guard: text that is raw rows (`scripts/consult.looks_like_raw_rows`) | recall |
| `jargon` | Plain-language check (`server/analytics` jargon terms) | recall |
| `causal` | Causal wording in a deliverable (`scripts/claims_lint.py`, new) | recall |
| `figures` | Figures checker: unsourced or wrong figures (`scripts/figures_check.check`) | recall |

### 2. Fixes come from dev cases; holdout cases judge them

Each suite has **dev** cases, whose misses are read and fixed, and **holdout** cases, which are scored but never read for fixes. For the three text classifiers (intent, jargon, causal), the holdout is a **blind set**: an independent agent writes it from the label definitions alone, without seeing the rules or the dev cases. After each round, the old holdout joins dev and a new blind set takes its place. This is how overfitting showed up and was kept honest: intent scored 100% on dev and 68% on the second blind set.

### 3. Floors stop regressions

`evals/floors.json` holds each suite's floor (dev and holdout), set from the last measurement and rounded down. `tests/test_evals.py` runs every suite and fails below a floor, so a later change cannot quietly undo a gain. The reviewer benchmark has floors for the Tier 0 checker too.

### 4. The fixes

All of these came from dev misses:

- **Privacy:** a column is personal by its values, not only its name. Person names are recognised in Latin and Arabic script, and dates and times no longer pass as phone numbers. A name match is dropped when the values are categories or short counts.
- **Column mapping:** a year column beside the time axis is a breakdown, and `_centre` or `_center` marks an identifier. Personal columns come from the privacy check.
- **Routing:** naming conventions are read. A colon tag (`qwen2.5:7b`) is local, and an `org/model` path or a `-versatile` suffix is a hosted open model.
- **Raw-data guard:** three more shapes count as rows: JSON records or JSON Lines, space-aligned tables, and repeated `key: value` blocks.
- **Jargon:** more statistical terms in English and Arabic, abbreviations matched as whole words, and `p = 0.03` written out.
- **Causal wording:** `scripts/claims_lint.py` is a new Tier 0 tool, in English and Arabic. It flags effect verbs and their objects ("the discount increased orders"). It leaves alone changes ("orders increased 15%") and sentences about causation itself ("this cannot show which way it runs").
- **Figures checker:**
    - Arabic-Indic digits, accounting brackets and approximations ("about 6,400") are read.
    - From the reviewer benchmark (§5): "12%" and "$12" are figures, not small counts. A percentage is not sourced by a dollar amount.
    - A figure that follows from the sourced figures its sentence names is derived. One that a sentence presents as computed from them, but which does not follow, is wrong arithmetic: "610 staff across 48 stores, 15.2 each" computes to 12.7.
- **Assistant:**
    - Many more ways to ask for help, notes, recall, status and the report, in both languages.
    - `forget` accepts a description ("forget the note about the budget"). It confirms and deletes only when exactly one note matches. Otherwise it lists the matches and deletes nothing.

### 5. The reviewer subagents are scored on seeded memos

`evals/reviewers/` holds three synthetic memos with numbered paragraphs and planted defects. Each paragraph is labelled with one of five categories: unsourced figure, arithmetic, causal claim, denominator, overclaim.

- **A** is the dev memo, used to choose fixes.
- **B** is held out. The same author wrote it.
- **C** was written blind by an independent agent from the category definitions only.

`scripts/score_review.py` parses a reviewer's FINDING blocks and scores three views:

- **Lane recall:** planted defects named in the reviewer's own categories.
- **Detection:** whether each defective paragraph is flagged at all, and false alarms on correct paragraphs.
- **A category confusion matrix:** what the reviewer called each planted defect.

A finding of another category on a defective paragraph is secondary, not a false alarm. `--figures-tool` scores the Tier 0 checker as if it were a reviewer.

The prompts of `figures-auditor` and `analytics-expert-reviewer` were changed from A's misses only:

- **Both:** the five category definitions.
- **figures-auditor:** always runs the sourcing pass, and reads the text for figures the checker cannot see.
- **analytics-expert-reviewer:** "what is a finding": a correct sentence that could say more is a note, not a finding.

Named subagents load their instructions when a session starts. So the comparison gave a model of the reviewer's tier the v1 or the v2 instructions, with the task, tools and checker unchanged ("ctl" runs).

### 6. A house style for agent outputs

`.claude/skills/rta-style/` holds one palette for the dashboards renderer (`--theme rta`), the motion clips (`"theme": "rta"` or `"rta-dark"`) and the evaluation report. It is the user's executive-dashboard look: a red bar, navy and grey charts, tiles with a leading edge, and system fonts with Arabic.

- It carries colours, type and layout only. There is no logo, no name and no data of any organisation, and themed outputs are tested for that.
- The dark palette, and the darker green and amber, are derived so that every text pair meets WCAG 2.2 AA (4.5:1) and every chart colour 3:1, in both modes.

## Results

Headline recall, on synthetic cases. The first round of each suite is before any fix in this ADR.

| Suite | Before: dev / holdout | Now: dev / holdout | Holdout now |
| --- | --- | --- | --- |
| Intent | 82% / 65% | 100% / 80% | blind set, 60 cases (the previous blind set scored 68%) |
| Column roles | 94% / 97% | 100% / 100% | 33 columns |
| Personal data | 67% / 83% (precision 50% / 83%) | 100% / 100% (precision 100%) | 33 columns |
| Router | 86% / 75% | 100% / 90% | 12 names |
| Raw-data guard | 57% / 50% | 100% / 100% | 7 texts |
| Jargon | 56% / 40% | 100% / 83% (precision 100%) | blind set, 24 cases |
| Causal wording | new | 100% / 67% (precision 73%) | blind set, 24 cases |
| Figures | 83% / 80% (precision 56% / 44%) | 100% / 100% (precision 100%) | 11 figures |

Reviewers on the seeded memos: lane recall and false alarms on correct paragraphs, from `evals/reviewers/summary.json`.

| Reviewer | A (dev) | B (held out) | C (blind) |
| --- | --- | --- | --- |
| Tier 0 figures checker, before → after | 25% → 100% (1 → 0 false alarms) | 50% → 100% | 0% → 75% (detection 50% → 75%, 1 → 0 false alarms) |
| figures-auditor (Haiku), ctl v1 → v2 | 100% → 100% | 100% → 100% | 100% → 100% |
| analytics-expert-reviewer (Sonnet), ctl v1 → v2 | 83% → 100% | 80% → 80% | 100% → 100% |
| Both reviewers together, ctl v1 → v2 | 100% → 100% | 89% → 89% | 100% → 100% |

## Consequences

- **Overfitting is visible.** Rules reach 100% on the cases they were fixed on and less on cases they have not seen. The blind holdouts are the honest number: 80% for intent, 83% for jargon and 67% for causal wording, which is the weakest. A new blind set after each round keeps that number honest.
- **The language models were near their ceiling on these memos.** The figures auditor caught every planted figure defect with either prompt, because it reads past the checker. Most of the measurable gain came in the free Tier 0 checker, which now catches more before a model reads a word. The prompt changes are justified on A but not proven on B or C. Harder memos are needed to show a gain.
- **One planted defect sits on a category boundary.** B's "one month's gap proves the shift pattern works" is labelled overclaim, and every analytics run called it a causal claim. The label was not changed after the results were seen.
- **Run-to-run variation is real.** The named analytics reviewer raised 3, 0 and 0 false alarms on A, B and C in its first runs, and 0, 2 and 1 in repeats. No controlled run raised one. One run per condition cannot separate the prompt from chance.
- **What was not measured, and why:**
    - Local open-source models through Ollama could not be downloaded in this environment.
    - The hosted narrator models need provider keys. The key once pasted into chat is treated as compromised and was not used.
- **The checker's figure blind spots:**
    - It still cannot read figures written in words ("one in five"). The auditor's instructions now say to look for them.
    - The derived-figure rule could accept a coincidence. It uses only the sentence's own figures, or register rows named by every word of their label, and the figure's own rounding.
    - The figures holdout caught one coincidence during this work: 75.2% and 0.752 counted as two inputs. The rule now counts one quantity once. That holdout informed the fix, so its 100% is no longer a blind result.
    - The offline capstone dashboard caught another: its data table, read as one long sentence, gave dozens of figures and the word "per", so months were flagged as wrong arithmetic. The rule now applies to prose only, at most 300 characters and six figures. The dashboard and the capstone gates give the same result with the old and the new checker.
- **Precision is kept beside recall.** A detector that flags everything has perfect recall. The report shows precision for every detector, and the floors are on recall only because no change so far traded precision away.

## Tests

- `tests/test_evals.py`:
    - the metrics counted by hand;
    - every suite's labels;
    - every floor;
    - the report page;
    - one example per fix;
    - the reviewer scorer (misses, false alarms, secondary findings, confusion);
    - every benchmark's labels;
    - the Tier 0 checker's floors on A, B and C.
- `tests/test_assistant.py`: forget by description, with one match, several matches, none, and in Arabic.
- `tests/test_rta_style.py`:
    - the CSS built from the tokens;
    - contrast in light and dark;
    - the clip themes match the tokens;
    - the dashboard and the report wear the style;
    - no name or logo in any themed output.
