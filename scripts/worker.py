#!/usr/bin/env python3
"""Run the background worker that advances analytics runs server-side.

    python scripts/worker.py                # poll forever (Ctrl-C to stop)
    python scripts/worker.py --once         # finish one run and exit
    DATABASE_URL=postgresql://... python scripts/worker.py

Runs then progress with no browser open. The worker never decides an
approval: it stops at the gate and waits for a human. See
docs/adr/0006-durable-execution.md.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.worker import main

if __name__ == "__main__":
    raise SystemExit(main())
