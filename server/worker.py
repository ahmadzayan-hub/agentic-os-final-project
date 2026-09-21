"""Background run worker: database-backed leases with heartbeats.

Without this, an analytics run only advances while somebody has the Runs
view open — close the tab and the work stops. The worker claims runnable
runs and steps them server-side.

Concurrency control is a lease on the run row: a worker sets
`lease_owner` and `lease_expires_at`, renews the expiry after every task,
and releases the lease when the run stops being runnable. Two workers
cannot claim the same run because the claim is a conditional UPDATE — the
loser changes zero rows. A worker that crashes simply stops renewing; the
expiry passes and another worker (or a client) takes over from the run's
durable state. There is no lock to clean up after a crash, which is the
whole reason to prefer a lease over one.

What the worker deliberately does **not** do: decide approvals. It stops
at the approval gate and waits for a human, exactly like a client-stepped
run. An autonomous publisher would defeat the point of the gate.
"""

import argparse
import json
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

from server.model_gateway import ModelGateway
from server.routing import RoutedGateway, build_router
from server.runs import RunEngine, _stamp, _utcnow
from server.storage import open_store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNNABLE_STATES = ("queued", "running")
DEFAULT_LEASE_SECONDS = 30
# The pipeline is eleven tasks; a bounded loop cannot spin forever if an
# unexpected state ever leaves a run runnable with nothing to do.
MAX_STEPS_PER_CLAIM = 64


def read_config(config_path=None):
    path = Path(config_path or PROJECT_ROOT / "config.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class RunWorker:
    def __init__(self, engine, store, worker_id=None,
                 lease_seconds=DEFAULT_LEASE_SECONDS, clock=_utcnow):
        self.engine = engine
        self.store = store
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.clock = clock

    def _expiry(self):
        return _stamp(self.clock() + timedelta(seconds=self.lease_seconds))

    def claim(self):
        return self.store.claim_run(self.worker_id, _stamp(self.clock()),
                                    self._expiry())

    def step(self):
        """Claim one run and advance it until a human is needed or it ends.

        Returns the run id worked on, or None when nothing was runnable.
        """
        run_id = self.claim()
        if run_id is None:
            return None
        try:
            for _ in range(MAX_STEPS_PER_CLAIM):
                try:
                    run = self.engine.advance(run_id, lease_owner=self.worker_id)
                except ValueError:
                    # The run stopped being ours to advance between the
                    # claim and this call — a human paused it, cancelled
                    # it, or it reached the approval gate. Ordinary, not
                    # an error: release the lease and take the next run.
                    break
                if run["state"] not in RUNNABLE_STATES:
                    break
                if not any(t["state"] == "pending" for t in run["tasks"]):
                    break
                # Losing the lease means a successor already owns this run
                # (we were too slow); stop rather than race it.
                if not self.store.renew_lease(run_id, self.worker_id,
                                              self._expiry()):
                    return run_id
        finally:
            self.store.release_lease(run_id, self.worker_id)
        return run_id

    def run_forever(self, poll_seconds=1.0, stop=None, sleep=time.sleep):
        """Work until `stop` (a threading.Event) is set.

        One failing run must never take the worker down — the next run,
        and the same run after a fix, still deserve to make progress. The
        failure is reported on stderr and the loop continues.
        """
        while stop is None or not stop.is_set():
            try:
                worked = self.step()
            except Exception as error:  # one bad run, not a dead worker
                print(f"{self.worker_id}: run failed: {error!r}",
                      file=sys.stderr, flush=True)
                worked = None
            if worked is None:
                sleep(poll_seconds)


def build_worker(env=None, config_path=None, **kwargs):
    """A worker wired to the same database and vault as the API."""
    import os

    env = os.environ if env is None else env
    config = read_config(config_path)
    store = open_store(
        env.get("DATABASE_URL") or config.get("database_url"),
        config.get("database_file") or PROJECT_ROOT / "data" / "agentic.db",
    )
    gateway = ModelGateway()
    # The worker narrates the same reports the API does, so it routes the
    # same way; a run advanced in the background must not be narrated by a
    # different model than one advanced in a browser.
    router, router_name, problem = build_router(env, config)
    if router is not None:
        gateway = RoutedGateway(gateway, router, router_name)
    elif problem:
        # The API reports this in /api/health. A worker has no health
        # endpoint, so a misconfigured router would be invisible here.
        print(problem, file=sys.stderr, flush=True)
    engine = RunEngine(store, config.get("vault_dir") or PROJECT_ROOT / "vault",
                       gateway)
    return RunWorker(engine, store, **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Advance analytics runs server-side.")
    parser.add_argument("--once", action="store_true",
                        help="claim and finish at most one run, then exit")
    parser.add_argument("--poll", type=float, default=1.0,
                        help="seconds to wait when no run is available")
    parser.add_argument("--lease", type=int, default=DEFAULT_LEASE_SECONDS,
                        help="lease duration in seconds")
    parser.add_argument("--config", help="config.json to read the database from")
    args = parser.parse_args(argv)

    worker = build_worker(config_path=args.config, lease_seconds=args.lease)
    if args.once:
        run_id = worker.step()
        print(json.dumps({"worker": worker.worker_id, "run": run_id}))
        return 0
    print(json.dumps({"worker": worker.worker_id, "polling_seconds": args.poll}),
          flush=True)
    try:
        worker.run_forever(poll_seconds=args.poll)
    except KeyboardInterrupt:
        pass
    return 0
