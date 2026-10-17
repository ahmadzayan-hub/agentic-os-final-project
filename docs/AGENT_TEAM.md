# The agent team

How Claude Code works on this repository and its deliverables with a team of specialist agents:

- who does what;
- which model each job gets, so that cost stays as close to zero as quality allows;
- how a review loop reaches full validation, or says honestly why it cannot.

Written on 2026-10-16. The facts about Anthropic products are from Anthropic's own pages on that date, and they are cited below.

## 1. The cost rule: the cheapest tool that can be right

Every job goes to the first tier that can do it correctly.

| Tier | What | Cost | Used for |
| --- | --- | --- | --- |
| 0 | Deterministic scripts | Nothing, and no tokens | Tests, builds and budgets (`scripts/verify.py`); every figure checked against its register (`scripts/figures_check.py`); causal wording (`scripts/claims_lint.py`); the review scorecard (`scripts/review_gate.py`); every agent's confusion matrix and recall (`scripts/evaluate_agents.py`, `scripts/score_review.py`); the brain check; `render.mjs --check`; the governed analysis pipeline itself |
| 1 | Open-source models on your own machine, through Ollama (`scripts/consult.py`) | Nothing, and data stays on the machine | A second opinion on prose; English–Arabic checks; summarising long logs; triage. Never raw data |
| 2 | Claude Haiku subagents | Low | Reading and checking that needs tools: auditing figures, accessibility and translation checks, security and privacy sweeps |
| 3 | Claude Sonnet subagents | Moderate | Expert judgement: analytics method, compliance with a brief, dashboard analysis |
| 4 | The main session (its own model) | As configured | Running the loop, making the fixes, and talking to you |

Two habits keep tokens down whatever the tier:

- **Agents read scorecards, not files.** A reviewer gets the gate results and the paths that failed, not whole documents to re-read.
- **Agents call scripts, not prose.** A number is checked by `figures_check.py`, not by a model reading two documents side by side.

Claude models are not free. Claude Code's usage is covered by your plan, and tiers 0 and 1 add nothing to it. A free route for Claude Code's own reasoning exists: Claude Code can be pointed at a self-hosted gateway in front of an open model. It is not configured here, because review quality would drop where it matters most.

### Free models for tier 1

