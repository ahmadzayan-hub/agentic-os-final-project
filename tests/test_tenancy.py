"""One tenant's data must never reach another.

Sessions and runs have carried an owner since ADR 0002. Agent memory
never did: it was a single global store, read and written by whoever
asked. In local mode that is correct — one person, one machine, one
`data/memory.json`. In hosted mode it means the thing the product exists
to remember is the one thing everybody shares.

These tests are written from the attacker's side of the boundary: a
second authenticated user, doing nothing unusual, seeing or destroying
the first user's data.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

from server.auth import issue_local_test_token
from server.storage import RESTORE_ORDER, open_store

SECRET = "tenancy-test-secret-not-used-anywhere-else"


def clear(store):
    for table in reversed(RESTORE_ORDER):
        store._exec(f"DELETE FROM {table}")


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class TenantIsolationMixin:
    """The same expectations against whichever store the subclass wires."""

    def build_client(self, root):  # pragma: no cover - provided by subclasses
        raise NotImplementedError

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.client = self.build_client(self.root)

    def auth(self, subject):
        return {"Authorization": "Bearer " + issue_local_test_token(
            SECRET, subject=subject, role="owner")}

    def session_for(self, subject):
        response = self.client.post("/api/sessions", headers=self.auth(subject))
        self.assertEqual(response.status_code, 201)
        return response.json()["session_id"]

    def remember(self, subject, session, text, category="General"):
        response = self.client.post(
            f"/api/sessions/{session}/memory",
            json={"information": text, "category": category},
            headers=self.auth(subject))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def memories_of(self, subject, session):
        snapshot = self.client.get(f"/api/sessions/{session}",
                                   headers=self.auth(subject)).json()
        return [entry["text"] for entry in snapshot["memory_entries"]]

    # -- the boundary -----------------------------------------------------
    def test_one_tenant_cannot_read_another_tenants_memory(self):
        alice = self.session_for("alice")
        self.remember("alice", alice, "Alice salary 250000 AED", "Profile")

        bob = self.session_for("bob")
        self.assertEqual(self.memories_of("bob", bob), [],
                         "a new tenant started with somebody else's memory")

    def test_one_tenant_cannot_destroy_another_tenants_memory(self):
        """Saving rewrites the caller's memory. Unscoped, that rewrite
        took everybody's with it."""
        alice = self.session_for("alice")
        self.remember("alice", alice, "Alice salary 250000 AED", "Profile")

        bob = self.session_for("bob")
        self.remember("bob", bob, "Bob likes cricket")

        self.assertEqual(self.memories_of("alice", alice),
                         ["Alice salary 250000 AED"])
        self.assertEqual(self.memories_of("bob", bob), ["Bob likes cricket"])

    def test_two_tenants_can_hold_the_same_memory_key(self):
        """Keys are handed out per owner, so the first thing two tenants
        save is `memory_1` for both. A single-column primary key would
        make the second one collide."""
        alice = self.session_for("alice")
        bob = self.session_for("bob")
        self.remember("alice", alice, "Alice's first fact")
        self.remember("bob", bob, "Bob's first fact")

        alice_state = self.client.get(f"/api/sessions/{alice}",
                                      headers=self.auth("alice")).json()
        bob_state = self.client.get(f"/api/sessions/{bob}",
                                    headers=self.auth("bob")).json()
        alice_keys = [entry["key"] for entry in alice_state["memory_entries"]]
        bob_keys = [entry["key"] for entry in bob_state["memory_entries"]]
        self.assertEqual(alice_keys, bob_keys)
        self.assertEqual(alice_state["memory_entries"][0]["text"],
                         "Alice's first fact")
        self.assertEqual(bob_state["memory_entries"][0]["text"],
                         "Bob's first fact")

    def test_deleting_one_tenants_memory_leaves_the_other_untouched(self):
        alice = self.session_for("alice")
        bob = self.session_for("bob")
        self.remember("alice", alice, "Alice keeps this")
        self.remember("bob", bob, "Bob keeps this")

        response = self.client.delete(f"/api/sessions/{alice}/memory",
                                      headers=self.auth("alice"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.memories_of("alice", alice), [])
        self.assertEqual(self.memories_of("bob", bob), ["Bob keeps this"])

    def test_a_tenants_memory_survives_their_next_session(self):
        """Isolation must not be achieved by forgetting: the point of the
        feature is that memory persists for the person who saved it."""
        first = self.session_for("alice")
        self.remember("alice", first, "Remember me")
        second = self.session_for("alice")
        self.assertEqual(self.memories_of("alice", second), ["Remember me"])


@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class HostedPostgresTenancyTestCase(TenantIsolationMixin, unittest.TestCase):
    """The deployment shape this actually ships as."""

    def build_client(self, root):
        store = open_store(PG_TEST_URL)
        clear(store)
        config = root / "config.json"
        config.write_text(json.dumps({
            "agent_name": "Tenancy Test",
            "database_url": PG_TEST_URL,
            "vault_dir": str(root / "vault"),
        }), encoding="utf-8")
        return TestClient(
            create_app(config, env={"AGENTIC_OS_JWT_SECRET": SECRET,
                                    "AGENTIC_OS_ENV": "production"}),
            raise_server_exceptions=False)


class HostedSqliteTenancyTestCase(TenantIsolationMixin, unittest.TestCase):
    """A small deployment with authentication but no PostgreSQL is still
    multi-tenant, and used to share one memory file between everybody."""

    def build_client(self, root):
        config = root / "config.json"
        config.write_text(json.dumps({
            "agent_name": "Tenancy Test",
            "database_file": str(root / "agentic.db"),
            "memory_file": str(root / "memory.json"),
            "vault_dir": str(root / "vault"),
        }), encoding="utf-8")
        return TestClient(
            create_app(config, env={"AGENTIC_OS_JWT_SECRET": SECRET,
                                    "AGENTIC_OS_ENV": "production"}),
            raise_server_exceptions=False)


OLD_MEMORY_TABLE = """CREATE TABLE memory_kv (
  key TEXT PRIMARY KEY, text TEXT NOT NULL,
  category TEXT NOT NULL, updated TEXT)"""


class MemoryMigrationTestCase(unittest.TestCase):
    """Existing databases carry real memories, and the fix moves their
    primary key. A migration that drops a row is worse than the bug it
    fixes, so it is tested on data rather than on an empty table."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agentic.db"

    def old_database(self):
        """A database as it was written before memory had an owner."""
        import sqlite3

        connection = sqlite3.connect(self.path)
        connection.execute(OLD_MEMORY_TABLE)
        connection.executemany(
            "INSERT INTO memory_kv (key, text, category, updated) "
            "VALUES (?, ?, ?, ?)",
            [("memory_1", "A fact from before", "General", "2026-01-01"),
             ("memory_2", "Another one", "Profile", "2026-01-02")])
        connection.commit()
        connection.close()

    def test_memories_written_before_owners_existed_survive(self):
        self.old_database()
        store = open_store(None, self.path)   # opening runs the migration
        remembered = store.memory_load("local-owner")
        self.assertEqual(len(remembered), 2)
        self.assertEqual(remembered["memory_1"]["text"], "A fact from before")
        self.assertEqual(remembered["memory_2"]["category"], "Profile")

    def test_the_migration_runs_once_and_is_safe_to_repeat(self):
        """Every start-up runs it. The second one must be a no-op, not a
        second rebuild that copies rows onto themselves."""
        self.old_database()
        open_store(None, self.path)
        store = open_store(None, self.path)
        self.assertEqual(len(store.memory_load("local-owner")), 2)
        leftovers = store._exec(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name LIKE 'memory_kv%'")
        self.assertEqual([row["name"] for row in leftovers], ["memory_kv"],
                         "the migration left a scratch table behind")

    def test_a_migrated_database_can_hold_two_owners(self):
        self.old_database()
        store = open_store(None, self.path)
        store.memory_save({"memory_1": {"text": "Bob's", "category": "General",
                                        "updated": "2026-02-01"}}, "bob")
        self.assertEqual(store.memory_load("local-owner")["memory_1"]["text"],
                         "A fact from before")
        self.assertEqual(store.memory_load("bob")["memory_1"]["text"], "Bob's")


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class LocalModeTestCase(unittest.TestCase):
    """Local mode is one person on one machine, and its memory contract —
    a readable `data/memory.json` — is documented and must not change
    because hosted mode grew an owner column."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.memory_file = self.root / "memory.json"
        config = self.root / "config.json"
        config.write_text(json.dumps({
            "agent_name": "Local Test",
            "database_file": str(self.root / "agentic.db"),
            "memory_file": str(self.memory_file),
            "vault_dir": str(self.root / "vault"),
        }), encoding="utf-8")
        self.client = TestClient(create_app(config, env={}),
                                 raise_server_exceptions=False)

    def test_memory_still_lands_in_the_documented_json_file(self):
        session = self.client.post("/api/sessions").json()["session_id"]
        self.client.post(f"/api/sessions/{session}/memory",
                         json={"information": "A local fact",
                               "category": "General"})
        self.assertTrue(self.memory_file.exists(),
                        "local mode stopped writing data/memory.json")
        saved = json.loads(self.memory_file.read_text(encoding="utf-8"))
        self.assertIn("A local fact",
                      [entry["text"] for entry in saved.values()])


if __name__ == "__main__":
    unittest.main()
