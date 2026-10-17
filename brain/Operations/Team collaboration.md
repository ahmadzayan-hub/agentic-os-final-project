---
type: operation
aliases: [Collaboration, Contributing]
tags: [operating, team]
status: active
updated: 2026-10-16
review_every_days: 30
sources: [CONTRIBUTING.md, .github/pull_request_template.md]
---

# Team collaboration

How the [[User]]'s teammates take part in [[Agentic OS]]. The full guide is `CONTRIBUTING.md`.

- **Access:** collaborators with the Write role, invited by the owner. The repository is public, so anyone can fork it and open a pull request.
- **Flow:** branch from the default branch, open a pull request, have it reviewed by one teammate, and merge when CI is green. The pull-request template carries the safety checklist.
- **Rules:** no secrets, no personal data or course files, and no force-push, all from [[Soul]]. Course files go in a `private/` folder, which Git ignores.
- **Shared memory:** `session-logs.md`, `project-progress.md` and this [[Second brain]] are committed, so a teammate's Claude Code session starts from the same briefing. The hooks run for anyone who trusts the folder in Claude Code.

## Related

- [[Session lifecycle]]: what every session does with those files.
- [[Team 3 Capstone]]: the same team, on the course deliverables.
