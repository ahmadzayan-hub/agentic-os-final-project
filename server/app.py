"""FastAPI adapter that exposes the existing Agent class as a web API.

This layer contains no business logic. Every operation is mapped onto the
Agent's already-tested command surface (/remember, /forget, /set, /clear)
or reads the Agent's public state, and responses return fresh state
snapshots so the frontend never has to parse reply strings.

The command-line application (python main.py) is unaffected by this module.
"""

import asyncio
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from agent import Agent, language_code
from server.agent_runtime import build_runtime
from server import analytics
from server import datasets as dataset_reader
from server import joins as joining
from server import live
from server import mapping as colmap
from server import query as table_query
from server.assistant import Assistant
from server.connectors import Busy, ConnectorError, Connectors, TooSoon
from server.model_gateway import ModelGateway
from server.routing import RoutedGateway, build_router
from server.stages import describe, load_stages
from server.runs import RunEngine, TableNotReady, dataset_summary
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

# The same commands, described in Arabic. A command's spelling is the
# same in either language — it is what the person types.
COMMANDS_ARABIC = [
    {"command": "/help", "usage": "/help", "description": "عرض الأوامر المتاحة"},
    {"command": "/remember", "usage": "/remember <information>", "description": "حفظ معلومة في الذاكرة"},
    {"command": "/recall", "usage": "/recall", "description": "عرض الذاكرة المحفوظة"},
    {"command": "/forget", "usage": "/forget <key> | all", "description": "إزالة ذاكرة محفوظة"},
    {"command": "/set", "usage": "/set <setting> <value>", "description": "تحديث تفضيل"},
    {"command": "/preferences", "usage": "/preferences", "description": "عرض التفضيلات الحالية"},
    {"command": "/history", "usage": "/history", "description": "عرض سجل المحادثة"},
    {"command": "/clear", "usage": "/clear", "description": "مسح سجل المحادثة"},
    {"command": "/exit", "usage": "/exit", "description": "إنهاء الجلسة"},
]


def commands_for(language):
    """The command catalogue in the language the session replies in."""
    return COMMANDS_ARABIC if language_code(language) == "ar" else COMMANDS


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

    def add_entry(self, role, text, **extra):
        """Append a turn. `extra` carries what the assistant knows about an
        agent reply — who understood it (rules, model, command), what it
        did, and a pending confirmation — so the transcript is the record
        and survives a restart with it."""
        entry = {
            "id": self._next_entry_id,
            "role": role,
            "text": text,
            "time": now_iso(),
        }
        entry.update({key: value for key, value in extra.items() if value is not None})
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
            "commands": commands_for(self.agent.preferences.get("language")),
        }


class SessionIn(BaseModel):
    """Optional at creation: the language the interface is showing, so the
    agent's first words are already in it."""
    language: str | None = Field(default=None, max_length=64)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)


class MemoryIn(BaseModel):
    information: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    category: str | None = Field(default=None, max_length=24)


class PreferenceIn(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=200)


class KeyPairIn(BaseModel):
    """One key of a join: a column of the table so far and the column of
    the joined dataset that holds the same values (ADR 0030)."""
    left: str = Field(min_length=1, max_length=200)
    right: str = Field(min_length=1, max_length=200)


class JoinIn(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=32)
    keys: list[KeyPairIn] = Field(min_length=1, max_length=joining.MAX_KEYS)
    how: str = Field(default="left", pattern="^(left|inner)$")
    alias: str | None = Field(default=None, max_length=24)


class JoinPreviewIn(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=32)
    joins: list[JoinIn] = Field(min_length=1, max_length=joining.MAX_JOINS)
    breakdown: str | None = Field(default=None, max_length=200)