All have open weights under Apache 2.0 and run through [Ollama](https://ollama.com). Pull only what your machine can hold. The tool falls back down each list to whatever is installed.

| Task (`--task`) | First choice | Fallbacks | Why |
| --- | --- | --- | --- |
| `summarise` | `qwen3:4b` | `qwen3:1.7b`, `qwen3:0.6b` | Fast on a laptop CPU |
| `prose-review` | `qwen3:8b` | `qwen3:4b` | Plain-English and Arabic review of a draft |
| `translate-check` | `qwen3:8b` | `qwen3:4b` | Qwen3 covers over 100 languages, Arabic included |
| `code-review` | `qwen3-coder:30b` | `qwen2.5-coder:7b`, `qwen3:8b` | Code models: the 30B on a 24 GB GPU, the 7B on a laptop |
| `reason` | `gpt-oss:20b` | `qwen3:8b` | A reasoning model, for a second opinion on compliance with a brief |
| `classify` | `qwen3:1.7b` | `qwen3:0.6b` | One-word answers, such as triaging findings |

The table lives in `.claude/consult-models.json`, so a team can change it without touching code. Licences and sizes come from the model cards; check a card before pulling a new model.

## 2. The roster

Subagents live in `.claude/agents/`. Claude Code loads them when a session starts, and **a subagent cannot start another subagent**. So the loop is run by the main session, through the `review-loop` skill, and the reviewers report back to it. A reviewer never edits. Fixes are made by the main session, or by the maker agent for that kind of output.

| Agent | Model | Job | Tools |
| --- | --- | --- | --- |
| `figures-auditor` | haiku | Every number in a deliverable against its register; abbreviations and rounding accepted, anything else flagged | Read, Grep, Glob, Bash |
| `brief-compliance-reviewer` | sonnet | A deliverable against its brief or rubric: required sections, lengths, file names, evidence for each criterion | Read, Grep, Glob, Bash |
| `analytics-expert-reviewer` | sonnet | Method: weighted KPIs, denominators, baselines, association against cause, weak models stated as weak, limits stated | Read, Grep, Glob, Bash |
| `security-privacy-reviewer` | haiku | Secrets, personal and course data, raw data sent to a model, the public-repository rules | Read, Grep, Glob, Bash |
| `accessibility-i18n-reviewer` | haiku | WCAG 2.2 AA evidence (axe, keyboard, contrast), English and Arabic parity, right-to-left layout | Read, Grep, Glob, Bash |
| `dashboard-analyst` | sonnet | Deep analysis through the governed pipeline, then a dashboard: Claude Dashboards, or an offline HTML page | Read, Write, Edit, Bash, Glob, Grep |
| `motion-designer` | inherit | Animated explainers from sourced figures | Read, Write, Edit, Bash, Glob, Grep |

## 3. The review loop: what 100% means

**100% validated** means two things:

1. Every gate in the deliverable's review plan passes.
2. Every finding from every reviewer is either fixed, or accepted in writing by a named person.

That is the only definition the loop uses, and it never reports a percentage it did not measure.

- **Plan:** a JSON file names the gates: commands that must exit 0, figure registers, page ranges, text that must and must not appear, and files that must exist. `scripts/review_gate.py` runs them and keeps the score for each round.
- **Round:**
    1. Run the gates.
    2. Send the scorecard to the reviewers the plan names, in parallel.
    3. Fix what can be fixed, and record accepted exceptions with a name and a reason.
    4. Run the gates again.
- **Stopping:** at 100%; after five rounds; or after two rounds in a row with no gain. Then the loop reports what is left and whose it is.
- **Boundaries:** it never edits a fact it cannot source, never weakens a gate to pass it, and never accepts an exception on the owner's behalf. Items only the team can supply are listed for the team; they are not filled in. Examples are a registration number, a screenshot, or the date of an email.

The loop stops rather than running forever. That matches the project's rule that runs are bounded (`docs/KNOWN_LIMITATIONS.md`, item 5).

## 4. Claude Dashboards and Claude Motion

Both were announced by Anthropic on 8 October 2026 ([announcement](https://claude.com/resources/articles/dashboards-and-motion)). Both are hosted features of claude.ai, not packages, so neither can be installed in a repository.

- **Claude Dashboards** turns questions about live data into a dashboard that stays current. It is in beta on paid plans, and off by default on Enterprise until an admin enables it. Clicking a number shows the query behind it.
  - **Here:** in a claude.ai cloud session, its *Dashboard* artifact type is available to the `Artifact` tool. The `dashboard-analyst` builds real Claude Dashboards there, from datasets the governed pipeline has verified.
  - **Elsewhere:** the same agent writes an offline HTML dashboard with `.claude/skills/dashboards/render.py`. It is free, makes no network calls, and shows every figure's source.
- **Claude Motion** ([support article](https://support.claude.com/en/articles/17454997-get-started-with-claude-motion)) turns content into short animated explainers written as code. It is in beta on Team and Enterprise. The local equivalent is `.claude/skills/motion`, used by `motion-designer`.

## 5. The first run: the capstone deliverables, 16 October 2026

The loop's first real use was on Team 3's report, deck, briefing clip and Power BI kit. The deliverables are private, so this section records only what the run taught.

- **Score:** 50.0% → 56.2% → 62.5% → 62.5%. Six gates were added after round 1, one for each finding a pattern can check.
    - All ten gates the session could act on pass.
    - The six left need the team: the `.pbix` (only Power BI Desktop can save it), the team's own items, and two wording changes in the team's shared report.
- **Cost:** four reviewers ran in round 1, two Sonnet and two Haiku, in parallel. Round 2 used one Haiku reviewer to confirm the build fixes, which beat running all four again.
- **What only experts caught:** the analytics reviewer found two headline claims that do not hold, both confirmed by recomputing from the data.
    - A row-average comparison counted placeholder rows.
    - A causal reading of stockouts was not supported: those records fail twice as often, with the same downtime per failure.
- **What the tools learned:** each lesson became code and tests.
    - **The checker.** `figures_check.py` now reads figures glued to a word by text extraction. It checks written-out arithmetic and reads CSV cells one by one.
    - **The pipeline.** Analysing the capstone data for a dashboard showed that a monthly total "fell 39%" only because the last year holds half the records a month. Per record it rose: ADR 0026.
    - **The motion skill.** Transcripts keep on-screen words apart from their sources, and a clip can name its poster.
    - **Starting again.** `review_gate.py --reset` now archives earlier rounds instead of deleting them.
- **Verify the verifier:** a reviewer's figures were right nearly everywhere and wrong in two small places. The loop now recomputes before passing numbers on.

## 6. How well each agent does

Every classifying agent is measured (ADR 0027), with a confusion matrix, precision and recall:

- **Rule-based agents:** `python scripts/evaluate_agents.py [--misses] [--html report.html] [--check]` runs the labelled suites in `evals/`. Each has dev cases, used to find fixes, and holdout cases, used only to judge them. For the text classifiers, the holdout is a blind set written by an independent agent from the label definitions alone. `evals/floors.json` holds the recall each suite must keep, and `tests/test_evals.py` enforces it.
- **Reviewer subagents:** `evals/reviewers/` holds three synthetic memos with planted defects:
    - A is used to choose fixes;
    - B is held out;
    - C was written blind.

  Run a reviewer on a memo and save its reply in `evals/reviewers/runs/<agent>-<memo>-<tag>.txt`. Then `python scripts/score_review.py --summary` scores every saved run three ways: in its lane, by paragraph detection with false alarms, and as a category confusion matrix. `--figures-tool` scores the Tier 0 checker the same way.
- **Prompt changes:** a subagent's instructions load when a session starts, so an edited prompt is not live until the next session. To compare two versions now, give a general-purpose agent on the same model each version's instructions, and change nothing else ("ctl" runs).
- **What the numbers say today:**
    - On the newest blind set (v4), recall is 72% for intent, 92% for jargon and 69% for causal wording.
    - Each round of rule fixes helps less on unseen sentences than on the cases it came from: intent went 68% → 72% on v4, and causal wording did not move. Wider understanding needs a model behind the rules (ADR 0019), which this environment cannot measure.
    - The figures auditor and the analytics reviewer were near their ceiling on the seeded memos. Harder memos are the next step (`project-progress.md`).

## 7. Adding an agent

1. Give it one job that the roster does not already cover, and a tier.
2. Give it the fewest tools that job needs. Reviewers get no Write or Edit.
3. Give it rules it must not break: no unsourced figure, no course data in Git, no raw data to a model.
4. Add it to the table above and to `tests/test_agent_team.py`, which checks every agent's frontmatter and model.
5. If it classifies, give it a labelled suite (dev and holdout) or a seeded benchmark, and a floor (§6).
