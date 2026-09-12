"""Storage adapters for the run engine.

One narrow SQL store interface with two implementations:

- SQLiteStore — the local-first default (WAL journal, zero setup).
- PostgresStore — hosted mode via DATABASE_URL (psycopg2), pointed at a
  managed PostgreSQL such as Supabase. Imported lazily so the local app
  keeps working without the driver installed.

Both dialects share the same DDL and column names; only the parameter
placeholder differs. Rows cross the boundary as plain dicts, so the
engine never sees a driver type.
"""

# The single source of truth for which tables exist. Backup, restore and
# test teardown all derive from this, so adding a table cannot leave one
# of them stale (a bug that has already bitten once).
TABLES = (
    "runs",
    "tasks",
    "approvals",
    "artifacts",
    "sessions",
    "memory_kv",
    "vault_notes",
    "datasets",
)

# Restore must insert parents before children.
RESTORE_ORDER = (
    "datasets",
    "runs",
    "tasks",
    "approvals",
    "artifacts",
    "sessions",
    "memory_kv",
    "vault_notes",
)

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS runs (
      id TEXT PRIMARY KEY, goal TEXT NOT NULL, dataset_name TEXT NOT NULL,
      dataset_text TEXT NOT NULL, state TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT)""",
    """CREATE TABLE IF NOT EXISTS tasks (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
      idx INTEGER NOT NULL, role TEXT NOT NULL, title TEXT NOT NULL,
      state TEXT NOT NULL, summary TEXT, result_json TEXT, updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS approvals (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
      action TEXT NOT NULL, target TEXT NOT NULL, risk TEXT NOT NULL,
      impact TEXT NOT NULL, reversibility TEXT NOT NULL,
      content_hash TEXT NOT NULL, state TEXT NOT NULL,
      created_at TEXT NOT NULL, decided_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS artifacts (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
      name TEXT NOT NULL, kind TEXT NOT NULL, version INTEGER NOT NULL,
      content TEXT NOT NULL, published_path TEXT, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      ended INTEGER NOT NULL, preferences_json TEXT NOT NULL,
      history_json TEXT NOT NULL, transcript_json TEXT NOT NULL,
      next_entry_id INTEGER NOT NULL)""",
    # Memory is per owner. The composite key matters as much as the
    # column: keys are handed out per owner, so the first thing two
    # tenants save is "memory_1" for both, and a single-column primary
    # key would make the second one collide.
    """CREATE TABLE IF NOT EXISTS memory_kv (
      owner TEXT NOT NULL, key TEXT NOT NULL, text TEXT NOT NULL,
      category TEXT NOT NULL, updated TEXT,
      PRIMARY KEY (owner, key))""",
    """CREATE TABLE IF NOT EXISTS vault_notes (
      path TEXT PRIMARY KEY, run_id TEXT NOT NULL,
      content TEXT NOT NULL, created_at TEXT NOT NULL)""",
    # Datasets are content-addressed: uploading the same file twice
    # stores one row, and runs reference it instead of duplicating it.
    """CREATE TABLE IF NOT EXISTS datasets (
      id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, name TEXT NOT NULL,
      content TEXT NOT NULL, byte_size INTEGER NOT NULL,
      owner TEXT NOT NULL, created_at TEXT NOT NULL)""",
]


class SqlStore:
    """Dialect-neutral SQL access. Subclasses provide the connection and
    the parameter placeholder."""

    placeholder = "?"

    def _rows(self, cursor):
        if cursor.description is None:
            return []
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _exec(self, sql, params=()):
        cursor = self._conn.cursor()
        cursor.execute(sql.replace("?", self.placeholder), params)
        rows = self._rows(cursor)
        self._commit()
        return rows

    def _exec_rowcount(self, sql, params=()):
        """Like _exec, but reports how many rows the statement changed —
        which is how a lease claim knows whether it won the race."""
        cursor = self._conn.cursor()
        cursor.execute(sql.replace("?", self.placeholder), params)
        count = cursor.rowcount
        self._commit()
        return count

    def _create_schema(self):
        for statement in SCHEMA_STATEMENTS:
            self._exec(statement)
        self._migrate()

    def _migrate(self):
        """Additive migrations for databases created by earlier versions.

        ADD COLUMN errors when the column already exists in both dialects,
        which makes this safely repeatable on every startup."""
        for table in ("runs", "sessions"):
            try:
                self._exec(f"ALTER TABLE {table} ADD COLUMN owner TEXT")
            except Exception:
                self._rollback()
            else:
                # Rows written before ownership existed belong to the
                # local owner, matching pre-auth behavior.
                self._exec(
                    f"UPDATE {table} SET owner = 'local-owner' WHERE owner IS NULL")
        for column in ("dataset_id", "lease_owner", "lease_expires_at"):
            try:
                self._exec(f"ALTER TABLE runs ADD COLUMN {column} TEXT")
            except Exception:
                self._rollback()
        try:
            # NULL means "never paused", which reads as not paused.
            self._exec("ALTER TABLE runs ADD COLUMN paused INTEGER")
        except Exception:
            self._rollback()
        self._migrate_memory_owner()

    def _migrate_memory_owner(self):
        """Give memory_kv an owner, rebuilding the table if it predates one.

        This one cannot be an ADD COLUMN: the primary key has to move
        from (key) to (owner, key), or the second tenant to save a
        memory collides with the first. Rebuild-and-copy is the only
        shape both SQLite and PostgreSQL accept, and the guard makes it
        run exactly once.

        Existing rows are attributed to `local-owner` — the same
        assumption the runs and sessions migrations made, and the right
        one: a database written before ownership existed was written by
        a single-user install.
        """
        try:
            self._exec("SELECT owner FROM memory_kv LIMIT 1")
            return  # already migrated
        except Exception:
            self._rollback()
        try:
            self._exec("ALTER TABLE memory_kv RENAME TO memory_kv_pre_owner")
            for statement in SCHEMA_STATEMENTS:
                if "memory_kv (" in statement:
                    self._exec(statement)
            self._exec(
                "INSERT INTO memory_kv (owner, key, text, category, updated) "
                "SELECT 'local-owner', key, text, category, updated "
                "FROM memory_kv_pre_owner")
            self._exec("DROP TABLE memory_kv_pre_owner")
        except Exception:
            # A half-finished rebuild would lose memory, so leave the
            # old table in place and let the failure be visible rather
            # than deleting anything on the way out.
            self._rollback()
            raise

    def _rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    # -- generic helpers --------------------------------------------------
    def insert(self, table, row):
        columns = ", ".join(row)
        marks = ", ".join(["?"] * len(row))
        self._exec(f"INSERT INTO {table} ({columns}) VALUES ({marks})",
                   tuple(row.values()))

    def update(self, table, key, fields):
        assignments = ", ".join(f"{column} = ?" for column in fields)
        self._exec(f"UPDATE {table} SET {assignments} WHERE id = ?",
                   tuple(fields.values()) + (key,))

    # -- domain queries ---------------------------------------------------
    def get_run(self, run_id):
        rows = self._exec("SELECT * FROM runs WHERE id = ?", (run_id,))
        return rows[0] if rows else None

    def list_runs(self, owner=None, limit=50):
        if owner is None:
            return self._exec(
                "SELECT id, goal, dataset_name, state, created_at, updated_at "
                "FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        return self._exec(
            "SELECT id, goal, dataset_name, state, created_at, updated_at "
            "FROM runs WHERE owner = ? ORDER BY created_at DESC LIMIT ?",
            (owner, limit))

    def get_tasks(self, run_id):
        return self._exec(
            "SELECT * FROM tasks WHERE run_id = ? ORDER BY idx", (run_id,))

    def latest_artifact(self, run_id):
        rows = self._exec(
            "SELECT * FROM artifacts WHERE run_id = ? "
            "ORDER BY version DESC LIMIT 1", (run_id,))
        return rows[0] if rows else None

    def approvals_for_run(self, run_id):
        return self._exec(
            "SELECT * FROM approvals WHERE run_id = ?", (run_id,))

    def pending_approval(self, run_id):
        rows = self._exec(
            "SELECT * FROM approvals WHERE run_id = ? AND state = 'pending'",
            (run_id,))
        return rows[0] if rows else None

    def get_approval(self, approval_id, run_id):
        rows = self._exec(
            "SELECT * FROM approvals WHERE id = ? AND run_id = ?",
            (approval_id, run_id))
        return rows[0] if rows else None

    # -- worker leases ----------------------------------------------------
    # A lease is a row-level claim with an expiry. A worker that crashes
    # stops renewing, the expiry passes, and another worker picks the run
    # up — no lock to clean up, no heartbeat table to keep consistent.
    def claim_run(self, worker_id, now, expires_at):
        """Take the lease on one runnable run. Returns its id, or None."""
        candidates = self._exec(
            "SELECT id FROM runs WHERE state IN ('queued', 'running') "
            "AND (paused IS NULL OR paused = 0) "
            "AND (lease_owner IS NULL OR lease_expires_at < ?) "
            "ORDER BY created_at LIMIT 5", (now,))
        for row in candidates:
            # The guard repeats inside the UPDATE, so two workers that
            # both selected this candidate cannot both win: the loser
            # changes zero rows and tries the next one. The SELECT alone
            # would not be enough — it is a read, not a claim.
            if self._exec_rowcount(
                    "UPDATE runs SET lease_owner = ?, lease_expires_at = ? "
                    "WHERE id = ? AND state IN ('queued', 'running') "
                    "AND (paused IS NULL OR paused = 0) "
                    "AND (lease_owner IS NULL OR lease_expires_at < ?)",
                    (worker_id, expires_at, row["id"], now)):
                return row["id"]
            # Zero rows changed usually means another worker got there
            # first. It can also mean this worker won, the connection
            # died before the acknowledgement arrived, and the repeat
            # then failed its own guard — because we are now the holder.
            # Losing a race and winning one invisibly are different
            # things, and only the first should end quietly.
            if self._won_after_a_retry(row["id"], worker_id, expires_at):
                return row["id"]
        return None

    def _won_after_a_retry(self, run_id, worker_id, expires_at):
        """Did this exact claim land after all? Matching the expiry we
        tried to write distinguishes it from an older lease of ours."""
        rows = self._exec(
            "SELECT lease_owner, lease_expires_at FROM runs WHERE id = ?",
            (run_id,))
        return bool(rows) and (rows[0]["lease_owner"] == worker_id
                               and rows[0]["lease_expires_at"] == expires_at)

    def renew_lease(self, run_id, worker_id, expires_at):
        """Heartbeat. False means the lease was lost and must not be used."""
        return self._exec_rowcount(
            "UPDATE runs SET lease_expires_at = ? "
            "WHERE id = ? AND lease_owner = ?",
            (expires_at, run_id, worker_id)) == 1

    def release_lease(self, run_id, worker_id):
        """Release only our own lease, never a successor's."""
        self._exec(
            "UPDATE runs SET lease_owner = NULL, lease_expires_at = NULL "
            "WHERE id = ? AND lease_owner = ?", (run_id, worker_id))

    # -- sessions ---------------------------------------------------------
    def get_session(self, session_id):
        rows = self._exec("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return rows[0] if rows else None

    def upsert_session(self, row):
        fields = {k: v for k, v in row.items() if k != "id"}
        assignments = ", ".join(f"{column} = ?" for column in fields)
        cursor = self._conn.cursor()
        cursor.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ?".replace(
                "?", self.placeholder),
            tuple(fields.values()) + (row["id"],))
        if cursor.rowcount == 0:
            self.insert("sessions", row)
        else:
            self._commit()

    def trim_sessions(self, keep):
        self._exec(
            "DELETE FROM sessions WHERE id NOT IN "
            "(SELECT id FROM sessions ORDER BY updated_at DESC LIMIT ?)",
            (keep,))

    # -- shared memory ----------------------------------------------------
    def memory_load(self, owner="local-owner"):
        return {
            row["key"]: {"text": row["text"], "category": row["category"],
                         "updated": row["updated"]}
            for row in self._exec(
                "SELECT * FROM memory_kv WHERE owner = ?", (owner,))
        }

    def memory_save(self, payload, owner="local-owner"):
        """Replace one owner's memory. The DELETE is scoped for the same
        reason the SELECT is: unscoped, saving a memory deleted
        everybody else's."""
        self._exec("DELETE FROM memory_kv WHERE owner = ?", (owner,))
        for key, entry in payload.items():
            self.insert("memory_kv", {
                "owner": owner, "key": key, "text": entry["text"],
                "category": entry["category"], "updated": entry["updated"]})

    # -- vault notes ------------------------------------------------------
    def upsert_note(self, path, run_id, content, created_at):
        self._exec("DELETE FROM vault_notes WHERE path = ?", (path,))
        self.insert("vault_notes", {"path": path, "run_id": run_id,
                                    "content": content,
                                    "created_at": created_at})

    def list_notes(self):
        return self._exec(
            "SELECT path, run_id, created_at FROM vault_notes "
            "ORDER BY created_at DESC")

    def get_note(self, path):
        rows = self._exec("SELECT * FROM vault_notes WHERE path = ?", (path,))
        return rows[0] if rows else None

    # -- datasets ---------------------------------------------------------
    def find_dataset(self, sha256, owner):
        rows = self._exec(
            "SELECT * FROM datasets WHERE sha256 = ? AND owner = ? LIMIT 1",
            (sha256, owner))
        return rows[0] if rows else None

    def get_dataset(self, dataset_id):
        rows = self._exec("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        return rows[0] if rows else None

    # -- usage ------------------------------------------------------------
    # Usage is counted from the rows themselves rather than a parallel
    # tally, so it cannot drift away from what the tenant actually has.
    def count_runs_since(self, owner, since):
        rows = self._exec(
            "SELECT COUNT(*) AS n FROM runs WHERE owner = ? AND created_at >= ?",
            (owner, since))
        return int(rows[0]["n"]) if rows else 0

    def dataset_usage(self, owner):
        rows = self._exec(
            "SELECT COUNT(*) AS n, COALESCE(SUM(byte_size), 0) AS bytes "
            "FROM datasets WHERE owner = ?", (owner,))
        row = rows[0] if rows else {"n": 0, "bytes": 0}
        return {"datasets": int(row["n"]), "bytes": int(row["bytes"] or 0)}

    def list_datasets(self, owner):
        return self._exec(
            "SELECT id, sha256, name, byte_size, created_at FROM datasets "
            "WHERE owner = ? ORDER BY created_at DESC LIMIT 50", (owner,))

    # -- backup and restore ----------------------------------------------
    def export_all(self):
        """Every durable row, as plain JSON-serialisable dicts."""
        return {table: self._exec(f"SELECT * FROM {table}") for table in TABLES}

    def import_all(self, payload):
        """Replace all contents with a backup. Returns rows restored.

        Children are deleted before parents and inserted after them, so
        foreign keys hold at every point."""
        for table in reversed(RESTORE_ORDER):
            self._exec(f"DELETE FROM {table}")
        restored = 0
        for table in RESTORE_ORDER:
            for row in payload.get(table, []):
                if table == "memory_kv" and not row.get("owner"):
                    # Written before memory had an owner: the same
                    # attribution the migration makes.
                    row = dict(row, owner="local-owner")
                self.insert(table, row)
                restored += 1
        return restored


class DbMemoryBackend:
    """One owner's agent memory, in the store's memory_kv table.

    An instance is bound to an owner rather than shared, because the
    alternative — one backend for the process — is what let every tenant
    read and overwrite every other tenant's memory.
    """

    persistent = True

    def __init__(self, store, owner="local-owner"):
        self._store = store
        self._owner = owner or "local-owner"

    @property
    def owner(self):
        return self._owner

    def load(self):
        try:
            return self._store.memory_load(self._owner)
        except Exception:
            return {}

    def save(self, payload):
        try:
            self._store.memory_save(payload, self._owner)
            return True
        except Exception:
            return False


class SQLiteStore(SqlStore):
    placeholder = "?"

    def __init__(self, path):
        import os
        import sqlite3
        import tempfile
        from pathlib import Path

        path = Path(str(path))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Read-only deployment (e.g. a serverless bundle): fall back to
            # the writable temp directory. State is then per-instance and
            # ephemeral — configure DATABASE_URL for durable hosting.
            path = Path(tempfile.gettempdir()) / "agentic-os" / path.name
            path.parent.mkdir(parents=True, exist_ok=True)
        if not os.access(path.parent, os.W_OK):
            path = Path(tempfile.gettempdir()) / "agentic-os" / path.name
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _commit(self):
        self._conn.commit()


class PostgresStore(SqlStore):
    placeholder = "%s"

    def __init__(self, database_url):
        import psycopg2  # lazy: only hosted mode needs the driver

        self._psycopg2 = psycopg2
        self._database_url = database_url
        self._conn = self._connect()
        self._create_schema()

    def _connect(self):
        conn = self._psycopg2.connect(self._database_url, connect_timeout=10)
        conn.autocommit = True
        return conn

    def _retrying(self, statement, sql, params):
        """Run a statement, reconnecting once if the connection is gone.

        Two different failures land here and both are ordinary. A pooler
        or a server restart drops the socket, which surfaces as
        OperationalError on the next statement; a connection this process
        already closed surfaces as InterfaceError. Catching only the
        first meant a worker that had been idle — the normal state of a
        worker — could fail on the statement it woke up to run.

        Retrying is safe because autocommit means there is no transaction
        to rebuild: each statement stands alone. The one case where a
        blind repeat could mislead is a conditional UPDATE whose
        acknowledgement was lost, and `claim_run` checks for that
        directly rather than trusting the row count.
        """
        try:
            return statement(sql, params)
        except (self._psycopg2.OperationalError,
                self._psycopg2.InterfaceError):
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = self._connect()
            return statement(sql, params)

    def _exec(self, sql, params=()):
        return self._retrying(super()._exec, sql, params)

    def _exec_rowcount(self, sql, params=()):
        # The lease statements run through here, which is to say the
        # worker's entire job does.
        return self._retrying(super()._exec_rowcount, sql, params)

    def _commit(self):
        pass  # autocommit


def open_store(database_url=None, sqlite_path=None):
    """Hosted PostgreSQL when DATABASE_URL is configured; SQLite otherwise."""
    if database_url and str(database_url).startswith(("postgres://", "postgresql://")):
        return PostgresStore(str(database_url))
    return SQLiteStore(sqlite_path)