class RunIn(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    profile: str | None = Field(default=None, max_length=64)
    # Pasted CSV. A file goes through POST /api/datasets (ADR 0024).
    dataset_text: str | None = Field(default=None, max_length=dataset_reader.MAX_UPLOAD_BYTES)
    dataset_id: str | None = Field(default=None, max_length=32)
    dataset_name: str | None = Field(default=None, max_length=100)
    # The language the report is written in (ADR 0022). The interface
    # sends the reader's language.
    language: str = Field(default="en", pattern="^(en|ar)$")
    # Other stored datasets joined onto this one, and an optional
    # breakdown from the merged table (ADR 0030).
    joins: list[JoinIn] | None = Field(default=None, max_length=joining.MAX_JOINS)
    breakdown: str | None = Field(default=None, max_length=200)


class MappingIn(BaseModel):
    """A column mapping (ADR 0025). Roles, orders and grains are checked
    by server.mapping, which explains a refusal in the reader's language."""
    roles: dict[str, str] = Field(default_factory=dict, max_length=500)
    measure: str | None = Field(default=None, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    date_order: str = Field(default="auto", max_length=20)
    grain: str = Field(default="auto", max_length=20)


class QueryIn(BaseModel):
    """Totals by group under filters (ADR 0031). The shapes are checked by
    server.query, which explains a refusal in the reader's language."""
    group_by: list = Field(default_factory=list, max_length=table_query.MAX_GROUP_BY)
    measures: list = Field(default_factory=list, max_length=table_query.MAX_MEASURES)
    filters: list = Field(default_factory=list, max_length=table_query.MAX_FILTERS)
    sort: dict | None = None
    limit: int = 100


class RecordsIn(BaseModel):
    filters: list = Field(default_factory=list, max_length=table_query.MAX_FILTERS)
    sort: dict | None = None
    offset: int = 0
    limit: int = 50
    sample: int | None = None


class ApprovalIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


class ConnectorIn(BaseModel):
    """A live source (ADR 0034). The address is checked by server.connectors,
    which explains a refusal in the reader's language."""
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000)
    goal: str = Field(min_length=1, max_length=500)
    format: str | None = Field(default=None, pattern="^(csv|tsv|xlsx|json|jsonl)$")
    sheet: str | None = Field(default=None, max_length=31)
    every_minutes: int | None = None
    language: str = Field(default="en", pattern="^(en|ar)$")
    profile: str | None = Field(default=None, max_length=64)


class ConnectorUpdateIn(BaseModel):
    """Pause or resume, or change the interval. An interval that is not
    sent is kept; `null` means "only when asked"."""
    enabled: bool | None = None
    every_minutes: int | None = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Vite names every file under /assets by a hash of its content, so a cached
# copy can never be stale. The page, the service worker and the manifest
# point at the current hashes, so the browser revalidates them each visit.
# vercel.json sets the same headers in production (ADR 0023, amendment).
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


class InterfaceGZip:
    """Compress the built interface, never the API.

    API responses can carry a token beside text the caller chose, which is
    the shape a compression side channel (BREACH) needs, and they are small
    JSON anyway. The interface is public, static and most of the bytes.
    """

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope["path"].startswith("/api/"):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def create_app(config_path=None, env=None, dist_dir=None):
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
    # Custom stages (ADR 0020). A stage that fails to load leaves the
    # pipeline as it was; the problem is reported, not raised.
    stage_registry, stage_problems = load_stages(env, config)
    app.state.stage_problems = stage_problems
    engine = RunEngine(
        store,
        config.get("vault_dir") or PROJECT_ROOT / "vault",
        gateway,
        limits=limits,
        stages=stage_registry,
        profiles=config.get("profiles") or {},
    )
    app.state.engine = engine
    app.state.store = store
    # Free text in the chat goes here; slash commands go to the Agent.
    # An agent runtime (ADR 0021) is optional and, like the router and
    # the stages, a load failure is reported rather than raised.
    runtime, runtime_name, runtime_problem = build_runtime(env, config)
    app.state.runtime_name = runtime_name
    app.state.runtime_problem = runtime_problem
    assistant = Assistant(gateway, engine, runtime=runtime, runtime_name=runtime_name)
    app.state.assistant = assistant
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
    # Live sources (ADR 0034). The fence reads its host list and the test
    # fixture folder from the same environment as everything else.
    connectors = Connectors(engine, env=environ)
    app.state.connectors = connectors
    # Open event streams per owner in this process (ADR 0034): each polls
    # the database every second, so one owner cannot open hundreds.
    open_streams = {}
    streams_lock = threading.Lock()
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
        path = request.url.path
        if path.startswith("/api/"):
            # Session, memory, and export payloads are private.
            response.headers.setdefault("Cache-Control", "no-store")
        elif path.startswith("/assets/") and response.status_code == 200:
            response.headers.setdefault("Cache-Control", IMMUTABLE)
        else:
            response.headers.setdefault("Cache-Control", REVALIDATE)
        return response

    app.add_middleware(InterfaceGZip)

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
            "stage_problems": app.state.stage_problems,
            "agent_runtime": app.state.runtime_name,
            "runtime_problem": app.state.runtime_problem,
        }

    @app.post("/api/sessions", status_code=201)
    def create_session(body: SessionIn | None = None,
                       principal=Depends(requires("write"))):
        with lock:
            session = Session(config, memory_for(principal.subject),
                              owner=principal.subject)
            if body is not None and body.language:
                session.agent.set_preference("language", body.language)
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
            if text.startswith("/"):
                # A command is exact and deterministic; it does not need
                # understanding.
                entry = session.add_entry("agent", session.agent.process_input(text),
                                          source="command", action="command")
            else:
                session.agent.record_request(text)
                outcome = assistant.handle(text, session)
                entry = session.add_entry(
                    "agent", outcome["text"], source=outcome.get("source"),
                    provider=outcome.get("provider"), action=outcome.get("action"),
                    result=outcome.get("result"), pending=outcome.get("pending"),
                    steps=outcome.get("steps"), why=outcome.get("why"))
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
                                         dataset_id=run.dataset_id,
                                         profile=run.profile,
                                         language=run.language,
                                         joins=([j.model_dump() for j in run.joins]
                                                if run.joins else None),
                                         breakdown=run.breakdown)
            except KeyError:
                raise HTTPException(status_code=404, detail='Dataset not found.')
            except joining.JoinError as error:
                raise HTTPException(status_code=422, detail=error.detail(run.language))
            except ValueError as error:
                # An unknown profile, or one naming an unregistered stage.
                raise HTTPException(status_code=422, detail=str(error))
            except QuotaExceeded as error:
                # 429: the request is well formed and the caller is
                # entitled to make it — just not right now, or not this
                # much. The message says which and when it clears.
                raise HTTPException(status_code=429, detail=error.message)

    @app.post("/api/joins/preview")
    async def preview_joins(body: JoinPreviewIn,
                            language: str = Query(default="en", pattern="^(en|ar)$"),
                            principal=Depends(requires("read"))):
        """What a run with these joins would merge, without making the run
        (ADR 0030). Reads under the lock; merges outside it, because a
        merge of large tables takes long enough to hold up everyone."""
        def plan():
            with lock:
                return engine.join_plan(principal.subject, body.dataset_id,
                                        [j.model_dump() for j in body.joins],
                                        body.breakdown)
        try:
            primary, mapping, spec, inputs = await run_in_threadpool(plan)
            return await run_in_threadpool(
                analytics.preview_merge, primary["content"], mapping, inputs,
                spec["breakdown"], language)
        except KeyError:
            raise HTTPException(status_code=404, detail="Dataset not found.")
        except joining.JoinError as error:
            raise HTTPException(status_code=422, detail=error.detail(language))

    @app.get("/api/pipelines")
    def read_pipelines(principal=Depends(requires("read"))):
        """The registered custom stages, the profiles that choose among
        them, what a run gets by default, and why any stage could not
        be loaded."""
        return {"stages": [describe(d) for d in engine.stages.values()],
                "profiles": engine.profiles,
                "default": engine.custom_roles_for(None),
                "problems": app.state.stage_problems}

    @app.get("/api/usage")
    def read_usage(principal=Depends(requires("read"))):
        with lock:
            return quota_usage(store, principal.subject, limits)

    @app.post("/api/datasets", status_code=201)
    async def upload_dataset(
        request: Request,
        name: str = Query(min_length=1, max_length=100),
        format: str | None = Query(default=None, pattern="^(csv|tsv|xlsx|json|jsonl)$"),
        sheet: str | None = Query(default=None, max_length=31),
        language: str = Query(default="en", pattern="^(en|ar)$"),
        principal=Depends(requires("write")),
    ):
        """One file as the request body, read into a canonical table and
        stored content-addressed (ADR 0024). 201 when it is new; 200 when
        the same data was already stored, which costs nothing."""
        limit = dataset_reader.MAX_UPLOAD_BYTES
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise HTTPException(413, detail=dataset_reader.too_large().message(language))
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, detail=dataset_reader.too_large().message(language))
            chunks.append(chunk)
        # Only the file's own name: a browser sends no path, a script might.
        filename = re.split(r"[\\/]", name)[-1].strip() or "dataset"
        try:
            parsed = await run_in_threadpool(
                dataset_reader.read, b"".join(chunks), filename, format, sheet)
        except dataset_reader.DatasetError as error:
            raise HTTPException(error.status, detail=error.message(language))

        def store_it():
            with lock:
                return engine.store_upload(parsed, filename, principal.subject)
        try:
            dataset, created = await run_in_threadpool(store_it)
        except QuotaExceeded as error:
            raise HTTPException(status_code=429, detail=error.message)
        return JSONResponse(status_code=201 if created else 200, content={
            "dataset": dataset_summary(dataset), "created": created,
            "columns": parsed.columns, "preview": parsed.preview(),
            "warnings": parsed.warning_texts(language), "sheets": parsed.sheets})

    @app.get("/api/datasets")
    def list_datasets(principal=Depends(requires("read"))):
        with lock:
            return {"datasets": [
                {**row, "mapped": row.get("mapping_updated_at") is not None}
                for row in store.list_datasets(principal.subject)]}

    # Column mapping (ADR 0025). Another owner's dataset is a 404, never a
    # 403: whether it exists is not theirs to learn.
    @app.get("/api/datasets/{dataset_id}")
    def read_dataset(dataset_id: str,
                     language: str = Query(default="en", pattern="^(en|ar)$"),
                     principal=Depends(requires("read"))):
        with lock:
            try:
                return engine.dataset_detail(dataset_id, principal.subject, language)
            except KeyError:
                raise HTTPException(status_code=404, detail="Dataset not found.")

    @app.put("/api/datasets/{dataset_id}/mapping")
    def save_mapping(dataset_id: str, mapping: MappingIn,
                     language: str = Query(default="en", pattern="^(en|ar)$"),
                     principal=Depends(requires("write"))):
        with lock:
            try:
                return engine.save_mapping(dataset_id, principal.subject,
                                           mapping.model_dump(), language)
            except KeyError:
                raise HTTPException(status_code=404, detail="Dataset not found.")
            except colmap.MappingError as error:
                raise HTTPException(status_code=422, detail=error.detail(language))

    @app.delete("/api/datasets/{dataset_id}/mapping")
    def clear_mapping(dataset_id: str,
                      language: str = Query(default="en", pattern="^(en|ar)$"),
                      principal=Depends(requires("write"))):
        with lock:
            try:
                return engine.clear_mapping(dataset_id, principal.subject, language)
            except KeyError:
                raise HTTPException(status_code=404, detail="Dataset not found.")

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

    # ------------------------------------------------------------------
    # A run's cleaned table (ADR 0031): download, fields, totals, records
    # ------------------------------------------------------------------
    async def run_table(run_id, principal, language):
        """The run's analysis table, for its owner. Ownership and the store
        are read under the lock; the table is parsed and queried outside
        it, so a large table does not hold up everyone else."""
        def source():
            with lock:
                if not owns(principal, engine.owner_of(run_id)):
                    raise KeyError(run_id)
                return engine.table_source(run_id)
        try:
            key, stored, run = await run_in_threadpool(source)
        except KeyError:
            raise HTTPException(status_code=404, detail="Run not found.")
        except TableNotReady:
            raise HTTPException(status_code=409, detail=(
                "الجدول المنظَّف غير جاهز بعد: لم ينتهِ التشغيل من تنظيف بياناته."
                if language == "ar" else
                "The cleaned table is not ready yet: the run has not finished cleaning its data."))
        return await run_in_threadpool(engine.load_table, key, stored), run

    @app.get("/api/runs/{run_id}/data.csv")
    async def download_table(run_id: str,
                             language: str = Query(default="en", pattern="^(en|ar)$"),
                             principal=Depends(requires("read"))):
        table, run = await run_table(run_id, principal, language)
        name = table_query.download_name(run["goal"], run_id)
        text = await run_in_threadpool(table_query.to_csv, table)
        return Response(content=text.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{name}"; filename*=UTF-8\'\'{name}'})

    @app.get("/api/runs/{run_id}/fields")
    async def table_fields(run_id: str,
                           language: str = Query(default="en", pattern="^(en|ar)$"),
                           principal=Depends(requires("read"))):
        table, _ = await run_table(run_id, principal, language)
        return {"fields": await run_in_threadpool(table_query.fields, table),
                "records": len(table.rows)}

    @app.post("/api/runs/{run_id}/query")
    async def query_table(run_id: str, body: QueryIn,
                          language: str = Query(default="en", pattern="^(en|ar)$"),
                          principal=Depends(requires("read"))):
        table, _ = await run_table(run_id, principal, language)
        try:
            return await run_in_threadpool(table_query.aggregate, table, body.model_dump())
        except table_query.QueryError as error:
            raise HTTPException(status_code=422, detail=error.detail(language))

    @app.post("/api/runs/{run_id}/records")
    async def table_records(run_id: str, body: RecordsIn,
                            language: str = Query(default="en", pattern="^(en|ar)$"),
                            principal=Depends(requires("read"))):
        table, _ = await run_table(run_id, principal, language)
        try:
            return await run_in_threadpool(table_query.records, table, body.model_dump())
        except table_query.QueryError as error:
            raise HTTPException(status_code=422, detail=error.detail(language))

    @app.post("/api/runs/{run_id}/approvals/{approval_id}")
    def decide_approval(run_id: str, approval_id: str, decision: ApprovalIn, principal=Depends(requires("approve"))):
        with lock:
            return _run_or_404(
                lambda: engine.decide_approval(run_id, approval_id, decision.decision),
                principal, run_id,
            )

    # ------------------------------------------------------------------
    # Live data (ADR 0034): connectors and the event stream. A connector
    # is its owner's alone; another owner's is a 404, never a 403.
    # ------------------------------------------------------------------
    def _no_connector():
        raise HTTPException(status_code=404, detail="Live source not found.")

    @app.get("/api/connectors")
    def list_connectors(principal=Depends(requires("read"))):
        with lock:
            return {"connectors": connectors.list(principal.subject)}

    @app.post("/api/connectors", status_code=201)
    def create_connector(body: ConnectorIn,
                         language: str = Query(default="en", pattern="^(en|ar)$"),
                         principal=Depends(requires("write"))):
        with lock:
            try:
                return connectors.create(
                    principal.subject, body.name, body.url, body.goal, language=body.language,
                    format=body.format, sheet=body.sheet, every_minutes=body.every_minutes,
                    profile=body.profile)
            except ConnectorError as error:
                raise HTTPException(status_code=error.status, detail=error.message(language))
            except ValueError as error:  # an unknown pipeline profile
                raise HTTPException(status_code=422, detail=str(error))

    @app.put("/api/connectors/{connector_id}")
    def update_connector(connector_id: str, body: ConnectorUpdateIn,
                         language: str = Query(default="en", pattern="^(en|ar)$"),
                         principal=Depends(requires("write"))):
        every = body.every_minutes if "every_minutes" in body.model_fields_set else "keep"
        with lock:
            try:
                return connectors.update(connector_id, principal.subject,
                                         enabled=body.enabled, every_minutes=every)
            except KeyError:
                _no_connector()
            except ConnectorError as error:
                raise HTTPException(status_code=error.status, detail=error.message(language))

    @app.delete("/api/connectors/{connector_id}", status_code=204)
    def delete_connector(connector_id: str, principal=Depends(requires("write"))):
        with lock:
            try:
                connectors.delete(connector_id, principal.subject)
            except KeyError:
                _no_connector()
        return Response(status_code=204)

    @app.post("/api/connectors/{connector_id}/refresh")
    async def refresh_connector(connector_id: str,
                                language: str = Query(default="en", pattern="^(en|ar)$"),
                                principal=Depends(requires("write"))):
        """Fetch now. The fetch and the parse run outside the lock; the
        connector's lease keeps a worker from fetching it at the same time."""
        try:
            return await run_in_threadpool(
                connectors.refresh_now, connector_id, principal.subject, lock)
        except KeyError:
            _no_connector()
        except Busy:
            raise HTTPException(status_code=409, detail=(
                "يجري تحديث هذا المصدر الآن. حاول بعد قليل." if language == "ar" else
                "This source is being refreshed already. Try again in a moment."))
        except TooSoon as wait:
            raise HTTPException(status_code=429, headers={"Retry-After": str(wait.seconds)},
                                detail=(f"حُدّث هذا المصدر للتو. حاول بعد {wait.seconds} ثانية."
                                        if language == "ar" else
                                        f"This source was fetched moments ago. Try again in "
                                        f"{wait.seconds} seconds."))

    @app.get("/api/events")
    async def events(request: Request,
                     wait: float = Query(default=live.MAX_SECONDS, ge=0, le=live.MAX_SECONDS),
                     last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                     principal=Depends(requires("read"))):
        """The owner's runs and connectors as they change, as server-sent
        events. Each stream ends within `wait` seconds; the client resumes
        with Last-Event-ID. An unreadable one starts from now."""
        owner = principal.subject
        with streams_lock:
            if open_streams.get(owner, 0) >= live.MAX_STREAMS_PER_OWNER:
                raise HTTPException(status_code=429, headers={"Retry-After": "30"},
                                    detail="Too many open update streams. Close a tab.")
            open_streams[owner] = open_streams.get(owner, 0) + 1
        reader = live.Reader(store, owner,
                             live.parse_cursor(last_event_id) or live.cursor_now())

        def poll_locked():
            with lock:
                return reader.poll()

        async def poll():
            return await run_in_threadpool(poll_locked)

        async def body():
            try:
                async for part in live.stream(reader, poll, asyncio.sleep, time.monotonic,
                                              request.is_disconnected, max_seconds=wait):
                    yield part
            finally:
                with streams_lock:
                    open_streams[owner] -= 1

        return StreamingResponse(body(), media_type="text/event-stream", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------
    # Static frontend (production build), if present
    # ------------------------------------------------------------------
    dist = Path(dist_dir) if dist_dir else PROJECT_ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            # An API path no route matched is a missing endpoint, not a page.
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found.")
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
