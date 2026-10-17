# .claude: how Claude Code works in this repository

Everything here is shared with the team through Git, except the paths `.gitignore` excludes: `settings.local.json`, `state/` and `agent-memory-local/`. The operating rules are in `docs/PLAYBOOK.md`.

| Path | What it holds |
| --- | --- |
| `settings.json` | `permissions.deny` for force-push, hard reset, branch deletion and `.env` files, and the four project hooks below. Personal settings go in `settings.local.json`, which Git ignores. |
| `hooks/guard.py` | PreToolUse on Bash. Refuses force-pushes, pushes to any branch but the checked-out one, `git reset --hard`, branch deletion, `git filter-branch` and adding `.env` or `private/` to Git (ADR 0036). `AGENTIC_OS_GUARD_OFF=1` in your `settings.local.json` env turns it off for you alone. |
| `hooks/session_start.py` | Records where a session began, and briefs Claude: current focus, last log entry, brain health, whether maintenance is due. |
| `hooks/stop_gate.py` | Blocks a finish once when the session committed work but has no `session-logs.md` entry. |
| `hooks/session_end.py` | Appends a factual automatic log entry if the session-end skill never ran. |
| `skills/session-start/` | Orient: read the memory files, check the repository, state the plan. |
| `skills/session-end/` | Log the session, update progress, memory and the brain, then commit and push. Manual-only (`disable-model-invocation`): run `/session-end`, or follow it when the Stop hook asks. |
| `skills/brain-maintenance/` | Daily: refresh stale values, merge duplicates, repair and add wikilinks. |
| `skills/verify/` | Run every check with `scripts/verify.py` and report the real counts; how to measure Lighthouse. |
| `skills/motion/` | Short animated explainers (MP4) from verified figures, rendered frame by frame from code like Claude Motion: `composition.html`, `render.mjs`, and examples from the sample data. Needs the frontend's Playwright and `ffmpeg`. |
| `skills/review-loop/` | The review super-agent's method: score the gates, send the reviewers in parallel, fix, rescore, until 100% or the loop stops. Gates run with `scripts/review_gate.py`; figures with `scripts/figures_check.py`. |
| `skills/dashboards/` | Deep analysis with `scripts/analyse.py`, then a dashboard where every figure cites its calculation: a Claude Dashboard where the artifact type exists, or an offline page (`render.py`). |
| `skills/rta-style/` | The house style for agent outputs: tokens for light and dark (AA contrast tested), used by the dashboards renderer (`--theme rta`), the clips (`"theme": "rta"`) and the evaluation report; and a print variant for reports and decks (`document.css`, and `restyle.py`, which recolours default-palette HTML by role). Colours, type and layout only; no logo, name or data. |
| `skills/ui-ux-pro-max/` | Design intelligence for the interface: styles, palettes, type, UX rules, charts (ADR 0023). |
| `skills/design-system/`, `brand/`, `ui-styling/` | Token architecture and a token validator; brand voice and identity; shadcn/Tailwind and canvas posters (not for the app). |
| `skills/design/`, `banner-design/`, `slides/` | Logos, corporate identity, icons, banners and HTML decks. The logo, identity and icon generators call third-party image services and need an API key. |
| `commands/` | Slash commands. Empty for now; see below. |
| `agents/` | The agent team (`docs/AGENT_TEAM.md`), loaded when a session starts:<br>• `motion-designer`: sourced, animated explainers.<br>• `dashboard-analyst`: deep analysis and dashboards.<br>• Five read-only reviewers for the review loop: `figures-auditor`, `brief-compliance-reviewer`, `analytics-expert-reviewer`, `security-privacy-reviewer` and `accessibility-i18n-reviewer`.<br>Each has the cheapest model that does its job well. |
| `consult-models.json` | Which free local model `scripts/consult.py` asks for each kind of second opinion. |
| `plugins/` | How to add project plugins. Documentation only. |
| `state/` | Hook runtime state, one JSON file per session. Git ignores it. |

Hooks run only after you trust this folder in Claude Code, and they need `python3` on the path. Each one fails open: an error prints a warning and never stops your session. `/hooks` lists what is active, and `"disableAllHooks": true` in your `settings.local.json` turns them off for you alone.

## Adding a command

Claude Code has merged commands into skills. Prefer `skills/<name>/SKILL.md`, which is also invocable as `/<name>`. A one-file prompt can still go in `commands/<name>.md`:

```markdown
---
description: One line shown in the / menu
argument-hint: <dataset name>
---

Analyse the dataset named $ARGUMENTS with the governed pipeline, then …
```

Every `.md` file in `commands/` becomes a command, so keep notes like this one out of that folder. Do not reuse built-in names such as `/status`, `/help` or `/review`.

Planned, with the analytics roadmap in `project-progress.md`: `/analyse <dataset>` once the dataset API exists, and `/dashboard <run>` once dashboard pages exist. They are not here yet, because a command for a missing feature would be a stub.

## Adding a subagent

One file, `agents/<name>.md`:

```markdown
---
name: data-quality-reviewer
description: Reviews a dataset profile and the cleaning stage's output for problems a person should decide on.
tools: Read, Grep, Glob, Bash
model: inherit
---

You review data quality for Agentic OS. …
```

`name` and `description` are required. Files without a `name`, or whose `---` is not the first line, are skipped silently. Claude Code reads `agents/` when a session starts, so a new subagent is available from the next session. `motion-designer` is the example to copy: a narrow job, the tools it needs and no more, and rules it must not break. Candidates for the roadmap are a data-quality reviewer and a model evaluator that checks every model against its baseline. Each is added with the feature it serves.

A subagent cannot start another subagent, so a loop that coordinates several of them is a skill the main session runs (`review-loop`), not an agent. Until the next session start, a new agent can be run as a general-purpose agent told to read and follow its file.
