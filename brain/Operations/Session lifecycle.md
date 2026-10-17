---
type: operation
aliases: [Session loop, Operating loop]
tags: [operating]
status: active
updated: 2026-10-16
review_every_days: 30
sources: [.claude/settings.json, .claude/hooks/session_start.py, .claude/hooks/stop_gate.py, .claude/hooks/session_end.py, docs/PLAYBOOK.md, AGENTS.md, scripts/verify.py]
---

# Session lifecycle

Every working session on [[Agentic OS]] runs the same loop, so nothing learnt is lost between sessions and the [[Second brain]] stays current.

## The loop

1. **Start.** The SessionStart hook records where the session began (branch and commit) and injects a short briefing: the progress board's current focus, the last log entry's next steps and the brain's health. Claude then follows the session-start skill: it reads `Memory.md`, `project-progress.md`, [[Soul]] and [[User]], and states the plan.
2. **Daily brain care.** If brain maintenance has not run today, the briefing says so, and the brain-maintenance skill runs once the user's first request is handled.
3. **Work.** Build, test and commit as usual. Before claiming a change works, run `python scripts/verify.py` (the verify skill) and quote the counts it prints, as [[Soul]] requires.
4. **End.** The session-end skill appends the session's entry to `session-logs.md`, moves items on `project-progress.md`, keeps durable lessons in `Memory.md`, updates the brain notes the work touched, and commits.
5. **Safety nets.**
    - The Stop hook blocks a finish once if the session made commits but logged nothing, and names the session-end skill as the fix.
    - The SessionEnd hook appends a minimal automatic log entry when the skill never ran.

## Other coding agents

Codex and similar tools read `AGENTS.md`, which points them to `CLAUDE.md` and repeats the rules they must not miss. They run no hooks, so they verify with the same script and log by hand.

## Why hooks and skills both

Hooks are deterministic and cheap: they record facts and remind. Skills need judgement: they decide what is durable, what is stale and what to link. Neither edits code, and neither pushes.

## Related

- [[Identity]]: the builder agent's operating loop.
- [[Team collaboration]]: the same files keep teammates in sync.
- [[Maintenance log]]: what daily brain care changed.
