"""Vercel Python (ASGI) entry point.

Vercel serves this module's `app` for every /api/* request. The FastAPI
application is unchanged — this file only adds the repository root to
the import path so `agent`, `utils`, and `server.*` resolve inside the
function bundle.

Durable state lives in PostgreSQL (DATABASE_URL). Without it the app
falls back to SQLite in the function's temporary directory, which is
fine for a demo but is wiped between cold starts — see
docs/VERCEL_DEPLOYMENT.md.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app import app  # noqa: E402  (path setup must precede import)

__all__ = ["app"]
