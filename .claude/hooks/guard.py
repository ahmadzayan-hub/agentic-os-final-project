#!/usr/bin/env python3
"""PreToolUse hook: stop the Bash commands that brain/Soul.md forbids.

CLAUDE.md can only ask. This hook refuses, before the command runs:

- a force-push, a mirror push, or a push that deletes a branch;
- a push to any branch other than the one checked out (so never to main);
- `git reset --hard`, `git branch -D`, `git filter-branch`, `git filter-repo`;
- adding `.env` files or `private/` to Git.

It reads the command, splits compound commands (`&&`, `||`, `;`, `|`), and
checks each `git` call. It is a guard for honest mistakes, not a sandbox: a
determined shell trick can get past it, which is why the rules also live in
`permissions.deny` and in the Soul.

To allow one of these on purpose, set `AGENTIC_OS_GUARD_OFF=1` in your
`settings.local.json` env block, or ask Claude to run the command after you
have said so in the conversation and turn the guard off yourself. A crash in
this hook never blocks work: it fails open like the others.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import git, project_dir, read_input  # noqa: E402

SPLIT = re.compile(r"&&|\|\||[;|\n]")
# Options of `git` itself that take a value, so the subcommand is found after them.
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
FORCE_FLAGS = {"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror",
               "-d", "--delete", "--prune"}
REDIRECT = re.compile(r"^\d*[<>]+&?\d*-?$|^&>>?$")
SECRET_PATH = re.compile(r"(^|/)(\.env(\.(?!example$)[\w.-]+)?|private)(/|$)")


def strip_redirects(tokens: list[str]) -> list[str]:
    """Drop `2>&1`, `> file`, `>> file` and `< file`, which are not git arguments."""
    kept, skip = [], False
    for token in tokens:
        if skip:
            skip = False
        elif REDIRECT.match(token):
            skip = token[-1] in "<>"  # `>` and `2>` take the next word as a file
        else:
            kept.append(token)
    return kept


def git_call(tokens: list[str]) -> tuple[str, list[str]] | None:
    """The subcommand and its arguments if these tokens are a `git` call."""
    tokens = strip_redirects(tokens)
    for start, token in enumerate(tokens):
        if token == "git" or token.endswith("/git"):
            break
    else:
        return None
    rest = tokens[start + 1:]
    index = 0
    while index < len(rest) and rest[index].startswith("-"):
        index += 2 if rest[index] in GIT_VALUE_OPTIONS else 1
    if index >= len(rest):
        return None
    return rest[index], rest[index + 1:]


def check_push(args: list[str], branch: str) -> str | None:
    flags = [a for a in args if a.startswith("-") and not a.startswith("--force-with-lease=")]
    for flag in flags:
        short = set(flag[1:]) if not flag.startswith("--") else set()
        if flag in FORCE_FLAGS or "f" in short or "d" in short:
            return f"`git push {flag}` is a force-push or a deletion; Soul rule: no history rewriting or branch deletion."
    if any(a.startswith("--force-with-lease=") for a in args):
        return "A force-push is not allowed; Soul rule: no history rewriting."
    positional = [a for a in args if not a.startswith("-")]
    for refspec in positional[1:]:
        if refspec.startswith("+") or refspec.startswith(":"):
            return f"Refspec `{refspec}` forces or deletes; not allowed."
        target = refspec.split(":", 1)[-1]
        if target in ("HEAD", ""):
            continue
        target = target.removeprefix("refs/heads/")
        if branch and target != branch:
            return (f"Push to `{target}` refused: this session works on `{branch}`. "
                    "Pushing to another branch needs the user's explicit permission.")
    return None


def check_git(sub: str, args: list[str], branch: str) -> str | None:
    if sub == "push":
        return check_push(args, branch)
    if sub == "reset" and "--hard" in args:
        return "`git reset --hard` discards work; ask the user first."
    if sub == "branch" and any(a in ("-D", "--delete", "-d") or (a.startswith("-") and not a.startswith("--") and "D" in a)
                               for a in args):
        return "Branch deletion is not allowed; Soul rule: no branch deletion."
    if sub in ("filter-branch", "filter-repo"):
        return f"`git {sub}` rewrites history; Soul rule: no history rewriting."
    if sub == "add":
        for path in (a for a in args if not a.startswith("-")):
            if SECRET_PATH.search(path.replace("\\", "/")) and path not in (".env.example",):
                return f"`git add {path}` would put an env file or private/ content in Git; the repository is public."
    return None


def decide(data: dict) -> str | None:
    if os.environ.get("AGENTIC_OS_GUARD_OFF") == "1":
        return None
    if data.get("tool_name") not in (None, "Bash"):
        return None
    command = (data.get("tool_input") or {}).get("command") or ""
    if "git" not in command:
        return None
    branch = git(project_dir(data), "rev-parse", "--abbrev-ref", "HEAD")
    for part in SPLIT.split(command):
        try:
            tokens = shlex.split(part)
        except ValueError:
            tokens = part.split()
        call = git_call(tokens)
        if call and (reason := check_git(call[0], call[1], branch)):
            return reason
    return None


def main() -> int:
    reason = decide(read_input())
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by .claude/hooks/guard.py: {reason}",
        }}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open
        print(f"Guard hook error (ignored): {exc}", file=sys.stderr)
        sys.exit(0)
