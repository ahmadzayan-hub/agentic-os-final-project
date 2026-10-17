#!/usr/bin/env python3
"""Check the second brain in brain/: links, staleness, duplicates, connections.

The brain is an Obsidian vault of markdown notes joined by [[wikilinks]].
This script is the deterministic half of brain maintenance: it finds what
needs attention, and the brain-maintenance skill decides what to change.
A wrong merge or a guessed value is worse than a stale one, so nothing
here edits a note.

Standard library only, so the SessionStart hook can run it on any machine
with Python 3.

    python scripts/brain_check.py              # readable report
    python scripts/brain_check.py --summary    # one line, for hooks
    python scripts/brain_check.py --json       # everything, for the skill
    python scripts/brain_check.py --strict     # exit 1 on broken structure
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BRAIN = ROOT / "brain"

# Folders that hold no knowledge notes: note templates, the git-ignored
# private area, and Obsidian's own settings and trash.
SKIP_DIRS = {"_templates", "private", ".obsidian", ".trash"}
REQUIRED_FIELDS = ("type", "updated")
DEFAULT_REVIEW_DAYS = 30
MAINTENANCE_LOG = Path("_meta") / "Maintenance log.md"
# Titles closer than this are reported as possible duplicates. 0.88 joins
# "Weighted KPI" and "Weighted KPIs" but not "Approval gate" and
# "Approval log".
DUPLICATE_RATIO = 0.88

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
DATE_HEADING = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\b", re.M)


@dataclass
class Note:
    rel: str            # path inside the brain, without ".md"
    title: str          # the file name, which is what [[links]] use
    meta: dict
    body: str
    links: list = field(default_factory=list)

    @property
    def names(self) -> list:
        aliases = self.meta.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        return [self.title, *aliases]


def parse_frontmatter(text: str) -> tuple:
    """Read the YAML subset notes use: scalars, [a, b] lists, "- item" lists."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block, body = text[4:end], text[end + 4:].lstrip("\n")
    meta: dict = {}
    key = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and key is not None:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_scalar(stripped[2:]))
            continue
        name, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = name.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [_scalar(v) for v in value[1:-1].split(",") if v.strip()]
        elif value == "":
            meta[key] = []
        else:
            meta[key] = _scalar(value)
    return meta, body


def _scalar(value: str) -> str:
    return value.strip().strip('"').strip("'")


def visible_text(body: str) -> str:
    """The prose a reader sees: code blocks and inline code removed."""
    return INLINE_CODE.sub("", FENCE.sub("", body))


def load(brain: Path) -> list:
    notes = []
    for path in sorted(brain.rglob("*.md")):
        rel_parts = path.relative_to(brain).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        rel = path.relative_to(brain).with_suffix("").as_posix()
        links = [m.strip() for m in WIKILINK.findall(visible_text(body))]
        notes.append(Note(rel=rel, title=path.stem, meta=meta, body=body,
                          links=links))
    return notes


def build_index(notes: list) -> dict:
    """Every way a [[link]] can name a note: path, title, or alias."""
    index: dict = {}
    for note in notes:
        index.setdefault(note.rel.lower(), note)
        for name in note.names:
            index.setdefault(name.lower(), note)
    return index


def resolve(target: str, index: dict):
    key = target.strip().lower()
    if key.endswith(".md"):
        key = key[:-3]
    return index.get(key)


def parse_date(value):
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def normalise(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.lower()).split())


