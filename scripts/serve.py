#!/usr/bin/env python3
"""Start the web interface and print exactly where to open it.

    python scripts/serve.py                 # this computer and the local network
    python scripts/serve.py --local-only    # this computer only
    python scripts/serve.py --port 9000

Equivalent to `python -m uvicorn server.app:app --host 0.0.0.0`, except it
also works out the address to type into a phone on the same Wi-Fi and says
what binding to the network means. See server/serve.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.serve import main

if __name__ == "__main__":
    raise SystemExit(main())
