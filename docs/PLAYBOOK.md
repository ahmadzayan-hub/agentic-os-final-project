# Operating playbook

How this repository is structured and run, day to day, by people and by Claude Code. Agentic OS is the product. This playbook covers the system around it, which keeps the work continuous, verified and remembered from one session to the next.

## 1. The five layers

| Layer | Lives in | Job | Changed by |
| --- | --- | --- | --- |
| Product | `server/`, `frontend/`, `main.py`, `agent.py` | The analytics assistant itself | Feature work, with tests and an ADR |
| Working memory | `CLAUDE.md`, `Memory.md`, `project-progress.md`, `session-logs.md` | What every session must know, what is happening, what happened | The session skills |
| Second brain | `brain/` | Linked knowledge: who the user is, what the OS is, its principles, projects, concepts, data, decisions | The session-end and brain-maintenance skills |
| Automation | `.claude/` | Hooks that record and remind; skills that do the judgement work | Deliberate changes, reviewed like code |
| Governance | `docs/adr/`, `tests/`, `.github/workflows/ci.yml` | Decisions written down; claims checked; CI on every push | Every change |

Two rules hold the layers together:

1. **Facts flow one way, from evidence to records.** A number gets into `Memory.md`, the progress board or the brain only after something produced it: a test run, a commit, the code itself. Records never feed back into code as truth. When they disagree, the code wins, and the record is fixed.
2. **Hooks record and remind; skills edit.** Hooks are deterministic, fast and fail-open. Anything that needs judgement belongs to a skill: what is durable, what is stale, which notes are duplicates.

## 2. Structure

```text
CLAUDE.md                    instructions Claude Code reads first
AGENTS.md                    the same rules, short, for Codex and other agents
Memory.md                    durable facts, under about 150 lines
project-progress.md          Now · Next · milestones · gaps · shipped · risks
session-logs.md              one entry per session, oldest first
brain/                       Obsidian vault, entry point Home.md
  User.md Identity.md Soul.md   the core three
  Projects/ Concepts/ Data/ Decisions/ Operations/
  _meta/Note schema.md       rules for notes
  _meta/Maintenance log.md   what each maintenance round changed
  _templates/Note.md         start every new note here
  private/                   git-ignored, personal notes
.claude/
  settings.json              the three hooks
  hooks/                     session_start.py · stop_gate.py · session_end.py
  skills/                    session-start · session-end · brain-maintenance · verify · motion
                             · review-loop · dashboards
                             design: ui-ux-pro-max · design-system · brand · ui-styling
                             · design · banner-design · slides (third-party, see PROVENANCE.md)
  agents/                    the agent team (docs/AGENT_TEAM.md): motion-designer, dashboard-analyst
                             and five read-only reviewers
  consult-models.json        free local models for scripts/consult.py, one per kind of task
  commands/                  empty until a feature needs one
  plugins/README.md          how to add a plugin
  state/                     git-ignored hook state, one file per session
scripts/brain_check.py       finds brain problems; never edits
scripts/verify.py            runs every check and prints the real counts
scripts/review_gate.py       scores a deliverable's gates, round by round
scripts/figures_check.py     every figure in a document traced to a register, arithmetic checked
scripts/analyse.py           a file through the governed pipeline, exported as figures, never rows
scripts/consult.py           a second opinion from a free local model, refusing raw data
docs/PLAYBOOK.md             this file
```

## 3. The daily rhythm

### Every session

1. **Start (automatic).** The SessionStart hook records the starting branch and commit in `.claude/state/`. It then briefs Claude with the *Now* section, the last log entry and the brain's health, and says whether brain maintenance is due.
2. **Orient.** The `session-start` skill reads `Memory.md`, the board, the last log entry, `Soul.md` and `User.md`, checks Git, and states the plan in a few lines. If the user has already asked for something, that comes first.
3. **Work.** Branch rules from `CLAUDE.md` apply. Test as you go, and commit with messages that explain why. Before saying a change works, run `python scripts/verify.py` (the `verify` skill) and quote what it printed.
4. **End.** The `session-end` skill:
    - appends the log entry under the session's id;
    - moves items on the board;
    - updates `Memory.md` and the brain notes the work touched;
    - runs `python scripts/brain_check.py --strict`;
    - commits and pushes to the working branch.
