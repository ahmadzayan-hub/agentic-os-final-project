"""Unit tests for the FastAPI adapter in server/app.py.

These tests run the API in-process against a temporary configuration and
memory file, so they never touch the repository's real data files.
"""

import json
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - CLI-only environments
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.memory_path = root / "memory.json"
        self.config_path = config_path = root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "agent_name": "Web Test Agent",
                    "version": "9.9.9",
                    "preferences": {"tone": "concise"},
                    "memory_file": str(self.memory_path),
                    "database_file": str(root / "agentic.db"),
                    "vault_dir": str(root / "vault"),
                    "maximum_history_items": 50,
                }
            ),
            encoding="utf-8",
        )
        self.client = TestClient(create_app(config_path), raise_server_exceptions=False)

    def open_session(self):
        response = self.client.post("/api/sessions")
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_health_reports_agent_identity(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["agent_name"], "Web Test Agent")

    def test_create_session_returns_full_snapshot(self):
        state = self.open_session()
        self.assertIn("session_id", state)
        self.assertEqual(state["agent_name"], "Web Test Agent")
        self.assertFalse(state["ended"])
        self.assertEqual(state["transcript"], [])
        self.assertEqual(state["preferences"]["tone"], "concise")
        self.assertTrue(any(c["command"] == "/help" for c in state["commands"]))

    def test_unknown_session_returns_404(self):
        response = self.client.get("/api/sessions/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_send_message_appends_user_and_agent_entries(self):
        state = self.open_session()
        response = self.client.post(
            f"/api/sessions/{state['session_id']}/messages",
            json={"text": "Hello there"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        roles = [entry["role"] for entry in body["state"]["transcript"]]
        self.assertEqual(roles, ["user", "agent"])
        self.assertIn("Hello there", body["state"]["transcript"][0]["text"])
        self.assertEqual(body["reply"]["role"], "agent")

    def test_blank_message_is_rejected(self):
        state = self.open_session()
        response = self.client.post(
            f"/api/sessions/{state['session_id']}/messages",
            json={"text": "   "},
        )
        self.assertEqual(response.status_code, 422)

    def test_slash_exit_message_ends_the_session(self):
        state = self.open_session()
        sid = state["session_id"]
        response = self.client.post(
            f"/api/sessions/{sid}/messages", json={"text": "/exit"}
        )
        self.assertTrue(response.json()["state"]["ended"])
        follow_up = self.client.post(
            f"/api/sessions/{sid}/messages", json={"text": "still there?"}
        )
        self.assertEqual(follow_up.status_code, 409)

    def test_memory_add_and_delete_round_trip(self):
        state = self.open_session()
        sid = state["session_id"]
        added = self.client.post(
            f"/api/sessions/{sid}/memory",
            json={"information": "The tram opens at 6am", "category": "work"},
        )
        self.assertEqual(added.status_code, 201)
        memory = added.json()["state"]["memory"]
        self.assertIn("The tram opens at 6am", memory.values())
        entries = added.json()["state"]["memory_entries"]
        self.assertEqual(entries[0]["category"], "work")
        saved_file = json.loads(self.memory_path.read_text(encoding="utf-8"))
        key = next(iter(memory))
        self.assertEqual(saved_file[key]["text"], "The tram opens at 6am")
        self.assertEqual(saved_file[key]["category"], "work")

        key = next(iter(memory))
        deleted = self.client.delete(f"/api/sessions/{sid}/memory/{key}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["state"]["memory"], {})

    def test_update_memory_edits_in_place_and_persists(self):
        state = self.open_session()
        sid = state["session_id"]
        added = self.client.post(
            f"/api/sessions/{sid}/memory", json={"information": "Old text"}
        )
        key = next(iter(added.json()["state"]["memory"]))
        updated = self.client.put(
            f"/api/sessions/{sid}/memory/{key}",
            json={"information": "New text", "category": "profile"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["state"]["memory"][key], "New text")
        self.assertEqual(
            updated.json()["state"]["memory_entries"][0]["category"], "profile"
        )
        self.assertEqual(
            json.loads(self.memory_path.read_text(encoding="utf-8"))[key]["text"],
            "New text",
        )

    def test_update_unknown_memory_returns_404(self):
        state = self.open_session()
        response = self.client.put(
            f"/api/sessions/{state['session_id']}/memory/memory_9",
            json={"information": "x"},
        )
        self.assertEqual(response.status_code, 404)

    def test_export_returns_full_data_as_attachment(self):
        state = self.open_session()
        sid = state["session_id"]
        self.client.post(f"/api/sessions/{sid}/messages", json={"text": "Hello"})
        self.client.post(
            f"/api/sessions/{sid}/memory", json={"information": "A fact"}
        )
        response = self.client.get(f"/api/sessions/{sid}/export")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        body = response.json()
        self.assertIn("A fact", body["memory"].values())
        # Panel-driven memory operations are structured API calls, not
        # conversation, so only the typed message appears in history.
        self.assertEqual(body["history"], ["Hello"])
        self.assertEqual(len(body["transcript"]), 2)
        self.assertEqual(body["memory_entries"][0]["text"], "A fact")

    def test_snapshot_reports_memory_persistence(self):
        state = self.open_session()
        self.assertTrue(state["memory_persisted"])

    def test_delete_unknown_memory_returns_404(self):
        state = self.open_session()
        response = self.client.delete(
            f"/api/sessions/{state['session_id']}/memory/memory_9"
        )
        self.assertEqual(response.status_code, 404)

    def test_clear_memory_removes_everything(self):
        state = self.open_session()
        sid = state["session_id"]
        self.client.post(
            f"/api/sessions/{sid}/memory", json={"information": "One"}
        )
        self.client.post(
            f"/api/sessions/{sid}/memory", json={"information": "Two"}
        )
        response = self.client.delete(f"/api/sessions/{sid}/memory")
        self.assertEqual(response.json()["state"]["memory"], {})

    def test_update_preference_applies_to_responses(self):
        state = self.open_session()
        sid = state["session_id"]
        response = self.client.put(
            f"/api/sessions/{sid}/preferences",
            json={"key": "tone", "value": "formal"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"]["preferences"]["tone"], "formal")

    def test_boolean_preference_values_become_booleans(self):
        state = self.open_session()
        response = self.client.put(
            f"/api/sessions/{state['session_id']}/preferences",
            json={"key": "save_history", "value": "false"},
        )
        self.assertIs(response.json()["state"]["preferences"]["save_history"], False)

    def test_invalid_preference_key_is_rejected(self):
        state = self.open_session()
        response = self.client.put(
            f"/api/sessions/{state['session_id']}/preferences",
            json={"key": "bad key!", "value": "x"},
        )
        self.assertEqual(response.status_code, 422)

    def test_clear_history_empties_history_only(self):
        state = self.open_session()
        sid = state["session_id"]
        self.client.post(f"/api/sessions/{sid}/messages", json={"text": "Hello"})
        self.client.post(
            f"/api/sessions/{sid}/memory", json={"information": "Keep me"}
        )
        response = self.client.delete(f"/api/sessions/{sid}/history")
        body = response.json()
        self.assertEqual(body["state"]["history"], [])
        self.assertIn("Keep me", body["state"]["memory"].values())

    @unittest.skipUnless(
        DIST_DIR.is_dir(), "frontend build not present (run npm run build)"
    )
    def test_static_files_cannot_escape_the_dist_directory(self):
        # A traversal path must fall back to the SPA page, never serve
        # files outside frontend/dist (config.json contains settings).
        response = self.client.get("/../config.json")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("memory_file", response.text)
        response = self.client.get("/..%2F..%2Fconfig.json")
        self.assertNotIn("memory_file", response.text)

    def test_sessions_survive_an_application_restart(self):
        state = self.open_session()
        sid = state["session_id"]
        self.client.post(f"/api/sessions/{sid}/messages", json={"text": "Hello"})
        self.client.put(f"/api/sessions/{sid}/preferences",
                        json={"key": "tone", "value": "formal"})

        # Simulate a full restart: a brand-new app over the same config.
        fresh = TestClient(create_app(self.config_path),
                           raise_server_exceptions=False)
        restored = fresh.get(f"/api/sessions/{sid}")
        self.assertEqual(restored.status_code, 200)
        body = restored.json()
        self.assertEqual(len(body["transcript"]), 2)
        self.assertEqual(body["preferences"]["tone"], "formal")
        self.assertFalse(body["ended"])
        follow_up = fresh.post(f"/api/sessions/{sid}/messages",
                               json={"text": "Still here?"})
        self.assertEqual(follow_up.status_code, 200)
        self.assertEqual(len(follow_up.json()["state"]["transcript"]), 4)

    def test_end_session_marks_session_ended(self):
        state = self.open_session()
        response = self.client.delete(f"/api/sessions/{state['session_id']}")
        self.assertTrue(response.json()["ended"])

    def test_two_sessions_cannot_overwrite_each_others_memory(self):
        first = self.open_session()
        second = self.open_session()
        self.client.post(
            f"/api/sessions/{first['session_id']}/memory",
            json={"information": "Fact from session one"},
        )
        response = self.client.post(
            f"/api/sessions/{second['session_id']}/memory",
            json={"information": "Fact from session two"},
        )
        saved = json.loads(self.memory_path.read_text(encoding="utf-8"))
        texts = [entry["text"] for entry in saved.values()]
        self.assertIn("Fact from session one", texts)
        self.assertIn("Fact from session two", texts)
        self.assertEqual(len(saved), 2)
        self.assertEqual(len(response.json()["state"]["memory"]), 2)

    def test_api_responses_are_not_cacheable_and_carry_security_headers(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")

    def test_multiline_memory_is_rejected(self):
        state = self.open_session()
        response = self.client.post(
            f"/api/sessions/{state['session_id']}/memory",
            json={"information": "line one\nline two"},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
