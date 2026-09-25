"""Per-tenant quotas.

A quota that is only displayed is a suggestion, so these tests check the
server refuses the work — and that it refuses *before* writing anything,
because a limit that leaves half a resource behind is worse than none.
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

from server import quota
from server.storage import TABLES


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class QuotaTestCase(unittest.TestCase):
    """Tight limits so the boundary is reachable in a test."""

    # Runs are the limit under test here, so the storage allowances are
    # set well clear of the bundled sample dataset (~5 KB) — otherwise
    # storage would be the binding constraint and the test would pass for
    # the wrong reason.
    quota_env = {
        "AGENTIC_OS_QUOTA_RUNS_PER_DAY": "3",
        "AGENTIC_OS_QUOTA_DATASETS": "50",
        "AGENTIC_OS_QUOTA_DATASET_BYTES": "1000000",
    }

    def database_config(self):
        return {"database_file": str(self.root / "agentic.db")}

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "config.json"
        config = {"agent_name": "Quota Test Agent",
                  "memory_file": str(self.root / "memory.json"),
                  "vault_dir": str(self.root / "vault")}
        config.update(self.database_config())
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.client = TestClient(create_app(self.config_path, env=self.quota_env),
                                 raise_server_exceptions=False)

    def create_run(self, goal="Analyze the sample sales dataset", **body):
        return self.client.post("/api/runs", json={"goal": goal, **body})

    def client_with(self, **overrides):
        """Another application instance over the same database, with
        different limits — how an operator would tighten a live one."""
        env = dict(self.quota_env)
        env.update(overrides)
        return TestClient(create_app(self.config_path, env=env),
                          raise_server_exceptions=False)

    # -- runs per day -----------------------------------------------------
    def test_the_daily_run_limit_is_enforced_by_the_server(self):
        for index in range(3):
            self.assertEqual(self.create_run(f"Run {index}").status_code, 201, index)
        refused = self.create_run("One too many")
        self.assertEqual(refused.status_code, 429)
        detail = refused.json()["detail"]
        self.assertIn("3/3", detail)
        self.assertIn("resets at", detail)
        # The refusal is specific about what still works.
        self.assertIn("can still be advanced", detail)

    def test_a_refused_run_leaves_nothing_behind(self):
        for index in range(3):
            self.create_run(f"Run {index}")
        before = self.client.get("/api/runs").json()["runs"]
        self.create_run("Refused")
        after = self.client.get("/api/runs").json()["runs"]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(after), 3)

    def test_existing_runs_still_work_when_the_limit_is_reached(self):
        run = self.create_run("First").json()
        for index in range(2):
            self.create_run(f"Filler {index}")
        self.assertEqual(self.create_run("Refused").status_code, 429)

        # The point of the limit is to stop new work, not to strand
        # everything a tenant already started.
        for _ in range(30):
            state = self.client.post(f"/api/runs/{run['id']}/advance").json()
            if state["state"] == "awaiting_approval":
                break
        self.assertEqual(state["state"], "awaiting_approval")
        decided = self.client.post(
            f"/api/runs/{run['id']}/approvals/{state['approvals'][0]['id']}",
            json={"decision": "approve"})
        self.assertEqual(decided.status_code, 200)

    # -- dataset count and bytes ------------------------------------------
    def test_the_storage_limit_counts_bytes_not_uploads(self):
        tight = self.client_with(AGENTIC_OS_QUOTA_DATASET_BYTES="200")
        small = "team,sales\nA,1\n"                      # 15 bytes
        self.assertEqual(tight.post("/api/runs", json={
            "goal": "First", "dataset_text": small,
            "dataset_name": "a.csv"}).status_code, 201)

        big = "team,sales\n" + "\n".join(f"T{i},{i}" for i in range(60)) + "\n"
        self.assertGreater(len(big.encode()), 200)
        refused = tight.post("/api/runs", json={
            "goal": "Too big", "dataset_text": big, "dataset_name": "b.csv"})
        self.assertEqual(refused.status_code, 429)
        self.assertIn("allowance", refused.json()["detail"])
        # Nothing was stored for the rejected upload.
        names = [d["name"] for d in tight.get("/api/datasets").json()["datasets"]]
        self.assertEqual(names, ["a.csv"])

    def test_re_uploading_the_same_file_costs_nothing(self):
        """Content-addressed storage means a repeat upload adds no bytes,
        so it must not be refused once the allowance is nearly spent."""
        text = "team,sales\nA,1\nB,2\n"
        self.assertEqual(self.create_run("First", dataset_text=text,
                                         dataset_name="same.csv").status_code, 201)
        again = self.create_run("Same data again", dataset_text=text,
                                dataset_name="same.csv")
        self.assertEqual(again.status_code, 201)
        self.assertEqual(len(self.client.get("/api/datasets").json()["datasets"]), 1)

    def test_the_dataset_count_limit_is_enforced(self):
        tight = self.client_with(AGENTIC_OS_QUOTA_DATASETS="2")
        for index in range(2):
            response = tight.post("/api/runs", json={
                "goal": f"Run {index}",
                "dataset_text": f"team,sales\nA,{index}\n",
                "dataset_name": f"{index}.csv"})
            self.assertEqual(response.status_code, 201, index)
        refused = tight.post("/api/runs", json={
            "goal": "Third dataset", "dataset_text": "team,sales\nZ,9\n",
            "dataset_name": "third.csv"})
        self.assertEqual(refused.status_code, 429)
        self.assertIn("2/2", refused.json()["detail"])

    # -- reporting --------------------------------------------------------
    def test_usage_reports_what_is_used_and_what_is_left(self):
        self.create_run("One", dataset_text="team,sales\nA,1\n", dataset_name="a.csv")
        body = self.client.get("/api/usage").json()
        self.assertEqual(body["runs_today"]["used"], 1)
        self.assertEqual(body["runs_today"]["limit"], 3)
        self.assertEqual(body["runs_today"]["remaining"], 2)
        self.assertEqual(body["datasets"]["used"], 1)
        self.assertEqual(body["datasets"]["limit"], 50)
        self.assertEqual(body["dataset_bytes"]["used"], len(b"team,sales\nA,1\n"))
        self.assertIn("resets_at", body["runs_today"])
        # What is NOT measured is named rather than quietly omitted.
        self.assertIn("currency", body["not_tracked"])
        self.assertIn("model tokens", body["not_tracked"])

    def test_usage_is_per_tenant(self):
        """One tenant's spending must not appear in another's budget."""
        from server.quota import load_limits, usage

        store = self.client.app.state.store
        limits = load_limits(self.quota_env)
        self.create_run("Mine")
        mine = usage(store, "local-owner", limits)
        theirs = usage(store, "someone-else", limits)
        self.assertEqual(mine["runs_today"]["used"], 1)
        self.assertEqual(theirs["runs_today"]["used"], 0)
        self.assertEqual(theirs["runs_today"]["remaining"], 3)


class QuotaConfigurationTestCase(unittest.TestCase):
    def test_defaults_are_generous_enough_not_to_interrupt_normal_use(self):
        limits = quota.load_limits(env={})
        self.assertEqual(limits, quota.DEFAULTS)
        self.assertGreaterEqual(limits["runs_per_day"], 100)

    def test_a_typo_in_a_limit_falls_back_instead_of_breaking_startup(self):
        for bad in ("", "lots", "-5", None):
            with self.subTest(value=bad):
                env = {} if bad is None else {"AGENTIC_OS_QUOTA_RUNS_PER_DAY": bad}
                self.assertEqual(quota.load_limits(env=env)["runs_per_day"],
                                 quota.DEFAULTS["runs_per_day"])

    def test_a_zero_limit_is_honoured_as_a_real_stop(self):
        """Zero is a deliberate setting, not a typo: it must not silently
        become the default."""
        limits = quota.load_limits(env={"AGENTIC_OS_QUOTA_RUNS_PER_DAY": "0"})
        self.assertEqual(limits["runs_per_day"], 0)

    def test_the_daily_window_starts_at_midnight_utc(self):
        moment = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)
        self.assertTrue(quota._day_start(moment).startswith("2026-08-13T00:00:00"))
        self.assertTrue(quota._next_day(moment).startswith("2026-08-14T00:00:00"))
        # And it rolls over rather than drifting.
        late = moment + timedelta(hours=9)
        self.assertTrue(quota._day_start(late).startswith("2026-08-14T00:00:00"))


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class QuotaPostgresTestCase(QuotaTestCase):
    def database_config(self):
        return {"database_url": PG_TEST_URL}

    def setUp(self):
        import psycopg2

        conn = psycopg2.connect(PG_TEST_URL)
        conn.autocommit = True
        conn.cursor().execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        conn.close()
        super().setUp()


if __name__ == "__main__":
    unittest.main()
