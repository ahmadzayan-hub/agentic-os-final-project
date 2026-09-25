"""Tests for the durable run engine and analytics pipeline."""

from server import analytics

import json
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


import os

PG_TEST_URL = os.environ.get(
    "PG_TEST_URL", "postgresql://dev@127.0.0.1:54329/agentic_test"
)


def _postgres_available():
    try:
        import psycopg2

        psycopg2.connect(PG_TEST_URL, connect_timeout=3).close()
        return True
    except Exception:
        if os.environ.get("REQUIRE_PG"):
            raise RuntimeError(
                "REQUIRE_PG is set but the test PostgreSQL is unreachable: "
                + PG_TEST_URL
            )
        return False


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class RunEngineTestCase(unittest.TestCase):
    """Full engine suite against the SQLite store (the local default)."""

    def database_config(self):
        return {"database_file": str(self.root / "agentic.db")}

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.vault = self.root / "vault"
        self.config_path = self.root / "config.json"
        config = {
            "agent_name": "Runs Test Agent",
            "memory_file": str(self.root / "memory.json"),
            "vault_dir": str(self.vault),
        }
        config.update(self.database_config())
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.client = TestClient(create_app(self.config_path),
                                 raise_server_exceptions=False)

    def create_run(self, goal="Analyze the sample sales dataset"):
        response = self.client.post("/api/runs", json={"goal": goal})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def advance_until(self, run_id, stop_states, limit=30):
        run = None
        for _ in range(limit):
            run = self.client.post(f"/api/runs/{run_id}/advance").json()
            if run["state"] in stop_states:
                return run
        return run

    def test_full_pipeline_reaches_approval_with_verified_claims(self):
        run = self.create_run()
        self.assertEqual(run["state"], "queued")
        # Every stage, plus the approval-gated publish. Derived so
        # that adding a stage does not need this line edited — the
        # property under test is "one row per task", not "twenty".
        self.assertEqual(len(run["tasks"]), len(analytics.PIPELINE) + 1)
        run = self.advance_until(run["id"], {"awaiting_approval"})
        self.assertEqual(run["state"], "awaiting_approval")
        states = {t["role"]: t["state"] for t in run["tasks"]}
        for role, _stage in analytics.PIPELINE:
            self.assertEqual(states[role], "succeeded", role)
        validator = next(t for t in run["tasks"] if t["role"] == "validator")
        self.assertTrue(all(c["passed"] for c in validator["quality_checks"]))
        self.assertIsNotNone(run["report"])
        self.assertIn("## Every claim in this report", run["report"]["content"])
        self.assertIn("verified", run["report"]["content"])
        self.assertTrue(run["charts"])
        self.assertEqual(len(run["approvals"]), 1)
        self.assertEqual(run["approvals"][0]["risk"], "high")

    def test_reject_publishes_nothing(self):
        run = self.advance_until(self.create_run()["id"], {"awaiting_approval"})
        decided = self.client.post(
            f"/api/runs/{run['id']}/approvals/{run['approvals'][0]['id']}",
            json={"decision": "reject"}).json()
        self.assertEqual(decided["state"], "completed")
        publish = next(t for t in decided["tasks"] if t["role"] == "publish")
        self.assertEqual(publish["state"], "skipped")
        self.assertFalse((self.vault / "Reports").exists())

    def test_published_notes_are_also_durable_in_the_store(self):
        run = self.advance_until(self.create_run()["id"], {"awaiting_approval"})
        self.client.post(
            f"/api/runs/{run['id']}/approvals/{run['approvals'][0]['id']}",
            json={"decision": "approve"})
        listing = self.client.get("/api/vault").json()["notes"]
        self.assertEqual(len(listing), 2)
        paths = {note["path"] for note in listing}
        self.assertIn(f"Runs/{run['id']}.md", paths)
        report_path = next(p for p in paths if p.startswith("Reports/"))
        note = self.client.get("/api/vault/note",
                               params={"path": report_path}).json()
        self.assertIn("type: analytics-report", note["content"])
        missing = self.client.get("/api/vault/note", params={"path": "nope.md"})
        self.assertEqual(missing.status_code, 404)

    def test_approve_publishes_exactly_once_to_the_vault(self):
        run = self.advance_until(self.create_run()["id"], {"awaiting_approval"})
        approval_id = run["approvals"][0]["id"]
        decided = self.client.post(
            f"/api/runs/{run['id']}/approvals/{approval_id}",
            json={"decision": "approve"}).json()
        self.assertEqual(decided["state"], "completed")
        reports = list((self.vault / "Reports").glob("*.md"))
        logs = list((self.vault / "Runs").glob("*.md"))
        self.assertEqual(len(reports), 1)
        self.assertEqual(len(logs), 1)
        note = reports[0].read_text(encoding="utf-8")
        self.assertIn("type: analytics-report", note)
        self.assertIn("status: approved", note)
        self.assertIn(f"[[{run['id']}]]", note)
        # A second decision on the same approval must fail (idempotency).
        again = self.client.post(
            f"/api/runs/{run['id']}/approvals/{approval_id}",
            json={"decision": "approve"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(list((self.vault / "Reports").glob("*.md"))), 1)

    def test_run_survives_restart(self):
        run = self.create_run()
        for _ in range(4):
            self.client.post(f"/api/runs/{run['id']}/advance")
        # Simulate a full application restart with the same database.
        fresh = TestClient(create_app(self.config_path),
                           raise_server_exceptions=False)
        recovered = fresh.get(f"/api/runs/{run['id']}").json()
        self.assertEqual(recovered["id"], run["id"])
        done = [t for t in recovered["tasks"] if t["state"] == "succeeded"]
        self.assertEqual(len(done), 4)
        resumed = fresh.post(f"/api/runs/{run['id']}/advance").json()
        self.assertEqual(
            len([t for t in resumed["tasks"] if t["state"] == "succeeded"]), 5)

    def test_cancel_stops_the_run_and_blocks_further_transitions(self):
        run = self.create_run()
        self.client.post(f"/api/runs/{run['id']}/advance")
        cancelled = self.client.post(f"/api/runs/{run['id']}/cancel").json()
        self.assertEqual(cancelled["state"], "cancelled")
        blocked = self.client.post(f"/api/runs/{run['id']}/advance")
        self.assertEqual(blocked.status_code, 409)

    def test_advance_while_awaiting_approval_is_rejected(self):
        run = self.advance_until(self.create_run()["id"], {"awaiting_approval"})
        blocked = self.client.post(f"/api/runs/{run['id']}/advance")
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("approval", blocked.json()["detail"])

    def test_bad_dataset_fails_honestly(self):
        response = self.client.post("/api/runs", json={
            "goal": "Analyze an empty dataset", "dataset_text": "just,a,header\n"})
        run = self.advance_until(response.json()["id"], {"failed"})
        self.assertEqual(run["state"], "failed")
        self.assertIn("empty", run["error"])

    def test_uploaded_dataset_is_analyzed(self):
        csv_text = "team,quarter,sales\nA,Q1,100\nA,Q2,150\nB,Q1,90\nB,Q2,60\n"
        response = self.client.post("/api/runs", json={
            "goal": "Analyze team sales", "dataset_text": csv_text,
            "dataset_name": "team sales"})
        run = self.advance_until(response.json()["id"], {"awaiting_approval"})
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertIn("total_sales | 400.0", run["report"]["content"])

    def test_storage_falls_back_when_the_target_directory_is_unwritable(self):
        """Serverless bundles ship a read-only filesystem; the store must
        relocate to a writable directory instead of crashing at boot."""
        import tempfile
        import uuid

        from server.storage import SQLiteStore

        blocker = Path(tempfile.mkdtemp()) / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        # The fallback location is shared and survives between runs, so
        # this uses a unique file and row id to stay hermetic.
        name = f"fallback-{uuid.uuid4().hex[:8]}.db"
        requested = blocker / "nested" / name
        store = SQLiteStore(requested)
        self.addCleanup(lambda: store.path.unlink(missing_ok=True))
        self.assertNotEqual(store.path, requested)
        self.assertTrue(str(store.path).startswith(tempfile.gettempdir()))
        run_id = uuid.uuid4().hex[:12]
        store.insert("runs", {
            "id": run_id, "goal": "still works", "dataset_name": "d",
            "dataset_text": "t", "state": "queued", "created_at": "n",
            "updated_at": "n", "error": None, "owner": "local-owner"})
        self.assertEqual(store.get_run(run_id)["goal"], "still works")

    def test_identical_datasets_are_stored_once(self):
        csv_text = "team,sales\nA,100\nB,90\n"
        first = self.client.post("/api/runs", json={
            "goal": "First look", "dataset_text": csv_text,
            "dataset_name": "sales.csv"}).json()
        second = self.client.post("/api/runs", json={
            "goal": "Second look", "dataset_text": csv_text,
            "dataset_name": "sales.csv"}).json()
        datasets = self.client.get("/api/datasets").json()["datasets"]
        # Two runs, one stored copy of the data.
        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0]["byte_size"], len(csv_text.encode()))
        self.assertNotEqual(first["id"], second["id"])

    def test_a_run_can_reuse_a_previously_uploaded_dataset(self):
        csv_text = "team,sales\nA,100\nB,90\n"
        self.client.post("/api/runs", json={
            "goal": "Original", "dataset_text": csv_text,
            "dataset_name": "sales.csv"})
        dataset_id = self.client.get("/api/datasets").json()["datasets"][0]["id"]
        reused = self.client.post("/api/runs", json={
            "goal": "Reuse the upload", "dataset_id": dataset_id}).json()
        self.assertEqual(reused["dataset_name"], "sales.csv")
        run = self.advance_until(reused["id"], {"awaiting_approval", "failed"})
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertIn("total_sales | 190.0", run["report"]["content"])

    def test_unknown_dataset_reference_is_rejected(self):
        response = self.client.post("/api/runs", json={
            "goal": "Point at nothing", "dataset_id": "does-not-exist"})
        self.assertEqual(response.status_code, 404)

    def test_unknown_run_returns_404(self):
        self.assertEqual(self.client.get("/api/runs/nope").status_code, 404)

    def test_health_reports_deterministic_provider_without_credentials(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["model_provider"]["provider"], "deterministic")
        self.assertFalse(body["model_provider"]["configured"])


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class RunEnginePostgresTestCase(RunEngineTestCase):
    """The identical engine suite against the hosted-mode PostgresStore.

    Set PG_TEST_URL to point at a disposable database; set REQUIRE_PG=1
    (as CI does) to turn an unreachable database into a hard failure
    instead of a silent skip.
    """

    def database_config(self):
        return {"database_url": PG_TEST_URL}

    def setUp(self):
        import psycopg2

        from server.storage import TABLES

        # Fresh tables per test so runs from other tests never leak in.
        # The list is derived from the store's own table tuple: a
        # hand-maintained copy went stale once and leaked dataset rows.
        conn = psycopg2.connect(PG_TEST_URL)
        conn.autocommit = True
        conn.cursor().execute(
            f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        conn.close()
        super().setUp()

    def test_hosted_mode_keeps_memory_in_the_database(self):
        state = self.client.post("/api/sessions").json()
        self.assertTrue(state["memory_persisted"])
        self.client.post(
            f"/api/sessions/{state['session_id']}/memory",
            json={"information": "Hosted fact", "category": "work"})

        # A brand-new app instance over the same DATABASE_URL sees the
        # memory — and no local memory file was ever written.
        fresh = TestClient(create_app(self.config_path),
                           raise_server_exceptions=False)
        second = fresh.post("/api/sessions").json()
        self.assertIn("Hosted fact", second["memory"].values())
        self.assertFalse((self.root / "memory.json").exists())


if __name__ == "__main__":
    unittest.main()