5. **Safety nets.**
    - The Stop hook blocks a finish once if the session made commits but has no log entry.
    - The SessionEnd hook appends a factual automatic entry if the skill never ran. That entry is not committed until the next session.

### Once a day

The first session of the day runs the `brain-maintenance` skill after the user's first request. It:

- refreshes stale values against their sources;
- merges duplicate notes;
- repairs broken links and links unlinked mentions;
- strengthens the links among User, Identity and Soul;
- records the round in `brain/_meta/Maintenance log.md`.

The hook knows it is due because that log has no section dated today.

### Once a week

- Read `project-progress.md` top to bottom. Is *Now* still true, and are the milestone statuses honest?
- Skim the week's `session-logs.md` entries for decisions that deserve an ADR or a `Memory.md` line.
- Run `python scripts/brain_check.py`, and look past the strict faults at weakly linked notes and orphans.
- Prune `Memory.md` back to what a new session really needs.

## 4. Runbooks

### Analyse a dataset (today)

1. `python scripts/serve.py`, then open `http://localhost:8000`, or use the deployment.
2. In **Datasets**, add a file (CSV, Excel, JSON or JSON Lines, up to 4 MB, ADR 0024) and say what each column is under **Columns** (ADR 0025). Then, in **Runs**, give a goal ("Why did revenue fall in Q4?") and choose that dataset, or use the bundled sample.
3. The pipeline profiles, cleans, governs the measure, runs the four analytics types, validates and reports. Read the headline of each report tab, then the evidence behind each claim.
4. Approve the publish step only after reading. The report and its run log go to `vault/`.

Several datasets in one run, dashboards in the app and live data are milestones A3 to A7 on the board, not features yet. Outside the app, the `dashboards` skill already turns one file into a sourced dashboard (runbook below).

### Build a roadmap milestone

1. Write the ADR first (`docs/adr/00NN-….md`): the problem, the options, the decision, and what would prove it wrong.
2. Write the tests that define done: the gate column on the board. They cover English and Arabic for anything user-facing.
3. Implement. Keep the governed pipeline's guarantees: validation, provenance and the approval gate.
4. Update `README.md` (feature list and test counts), `docs/KNOWN_LIMITATIONS.md`, and the brain note `Projects/Analytics OS roadmap.md`.
5. Run `python scripts/verify.py --e2e`, with `PG_TEST_URL` set so that the PostgreSQL tests run too. Push, and confirm CI. Then mark the milestone Done on the board, with the date and the evidence.

### Add knowledge to the brain

1. Copy `brain/_templates/Note.md` into the right folder, titled by what the note is.
2. Fill in the frontmatter: `type`, today's `updated`, `review_every_days`, and `sources` (paths that exist).
3. Write the first sentence as the point. Link at least two related notes, and add a link from `Home.md`.
4. Run `python scripts/brain_check.py --strict`.

### Add a skill, command, subagent, hook or plugin

- **Skill:** `.claude/skills/<name>/SKILL.md` with `name` and a `description` that says when to use it. Bundle scripts beside it if needed. Prefer a skill to a command.
- **Command:** `.claude/commands/<name>.md`. Every `.md` file there becomes a command, so keep notes out of that folder.
- **Subagent:** `.claude/agents/<name>.md`, with `name` and `description` required.
- **Hook:** add the entry to `.claude/settings.json` and the script to `.claude/hooks/`. It must fail open, finish in seconds, and come with tests in `tests/test_project_os.py`.
- **Plugin:** follow `.claude/plugins/README.md`.

