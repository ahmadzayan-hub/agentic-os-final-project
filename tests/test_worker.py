"""Background worker: leases, heartbeats, crash recovery, and the limits
of what a worker is allowed to decide on its own.

Runs against SQLite and PostgreSQL, like the rest of the engine suites.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

from server import analytics
from server.model_gateway import ModelGateway
from server.runs import RunEngine
from server.storage import TABLES, open_store
from server.worker import RunWorker


class FrozenClock:
    """A clock the test moves by hand, so lease expiry is a decision
    rather than a sleep."""

    def __init__(self, start=None):
        self.now = start or datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class WorkerTestCase(unittest.TestCase):
    def database_config(self):
        return {"database_file": str(self.root / "agentic.db")}

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.vault = self.root / "vault"
        self.config_path = self.root / "config.json"
        config = {"agent_name": "Worker Test Agent",
                  "memory_file": str(self.root / "memory.json"),
                  "vault_dir": str(self.vault)}
        config.update(self.database_config())
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.client = TestClient(create_app(self.config_path),
                                 raise_server_exceptions=False)

    def new_worker(self, worker_id, clock=None, lease_seconds=30):
        """A worker in its own process-equivalent: its own store handle."""
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        store = open_store(config.get("database_url"),
                           config.get("database_file"))
        engine = RunEngine(store, self.vault, ModelGateway())
        return RunWorker(engine, store, worker_id=worker_id,
                         lease_seconds=lease_seconds,
                         clock=clock or (lambda: datetime.now(timezone.utc)))

    def create_run(self, goal="Analyze the sample sales dataset"):
        response = self.client.post("/api/runs", json={"goal": goal})
        self.assertEqual(response.status_code, 201)
        return response.json()

    # -- the point of the whole thing -------------------------------------
    def test_a_worker_advances_a_run_with_no_client_stepping_it(self):
        run = self.create_run()
        worked = self.new_worker("w1").step()
        self.assertEqual(worked, run["id"])

        # The browser could have been closed the entire time.
        state = self.client.get(f"/api/runs/{run['id']}").json()
        self.assertEqual(state["state"], "awaiting_approval")
        succeeded = [t for t in state["tasks"] if t["state"] == "succeeded"]
        self.assertEqual(len(succeeded), len(analytics.PIPELINE))
        self.assertIsNotNone(state["report"])

    def test_a_worker_stops_at_the_approval_gate_and_publishes_nothing(self):
        run = self.create_run()
        self.new_worker("w1").step()
        # Give it every chance to keep going: nothing is runnable now.
        self.assertIsNone(self.new_worker("w2").step())

        state = self.client.get(f"/api/runs/{run['id']}").json()
        self.assertEqual(state["state"], "awaiting_approval")
        self.assertEqual(state["approvals"][0]["state"], "pending")
        self.assertFalse((self.vault / "Reports").exists())

        # The human decides, and only then is anything published.
        decided = self.client.post(
            f"/api/runs/{run['id']}/approvals/{state['approvals'][0]['id']}",
            json={"decision": "approve"}).json()
        self.assertEqual(decided["state"], "completed")
        self.assertEqual(len(list((self.vault / "Reports").glob("*.md"))), 1)

    def test_nothing_runnable_returns_none_rather_than_spinning(self):
        self.assertIsNone(self.new_worker("w1").step())

    # -- leases ------------------------------------------------------------
    def test_two_workers_never_claim_the_same_run(self):
        run = self.create_run()
        first, second = self.new_worker("w1"), self.new_worker("w2")
        self.assertEqual(first.claim(), run["id"])
        self.assertIsNone(second.claim())
        # And a second run is claimable while the first is held.
        other = self.create_run("Analyze something else")
        self.assertEqual(second.claim(), other["id"])

    def test_a_client_cannot_advance_a_run_a_worker_is_holding(self):
        run = self.create_run()
        worker = self.new_worker("w1")
        self.assertEqual(worker.claim(), run["id"])

        # The client's advance is a no-op that returns current state, so an
        # open browser and a worker never execute the same task twice.
        for _ in range(3):
            state = self.client.post(f"/api/runs/{run['id']}/advance").json()
        self.assertEqual(state["state"], "queued")
        self.assertFalse([t for t in state["tasks"] if t["state"] != "pending"])

    def test_an_expired_lease_lets_the_work_continue_after_a_crash(self):
        """A worker that dies mid-run stops renewing; the run is not lost."""
        run = self.create_run()
        clock = FrozenClock()
        dead = self.new_worker("dead-worker", clock=clock, lease_seconds=30)
        self.assertEqual(dead.claim(), run["id"])
        dead.engine.advance(run["id"], lease_owner="dead-worker")
        # ...and then the process is killed: no release, no renewal.

        clock.advance(31)
        survivor = self.new_worker("survivor", clock=clock)
        self.assertEqual(survivor.step(), run["id"])
        state = self.client.get(f"/api/runs/{run['id']}").json()
        self.assertEqual(state["state"], "awaiting_approval")

    def test_a_client_resumes_stepping_once_a_lease_has_expired(self):
        run = self.create_run()
        clock = FrozenClock()
        dead = self.new_worker("dead-worker", clock=clock, lease_seconds=30)
        self.assertEqual(dead.claim(), run["id"])

        # Real time is well past the frozen lease expiry, so the API sees a
        # stale lease and steps the run itself.
        state = self.client.post(f"/api/runs/{run['id']}/advance").json()
        self.assertEqual(
            len([t for t in state["tasks"] if t["state"] == "succeeded"]), 1)

    def test_the_lease_is_released_when_the_run_stops_being_runnable(self):
        run = self.create_run()
        self.new_worker("w1").step()
        row = self.new_worker("w2").store.get_run(run["id"])
        self.assertIsNone(row["lease_owner"])
        self.assertIsNone(row["lease_expires_at"])

    def test_a_worker_that_lost_its_lease_stops_working_the_run(self):
        run = self.create_run()
        worker = self.new_worker("w1")
        self.assertEqual(worker.claim(), run["id"])
        # Somebody else takes ownership (as a successor would after expiry).
        worker.store.update("runs", run["id"], {"lease_owner": "w2"})

        self.assertFalse(worker.store.renew_lease(run["id"], "w1", "9999"))
        worker.store.release_lease(run["id"], "w1")
        # Releasing our own lease must never clear a successor's.
        self.assertEqual(worker.store.get_run(run["id"])["lease_owner"], "w2")

    # -- pause is server-side truth ---------------------------------------
    def test_a_worker_does_not_touch_a_paused_run(self):
        """Pause used to be a client-side toggle. With a worker that would
        make the button a decoration: it must stop the server too."""
        run = self.create_run()
        paused = self.client.post(f"/api/runs/{run['id']}/pause").json()
        self.assertTrue(paused["paused"])

        self.assertIsNone(self.new_worker("w1").step())
        state = self.client.get(f"/api/runs/{run['id']}").json()
        self.assertFalse([t for t in state["tasks"] if t["state"] != "pending"])

        resumed = self.client.post(f"/api/runs/{run['id']}/resume").json()
        self.assertFalse(resumed["paused"])
        self.assertEqual(self.new_worker("w1").step(), run["id"])
        self.assertEqual(
            self.client.get(f"/api/runs/{run['id']}").json()["state"],
            "awaiting_approval")

    def test_a_paused_run_refuses_to_advance(self):
        run = self.create_run()
        self.client.post(f"/api/runs/{run['id']}/pause")
        blocked = self.client.post(f"/api/runs/{run['id']}/advance")
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("paused", blocked.json()["detail"])

    def test_pause_survives_a_restart(self):
        run = self.create_run()
        self.client.post(f"/api/runs/{run['id']}/pause")
        fresh = TestClient(create_app(self.config_path),
                           raise_server_exceptions=False)
        self.assertTrue(fresh.get(f"/api/runs/{run['id']}").json()["paused"])

    def test_a_finished_run_cannot_be_paused(self):
        run = self.create_run()
        self.client.post(f"/api/runs/{run['id']}/cancel")
        refused = self.client.post(f"/api/runs/{run['id']}/pause")
        self.assertEqual(refused.status_code, 409)

    def test_a_pause_mid_run_ends_the_worker_s_turn_not_the_worker(self):
        """Found by running the real thing: pausing while a worker was
        mid-pipeline raised out of `advance` and killed the process."""
        run = self.create_run()
        worker = self.new_worker("w1")
        original = worker.store.renew_lease

        def pause_then_renew(*args, **kwargs):
            # A human hits Pause partway through the pipeline.
            worker.store.renew_lease = original
            self.client.post(f"/api/runs/{run['id']}/pause")
            return original(*args, **kwargs)

        worker.store.renew_lease = pause_then_renew
        self.assertEqual(worker.step(), run["id"])  # returns, does not raise

        state = self.client.get(f"/api/runs/{run['id']}").json()
        self.assertTrue(state["paused"])
        self.assertLess(
            len([t for t in state["tasks"] if t["state"] == "succeeded"]),
            len(analytics.PIPELINE))
        # The lease is released, so resuming can be picked up again.
        self.assertIsNone(worker.store.get_run(run["id"])["lease_owner"])
        self.client.post(f"/api/runs/{run['id']}/resume")
        self.assertEqual(self.new_worker("w2").step(), run["id"])
        self.assertEqual(
            self.client.get(f"/api/runs/{run['id']}").json()["state"],
            "awaiting_approval")

    def test_the_worker_loop_survives_a_failure_on_one_run(self):
        import threading

        run = self.create_run()
        worker = self.new_worker("w1")
        real_advance = worker.engine.advance
        calls = []

        def explode_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("a stage blew up")
            return real_advance(*args, **kwargs)

        worker.engine.advance = explode_once
        stop = threading.Event()
        naps = []

        def fake_sleep(seconds):
            naps.append(seconds)
            if len(naps) >= 2:
                stop.set()

        worker.run_forever(poll_seconds=0.01, stop=stop, sleep=fake_sleep)

        # The loop recovered and finished the very run that had failed.
        self.assertEqual(
            self.client.get(f"/api/runs/{run['id']}").json()["state"],
            "awaiting_approval")

    def test_a_cancelled_run_is_not_picked_up(self):
        run = self.create_run()
        self.client.post(f"/api/runs/{run['id']}/cancel")
        self.assertIsNone(self.new_worker("w1").step())


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class WorkerPostgresTestCase(WorkerTestCase):
    """The same suite where workers are genuinely separate connections."""

    def database_config(self):
        return {"database_url": PG_TEST_URL}

    def setUp(self):
        import psycopg2

        conn = psycopg2.connect(PG_TEST_URL)
        conn.autocommit = True
        conn.cursor().execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        conn.close()
        super().setUp()

    def test_concurrent_workers_never_double_claim_a_run(self):
        """Only real parallelism exercises the conditional UPDATE.

        Sequential tests are satisfied by the candidate SELECT alone —
        but a SELECT is a read, not a claim. Here six workers on six
        connections start together and race for the same rows; if the
        UPDATE's guard were dropped, two of them would come away holding
        the same run.
        """
        import threading

        runs = {self.create_run(f"Race {i}")["id"] for i in range(12)}
        claimed, errors = [], []
        results_lock = threading.Lock()
        start = threading.Barrier(6)

        def grab(name):
            try:
                worker = self.new_worker(name)
                start.wait(timeout=30)
                while True:
                    run_id = worker.claim()
                    if run_id is None:
                        return
                    with results_lock:
                        claimed.append(run_id)
            except Exception as error:  # surfaced below, not swallowed
                with results_lock:
                    errors.append(error)

        threads = [threading.Thread(target=grab, args=(f"w{i}",))
                   for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive(), "a worker thread hung")

        self.assertEqual(errors, [])
        self.assertEqual(len(claimed), len(set(claimed)),
                         "the same run was claimed by two workers")
        self.assertEqual(set(claimed), runs)


if __name__ == "__main__":
    unittest.main()
