"""Erase everything belonging to one owner, and say what survived.

A deletion feature is judged by the things it misses. This one is built
to be checked rather than believed: it counts what it removes, it walks
the disk as well as the database, and it names — every time, in the same
report — the copies it cannot reach.

The honest part is the last one. An erasure that quietly leaves the
owner's rows inside last night's backup, or the markdown note somebody
synced into their own Obsidian vault, has not erased anything; it has
only stopped showing it. Saying so is not a disclaimer, it is the
result.
"""

import json
from pathlib import Path

# Children before parents, so foreign keys hold at every step.
DELETE_ORDER = ("tasks", "approvals", "artifacts", "vault_notes", "runs",
                "datasets", "sessions", "memory_kv")

# Tables that carry an owner directly. Everything else in DELETE_ORDER
# belongs to an owner through the run it hangs off.
OWNED_DIRECTLY = ("runs", "datasets", "sessions", "memory_kv")


def owned_run_ids(store, owner):
    return [row["id"] for row in
            store._exec("SELECT id FROM runs WHERE owner = ?", (owner,))]


def survey(store, owner):
    """What this owner has, without changing anything."""
    run_ids = owned_run_ids(store, owner)
    counts = {}
    for table in DELETE_ORDER:
        if table in OWNED_DIRECTLY:
            rows = store._exec(
                f"SELECT COUNT(*) AS n FROM {table} WHERE owner = ?", (owner,))
        elif not run_ids:
            counts[table] = 0
            continue
        else:
            marks = ", ".join("?" * len(run_ids))
            rows = store._exec(
                f"SELECT COUNT(*) AS n FROM {table} WHERE run_id IN ({marks})",
                tuple(run_ids))
        counts[table] = int(rows[0]["n"]) if rows else 0
    return {"owner": owner, "runs": len(run_ids), "rows": counts,
            "total_rows": sum(counts.values())}


def published_paths(store, run_ids):
    """Vault notes belonging to these runs, as repository-relative paths."""
    if not run_ids:
        return []
    marks = ", ".join("?" * len(run_ids))
    return [row["path"] for row in store._exec(
        f"SELECT path FROM vault_notes WHERE run_id IN ({marks})",
        tuple(run_ids))]


def erase(store, owner, vault_dir=None, memory_file=None):
    """Delete one owner's data. Returns a report of what happened.

    The database and the disk are both walked, because a published
    report exists in two places and deleting one of them is the mistake
    this function is written to avoid.
    """
    run_ids = owned_run_ids(store, owner)
    notes = published_paths(store, run_ids)

    deleted = {}
    for table in DELETE_ORDER:
        if table in OWNED_DIRECTLY:
            deleted[table] = store._exec_rowcount(
                f"DELETE FROM {table} WHERE owner = ?", (owner,))
        elif not run_ids:
            deleted[table] = 0
        else:
            marks = ", ".join("?" * len(run_ids))
            deleted[table] = store._exec_rowcount(
                f"DELETE FROM {table} WHERE run_id IN ({marks})",
                tuple(run_ids))

    files_deleted, files_missing = [], []
    if vault_dir:
        root = Path(vault_dir)
        for relative in notes:
            path = root / relative
            try:
                # Containment check: a note path comes from the database,
                # and a deletion routine is the last place to trust one.
                path.resolve().relative_to(root.resolve())
            except (ValueError, OSError):
                files_missing.append(f"{relative} (outside the vault; left alone)")
                continue
            if path.exists():
                path.unlink()
                files_deleted.append(relative)
            else:
                files_missing.append(relative)

    memory_file_cleared = False
    if memory_file and owner == "local-owner":
        # Local mode keeps memory in data/memory.json, outside the
        # database entirely. Erasing the database and leaving that file
        # would be the clearest possible version of this function's
        # failure mode.
        path = Path(memory_file)
        if path.exists():
            path.write_text(json.dumps({}, indent=4), encoding="utf-8")
            memory_file_cleared = True

    return {
        "owner": owner,
        "runs": len(run_ids),
        "deleted": deleted,
        "total_rows": sum(deleted.values()),
        "vault_files_deleted": files_deleted,
        "vault_files_not_found": files_missing,
        "memory_file_cleared": memory_file_cleared,
        "not_reached": not_reached(),
    }


def not_reached():
    """Copies this command cannot touch, listed every time.

    Not a disclaimer — the point of the report. A data-subject request
    answered with "deleted" when these exist is answered wrongly.
    """
    return [
        "Database backups: every backup taken before this erasure still "
        "contains the owner's rows. Restoring one restores them. Delete or "
        "rotate the backups as well (scripts/backup.py writes to backups/).",
        "Obsidian vaults synced elsewhere: a published report copied into "
        "someone's own vault, a cloud sync, or a git repository is beyond "
        "this database and this machine.",
        "Exports the owner downloaded themselves, and anything a reader "
        "saved from a report before it was erased.",
        "Operational logs and CI artifacts, which may quote a goal or a "
        "dataset name in passing.",
    ]
