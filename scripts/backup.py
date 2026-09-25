#!/usr/bin/env python3
"""Write a backup of the configured database to a JSON file.

    python scripts/backup.py                    # -> backups/agentic-<utc>.json
    python scripts/backup.py --out /path/to.json
    DATABASE_URL=postgresql://... python scripts/backup.py

Prints a JSON summary (path, bytes, seconds, rows per table) so the
result can be checked by a human or a scheduler without opening the file.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.backup import backup_counts, create_backup, open_configured_store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="destination file (default backups/agentic-<utc>.json)")
    parser.add_argument("--config", help="config.json to read the database from")
    args = parser.parse_args(argv)

    started = time.monotonic()
    store = open_configured_store(config_path=args.config)
    payload = create_backup(store)

    if args.out:
        destination = Path(args.out)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = Path(__file__).resolve().parent.parent / "backups" / f"agentic-{stamp}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    counts = backup_counts(payload)
    print(json.dumps({
        "file": str(destination),
        "bytes": destination.stat().st_size,
        "seconds": round(time.monotonic() - started, 3),
        "rows": counts,
        "total_rows": sum(counts.values()),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
