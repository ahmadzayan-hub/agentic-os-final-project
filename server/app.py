"""FastAPI adapter that exposes the existing Agent class as a web API.

This layer contains no business logic. Every operation is mapped onto the
Agent's already-tested command surface (/remember, /forget, /set, /clear)
or reads the Agent's public state, and responses return fresh state
snapshots so the frontend never has to parse reply strings.

The command-line application (python main.py) is unaffected by this module.
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import Agent
from server.model_gateway import ModelGateway
from server.routing import RoutedGateway, build_router
from server.runs import RunEngine
from server.auth import AuthError, build_identity, public_auth_config
from server.quota import QuotaExceeded, load_limits
from server.quota import usage as quota_usage
from server.rate_limit import WRITE_METHODS, RateLimiter
from server.storage import DbMemoryBackend, PostgresStore, open_store
from utils import load_config

MAX_SESSIONS = 32
MAX_TEXT_LENGTH = 4000
PREFERENCE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# Presentation metadata for the Agent's command surface, used by the UI for
# quick actions and the command palette. Behaviour lives in agent.py only.
COMMANDS = [
    {"command": "/help", "usage": "/help", "description": "Show available commands"},
    {"command": "/remember", "usage": "/remember <information>", "description": "Save information to memory"},
    {"command": "/recall", "usage": "/recall", "description": "Show saved memory"},
    {"command": "/forget", "usage": "/forget <key> | all", "description": "Remove saved memory"},
    {"command": "/set", "usage": "/set <setting> <value>", "description": "Update a preference"},
    {"command": "/preferences", "usage": "/preferences", "description": "Show current preferences"},
    {"command": "/history", "usage": "/history", "description": "Show conversation history"},
    {"command": "/clear", "usage": "/clear", "description": "Clear conversation history"},
    {"command": "/exit", "usage": "/exit", "description": "End the session"},
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Session:
    """One conversation: an Agent instance plus its visible transcript.

    Sessions are durable: every mutation is written back to the store, so
    conversations survive an application restart in both SQLite and
    hosted-PostgreSQL modes."""

    def __init__(self, config, memory_backend=None, row=None, owner="local-owner"):
        self.agent = Agent(config, memory_backend=memory_backend)
        self.owner = (row or {}).get("owner") or owner
        if row is None:
            self.id = uuid.uuid4().hex
            self.transcript = []
            self.ended = False
            self.created_at = now_iso()
            self._next_entry_id = 1
        else:
            self.id = row["id"]
            self.created_at = row["created_at"]
            self.ended = bool(row["ended"])
            self.transcript = json.loads(row["transcript_json"])
            self._next_entry_id = row["next_entry_id"]
            self.agent.preferences.update(json.loads(row["preferences_json"]))
            self.agent.history = json.loads(row["history_json"])

    def to_row(self):
        return {
            "id": self.id,
            "owner": self.owner,
            "created_at": self.created_at,
            "updated_at": now_iso(),
            "ended": 1 if self.ended else 0,
            "preferences_json": json.dumps(self.agent.preferences),
            "history_json": json.dumps(self.agent.history),
            "transcript_json": json.dumps(self.transcript),
            "next_entry_id": self._next_entry_id,
        }

    def add_entry(self, role, text):
        entry = {
            "id": self._next_entry_id,
            "role": role,
            "text": text,
            "time": now_iso(),
        }
        self._next_entry_id += 1
        self.transcript.append(entry)
        return entry

    def snapshot(self):
        return {
            "session_id": self.id,
            "agent_name": self.agent.name,
            "version": self.agent.version,
            "welcome": self.agent.get_welcome_message(),
            "ended": self.ended,
            "created_at": self.created_at,
            "transcript": self.transcript,
            "preferences": dict(self.agent.preferences),
            "memory": dict(self.agent.memory),
            "memory_entries": self.agent.memory_entries(),
            "history": list(self.agent.history),
            "memory_persisted": self.agent.memory_persistent,
            "commands": COMMANDS,
        }


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)


class MemoryIn(BaseModel):
    information: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    category: str | None = Field(default=None, max_length=24)


class PreferenceIn(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=200)


class RunIn(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    dataset_text: str | None = Field(default=None, max_length=2_100_000)
    dataset_id: str | None = Field(default=None, max_length=32)
    dataset_name: str | None = Field(default=None, max_length=100)


class ApprovalIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(config_path=None, env=None):
    config = load_config(config_path or PROJECT_ROOT / "config.json")
    # Fails closed: declaring production without a managed identity
    # provider raises here rather than serving data unauthenticated.
    identity = build_identity(env)
    app = FastAPI(
        title=config.get("agent_name", "Agentic OS"),
        version=str(config.get("version", "1.0.0")),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    lock = threading.Lock()

    gateway = ModelGateway()
    # Optional: something that chooses which model narrates each report
    # (ADR 0017). Absent — the default, and always in tests and CI — this
    # wraps nothing and changes nothing.
    router, router_name, router_problem = build_router(env, config)
    if router is not None:
        gateway = RoutedGateway(gateway, router, router_name)
    app.state.router_problem = router_problem
    # Hosted PostgreSQL (DATABASE_URL / config "database_url") when
    # configured; local SQLite otherwise. See docs/adr/0001-database.md.
    store = open_store(
        os.environ.get("DATABASE_URL") or config.get("database_url"),
        config.get("database_file") or PROJECT_ROOT / "data" / "agentic.db",
    )
    limits = load_limits(env)
    engine = RunEngine(
        store,
        config.get("vault_dir") or PROJECT_ROOT / "vault",
        gateway,
        limits=limits,
    )
    app.state.engine = engine
    app.state.store = store
    # Where memory lives, and whose it is.
    #
    # Local mode is one person on one machine, and keeps the documented
    # data/memory.json contract. The moment an identity provider is
    # configured the install is multi-tenant, and memory has to be
    # scoped like sessions and runs are — otherwise one tenant reads and
    # overwrites another's, which is what happened until ADR 0014. That
    # is a property of authentication, not of the database: a small
    # deployment with JWTs and SQLite is just as multi-tenant as one
    # with PostgreSQL, and used to share one memory file between
    # everybody.
    # Two independent reasons to keep memory in the database, and either
    # is enough: a PostgreSQL store means the backend must not depend on
    # local files (a serverless filesystem is read-only, ADR 0001), and
    # an identity provider means more than one owner exists. With a
    # single owner the scoping is a no-op; with several it is the whole
    # point.
    multi_tenant = identity.mode != "local"
    memory_in_database = multi_tenant or isinstance(store, PostgresStore)

    def memory_for(owner):
        if not memory_in_database:
            return None  # the Agent's own data/memory.json backend
        return DbMemoryBackend(store, owner or "local-owner")

    allowed_origins = [
        origin.strip()
        for origin in os.environ.get(
            "AGENTIC_OS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    environ = os.environ if env is None else env
    # The default must exceed the application's own legitimate write
    # cadence: a client-stepped analytics run issues ~3 advance calls per
    # second, so a 120/min budget (2/s) would throttle a normal run.
    # 600/min leaves headroom while still stopping runaway loops.
    limiter = RateLimiter(
        limit=int(environ.get("AGENTIC_OS_RATE_LIMIT", "600")),
        window_seconds=int(environ.get("AGENTIC_OS_RATE_WINDOW", "60")),
    )

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.method in WRITE_METHODS and request.url.path.startswith("/api/"):
            # Key on the caller: the token subject when present, the
            # client address otherwise. Tokens are never used as keys.
            header = request.headers.get("authorization")
            try:
                key = identity.authenticate(header).subject
            except AuthError:
                key = request.client.host if request.client else "anonymous"
            allowed, remaining, retry_after = limiter.check(key)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please slow down."},
                    headers={"Retry-After": str(retry_after)},
                )
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path.startswith("/api/"):
            # Session, memory, and export payloads are private.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        # Never leak stack traces or internal details to the browser.
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong on the server. Please try again."},
        )

    # ------------------------------------------------------------------
    # Identity and authorization
    # ------------------------------------------------------------------
    def current_principal(authorization: str = Header(default=None)):
        try:
            return identity.authenticate(authorization)
        except AuthError as error:
            raise HTTPException(status_code=401, detail=str(error))

    def requires(permission):
        def dependency(principal=Depends(current_principal)):
            if not principal.can(permission):
                raise HTTPException(
                    status_code=403,
                    detail=f"Your role ({principal.role}) cannot {permission} here.",
                )
            return principal
        return dependency

    def owns(principal, owner):
        """Objects belong to their creator; admins may act across owners."""
        return owner == principal.subject or principal.can("admin")

    @app.get("/api/auth/config")
    def auth_config():
        """Public: the browser needs this before it can sign in. Contains
        no secret — only the mode and the provider's publishable key."""
        return public_auth_config(identity, env)

    @app.get("/api/identity")
    def whoami(principal=Depends(current_principal)):
        return {"mode": identity.mode, "principal": principal.as_dict()}

    def get_session(session_id, principal=None):
        row = store.get_session(session_id)
        if row is None or (principal is not None
                           and not owns(principal, row.get("owner") or "local-owner")):
            # Same response for missing and forbidden: no existence oracle.
            raise HTTPException(
                status_code=404,
                detail="Session not found. It may have expired — start a new session.",
            )
        return Session(config,
                       memory_for(row.get("owner") or "local-owner"),
                       row=row)

    def save_session(session):
        store.upsert_session(session.to_row())

    def clean_single_line(value, field_name):
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} must be a single non-empty line.",
            )
        return value

    # ------------------------------------------------------------------
    # Health and sessions
    # ------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "agent_name": config.get("agent_name", "Agentic OS"),
            "version": str(config.get("version", "1.0.0")),
            "model_provider": gateway.status(),
            # A misconfigured router is the operator's to fix, and they
            # will not find it unless something says so.
            "router_problem": app.state.router_problem,
        }

    @app.post("/api/sessions", status_code=201)
    def create_session(principal=Depends(requires("write"))):
        with lock:
            session = Session(config, memory_for(principal.subject),
                              owner=principal.subject)
            save_session(session)
            store.trim_sessions(MAX_SESSIONS)
            return session.snapshot()

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str, principal=Depends(requires("read"))):
        with lock:
            return get_session(session_id, principal).snapshot()

    @app.delete("/api/sessions/{session_id}")
    def end_session(session_id: str, principal=Depends(requires("write"))):
        with lock:
            session = get_session(session_id, principal)
            session.ended = True
            reply = session.agent.process_input("/exit")
            session.add_entry("agent", reply)
            save_session(session)
            return session.snapshot()

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------
    @app.post("/api/sessions/{session_id}/messages")
    def send_message(session_id: str, message: MessageIn, principal=Depends(requires("write"))):
        text = message.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Message text is empty.")
        with lock:
            session = get_session(session_id, principal)
            if session.ended:
                raise HTTPException(
                    status_code=409,
                    detail="This session has ended. Start a new session to continue.",
                )
            session.add_entry("user", text)
            reply = session.agent.process_input(text)
            entry = session.add_entry("agent", reply)
            if text.split()[0].lower() == "/exit":
                session.ended = True
            save_session(session)
            return {"reply": entry, "state": session.snapshot()}

    @app.delete("/api/sessions/{session_id}/history")
    def clear_history(session_id: str, principal=Depends(requires("write"))):
        with lock:
            session = get_session(session_id, principal)
            session.agent.history.clear()
            save_session(session)
            return {
                "reply_text": "Conversation history cleared.",
                "state": session.snapshot(),
            }

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    @app.put("/api/sessions/{session_id}/preferences")
    def update_preference(session_id: str, preference: PreferenceIn, principal=Depends(requires("write"))):
        key = preference.key.strip().lower()
        if not PREFERENCE_KEY_PATTERN.match(key):
            raise HTTPException(
                status_code=422,
                detail="Preference names may use lowercase letters, digits, and underscores.",
            )
        value = clean_single_line(preference.value, "Preference value")
        with lock:
            session = get_session(session_id, principal)
            reply = session.agent.set_preference(key, value)
            save_session(session)
            return {"reply_text": reply, "state": session.snapshot()}

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------
    @app.post("/api/sessions/{session_id}/memory", status_code=201)
    def add_memory(session_id: str, memory: MemoryIn, principal=Depends(requires("write"))):
        information = clean_single_line(memory.information, "Memory text")
        with lock:
            session = get_session(session_id, principal)
            # Reload the shared file first so a concurrent session's saves
            # are never overwritten (lost-update prevention).
            session.agent.reload_memory()
            reply = session.agent.add_memory(information, memory.category)
            save_session(session)
            return {"reply_text": reply, "state": session.snapshot()}

    @app.put("/api/sessions/{session_id}/memory/{key}")
    def update_memory(session_id: str, key: str, memory: MemoryIn, principal=Depends(requires("write"))):
        information = clean_single_line(memory.information, "Memory text")
        with lock:
            session = get_session(session_id, principal)
            session.agent.reload_memory()
            if key not in session.agent.memory:
                raise HTTPException(status_code=404, detail=f"No memory named {key}.")
            reply = session.agent.update_memory(key, information, memory.category)
            save_session(session)
            return {"reply_text": reply, "state": session.snapshot()}

    @app.get("/api/sessions/{session_id}/export")
    def export_data(session_id: str, principal=Depends(requires("read"))):
        with lock:
            session = get_session(session_id, principal)
            return JSONResponse(
                content={
                    "exported_at": now_iso(),
                    "agent_name": session.agent.name,
                    "preferences": dict(session.agent.preferences),
                    "memory": dict(session.agent.memory),
                    "memory_entries": session.agent.memory_entries(),
                    "history": list(session.agent.history),
                    "transcript": session.transcript,
                },
                headers={
                    "Content-Disposition": 'attachment; filename="agentic-os-export.json"'
                },
            )

    @app.delete("/api/sessions/{session_id}/memory/{key}")
    def delete_memory(session_id: str, key: str, principal=Depends(requires("write"))):
        with lock:
            session = get_session(session_id, principal)
            session.agent.reload_memory()
            if key not in session.agent.memory:
                raise HTTPException(status_code=404, detail=f"No memory named {key}.")
            reply = session.agent.remove_memory(key)
            save_session(session)
            return {"reply_text": reply, "state": session.snapshot()}

    @app.delete("/api/sessions/{session_id}/memory")
    def clear_memory(session_id: str, principal=Depends(requires("write"))):
        with lock:
            session = get_session(session_id, principal)
            session.agent.reload_memory()
            reply = session.agent.clear_all_memory()
            save_session(session)
            return {"reply_text": reply, "state": session.snapshot()}

    # ------------------------------------------------------------------
    # Vault: durable record of approved, published knowledge
    # ------------------------------------------------------------------
    @app.get("/api/vault")
    def list_vault_notes(principal=Depends(requires("read"))):
        with lock:
            return {"notes": store.list_notes()}

    @app.get("/api/vault/note")
    def get_vault_note(path: str, principal=Depends(requires("read"))):
        with lock:
            note = store.get_note(path)
            if note is None:
                raise HTTPException(status_code=404, detail="Note not found.")
            return note

    # ------------------------------------------------------------------
    # Runs: goal -> plan -> tasks -> approval -> artifact
    # ------------------------------------------------------------------
    def _run_or_404(action, principal=None, run_id=None):
        try:
            if principal is not None and run_id is not None:
                # Ownership is checked before any state change, and a run
                # owned by someone else is indistinguishable from missing.
                if not owns(principal, engine.owner_of(run_id)):
                    raise KeyError(run_id)
            return action()
        except KeyError:
            raise HTTPException(status_code=404, detail="Run not found.")
        except QuotaExceeded as error:
            raise HTTPException(status_code=429, detail=error.message)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))

    @app.post("/api/runs", status_code=201)
    def create_run(run: RunIn, principal=Depends(requires("write"))):
        with lock:
            try:
                return engine.create_run(run.goal, run.dataset_text,
                                         run.dataset_name,
                                         owner=principal.subject,
                                         dataset_id=run.dataset_id)
            except KeyError:
                raise HTTPException(status_code=404, detail='Dataset not found.')
            except QuotaExceeded as error:
                # 429: the request is well formed and the caller is
                # entitled to make it — just not right now, or not this
                # much. The message says which and when it clears.
                raise HTTPException(status_code=429, detail=error.message)

    @app.get("/api/usage")
    def read_usage(principal=Depends(requires("read"))):
        with lock:
            return quota_usage(store, principal.subject, limits)

    @app.get("/api/datasets")
    def list_datasets(principal=Depends(requires("read"))):
        with lock:
            return {"datasets": store.list_datasets(principal.subject)}

    @app.get("/api/runs")
    def list_runs(principal=Depends(requires("read"))):
        with lock:
            owner = None if principal.can("admin") else principal.subject
            return {"runs": engine.list_runs(owner=owner)}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, principal=Depends(requires("read"))):
        with lock:
            return _run_or_404(lambda: engine.get_run(run_id), principal, run_id)

    @app.post("/api/runs/{run_id}/advance")
    def advance_run(run_id: str, principal=Depends(requires("write"))):
        with lock:
            return _run_or_404(lambda: engine.advance(run_id), principal, run_id)

    @app.post("/api/runs/{run_id}/pause")
    def pause_run(run_id: str, principal=Depends(requires("write"))):
        with lock:
            return _run_or_404(lambda: engine.set_paused(run_id, True),
                               principal, run_id)

    @app.post("/api/runs/{run_id}/resume")
    def resume_run(run_id: str, principal=Depends(requires("write"))):
        with lock:
            return _run_or_404(lambda: engine.set_paused(run_id, False),
                               principal, run_id)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str, principal=Depends(requires("write"))):
        with lock:
            return _run_or_404(lambda: engine.cancel(run_id), principal, run_id)

    @app.post("/api/runs/{run_id}/approvals/{approval_id}")
    def decide_approval(run_id: str, approval_id: str, decision: ApprovalIn, principal=Depends(requires("approve"))):
        with lock:
            return _run_or_404(
                lambda: engine.decide_approval(run_id, approval_id, decision.decision),
                principal, run_id,
            )

    # ------------------------------------------------------------------
    # Static frontend (production build), if present
    # ------------------------------------------------------------------
    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = (dist / full_path).resolve()
            # Serve real files inside dist; anything else falls back to the
            # SPA entry point. Path-aware containment (is_relative_to on the
            # resolved path) blocks traversal — a string prefix check would
            # not, e.g. a sibling directory named "dist-evil".
            if (
                full_path
                and candidate.is_relative_to(dist.resolve())
                and candidate.is_file()
            ):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


# AGENTIC_OS_CONFIG lets tests and tools point the server at an alternative
# configuration file (and therefore an alternative memory file).
app = create_app(os.environ.get("AGENTIC_OS_CONFIG"))
