"""Backup and restore for the durable store.

A backup is one JSON document: a version, a timestamp, and every row of
every table in `storage.TABLES`. It carries no driver types and no SQL,
so a SQLite backup restores into PostgreSQL and back — which is what
makes the drill in tests/test_backup.py a real exercise rather than a
same-engine file copy.

Restore is deliberately a *replace*, not a merge: recovering from a
backup means the database ends up as the backup describes it, with no
survivors from the damaged state.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from server.storage import TABLES, open_store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_VERSION = 1


def open_configured_store(env=None, config_path=None):
    """Open the same store the API uses, from the same configuration."""
    env = os.environ if env is None else env
    config = {}
    path = Path(config_path or PROJECT_ROOT / "config.json")
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            config = {}
    return open_store(
        env.get("DATABASE_URL") or config.get("database_url"),
        config.get("database_file") or PROJECT_ROOT / "data" / "agentic.db",
    )


def create_backup(store, taken_at=None):
    """Read every durable row into a JSON-serialisable document."""
    return {
        "version": BACKUP_VERSION,
        "taken_at": taken_at or datetime.now(timezone.utc).isoformat(),
        "tables": store.export_all(),
    }


def restore_backup(store, payload):
    """Replace the store's contents with a backup. Returns rows restored.

    Refuses anything it cannot read correctly rather than restoring part
    of a database: a half-restore is worse than a failed one, because it
    looks like it worked.
    """
    if not isinstance(payload, dict) or "tables" not in payload:
        raise ValueError("not a backup document")
    version = payload.get("version")
    if version != BACKUP_VERSION:
        raise ValueError(
            f"backup version {version!r} cannot be read by this build "
            f"(expected {BACKUP_VERSION})")
    tables = payload["tables"]
    unknown = sorted(set(tables) - set(TABLES))
    if unknown:
        raise ValueError(f"backup contains unknown tables: {', '.join(unknown)}")
    return store.import_all(tables)


def backup_counts(payload):
    """Rows per table, for reporting what a backup actually contains."""
    return {table: len(rows) for table, rows in payload["tables"].items()}
