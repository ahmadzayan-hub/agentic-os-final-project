---
type: meta
aliases: [Brain rules, Frontmatter schema]
tags: [meta]
status: active
updated: 2026-10-16
review_every_days: 90
sources: [scripts/brain_check.py, brain/_templates/Note.md]
---

# Note schema

The rules every note in the [[Second brain]] follows. `scripts/brain_check.py` checks them.

## Frontmatter

| Field | Required | Meaning |
| --- | --- | --- |
| `type` | Yes | `index`, `profile`, `identity`, `principles`, `project`, `concept`, `dataset`, `decision`, `operation`, `meta` or `log` |
| `updated` | Yes | The date the content was last checked against its sources, as `YYYY-MM-DD` |
| `review_every_days` | No, default 30 | After this many days the note counts as stale |
| `aliases` | No | Other names, which links may use and which duplicate detection compares |
| `sources` | No | Repository paths or URLs the facts come from. Paths must exist |
| `tags`, `status` | No | Grouping, and `active` or `archived` |

## Writing

- One idea per note, titled by its file name. Links use the title: `[[Weighted KPIs]]`, or `[[Custom stages|custom stage]]` to show different words.
- The first sentence says what the thing is. Facts carry numbers, units and dates.
- Every note links back to at least one of [[User]], [[Identity]] or [[Soul]], or to a note that does, and has at least two links out.
- Link the first mention of another note's name. The checker reports unlinked mentions.
- Notes hold no secrets and no personal data about others. Private notes go in `brain/private/`, which Git ignores.
- New notes start from `_templates/Note.md`.

## Folders

`Projects/`, `Concepts/`, `Data/`, `Decisions/`, `Operations/` and `_meta/`, with [[Home]] and the core three at the root. Folders are for people; links resolve by title wherever a note sits.
