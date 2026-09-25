"""Erasing one owner, and not erasing anyone else.

A deletion feature is judged by what it misses, so most of these tests
are about the misses: the published markdown file left on disk after its
database row is gone, the second tenant's identical dataset deleted
along with the first's, the memory file that lives outside the database
entirely. Each of those turns "erased" into a false statement, which is
worse than a missing feature.

The drills run against both dialects, because a DELETE that respects
foreign keys in SQLite and not in PostgreSQL is a deletion that stops
halfway.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

from server import analytics
from server.erasure import DELETE_ORDER, erase, not_reached, survey
from server.model_gateway import ModelGateway
from server.runs import RunEngine
from server.storage import RESTORE_ORDER, open_store


def finish_run(engine, run_id):
    for _ in range(len(analytics.PIPELINE) + 5):
        state = engine.advance(run_id)
        if state["state"] in ("awaiting_approval", "completed", "failed"):
            return state
    return engine.get_run(run_id)


class ErasureMixin:
    """The same expectations against whichever store the subclass wires."""

    def build_store(self):  # pragma: no cover - provided by subclasses
        raise NotImplementedError

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.store = self.build_store()
        self.engine = RunEngine(self.store, self.vault, ModelGateway(),
                                glossary={"metrics": [], "problems": []})

    def make_run(self, owner, goal="Erasure drill", publish=False,
                 dataset_text=None):
        run = self.engine.create_run(goal,
                                     dataset_text or analytics.sample_dataset(),
                                     "sample.csv", owner=owner)
        state = finish_run(self.engine, run["id"])
        if publish:
            self.assertEqual(state["state"], "awaiting_approval")
            self.engine.decide_approval(run["id"], state["approvals"][0]["id"],
                                        "approve")
        return run["id"]

    def remember(self, owner, text, key="memory_1"):
        self.store.memory_save(
            {key: {"text": text, "category": "General",
                   "updated": "2026-09-12"}}, owner)

    # -- the survey -------------------------------------------------------
    def test_the_survey_counts_without_deleting(self):
        self.make_run("alice")
        self.remember("alice", "Alice remembers")
        before = survey(self.store, "alice")
        self.assertGreater(before["total_rows"], 0)
        self.assertEqual(before["runs"], 1)
        self.assertEqual(survey(self.store, "alice"), before,
                         "surveying changed something")

    def test_an_unknown_owner_surveys_as_empty(self):
        found = survey(self.store, "nobody@example.com")
        self.assertEqual(found["total_rows"], 0)
        self.assertEqual(found["runs"], 0)

    # -- the erasure ------------------------------------------------------
    def test_every_trace_of_the_owner_leaves_the_database(self):
        self.make_run("alice", publish=True)
        self.remember("alice", "Alice remembers")
        self.store.upsert_session({
            "id": "s-alice", "owner": "alice", "created_at": "2026-01-01",
            "updated_at": "2026-01-01", "ended": 0, "preferences_json": "{}",
            "history_json": "[]", "transcript_json": "[]", "next_entry_id": 1})

        report = erase(self.store, "alice", vault_dir=self.vault)
        self.assertGreater(report["total_rows"], 0)
        self.assertEqual(survey(self.store, "alice")["total_rows"], 0)
        for table in DELETE_ORDER:
            remaining = self.store._exec(f"SELECT COUNT(*) AS n FROM {table}")
            self.assertEqual(int(remaining[0]["n"]), 0,
                             f"{table} still holds rows")

    def test_a_published_report_leaves_the_disk_as_well_as_the_database(self):
        """The row and the markdown file are two copies of the same
        report. Deleting one of them is the whole failure mode."""
        self.make_run("alice", publish=True)
        notes = sorted(p for p in self.vault.rglob("*.md"))
        self.assertTrue(notes, "the run published nothing to delete")

        report = erase(self.store, "alice", vault_dir=self.vault)
        self.assertTrue(report["vault_files_deleted"])
        self.assertEqual(sorted(self.vault.rglob("*.md")), [])
        self.assertEqual(int(self.store._exec(
            "SELECT COUNT(*) AS n FROM vault_notes")[0]["n"]), 0)

    def test_a_note_already_gone_from_disk_is_reported_not_ignored(self):
        """Somebody tidied the vault by hand. The report says so rather
        than claiming a deletion that did not happen."""
        self.make_run("alice", publish=True)
        for note in self.vault.rglob("*.md"):
            note.unlink()
        report = erase(self.store, "alice", vault_dir=self.vault)
        self.assertEqual(report["vault_files_deleted"], [])
        self.assertTrue(report["vault_files_not_found"])

    # -- the neighbour ----------------------------------------------------
    def test_the_other_tenant_keeps_everything(self):
        self.make_run("alice")
        bob_run = self.make_run("bob", goal="Bob's work", publish=True)
        self.remember("alice", "Alice remembers")
        self.remember("bob", "Bob remembers")

        erase(self.store, "alice", vault_dir=self.vault)

        self.assertEqual(survey(self.store, "bob")["runs"], 1)
        self.assertIsNotNone(self.store.get_run(bob_run))
        self.assertEqual(self.store.memory_load("bob")["memory_1"]["text"],
                         "Bob remembers")
        self.assertTrue(list(self.vault.rglob("*.md")),
                        "Bob's published report was deleted with Alice's")

    def test_an_identical_dataset_uploaded_by_two_tenants_survives(self):
        """Datasets are content-addressed. If the same bytes were stored
        once and shared, erasing one owner would quietly delete the
        other's data — so this asserts the rows are actually per owner."""
        shared = analytics.sample_dataset()
        alice_row = self.engine.store_dataset(shared, "shared.csv", "alice")
        bob_row = self.engine.store_dataset(shared, "shared.csv", "bob")
        self.assertNotEqual(alice_row["id"], bob_row["id"],
                            "the same bytes were stored once and shared")

        erase(self.store, "alice", vault_dir=self.vault)

        self.assertIsNone(self.store.get_dataset(alice_row["id"]))
        surviving = self.store.get_dataset(bob_row["id"])
        self.assertIsNotNone(surviving, "the other tenant's dataset went too")
        self.assertEqual(surviving["content"], shared)

    # -- honesty ----------------------------------------------------------
    def test_the_report_always_names_what_it_could_not_reach(self):
        self.make_run("alice")
        report = erase(self.store, "alice", vault_dir=self.vault)
        self.assertTrue(report["not_reached"])
        joined = " ".join(report["not_reached"]).lower()
        self.assertIn("backup", joined)
        self.assertIn("obsidian", joined)

    def test_the_unreachable_list_is_not_conditional_on_finding_anything(self):
        """An owner with no data still gets the caveat: 'nothing here'
        and 'nothing anywhere' are different answers."""
        report = erase(self.store, "nobody@example.com", vault_dir=self.vault)
        self.assertEqual(report["total_rows"], 0)
        self.assertTrue(report["not_reached"])

    def test_local_mode_memory_outside_the_database_is_cleared_too(self):
        memory_file = self.root / "memory.json"
        memory_file.write_text(json.dumps(
            {"memory_1": {"text": "A local fact", "category": "General",
                          "updated": "2026-09-12"}}), encoding="utf-8")
        report = erase(self.store, "local-owner", vault_dir=self.vault,
                       memory_file=memory_file)
        self.assertTrue(report["memory_file_cleared"])
        self.assertEqual(json.loads(memory_file.read_text(encoding="utf-8")), {})

    def test_a_hosted_owner_does_not_clear_the_local_memory_file(self):
        """data/memory.json belongs to the single-user install. Wiping it
        while erasing a hosted tenant would delete a different person's
        data on the way past."""
        memory_file = self.root / "memory.json"
        memory_file.write_text(json.dumps(
            {"memory_1": {"text": "Somebody else's", "category": "General",
                          "updated": "2026-09-12"}}), encoding="utf-8")
        report = erase(self.store, "alice", vault_dir=self.vault,
                       memory_file=memory_file)
        self.assertFalse(report["memory_file_cleared"])
        self.assertIn("Somebody else's", memory_file.read_text(encoding="utf-8"))


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class SqliteErasureTestCase(ErasureMixin, unittest.TestCase):
    def build_store(self):
        return open_store(None, self.root / "agentic.db")


@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class PostgresErasureTestCase(ErasureMixin, unittest.TestCase):
    def build_store(self):
        store = open_store(PG_TEST_URL)
        for table in reversed(RESTORE_ORDER):
            store._exec(f"DELETE FROM {table}")
        return store


class UnreachableCopiesTestCase(unittest.TestCase):
    def test_backups_are_named_first(self):
        """They are the copy people actually forget, and the one most
        likely to be restored by accident."""
        self.assertIn("backup", not_reached()[0].lower())


if __name__ == "__main__":
    unittest.main()
