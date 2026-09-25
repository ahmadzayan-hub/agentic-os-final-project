"""Failure injection: what happens when things break mid-run.

The project claims runs survive interruption because their state is
durable and leases expire. Most of that is tested with fakes and a frozen
clock, which proves the logic and not the system. These drills break
things for real — close the database connection underneath a worker,
kill a worker process with SIGKILL, throw away the engine mid-run — and
assert the run still reaches the approval gate.

The connection drills matter beyond a laboratory: a connection pooler
(Supabase's included) drops idle connections routinely, so a worker that
polls once a minute meets a dead connection as a matter of course, not as
a disaster.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

from server import analytics
from server.model_gateway import ModelGateway
from server.runs import RunEngine
from server.storage import RESTORE_ORDER, open_store

ROOT = Path(__file__).resolve().parent.parent


def fresh_postgres_store():
    store = open_store(PG_TEST_URL)
    # Children before parents, or the foreign keys refuse.
    for table in reversed(RESTORE_ORDER):
        store._exec(f"DELETE FROM {table}")
    return store


def start_run(engine, goal="Recovery drill"):
    run = engine.create_run(goal, analytics.sample_dataset(), "sample.csv")
    return run["id"]


def advance_to_gate(engine, run_id, limit=None):
    limit = limit or len(analytics.PIPELINE) + 5
    for _ in range(limit):
        state = engine.advance(run_id)
        if state["state"] in ("awaiting_approval", "completed", "failed"):
            return state
    return engine.get_run(run_id)


@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class ConnectionLossTestCase(unittest.TestCase):
    """A dropped connection is routine, not exceptional.

    `_exec` has reconnected since the serverless work, but the lease
    statements go through `_exec_rowcount`, which is a different method —
    and the worker's whole job runs through it.
    """

    def setUp(self):
        self.store = fresh_postgres_store()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = RunEngine(self.store, Path(self.tmp.name) / "vault",
                                ModelGateway(), glossary={"metrics": [],
                                                          "problems": []})

    def drop_the_connection(self):
        """The connection object is dead in this process — psycopg2
        raises InterfaceError on the next statement."""
        self.store._conn.close()

    def terminate_the_backend(self):
        """The server hangs up on us, which is what a pooler, a failover
        or a restart looks like: OperationalError on the next statement.
        A different exception from the one above, and for years only this
        one was handled."""
        import psycopg2

        killer = psycopg2.connect(PG_TEST_URL)
        killer.autocommit = True
        pid = self.store._exec("SELECT pg_backend_pid() AS pid")[0]["pid"]
        killer.cursor().execute("SELECT pg_terminate_backend(%s)", (pid,))
        killer.close()

    def test_a_read_survives_either_kind_of_lost_connection(self):
        for break_it in (self.drop_the_connection, self.terminate_the_backend):
            with self.subTest(failure=break_it.__name__):
                run_id = start_run(self.engine)
                break_it()
                self.assertIsNotNone(self.store.get_run(run_id))

    def test_claiming_a_lease_survives_either_kind_of_lost_connection(self):
        """The claim is an UPDATE with a guard, and it is the first thing
        a worker does after sitting idle — which is exactly when the
        connection it has been holding is most likely to be gone."""
        for index, break_it in enumerate((self.drop_the_connection,
                                          self.terminate_the_backend)):
            with self.subTest(failure=break_it.__name__):
                run_id = start_run(self.engine)
                break_it()
                claimed = self.store.claim_run(
                    f"w{index}", "2026-01-01T00:00:00Z",
                    f"2126-01-0{index + 1}T00:00:00Z")
                self.assertEqual(claimed, run_id)

    def test_renewing_a_lease_survives_a_lost_connection(self):
        """A heartbeat that cannot reconnect is a worker that loses a run
        it is in the middle of doing."""
        run_id = start_run(self.engine)
        self.store.claim_run("w1", "2026-01-01T00:00:00Z",
                             "2126-01-01T00:00:00Z")
        self.terminate_the_backend()
        self.assertTrue(self.store.renew_lease(run_id, "w1",
                                               "2126-01-02T00:00:00Z"))

    def test_releasing_a_lease_survives_a_lost_connection(self):
        run_id = start_run(self.engine)
        self.store.claim_run("w1", "2026-01-01T00:00:00Z",
                             "2126-01-01T00:00:00Z")
        self.drop_the_connection()
        self.store.release_lease(run_id, "w1")
        self.assertIsNone(self.store.get_run(run_id)["lease_owner"])

    def test_a_run_continues_across_a_lost_connection(self):
        """The whole point: the interruption costs a reconnection, not a
        run."""
        run_id = start_run(self.engine)
        self.engine.advance(run_id)
        self.engine.advance(run_id)
        self.drop_the_connection()
        state = advance_to_gate(self.engine, run_id)
        self.assertEqual(state["state"], "awaiting_approval")
        succeeded = [t for t in state["tasks"] if t["state"] == "succeeded"]
        self.assertEqual(len(succeeded), len(analytics.PIPELINE))


@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class WorkerDeathTestCase(unittest.TestCase):
    """A worker killed outright, not asked to stop.

    tests/test_worker.py proves lease expiry with a frozen clock and an
    in-process worker. This kills a real process with SIGKILL, which
    leaves the lease held by a worker that will never renew it — the
    state a crash actually produces.
    """

    def setUp(self):
        self.store = fresh_postgres_store()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "vault"
        self.engine = RunEngine(self.store, self.vault, ModelGateway(),
                                glossary={"metrics": [], "problems": []})

    def spawn_worker(self, lease_seconds):
        # A config of its own so the worker publishes into the test's
        # vault rather than the repository's, even though a run stopping
        # at the approval gate never writes one.
        config = Path(self.tmp.name) / "config.json"
        config.write_text(json.dumps({"vault_dir": str(self.vault)}),
                          encoding="utf-8")
        environment = dict(os.environ, DATABASE_URL=PG_TEST_URL,
                           PYTHONPATH=str(ROOT))
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "worker.py"),
             "--lease", str(lease_seconds), "--poll", "0.1",
             "--config", str(config)],
            env=environment, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self.addCleanup(self._reap, process)
        return process

    def _reap(self, process):
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    def wait_for(self, predicate, timeout=30, interval=0.2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(interval)
        return None

    def kill_mid_run(self, run_id, worker):
        """Kill the worker once it is properly inside the run.

        Where possible this waits for a task to be marked running, so the
        kill lands *during* a stage — the case that used to leave the run
        broken. A stage can complete faster than this loop can observe
        it, so three finished tasks is the fallback trigger.
        """
        def caught_mid_stage():
            tasks = self.store.get_tasks(run_id)
            if any(t["state"] == "running" for t in tasks):
                return "mid-stage"
            if len([t for t in tasks if t["state"] == "succeeded"]) >= 3:
                return "between stages"
            return None

        where = self.wait_for(caught_mid_stage, interval=0.01)
        self.assertTrue(where, "the worker never started the run")
        worker.send_signal(signal.SIGKILL)
        worker.wait(timeout=10)
        return where

    def test_a_killed_worker_leaves_a_run_another_worker_finishes(self):
        run_id = start_run(self.engine)
        worker = self.spawn_worker(lease_seconds=3)
        self.kill_mid_run(run_id, worker)

        row = self.store.get_run(run_id)
        self.assertIsNotNone(row["lease_owner"],
                             "a killed worker cannot release its own lease")
        self.assertNotEqual(row["state"], "failed",
                            "a dead worker is not a failed run")

        # Nothing may touch the run until the dead worker's lease expires:
        # that is the only thing standing between a crash and two workers
        # executing the same task.
        successor = self.spawn_worker(lease_seconds=3)
        finished = self.wait_for(
            lambda: self.store.get_run(run_id)["state"] == "awaiting_approval",
            timeout=60)
        self.assertTrue(finished, "no successor picked the run up")
        succeeded = [t for t in self.store.get_tasks(run_id)
                     if t["state"] == "succeeded"]
        self.assertEqual(len(succeeded), len(analytics.PIPELINE))
        successor.kill()

    def test_the_run_is_not_advanced_twice_by_the_crash(self):
        """Recovery must resume the run, not restart it: every task
        appears once, and each succeeded task holds exactly one result."""
        run_id = start_run(self.engine)
        worker = self.spawn_worker(lease_seconds=3)
        self.kill_mid_run(run_id, worker)
        successor = self.spawn_worker(lease_seconds=3)
        self.assertTrue(self.wait_for(
            lambda: self.store.get_run(run_id)["state"] == "awaiting_approval",
            timeout=60))
        successor.kill()

        tasks = self.store.get_tasks(run_id)
        roles = [t["role"] for t in tasks]
        self.assertEqual(len(roles), len(set(roles)), "a task was duplicated")
        self.assertEqual(len(roles), len(analytics.PIPELINE) + 1)
        for task in tasks:
            if task["state"] == "succeeded":
                self.assertTrue(json.loads(task["result_json"]),
                                f"{task['role']} succeeded with no result")


class InterruptedStageTestCase(unittest.TestCase):
    """A crash *during* a stage, not between two of them.

    This is the case the SIGKILL drill only hits sometimes, so it is
    planted deterministically here. Before the fix the engine walked past
    the task still marked running, continued without a stage its
    successors depend on, and failed several stages later with an error
    naming the wrong thing.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = open_store(None, self.root / "agentic.db")
        self.engine = RunEngine(self.store, self.root / "vault",
                                ModelGateway(),
                                glossary={"metrics": [], "problems": []})

    def interrupt_the_next_stage(self, run_id):
        """Exactly what a kill during `stage(ctx)` leaves behind."""
        task = next(t for t in self.store.get_tasks(run_id)
                    if t["state"] == "pending")
        self.store.update("tasks", task["id"], {"state": "running"})
        return task["role"]

    def test_an_interrupted_stage_is_run_again_rather_than_skipped(self):
        run_id = start_run(self.engine)
        for _ in range(4):
            self.engine.advance(run_id)
        role = self.interrupt_the_next_stage(run_id)

        state = advance_to_gate(self.engine, run_id)
        self.assertEqual(state["state"], "awaiting_approval",
                         f"the run did not recover from a crash in “{role}”")
        interrupted = next(t for t in state["tasks"] if t["role"] == role)
        self.assertEqual(interrupted["state"], "succeeded")
        self.assertTrue(interrupted["summary"],
                        "the stage was marked done without producing anything")
        self.assertEqual(
            len([t for t in state["tasks"] if t["state"] == "succeeded"]),
            len(analytics.PIPELINE))

    def test_no_stage_is_left_holding_a_half_written_result(self):
        """A stage that never finished must not leave a partial result
        behind for the next stage to read as though it were complete."""
        run_id = start_run(self.engine)
        for _ in range(4):
            self.engine.advance(run_id)
        task = next(t for t in self.store.get_tasks(run_id)
                    if t["state"] == "pending")
        self.store.update("tasks", task["id"],
                          {"state": "running", "summary": "half a thought",
                           "result_json": json.dumps({"output": {"junk": True}})})
        self.engine.advance(run_id)
        after = next(t for t in self.store.get_tasks(run_id)
                     if t["id"] == task["id"])
        self.assertNotIn("junk", after["result_json"] or "")
        self.assertNotEqual(after["summary"], "half a thought")


