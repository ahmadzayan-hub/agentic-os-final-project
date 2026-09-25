#!/usr/bin/env python3
"""Restore the configured database from a backup file.

    python scripts/restore.py backups/agentic-20260812T101500Z.json --yes

This REPLACES every row in the target database with the backup's
contents. `--yes` is required: restoring into the wrong database is not
an error a confirmation prompt should be able to swallow in a script.
Use `--dry-run` first to see what the file contains without writing.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.backup import backup_counts, open_configured_store, restore_backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", help="path to a backup JSON file")
    parser.add_argument("--yes", action="store_true",
                        help="confirm the destructive replace")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the file's contents and exit")
    parser.add_argument("--config", help="config.json to read the database from")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.backup).read_text(encoding="utf-8"))
    counts = backup_counts(payload)

    if args.dry_run:
        print(json.dumps({"file": args.backup, "taken_at": payload.get("taken_at"),
                          "rows": counts, "total_rows": sum(counts.values())}, indent=1))
        return 0
    if not args.yes:
        print("refusing to overwrite the database without --yes "
              "(use --dry-run to inspect the backup)", file=sys.stderr)
        return 2

    started = time.monotonic()
    store = open_configured_store(config_path=args.config)
    restored = restore_backup(store, payload)
    print(json.dumps({
        "file": args.backup,
        "taken_at": payload.get("taken_at"),
        "seconds": round(time.monotonic() - started, 3),
        "rows": counts,
        "restored_rows": restored,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
