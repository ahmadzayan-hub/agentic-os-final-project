---
name: brain-maintenance
description: Daily gardening of the second brain in brain/. Refresh stale values against their sources, merge duplicate notes, repair broken wikilinks, link unlinked mentions, strengthen connections between User, Identity, Soul and the other notes, and record what changed. Use once a day (the SessionStart briefing says when it is due), or when the user asks to tidy, update, merge or reorganise the brain.
---

# Brain maintenance

The brain is only useful if it is true and connected. This skill keeps it so. `scripts/brain_check.py` finds the work; you judge it and make the edits. The rules for notes are in `brain/_meta/Note schema.md`.

## Steps

1. **Measure.** Run `python scripts/brain_check.py --json` and keep the report.
2. **Fix structure first:** broken links, missing frontmatter, unreadable dates and sources that do not exist.
    - For a broken link, point it at the note that was meant (check aliases), or remove it. Create a note only if the concept really deserves one.
3. **Refresh stale values.** For each stale note, check every fact against its `sources`: code, docs, `project-progress.md`, `git log` and test output.
    - Correct values that changed, then set `updated:` to today.
    - If a fact cannot be verified, do not guess. Add `> [!warning] Unverified since YYYY-MM-DD: <what>` and say so in the log.
    - `brain/User.md` follows the user's latest goals and preferences in `Memory.md` and recent session logs.
4. **Merge duplicates.** For each candidate pair, read both notes.
    - If they are the same thing, keep the better-named note and move every unique fact into it. Combine their aliases, tags and sources, and add the old title as an alias.
    - Rewrite every `[[Old title]]` link in the vault to the kept note, then delete the old file. Git keeps its history.
    - If they are different things, sharpen both first sentences so the difference is plain. Record the decision so the pair is not re-checked blindly.
5. **Strengthen connections.**
    - **Unlinked mentions:** turn the first mention in each note into a `[[wikilink]]`.
    - **Orphans:** link each from [[Home]] and from the note it most belongs with.
    - **Weakly linked notes:** add real relationships in a *Related* section, two to five links, each with a few words on why.
    - **The core triad:** [[User]], [[Identity]] and [[Soul]] link to each other. Every project note links to at least one of them.
    - Never add a link just to raise a count.
6. **Verify.** `python scripts/brain_check.py --strict` must exit 0. Re-read [[Home]] to confirm it still lists every note.
7. **Record.** Append a dated section (`## YYYY-MM-DD`) to `brain/_meta/Maintenance log.md`, with one bullet per change: "Merged X into Y", "Refreshed 3 values in Z (sources: …)", "Linked 4 mentions". The SessionStart hook reads this date to decide whether maintenance is due.
8. **Commit** with `Brain maintenance: YYYY-MM-DD`, together with the session's other tracking files, or on its own.

## Rules

- The repository is public. Notes hold no secrets, credentials, contact details or personal data about anyone else. Private notes go in `brain/private/`, which Git ignores.
- Facts only, each with a source. A note that is uncertain says so.
- Brain notes are curated project knowledge. The runtime `vault/` is user data from published reports; never copy from it into the brain without the user asking.
