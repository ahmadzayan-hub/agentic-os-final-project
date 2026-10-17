"""Pushed updates (ADR 0034): one server-sent event stream per owner.

The stream reads changes from the database rather than from memory, so a
run the worker advanced in another process reaches every open page. Each
event carries an `id`, the position to resume from: the change's time,
kind and id, which together order every change. A client that reconnects
with `Last-Event-ID` receives what it missed; one that starts afresh
starts from now.

Within one connection the reader looks a few seconds back on every poll
and remembers what it sent, because a write stamped before a poll can
commit after it. A change may therefore arrive more than once, and the
client treats every event as "look again", never as a total.
"""

import json
import re
from datetime import datetime, timedelta

from server.runs import _stamp, _utcnow

POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
MAX_SECONDS = 55.0
OVERLAP_SECONDS = 5
RETRY_MS = 3000
# Open streams one owner may hold in this process; more is refused (429).
MAX_STREAMS_PER_OWNER = 5
MAX_ROWS = 200
CURSOR = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00)~(run|connector)~([A-Za-z0-9_-]{1,64})$")


def cursor_now(clock=_utcnow):
    """A position just before anything that happens from now on."""
    return (_stamp(clock()), "run", "0")


def parse_cursor(value):
    """(time, kind, id) from a Last-Event-ID, or None for anything else."""
    match = CURSOR.match((value or "").strip())
    return match.groups() if match else None


def cursor_text(key):
    return "~".join(key)


def event(kind, data, event_id=None):
    lines = [f"id: {event_id}"] if event_id else []
    lines.append(f"event: {kind}")
    lines.append("data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


def heartbeat():
    return ": keep-alive\n\n"


def _run(row):
    return {"kind": "run", "id": row["id"], "state": row["state"], "goal": row["goal"],
            "connector_id": row.get("connector_id"), "created_at": row.get("created_at"),
            "updated_at": row["updated_at"]}


def _connector(row):
    return {"kind": "connector", "id": row["id"], "name": row["name"],
            "enabled": bool(row.get("enabled")), "last_status": row.get("last_status"),
            "last_error": row.get("last_error"), "last_run_id": row.get("last_run_id"),
            "last_checked_at": row.get("last_checked_at"),
            "next_due_at": row.get("next_due_at"), "updated_at": row["updated_at"]}


class Reader:
    """What one connection has seen, and where it stands."""

    def __init__(self, store, owner, after):
        self.store = store
        self.owner = owner
        self.after = tuple(after)
        self.seen = set()
        self.started = False

    def poll(self):
        """Events for changes this connection has not seen, oldest first,
        as (event id, kind, data)."""
        start = self.after[0]
        runs, connectors = self.store.changes_since(self.owner, start, MAX_ROWS)
        # A table cut off at MAX_ROWS has more after its last row; nothing
        # beyond that row is sent yet, or the cursor would skip past it.
        cut = [rows[-1]["updated_at"] for rows in (runs, connectors) if len(rows) >= MAX_ROWS]
        boundary = min(cut) if cut else None
        changes = self._changes(runs, connectors)
        if self.started:
            # Late commits: stamped a moment before the cursor, written after.
            back = _stamp(datetime.fromisoformat(start) - timedelta(seconds=OVERLAP_SECONDS))
            changes = self._changes(*self.store.changes_since(
                self.owner, back, MAX_ROWS, before=start)) + changes
        out = []
        for key, kind, data in changes:
            if boundary is not None and key[0] > boundary:
                break
            if key in self.seen:
                continue
            self.seen.add(key)
            # A resumed stream starts strictly after its cursor.
            if not self.started and key <= self.after:
                continue
            self.after = max(self.after, key)
            out.append((cursor_text(key), kind, data))
        self.started = True
        return out

    @staticmethod
    def _changes(runs, connectors):
        return sorted([((r["updated_at"], "run", r["id"]), "run", _run(r)) for r in runs]
                      + [((k["updated_at"], "connector", k["id"]), "connector", _connector(k))
                         for k in connectors])


async def stream(reader, poll, sleep, now, disconnected, max_seconds=MAX_SECONDS,
                 poll_seconds=POLL_SECONDS, heartbeat_seconds=HEARTBEAT_SECONDS):
    """The text of one connection. `poll` runs the reader's poll off the
    event loop, `sleep` waits, `now` is a monotonic clock in seconds and
    `disconnected` says whether the client has gone."""
    started = last_beat = now()
    yield f"retry: {RETRY_MS}\n\n"
    # A position to resume from, even if nothing changes.
    yield event("ready", {"kind": "ready"}, cursor_text(reader.after))
    while True:
        for event_id, kind, data in await poll():
            yield event(kind, data, event_id)
        if now() - started >= max_seconds or await disconnected():
            return
        if now() - last_beat >= heartbeat_seconds:
            last_beat = now()
            yield heartbeat()
        await sleep(min(poll_seconds, max(0.0, max_seconds - (now() - started))))
