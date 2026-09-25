#!/usr/bin/env python3
"""Erase everything belonging to one owner.

    python scripts/erase.py --owner alice@example.com            # survey only
    python scripts/erase.py --owner alice@example.com --yes      # delete

The survey is the default because this is irreversible and the owner
identifier is a string somebody typed. `--yes` is required to delete,
the same contract `scripts/restore.py` uses: a mistake here is not
something a confirmation prompt should be able to swallow in a script.

The report always ends with what the command could not reach — backups
above all. An erasure answered with "done" while last night's backup
still holds the rows is answered wrongly.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.backup import open_configured_store
from server.erasure import erase, not_reached, survey
from utils import load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _config(path):
    try:
        return load_config(path or PROJECT_ROOT / "config.json")
    except (FileNotFoundError, ValueError):
        return {}


def _target(config):
    """Which database this is about to act on, named in the report.

    A relative `database_file` resolves against the working directory,
    so running this from the wrong place finds an empty database and
    reports, accurately and unhelpfully, that the owner has nothing.
    Naming the target turns that into an obvious mistake instead of a
    puzzling result.
    """
    import os

    url = os.environ.get("DATABASE_URL") or config.get("database_url")
    if url:
        # Never print the password: a DSN in a terminal is a leaked
        # credential in a scrollback buffer.
        remainder = url.split("@")[-1]
        return f"postgresql://…@{remainder}"
    return str(Path(config.get("database_file")
                    or PROJECT_ROOT / "data" / "agentic.db").resolve())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True,
                        help="the owner identifier (a token subject, or "
                             "local-owner for a single-user install)")
    parser.add_argument("--yes", action="store_true",
                        help="confirm the irreversible deletion")
    parser.add_argument("--config", help="config.json to read the database from")
    args = parser.parse_args(argv)

    config = _config(args.config)
    store = open_configured_store(config_path=args.config)
    found = survey(store, args.owner)

    target = _target(config)
    if not args.yes:
        print(json.dumps({**found, "database": target,
                          "would_delete": found["total_rows"],
                          "not_reached": not_reached()}, indent=1))
        if found["total_rows"] == 0:
            print(f"\nNothing is stored for “{args.owner}” in {target}. "
                  "Check both: an owner that does not exist, an owner with "
                  "no data, and the wrong database look identical from "
                  "here.", file=sys.stderr)
        else:
            print(f"\nSurvey only. Re-run with --yes to delete "
                  f"{found['total_rows']} row(s).", file=sys.stderr)
        return 0

    started = time.monotonic()
    report = erase(
        store, args.owner,
        vault_dir=config.get("vault_dir") or PROJECT_ROOT / "vault",
        memory_file=config.get("memory_file") or PROJECT_ROOT / "data" / "memory.json")
    report["database"] = target
    report["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