Each of these is code that runs on teammates' machines. Review it like code.

### Make an animated clip for a deliverable

1. Gather the figures from a verified source, such as the KPI register, a run's calculations or `Expected_Values.csv`.
2. Ask for the `motion-designer` subagent, or use the `motion` skill directly. Either way, every figure in the spec carries its `source`.
3. Run `node .claude/skills/motion/render.mjs spec.json --check`, then render to an MP4.
4. Read the review sheet before delivering. Hand over the MP4 with its poster and transcript; the transcript is the text alternative.
5. Course and client clips are written outside the repository. Only sample-data examples live in `.claude/skills/motion/examples/`.

Claude Motion, Anthropic's hosted feature, does the same thing in claude.ai on Team and Enterprise plans. This repository's skill is the local equivalent, because the hosted feature has no API.

### Review a deliverable until it is validated

1. Write a plan for `scripts/review_gate.py`: the gates (page counts, figures against the register, required sections, markers that must be gone), each team-owned gate with its `owner`.
2. Run the `review-loop` skill. Each round:
    - scores the gates;
    - sends the reviewers in parallel;
    - fixes what is yours;
    - rescores.
3. Recompute a reviewer's figures yourself before passing them on. The first capstone review found that a reviewer's numbers were right nearly everywhere, but not everywhere.
4. Turn each finding into a gate where a pattern can check it, so the next round checks the fix without a reviewer.
5. 100% means every gate passes, or is accepted in the plan by a named person with a reason. Otherwise the loop stops after five rounds, or after two rounds with no gain, and reports what is left and whose it is.

### Build a dashboard from a file

1. `python scripts/analyse.py data.csv --mapping m.json --out analysis.json --csv-dir aggregates/` runs the governed pipeline at no cost. The export holds totals with their record counts, per-record values, calculations and claims, never rows.
2. Read the claims marked `limitation` first. ADR 0026: when periods or groups hold different numbers of records, read the per-record view before the totals.
3. In claude.ai, the `dashboards` skill builds a Claude Dashboard from the aggregate files. Anywhere else, `render.py` writes an offline page.
4. Check that every number is sourced with `scripts/figures_check.py`, passing the aggregate files as references.

### Work with another coding agent

Codex, Copilot and similar tools read `AGENTS.md`. It points them to `CLAUDE.md` and repeats the rules that must not be missed. They do not run the hooks or skills in `.claude/`, so they verify with `python scripts/verify.py` and write their own `session-logs.md` entry by hand. When a rule in `CLAUDE.md` changes, change `AGENTS.md` in the same commit; `tests/test_docs.py` checks that every path it names exists.

### Onboard a teammate

Send them `CONTRIBUTING.md`. Once they clone the repository and trust the folder in Claude Code, their sessions get the same briefing, skills and brain. Their private notes go in `brain/private/`.

### When something goes wrong

| Symptom | Fix |
| --- | --- |
| No briefing at session start | Check `/hooks`, that `python3` is on the path, and that the folder is trusted. Run `echo '{}' \| python3 .claude/hooks/session_start.py` to see the output |
| The Stop hook keeps asking for a log | Run the session-end skill, or tell Claude to stop without logging. The gate fires only once per session |
| `verify.py` reports FAIL | It prints the end of the failing step's output. Rerun that step alone, with the command `python scripts/verify.py --list` shows, to see all of it |
| `brain_check.py --strict` fails | It names the note and the problem. Fix links to the note that was meant, and sources to paths that exist |
| `Memory.md` or the board contradicts the code | The code wins. Fix the record and mention it in the session log |
| A cloud session ended before logging | Its automatic entry, if written, was lost with the container. Reconstruct it from `git log` at the next session start |

## 5. Principles

Everything here serves the principles in `brain/Soul.md`: evidence before claims, no secrets, raw data never sent to a model, people approve consequential actions, no rewritten history, limits stated openly, private data kept private, both languages first-class, and decisions written down.
