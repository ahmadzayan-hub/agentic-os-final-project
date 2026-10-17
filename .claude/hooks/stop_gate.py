#!/usr/bin/env python3
"""Stop hook: do not let a session that changed the code end unlogged.

If the session has made commits since it started and session-logs.md has
no entry for it, block the stop once and name the session-end skill as
the fix. It fires at most once per session. A person who wants to stop
without logging can say so, and the second stop goes through. It does
nothing when stop_hook_active is set, so it can never loop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (git, has_log_entry, load_state, now, project_dir,  # noqa: E402
                     read_input, save_state, short_id)


def decide(data: dict) -> dict | None:
    if data.get("stop_hook_active"):
        return None
    root = project_dir(data)
    sid = data.get("session_id") or ""
    state = load_state(root, sid)
    if not state or state.get("gate_fired"):
        return None
    start = state.get("start_head") or ""
    if not start or git(root, "rev-parse", "HEAD") in ("", start):
        return None
    commits = git(root, "rev-list", "--count", f"{start}..HEAD")
    if not commits or commits == "0" or has_log_entry(root, sid):
        return None
    state["gate_fired"] = now()
    save_state(root, sid, state)
    return {
        "decision": "block",
        "reason": (
            f"This session made {commits} commit(s), but session-logs.md has no "
            f"entry for session `{short_id(sid)}`. Follow the session-end skill "
            "(read .claude/skills/session-end/SKILL.md; it is manual-only, so the "
            "user can also run /session-end): log the session, update "
            "project-progress.md, Memory.md and the brain notes it touched, then "
            "commit. If the user asked to stop without logging, say so and stop."
        ),
    }


def main() -> int:
    decision = decide(read_input())
    if decision:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open
        print(f"Stop hook error (ignored): {exc}", file=sys.stderr)
        sys.exit(0)
