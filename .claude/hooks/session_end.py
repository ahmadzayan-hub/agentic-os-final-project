#!/usr/bin/env python3
"""SessionEnd hook: the safety net for a session that was never logged.

If the session-end skill already wrote this session's entry, nothing
happens. Otherwise, when the session committed or changed anything, it
appends a short factual entry to session-logs.md: commits, uncommitted
changes, and a note that no summary was written. It never commits; the
next session picks the entry up.

SessionEnd cannot talk to Claude, and it has a tight time budget (the
settings give it 10 seconds), so it only runs fast git queries.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (SESSION_LOG, changed_files, git, has_log_entry,  # noqa: E402
                     load_state, now, project_dir, read_input, save_state, short_id)

MAX_COMMITS = 15


def entry_for(root: Path, data: dict, state: dict) -> str | None:
    start = state.get("start_head") or ""
    commits = git(root, "log", "--oneline", "--no-decorate",
                  f"--max-count={MAX_COMMITS}", f"{start}..HEAD") if start else ""
    dirty = changed_files(root)
    if not commits and not dirty:
        return None
    sid = data.get("session_id") or ""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD") or state.get("branch") or "?"
    lines = [
        "",
        f"## {dt.date.today().isoformat()} · `{short_id(sid)}` · {branch} (automatic)",
        "",
        f"_Written by the SessionEnd hook ({data.get('reason') or 'other'}) because "
        "the session-end skill did not run. Facts only: review it at the start of "
        "the next session and add what was decided._",
        "",
    ]
    commit_lines = commits.splitlines()
    lines.append(f"- Commits: {len(commit_lines)}"
                 + (" (newest first, at most 15)" if len(commit_lines) >= MAX_COMMITS else ""))
    for c in commit_lines:
        sha, _, message = c.partition(" ")
        lines.append(f"    - `{sha}` {message}")
    lines.append(f"- Uncommitted changes when the session ended: {len(dirty)} file(s)")
    lines.append("- Next: not recorded")
    return "\n".join(lines) + "\n"


def main() -> int:
    data = read_input()
    root = project_dir(data)
    sid = data.get("session_id") or ""
    state = load_state(root, sid)
    if not state or state.get("ended"):
        return 0
    if not has_log_entry(root, sid):
        entry = entry_for(root, data, state)
        if entry:
            log = root / SESSION_LOG
            with log.open("a", encoding="utf-8") as handle:
                handle.write(entry)
    state["ended"] = now()
    save_state(root, sid, state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open
        print(f"SessionEnd hook error (ignored): {exc}", file=sys.stderr)
        sys.exit(0)
