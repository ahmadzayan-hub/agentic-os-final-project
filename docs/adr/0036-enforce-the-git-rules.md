# ADR 0036 — The Git rules are enforced, not only written

**Status:** Accepted
**Date:** 2026-10-17
**Keeps:** `brain/Soul.md` and the rules in `CLAUDE.md`; the hooks fail open (a crash never stops work)

## Context

`CLAUDE.md` and `brain/Soul.md` forbid force-pushes, history rewriting, branch deletion, pushes to another branch and secrets in Git. Until now the only enforcement was the prose. Anthropic's best-practices guide separates the two: `CLAUDE.md` is advisory, a hook is deterministic. The repository is public and a capstone deadline is near, so a rule that only a model remembers is a risk. Separately, `session-end` commits and pushes, yet the model could start it on its own.

## Decision

1. `.claude/hooks/guard.py` runs before every Bash call and refuses, with a reason Claude can read:
    - a force-push, a mirror push, a push that deletes, or a refspec starting with `+` or `:`;
    - a push to any branch other than the checked-out one;
    - `git reset --hard`, `git branch -D`, `git filter-branch`, `git filter-repo`;
    - `git add` of `.env` files (not `.env.example`) or `private/`.
2. `permissions.deny` in `settings.json` repeats the sharpest of these and blocks reading or editing `.env` and `.env.local`, so the rule holds even if the hook is off.
3. `session-end` sets `disable-model-invocation: true`. The Stop hook now tells Claude to read and follow the skill, and says the user can run `/session-end`.
4. `CLAUDE.md` says what to keep when compacting and when to run `/context` and `/clear`.

## Consequences

- A person who really wants one of these commands sets `AGENTIC_OS_GUARD_OFF=1` in `settings.local.json`; the setting is theirs and is never committed.
- The guard reads command text. It stops honest mistakes, not a determined shell trick. It is one layer with `permissions.deny` and the Soul.
- `git rebase` and `git commit --amend` are not blocked: they are routine on unpushed local commits, and a rewrite only matters once pushed, where the force-push rule catches it.
- The guard asks Git for the current branch on each Git command (at most five seconds, then it allows).