def mentions(text: str, name: str) -> bool:
    """Is `name` written in `text` as a word? One-word names must match case
    and be five letters or more, so "user" in a sentence is not a link to
    User; longer names match in any case."""
    if " " in name:
        return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I) is not None
    if len(name) < 5:
        return False
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def last_maintained(brain: Path):
    log = brain / MAINTENANCE_LOG
    if not log.exists():
        return None
    dates = [parse_date(d) for d in DATE_HEADING.findall(log.read_text(encoding="utf-8"))]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def check(brain: Path = DEFAULT_BRAIN, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    notes = load(brain)
    index = build_index(notes)

    broken, inbound = [], {n.rel: set() for n in notes}
    for note in notes:
        for target in note.links:
            found = resolve(target, index)
            if found is None:
                broken.append({"note": note.rel, "link": target})
            elif found.rel != note.rel:
                inbound[found.rel].add(note.rel)

    missing, bad_dates, stale = [], [], []
    for note in notes:
        lacking = [f for f in REQUIRED_FIELDS if not note.meta.get(f)]
        if lacking:
            missing.append({"note": note.rel, "fields": lacking})
        if not note.meta.get("updated"):
            continue
        updated = parse_date(note.meta["updated"])
        if updated is None:
            bad_dates.append({"note": note.rel, "updated": note.meta["updated"]})
            continue
        try:
            every = int(note.meta.get("review_every_days") or DEFAULT_REVIEW_DAYS)
        except ValueError:
            every = DEFAULT_REVIEW_DAYS
        age = (today - updated).days
        if age > every:
            stale.append({"note": note.rel, "updated": updated.isoformat(),
                          "days": age, "review_every_days": every})

    # A source is what a stale value is checked against, so one that no
    # longer exists leaves the note unverifiable. Repository paths are
    # checked; URLs are left to the maintenance skill.
    repo = brain.resolve().parent
    missing_sources = []
    for note in notes:
        sources = note.meta.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        for source in sources:
            if "://" in source:
                continue
            if not (repo / source).exists():
                missing_sources.append({"note": note.rel, "source": source})

    orphans = [n.rel for n in notes
               if not inbound[n.rel] and n.meta.get("type") != "index"]

    duplicates, seen = [], set()
    for i, a in enumerate(notes):
        for b in notes[i + 1:]:
            reason = None
            a_names = {normalise(x) for x in a.names}
            b_names = {normalise(x) for x in b.names}
            if a_names & b_names:
                reason = "same name or alias: " + ", ".join(sorted(a_names & b_names))
            else:
                ratio = difflib.SequenceMatcher(
                    None, normalise(a.title), normalise(b.title)).ratio()
                if ratio >= DUPLICATE_RATIO:
                    reason = f"similar titles ({ratio:.2f})"
            if reason and (a.rel, b.rel) not in seen:
                seen.add((a.rel, b.rel))
                duplicates.append({"notes": [a.rel, b.rel], "reason": reason})

    unlinked = []
    for note in notes:
        linked = {resolve(t, index).rel for t in note.links if resolve(t, index)}
        text = WIKILINK.sub(" ", visible_text(note.body))
        for other in notes:
            if other.rel == note.rel or other.rel in linked:
                continue
            hit = next((name for name in other.names if mentions(text, name)), None)
            if hit:
                unlinked.append({"note": note.rel, "mentions": other.rel, "as": hit})

    weakly_linked = [n.rel for n in notes
                     if n.meta.get("type") not in ("index", "log")
                     and len({resolve(t, index).rel for t in n.links
                              if resolve(t, index)} - {n.rel}) < 2]

    maintained = last_maintained(brain)
    return {
        "brain": str(brain),
        "today": today.isoformat(),
        "notes": len(notes),
        "links": sum(len(n.links) for n in notes),
        "broken_links": broken,
        "missing_fields": missing,
        "bad_dates": bad_dates,
        "missing_sources": missing_sources,
        "stale": stale,
        "orphans": orphans,
        "duplicates": duplicates,
        "unlinked_mentions": unlinked,
        "weakly_linked": weakly_linked,
        "last_maintained": maintained.isoformat() if maintained else None,
        "maintenance_due": maintained is None or maintained < today,
    }


def structural_problems(report: dict) -> int:
    """Faults a reader would hit: a link to nothing, a note with no type or
    date, a date that is not a date, a source that is not there.
    Staleness and duplicates are work for the maintenance skill, not
    faults."""
    return (len(report["broken_links"]) + len(report["missing_fields"])
            + len(report["bad_dates"]) + len(report["missing_sources"]))


def summary_line(report: dict) -> str:
    due = "due today" if report["maintenance_due"] else "done today"
    return (f"Brain: {report['notes']} notes · "
            f"{len(report['broken_links'])} broken links · "
            f"{len(report['stale'])} stale · "
            f"{len(report['duplicates'])} duplicate candidates · "
            f"{len(report['unlinked_mentions'])} unlinked mentions · "
            f"{len(report['orphans'])} orphans · "
            f"last maintained {report['last_maintained'] or 'never'} ({due})")


def readable(report: dict) -> str:
    lines = [summary_line(report), ""]
    sections = [
        ("Broken links", report["broken_links"],
         lambda x: f"{x['note']} → [[{x['link']}]]"),
        ("Missing frontmatter", report["missing_fields"],
         lambda x: f"{x['note']}: {', '.join(x['fields'])}"),
        ("Unreadable dates", report["bad_dates"],
         lambda x: f"{x['note']}: {x['updated']}"),
        ("Sources that do not exist", report["missing_sources"],
         lambda x: f"{x['note']}: {x['source']}"),
        ("Stale notes", report["stale"],
         lambda x: f"{x['note']}: updated {x['updated']}, {x['days']} days ago "
                   f"(review every {x['review_every_days']})"),
        ("Duplicate candidates", report["duplicates"],
         lambda x: f"{x['notes'][0]} ≈ {x['notes'][1]} ({x['reason']})"),
        ("Unlinked mentions", report["unlinked_mentions"],
         lambda x: f"{x['note']} mentions “{x['as']}” → [[{x['mentions']}]]"),
        ("Orphans (nothing links here)", report["orphans"], str),
        ("Weakly linked (fewer than 2 links out)", report["weakly_linked"], str),
    ]
    for title, items, fmt in sections:
        if items:
            lines.append(f"{title}:")
            lines.extend(f"  - {fmt(item)}" for item in items)
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brain", type=Path, default=DEFAULT_BRAIN)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=None,
                        help="treat this date (YYYY-MM-DD) as today")
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true")
    out.add_argument("--summary", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on broken links, missing fields or bad dates")
    args = parser.parse_args(argv)

    if not args.brain.is_dir():
        print(f"No brain at {args.brain}", file=sys.stderr)
        return 1
    report = check(args.brain, args.today)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.summary:
        print(summary_line(report))
    else:
        print(readable(report))
    return 1 if args.strict and structural_problems(report) else 0


if __name__ == "__main__":
    sys.exit(main())
