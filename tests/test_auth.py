"""Identity, authorization, and tenant-isolation tests.

Covers the happy path plus the attacks the threat model names: forged
signatures, expired tokens, algorithm confusion ("alg": "none"), audience
mismatch, role escalation, and cross-tenant access.
"""

import json
import tempfile
import unittest
from pathlib import Path

try:
    import jwt  # noqa: F401
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.auth import (
        AuthNotConfigured,
        JwtIdentity,
        build_identity,
        issue_local_test_token,
    )
    DEPS_AVAILABLE = True
except ImportError:  # pragma: no cover - CLI-only environments
    DEPS_AVAILABLE = False

SECRET = "test-signing-secret-not-a-real-credential"
AUDIENCE = "agentic-os-test"


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/pyjwt are not installed")
class IdentitySelectionTestCase(unittest.TestCase):
    def test_local_mode_is_the_default(self):
        identity = build_identity({})
        self.assertEqual(identity.mode, "local")
        self.assertEqual(identity.authenticate(None).role, "owner")

    def test_production_without_a_provider_fails_closed(self):
        with self.assertRaises(AuthNotConfigured):
            build_identity({"AGENTIC_OS_ENV": "production"})
        with self.assertRaises(AuthNotConfigured):
            build_identity({"AGENTIC_OS_REQUIRE_AUTH": "1"})

    def test_production_with_a_secret_selects_jwt_mode(self):
        identity = build_identity(
            {"AGENTIC_OS_ENV": "production", "AGENTIC_OS_JWT_SECRET": SECRET})
        self.assertEqual(identity.mode, "jwt")

    def test_supabase_secret_variable_is_honored(self):
        self.assertEqual(
            build_identity({"SUPABASE_JWT_SECRET": SECRET}).mode, "jwt")


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/pyjwt are not installed")
class TokenVerificationTestCase(unittest.TestCase):
    def setUp(self):
        self.identity = JwtIdentity(secret=SECRET, audience=AUDIENCE)

    def header(self, **kwargs):
        kwargs.setdefault("audience", AUDIENCE)
        return "Bearer " + issue_local_test_token(SECRET, **kwargs)

    def assert_rejected(self, header):
        from server.auth import AuthError

        with self.assertRaises(AuthError):
            self.identity.authenticate(header)

    def test_valid_token_yields_the_claimed_role(self):
        principal = self.identity.authenticate(
            self.header(subject="user-1", role="analyst"))
        self.assertEqual(principal.subject, "user-1")
        self.assertEqual(principal.role, "analyst")
        self.assertTrue(principal.can("write"))
        self.assertFalse(principal.can("admin"))

    def test_token_without_a_role_claim_gets_least_privilege(self):
        principal = self.identity.authenticate(self.header(subject="user-2"))
        self.assertEqual(principal.role, "viewer")
        self.assertFalse(principal.can("write"))

    def test_unknown_role_claim_is_not_trusted(self):
        token = issue_local_test_token(SECRET, subject="u", audience=AUDIENCE)
        import jwt as pyjwt

        forged = pyjwt.encode(
            {**pyjwt.decode(token, SECRET, algorithms=["HS256"],
                            audience=AUDIENCE),
             "agentic_os_role": "superuser"},
            SECRET, algorithm="HS256")
        principal = self.identity.authenticate("Bearer " + forged)
        self.assertEqual(principal.role, "viewer")

    def test_missing_header_is_rejected(self):
        self.assert_rejected(None)
        self.assert_rejected("")

    def test_non_bearer_scheme_is_rejected(self):
        self.assert_rejected("Basic dXNlcjpwYXNz")

    def test_forged_signature_is_rejected(self):
        self.assert_rejected(
            "Bearer " + issue_local_test_token(
                "attacker-secret", subject="mallory", audience=AUDIENCE))

    def test_expired_token_is_rejected(self):
        self.assert_rejected(
            self.header(subject="user-3", expires_in=-3600))

    def test_alg_none_token_is_rejected(self):
        import jwt as pyjwt

        unsigned = pyjwt.encode(
            {"sub": "mallory", "exp": 9999999999, "aud": AUDIENCE},
            key="", algorithm="none")
        self.assert_rejected("Bearer " + unsigned)

    def test_wrong_audience_is_rejected(self):
        self.assert_rejected(
            "Bearer " + issue_local_test_token(
                SECRET, subject="user-4", audience="some-other-app"))

    def test_error_messages_never_leak_the_token(self):
        from server.auth import AuthError

        token = issue_local_test_token("attacker-secret", subject="mallory")
        try:
            self.identity.authenticate("Bearer " + token)
        except AuthError as error:
            self.assertNotIn(token, str(error))
        else:  # pragma: no cover
            self.fail("expected AuthError")


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/pyjwt are not installed")
class ApiAuthorizationTestCase(unittest.TestCase):
    """Role and ownership enforcement against the real API surface."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.config_path = root / "config.json"
        self.config_path.write_text(json.dumps({
            "agent_name": "Auth Test Agent",
            "memory_file": str(root / "memory.json"),
            "database_file": str(root / "agentic.db"),
            "vault_dir": str(root / "vault"),
        }), encoding="utf-8")
        self.client = TestClient(
            create_app(self.config_path,
                       env={"AGENTIC_OS_JWT_SECRET": SECRET,
                            "AGENTIC_OS_ENV": "production"}),
            raise_server_exceptions=False)

    def auth(self, subject, role):
        return {"Authorization": "Bearer " + issue_local_test_token(
            SECRET, subject=subject, role=role)}

    def test_unauthenticated_requests_are_rejected(self):
        self.assertEqual(self.client.post("/api/sessions").status_code, 401)
        self.assertEqual(self.client.get("/api/runs").status_code, 401)
        self.assertEqual(self.client.get("/api/vault").status_code, 401)

    def test_health_stays_public_for_load_balancers(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_identity_endpoint_reports_role_and_permissions(self):
        body = self.client.get("/api/identity",
                               headers=self.auth("u1", "analyst")).json()
        self.assertEqual(body["mode"], "jwt")
        self.assertEqual(body["principal"]["role"], "analyst")
        self.assertIn("write", body["principal"]["permissions"])

    def test_viewer_can_read_but_not_write(self):
        owner = self.auth("owner-1", "owner")
        session = self.client.post("/api/sessions", headers=owner).json()
        viewer = self.auth("viewer-1", "viewer")
        # Writes are refused by role before ownership is even considered.
        self.assertEqual(
            self.client.post("/api/sessions", headers=viewer).status_code, 403)
        self.assertEqual(
            self.client.post(f"/api/sessions/{session['session_id']}/messages",
                             json={"text": "hi"}, headers=viewer).status_code, 403)
        # Reads are allowed by role, then filtered by ownership.
        self.assertEqual(self.client.get("/api/runs", headers=viewer).status_code, 200)

    def test_auditor_cannot_approve_a_publish(self):
        owner = self.auth("owner-2", "owner")
        run = self.client.post("/api/runs", json={"goal": "Audit test run"},
                               headers=owner).json()
        response = self.client.post(
            f"/api/runs/{run['id']}/approvals/anything",
            json={"decision": "approve"}, headers=self.auth("aud-1", "auditor"))
        self.assertEqual(response.status_code, 403)

    def test_sessions_are_isolated_between_users(self):
        alice = self.auth("alice", "analyst")
        bob = self.auth("bob", "analyst")
        session = self.client.post("/api/sessions", headers=alice).json()
        sid = session["session_id"]
        self.assertEqual(self.client.get(f"/api/sessions/{sid}",
                                         headers=alice).status_code, 200)
        # Bob may not read, write to, or destroy Alice's session.
        self.assertEqual(self.client.get(f"/api/sessions/{sid}",
                                         headers=bob).status_code, 404)
        self.assertEqual(
            self.client.post(f"/api/sessions/{sid}/messages",
                             json={"text": "peek"}, headers=bob).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/sessions/{sid}/memory",
                                            headers=bob).status_code, 404)

    def test_runs_are_isolated_between_users(self):
        alice = self.auth("alice", "analyst")
        bob = self.auth("bob", "analyst")
        run = self.client.post("/api/runs", json={"goal": "Alice's private run"},
                               headers=alice).json()
        listing = self.client.get("/api/runs", headers=bob).json()["runs"]
        self.assertEqual(listing, [])
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}",
                                         headers=bob).status_code, 404)
        self.assertEqual(self.client.post(f"/api/runs/{run['id']}/advance",
                                          headers=bob).status_code, 404)
        self.assertEqual(self.client.post(f"/api/runs/{run['id']}/cancel",
                                          headers=bob).status_code, 404)
        # The owner is unaffected by the failed attempts.
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}",
                                         headers=alice).json()["state"], "queued")

    def test_admins_may_act_across_owners(self):
        alice = self.auth("alice", "analyst")
        run = self.client.post("/api/runs", json={"goal": "Shared run"},
                               headers=alice).json()
        admin = self.auth("root", "admin")
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}",
                                         headers=admin).status_code, 200)
        self.assertEqual(len(self.client.get("/api/runs",
                                             headers=admin).json()["runs"]), 1)


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/pyjwt are not installed")
class AuthConfigTestCase(unittest.TestCase):
    """The public sign-in configuration must never carry a secret."""

    def build(self, env):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        config_path = root / "config.json"
        config_path.write_text(json.dumps({
            "agent_name": "Config Test",
            "memory_file": str(root / "memory.json"),
            "database_file": str(root / "agentic.db"),
            "vault_dir": str(root / "vault"),
        }), encoding="utf-8")
        return TestClient(create_app(config_path, env=env),
                          raise_server_exceptions=False)

    def test_local_mode_advertises_no_sign_in(self):
        body = self.build({}).get("/api/auth/config").json()
        self.assertEqual(body["mode"], "local")
        self.assertEqual(body["flows"], [])

    def test_hosted_mode_advertises_publishable_config_only(self):
        client = self.build({
            "AGENTIC_OS_JWT_SECRET": SECRET,
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "publishable-anon-key",
        })
        response = client.get("/api/auth/config")
        body = response.json()
        self.assertEqual(body["mode"], "jwt")
        self.assertEqual(body["provider"], "supabase")
        self.assertEqual(body["publishable_key"], "publishable-anon-key")
        self.assertIn("password", body["flows"])
        # The signing secret must never appear in a public response.
        self.assertNotIn(SECRET, response.text)

    def test_config_is_reachable_without_a_token(self):
        client = self.build({"AGENTIC_OS_JWT_SECRET": SECRET,
                             "AGENTIC_OS_ENV": "production"})
        self.assertEqual(client.get("/api/auth/config").status_code, 200)

    def test_hosted_mode_without_provider_urls_offers_no_flows(self):
        body = self.build({"AGENTIC_OS_JWT_SECRET": SECRET}).get(
            "/api/auth/config").json()
        self.assertEqual(body["flows"], [])


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/pyjwt are not installed")
class RateLimitTestCase(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        config_path = root / "config.json"
        config_path.write_text(json.dumps({
            "agent_name": "Rate Test",
            "memory_file": str(root / "memory.json"),
            "database_file": str(root / "agentic.db"),
            "vault_dir": str(root / "vault"),
        }), encoding="utf-8")
        self.client = TestClient(
            create_app(config_path,
                       env={"AGENTIC_OS_RATE_LIMIT": "3",
                            "AGENTIC_OS_RATE_WINDOW": "60"}),
            raise_server_exceptions=False)

    def test_writes_are_limited_and_report_retry_after(self):
        statuses = [self.client.post("/api/sessions").status_code
                    for _ in range(5)]
        self.assertEqual(statuses[:3], [201, 201, 201])
        self.assertEqual(statuses[3], 429)
        response = self.client.post("/api/sessions")
        self.assertEqual(response.status_code, 429)
        self.assertTrue(int(response.headers["Retry-After"]) >= 1)
        self.assertNotIn("traceback", response.text.lower())

    def test_reads_are_not_limited(self):
        for _ in range(5):
            self.client.post("/api/sessions")
        for _ in range(10):
            self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_remaining_budget_is_reported(self):
        response = self.client.post("/api/sessions")
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "2")


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/pyjwt are not installed")
class RateLimiterUnitTestCase(unittest.TestCase):
    def test_budget_refills_over_time(self):
        from server.rate_limit import RateLimiter

        now = [0.0]
        limiter = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
        self.assertTrue(limiter.check("k")[0])
        self.assertTrue(limiter.check("k")[0])
        self.assertFalse(limiter.check("k")[0])
        now[0] += 31  # half a window restores one token
        self.assertTrue(limiter.check("k")[0])

    def test_callers_have_independent_budgets(self):
        from server.rate_limit import RateLimiter

        limiter = RateLimiter(limit=1, window_seconds=60)
        self.assertTrue(limiter.check("alice")[0])
        self.assertFalse(limiter.check("alice")[0])
        self.assertTrue(limiter.check("bob")[0])


if __name__ == "__main__":
    unittest.main()
