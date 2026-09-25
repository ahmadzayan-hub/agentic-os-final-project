"""Start the web interface and say exactly where to open it.

`uvicorn server.app:app` works and is documented, but it leaves two
things to the reader: binding to the network so a phone on the same
Wi-Fi can reach it, and finding the machine's address to type into that
phone. Both are easy to get wrong and neither is interesting, so this
does them and prints the result.

It also states the consequence, because binding to the network is a real
decision: local mode has no login, so everyone on that network can use
the app and read its memory. That belongs on screen at the moment it
becomes true, not in a document nobody opens.
"""

import argparse
import socket

LOOPBACK = "127.0.0.1"


def lan_address(probe=("192.0.2.1", 80)):
    """This machine's address on the local network, or None.

    Opens a UDP socket toward an address it never sends to — the kernel
    picks the outbound interface, which is the one a phone on the same
    network would reach. No packets, no DNS, works offline. The default
    target is TEST-NET-1 (RFC 5737), reserved for documentation, so this
    cannot accidentally touch a real host.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(probe)
        address = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    return None if address.startswith("127.") else address


def banner(port, local_only=False, address=None):
    """What to print once the server is up.

    Takes the address rather than detecting it, so it stays a pure
    function of what the caller decided: `main` does the detection.
    """
    lines = ["", "  Agentic OS is running.", "",
             f"    On this computer:  http://localhost:{port}"]
    if local_only:
        lines += ["",
                  "    Reachable from this computer only (--local-only).",
                  "    Drop that flag to open it from a phone on the same Wi-Fi."]
    else:
        if address:
            lines += [f"    On your phone:     http://{address}:{port}"
                      "   (same Wi-Fi)"]
        else:
            lines += ["    No local network address found — this computer only."]
        lines += ["",
                  "    Anyone on this network can open it. Local mode has no",
                  "    login, so they can read and change the saved memory.",
                  "    Use --local-only on a network you do not trust."]
    lines += ["",
              "    “Add to Home screen” needs HTTPS on most phones, so the",
              "    installable app comes from a real deployment, not from here.",
              "", "  Press Ctrl+C to stop.", ""]
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--local-only", action="store_true",
                        help="bind to 127.0.0.1 — nothing else on the network "
                             "can reach it")
    parser.add_argument("--reload", action="store_true",
                        help="restart on code changes (development)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    address = None if args.local_only else lan_address()
    print(banner(args.port, args.local_only, address), flush=True)

    import uvicorn

    uvicorn.run("server.app:app",
                host=LOOPBACK if args.local_only else "0.0.0.0",
                port=args.port, reload=args.reload, log_level="warning")
    return 0
