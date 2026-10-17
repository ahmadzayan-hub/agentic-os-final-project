#!/usr/bin/env python3
"""SessionStart hook: record where the session began, then brief Claude.

What it prints becomes context at the top of the session: the current
focus from project-progress.md, the last session's entry, the brain's
health, and whether daily brain maintenance is due. It also tells Claude
to follow the session-start skill. It never edits a tracked file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (PROGRESS, SESSION_LOG, changed_files, git, last_entry,  # noqa: E402
                     load_state, now, project_dir, read_input, save_state, section,
                     short_id)

MAX_CHARS = 6000  # well under the 10,000-character cap on hook context


def brain_status(root: Path) -> tuple:
    """(summary line, maintenance due?) from scripts/brain_check.py."""
    script = root / "scripts" / "brain_check.py"
    if not script.exists() or not (root / "brain").is_dir():
        return "", False
    spec = importlib.util.spec_from_file_location("brain_check", script)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their module through sys.modules, so register it
    # before running it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = module.check(root / "brain")
    return module.summary_line(report), report["maintenance_due"]


def briefing(root: Path, data: dict, branch: str, head: str) -> str:
    source = data.get("source") or "startup"
    sid = data.get("session_id") or ""
    changes = len(changed_files(root))

    out = ["# Session briefing (from the SessionStart hook)", ""]
    out.append(f"Session `{short_id(sid)}` · {source} · branch `{branch or '?'}` at "
               f"`{head[:7] or '?'}` · {changes} uncommitted change(s).")

    progress = root / PROGRESS
    if progress.exists():
        now_section = section(progress.read_text(encoding="utf-8"), "Now")
        if now_section:
            out += ["", "## Current focus (project-progress.md)", now_section]

    if source != "compact":
        log = root / SESSION_LOG
        if log.exists():
            entry = last_entry(log.read_text(encoding="utf-8"))
            if entry:
                out += ["", "## Last session (session-logs.md)", entry]

    try:
        summary, due = brain_status(root)
    except Exception as exc:  # the briefing must survive a broken checker
        summary, due = f"Brain check failed: {exc}", False
    if summary:
        out += ["", "## Brain", summary]
        if due:
            out.append("Brain maintenance is due today: after the user's first "
                       "request, run the brain-maintenance skill.")

    out += ["", "## What to do"]
    if source == "compact":
        out.append("The conversation was compacted. Re-read Memory.md if a "
                   "decision depends on it, and carry on.")
    else:
        out.append("Follow the session-start skill (.claude/skills/session-start/"
                   "SKILL.md). If the user has already asked for something, that "
                   "comes first; orient briefly, then do it.")
        out.append(f"Log this session under `{short_id(sid)}` when it ends "
                   "(session-end skill).")

    text = "\n".join(out)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n…"


def main() -> int:
    data = read_input()
    root = project_dir(data)
    sid = data.get("session_id") or ""
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if sid and load_state(root, sid) is None:
        save_state(root, sid, {
            "session_id": sid,
            "started_at": now(),
            "start_head": head,
            "branch": branch,
            "source": data.get("source") or "startup",
        })
    print(briefing(root, data, branch, head))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open: never block a session from starting
        print(f"SessionStart hook error (ignored): {exc}", file=sys.stderr)
        sys.exit(0)
