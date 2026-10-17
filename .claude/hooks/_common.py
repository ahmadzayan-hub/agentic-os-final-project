"""Shared helpers for this project's Claude Code hooks.

Every hook fails open: a hook that crashes must never stop someone from
working, so callers wrap their work and exit 0 on any error. Standard
library only, because hooks run on every teammate's machine.

Hook state lives in .claude/state/ (git-ignored): one small JSON file per
session, recording where the session started so later hooks can tell what
it changed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SESSION_LOG = "session-logs.md"
PROGRESS = "project-progress.md"


def read_input() -> dict:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def project_dir(data: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())


def git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def changed_files(root: Path) -> list:
    """Uncommitted changes, not counting the hooks' own state files. Untracked
    files are listed one by one, so a folder holding only hook state is not
    mistaken for work."""
    out = git(root, "status", "--porcelain", "--untracked-files=all")
    return [line for line in out.splitlines()
            if line.strip() and ".claude/state/" not in line]


def short_id(session_id: str) -> str:
    return safe_id(session_id)[:8] or "unknown"


def safe_id(session_id: str) -> str:
    """A session id as a file name: nothing that could climb out of state/."""
    return re.sub(r"[^A-Za-z0-9_-]", "", session_id or "")


def state_file(root: Path, session_id: str) -> Path:
    return root / ".claude" / "state" / "sessions" / f"{safe_id(session_id)}.json"


def load_state(root: Path, session_id: str) -> dict | None:
    if not safe_id(session_id):
        return None
    try:
        return json.loads(state_file(root, session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(root: Path, session_id: str, state: dict) -> None:
    path = state_file(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def has_log_entry(root: Path, session_id: str) -> bool:
    """Has this session been logged? Entries name the session as `abcd1234`."""
    log = root / SESSION_LOG
    if not log.exists():
        return False
    return f"`{short_id(session_id)}`" in log.read_text(encoding="utf-8")


def section(text: str, heading: str, max_lines: int = 15) -> str:
    """The body of a `## heading` section, trimmed for a briefing."""
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lower().startswith(heading.lower())
            continue
        if inside and line.strip():
            lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["…"]
    return "\n".join(lines)


def last_entry(text: str, max_lines: int = 12) -> str:
    """The newest `## ` entry of the session log (entries are appended)."""
    entries = re.split(r"(?m)^(?=## )", text)
    entries = [e for e in entries if e.startswith("## ")]
    if not entries:
        return ""
    lines = [l for l in entries[-1].splitlines() if l.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["…"]
    return "\n".join(lines)
