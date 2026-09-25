"""Identity and authorization boundary.

Two providers behind one interface:

- LocalIdentity — the labelled local-first mode. Every request is the
  single local owner; no login, no credentials, unchanged offline UX.
  This is the default and what tests/CI exercise.
- JwtIdentity — production mode. Verifies a standards-based Bearer JWT
  from a managed provider (Supabase Auth, or any OIDC issuer) using a
  shared secret (HS256) or a JWKS endpoint (RS256/ES256). No password
  handling, no credential storage, no homemade auth.

Fail-closed rule: when the deployment declares production
(AGENTIC_OS_ENV=production) or demands auth (AGENTIC_OS_REQUIRE_AUTH=1)
and no provider is configured, app startup raises instead of silently
serving everything as the local owner.
"""

import os
import time
from dataclasses import dataclass

# Role -> permission set. Checked server-side on every action; the UI is
# never the enforcement point.
PERMISSIONS = {
    "owner": {"read", "write", "approve", "admin"},
    "admin": {"read", "write", "approve", "admin"},
    "analyst": {"read", "write", "approve"},
    "viewer": {"read"},
    "auditor": {"read"},
}
ROLES = tuple(PERMISSIONS)

# Least privilege: an authenticated user whose token carries no role
# claim gets read-only access until an operator grants more.
DEFAULT_ROLE = "viewer"

ROLE_CLAIMS = ("agentic_os_role", "role", "user_role")


class AuthNotConfigured(RuntimeError):
    """Raised at startup when production is declared without a provider."""


class AuthError(Exception):
    """Invalid or missing credentials (mapped to 401 by the API layer)."""


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    provider: str
    email: str = ""

    def can(self, permission):
        return permission in PERMISSIONS.get(self.role, frozenset())

    def as_dict(self):
        return {
            "subject": self.subject,
            "role": self.role,
            "provider": self.provider,
            "email": self.email,
            "permissions": sorted(PERMISSIONS.get(self.role, frozenset())),
        }


LOCAL_PRINCIPAL = Principal(subject="local-owner", role="owner", provider="local")


class LocalIdentity:
    mode = "local"
    requires_token = False

    def authenticate(self, authorization_header):
        return LOCAL_PRINCIPAL


class JwtIdentity:
    mode = "jwt"
    requires_token = True

    def __init__(self, secret=None, jwks_url=None, audience=None, issuer=None,
                 default_role=DEFAULT_ROLE):
        if not secret and not jwks_url:
            raise AuthNotConfigured("JwtIdentity needs a secret or a JWKS URL.")
        self.secret = secret
        self.jwks_url = jwks_url
        self.audience = audience
        self.issuer = issuer
        self.default_role = default_role if default_role in PERMISSIONS else DEFAULT_ROLE
        self._jwks_client = None

    def _decode(self, token):
        import jwt  # lazy: only hosted mode needs the dependency

        options = {"require": ["exp", "sub"], "verify_aud": bool(self.audience)}
        common = {
            "audience": self.audience,
            "issuer": self.issuer,
            "options": options,
            "leeway": 10,
        }
        if self.jwks_url:
            if self._jwks_client is None:
                self._jwks_client = jwt.PyJWKClient(self.jwks_url, cache_keys=True)
            key = self._jwks_client.get_signing_key_from_jwt(token).key
            # Asymmetric only: an attacker cannot downgrade to HS256 and
            # sign with the public key.
            return jwt.decode(token, key, algorithms=["RS256", "ES256"], **common)
        # Shared-secret mode pins HS256, so "alg": "none" and asymmetric
        # confusion attacks are rejected before signature checking.
        return jwt.decode(token, self.secret, algorithms=["HS256"], **common)

    def authenticate(self, authorization_header):
        import jwt

        if not authorization_header:
            raise AuthError("Authentication required.")
        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthError("Expected an Authorization: Bearer <token> header.")
        try:
            claims = self._decode(token.strip())
        except jwt.ExpiredSignatureError:
            raise AuthError("The session token has expired. Sign in again.")
        except Exception:
            # Never echo library internals or token content back to a client.
            raise AuthError("The session token is not valid.")
        return self._principal_from(claims)

    def _principal_from(self, claims):
        role = None
        for source in (claims, claims.get("app_metadata") or {},
                       claims.get("user_metadata") or {}):
            if not isinstance(source, dict):
                continue
            for claim in ROLE_CLAIMS:
                candidate = source.get(claim)
                if isinstance(candidate, str) and candidate in PERMISSIONS:
                    role = candidate
                    break
            if role:
                break
        return Principal(
            subject=str(claims["sub"]),
            role=role or self.default_role,
            provider="jwt",
            email=str(claims.get("email") or ""),
        )


def public_auth_config(identity, env=None):
    """Non-secret configuration the browser needs to start a sign-in.

    The publishable ("anon") key is designed to be public; the JWT
    secret, service-role key and database URL are never included."""
    env = os.environ if env is None else env
    if identity.mode == "local":
        return {"mode": "local", "flows": []}
    provider_url = (env.get("SUPABASE_URL") or "").rstrip("/")
    publishable_key = (
        env.get("SUPABASE_PUBLISHABLE_KEY") or env.get("SUPABASE_ANON_KEY") or ""
    )
    flows = []
    if provider_url and publishable_key:
        flows = ["password", "magic_link"]
    return {
        "mode": "jwt",
        "provider": "supabase" if provider_url else "custom",
        "provider_url": provider_url,
        "publishable_key": publishable_key,
        "flows": flows,
    }


def build_identity(env=None):
    """Select the provider from the environment, failing closed."""
    env = os.environ if env is None else env
    secret = env.get("AGENTIC_OS_JWT_SECRET") or env.get("SUPABASE_JWT_SECRET")
    jwks_url = env.get("AGENTIC_OS_JWKS_URL")
    if secret or jwks_url:
        return JwtIdentity(
            secret=secret,
            jwks_url=jwks_url,
            audience=env.get("AGENTIC_OS_JWT_AUDIENCE"),
            issuer=env.get("AGENTIC_OS_JWT_ISSUER"),
            default_role=env.get("AGENTIC_OS_DEFAULT_ROLE", DEFAULT_ROLE),
        )
    production = env.get("AGENTIC_OS_ENV", "").lower() == "production"
    if production or env.get("AGENTIC_OS_REQUIRE_AUTH") == "1":
        raise AuthNotConfigured(
            "Production mode requires a managed identity provider. Set "
            "AGENTIC_OS_JWT_SECRET (or SUPABASE_JWT_SECRET) for shared-secret "
            "tokens, or AGENTIC_OS_JWKS_URL for OIDC/JWKS verification."
        )
    return LocalIdentity()


def issue_local_test_token(secret, subject, role=None, audience=None,
                           issuer=None, expires_in=3600, algorithm="HS256"):
    """Helper used by the test suite only — never called by the server."""
    import jwt

    claims = {"sub": subject, "exp": int(time.time()) + expires_in}
    if role:
        claims["agentic_os_role"] = role
    if audience:
        claims["aud"] = audience
    if issuer:
        claims["iss"] = issuer
    return jwt.encode(claims, secret, algorithm=algorithm)