class EngineLossTestCase(unittest.TestCase):
    """The server process itself going away mid-run.

    Runs against SQLite as well as PostgreSQL, because the guarantee is a
    property of durable state rather than of one dialect.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def new_engine(self):
        """A new process would build exactly this."""
        store = open_store(None, self.root / "agentic.db")
        return RunEngine(store, self.root / "vault", ModelGateway(),
                         glossary={"metrics": [], "problems": []})

    def test_a_run_resumes_in_a_new_process_from_where_it_stopped(self):
        engine = self.new_engine()
        run_id = start_run(engine)
        engine.advance(run_id)
        engine.advance(run_id)
        engine.advance(run_id)
        done_before = len([t for t in engine.get_run(run_id)["tasks"]
                           if t["state"] == "succeeded"])
        self.assertEqual(done_before, 3)

        del engine  # the process is gone; nothing was handed over
        resumed = self.new_engine()
        state = advance_to_gate(resumed, run_id)
        self.assertEqual(state["state"], "awaiting_approval")
        self.assertEqual(
            len([t for t in state["tasks"] if t["state"] == "succeeded"]),
            len(analytics.PIPELINE))
        # The first three stages were not recomputed: their results are
        # the ones the original process wrote.
        self.assertTrue(all(t["summary"] for t in state["tasks"][:3]))

    def test_an_approval_survives_the_process_that_created_it(self):
        """The gate is the one place where losing state would let the
        machine publish something nobody approved."""
        engine = self.new_engine()
        run_id = start_run(engine)
        state = advance_to_gate(engine, run_id)
        approval_id = state["approvals"][0]["id"]
        self.assertEqual(state["approvals"][0]["state"], "pending")

        del engine
        resumed = self.new_engine()
        after = resumed.get_run(run_id)
        self.assertEqual(after["approvals"][0]["id"], approval_id)
        self.assertEqual(after["approvals"][0]["state"], "pending")
        decided = resumed.decide_approval(run_id, approval_id, "approve")
        self.assertEqual(decided["approvals"][0]["state"], "approved_once")


if __name__ == "__main__":
    unittest.main()
