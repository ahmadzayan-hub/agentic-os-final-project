"""Live data (ADR 0034): connectors that snapshot a source into datasets.

A connector is an owner's saved `https://` source. Refreshing it fetches
the file, reads it with the dataset reader (ADR 0024) and stores it like
an upload, content-addressed: the same content is "unchanged" and does
nothing; new content becomes a dataset, keeps the previous snapshot's
column mapping when it still fits, and starts the connector's analysis,
which stops at the approval gate like any run.

Fetching on a user's behalf is the classic way to reach what the user
cannot (server-side request forgery), so `fetch` is fenced: https only,
public addresses only, the checked address is the one connected to,
redirects refused, the upload's size limit and a time limit.
"""

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

from server import datasets as reader
from server import mapping as colmap
from server.quota import QuotaExceeded
from server.runs import _stamp, _utcnow

MIN_EVERY_MINUTES = 15
MAX_EVERY_MINUTES = 7 * 24 * 60
MAX_FAILURE_WAIT_MINUTES = 24 * 60
MAX_PER_OWNER = 10
# "Refresh now" waits this long after the last fetch of the same source,
# so ten sources cannot become hundreds of fetches a minute.
COOLDOWN_SECONDS = 60
TIMEOUT_SECONDS = 15
LEASE_SECONDS = 120
# Reserved by RFC 2606: never a real host, so only the test seam answers it.
FIXTURE_HOST = "fixtures.invalid"
FIXTURE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
FORMATS = ("csv", "tsv", "xlsx", "json", "jsonl")
CHUNK = 16 * 1024
# Query keys that carry a credential. Live sources store no secrets
# (ADR 0034), so an address carrying one is refused rather than kept.
SECRET_KEYS = re.compile(
    r"(^|[_-])(key|apikey|token|secret|password|passwd|pwd|signature|sig|auth|"
    r"credential|session)s?($|[_-])", re.IGNORECASE)
NAT64 = ipaddress.ip_network("64:ff9b::/96")
NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


class ConnectorError(Exception):
    """A source that could not be used, said in both languages."""

    def __init__(self, en, ar, status=422):
        super().__init__(en)
        self.en, self.ar, self.status = en, ar, status

    def message(self, language="en"):
        return self.ar if language == "ar" else self.en


class Busy(Exception):
    """A refresh of this connector is already under way."""


class TooSoon(Exception):
    """Asked again within the cooldown; `seconds` until it is allowed."""

    def __init__(self, seconds):
        super().__init__(seconds)
        self.seconds = seconds


# ---------------------------------------------------------------------------
# The fence
# ---------------------------------------------------------------------------

def _public(address):
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6:
        if ip in NAT64_LOCAL:
            return False
        if ip in NAT64:  # an IPv4 address inside the NAT64 prefix
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        elif ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _parts(url, env):
    """(host, port, request path) of an acceptable address, or
    ConnectorError. Checks the form only; no name is looked up."""
    try:
        parts = urlsplit(str(url).strip())
        port = parts.port or 443
    except ValueError:
        raise ConnectorError("The address is not a valid web address.",
                             "العنوان ليس عنوان ويب صالحاً.")
    if parts.scheme != "https" or not parts.hostname:
        raise ConnectorError("The address must start with https:// and name a host.",
                             "يجب أن يبدأ العنوان بـ https:// وأن يحدد خادماً.")
    if parts.username or parts.password:
        raise ConnectorError("The address may not carry a user name or password.",
                             "لا يجوز أن يحمل العنوان اسم مستخدم أو كلمة مرور.")
    host = parts.hostname.lower()
    allowed = [h.strip().lower() for h in (env.get("AGENTIC_OS_CONNECTOR_HOSTS") or "").split(",")
               if h.strip()]
    if allowed and host not in allowed:
        raise ConnectorError(f"{host} is not on this server's list of allowed sources.",
                             f"{host} ليس ضمن قائمة المصادر المسموح بها على هذا الخادم.")
    secrets = [key for key, _ in parse_qsl(parts.query, keep_blank_values=True)
               if SECRET_KEYS.search(key)]
    if secrets:
        names = ", ".join(sorted(set(secrets)))
        raise ConnectorError(
            f"The address carries what looks like a credential ({names}). Live sources "
            "store no secrets: use an address that needs none.",
            f"يحمل العنوان ما يبدو بيانات اعتماد ({names}). لا تحفظ المصادر الحية أسراراً: "
            "استخدم عنواناً لا يحتاج إليها.")
    # Sent as ASCII: anything else is percent-encoded, as a browser would.
    safe = "/:@!$&'()*+,;=-._~%"
    path = quote(parts.path or "/", safe=safe) + (
        "?" + quote(parts.query, safe=safe + "?") if parts.query else "")
    return host, port, path


def check_address(url, env=None, resolve=socket.getaddrinfo):
    """(host, port, request path, the public address to connect to), or
    ConnectorError. Every address the host resolves to must be public."""
    env = os.environ if env is None else env
    host, port, path = _parts(url, env)
    if host == FIXTURE_HOST:
        return host, port, path, None
    try:
        answers = resolve(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        answers = []
    addresses = sorted({answer[4][0] for answer in answers})
    if not addresses:
        raise ConnectorError(f"{host} could not be found.", f"تعذّر العثور على {host}.",
                             status=502)
    if any(not _public(address) for address in addresses):
        raise ConnectorError(
            f"{host} points to a private or reserved address, which a connector may not reach.",
            f"يشير {host} إلى عنوان خاص أو محجوز، ولا يجوز للموصل الوصول إليه.")
    return host, port, path, addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the address that was checked, keeping the host name for
    TLS, so a second DNS answer cannot swap in a private address."""

    def __init__(self, host, address, port, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _too_large():
    limit = reader.MAX_UPLOAD_BYTES // 1_000_000
    return ConnectorError(f"The source is larger than {limit} MB, the limit for one snapshot.",
                          f"المصدر أكبر من {limit} ميغابايت، وهو الحد للقطة الواحدة.",
                          status=413)


def _too_slow(seconds):
    return ConnectorError(f"The source took longer than {seconds} seconds to send.",
                          f"استغرق المصدر أكثر من {seconds} ثانية للإرسال.", status=504)


def fetch(url, env=None, resolve=socket.getaddrinfo, limit=None, timeout=TIMEOUT_SECONDS,
          connection_class=_PinnedHTTPSConnection, clock=time.monotonic):
    """The bytes at `url`, inside the fence. Raises ConnectorError."""
    env = os.environ if env is None else env
    limit = limit or reader.MAX_UPLOAD_BYTES
    deadline = clock() + timeout
    host, port, path, address = check_address(url, env, resolve)
    if host == FIXTURE_HOST:
        return _fixture(path, env, limit)
    connection = connection_class(host, address, port, timeout)
    try:
        connection.request("GET", path, headers={"User-Agent": "AgenticOS-connector/1",
                                                 "Accept": "*/*", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            target = (response.getheader("Location") or "?")[:200]
            raise ConnectorError(
                f"The source redirects to {target}. Use that address directly.",
                f"يعيد المصدر التوجيه إلى {target}. استخدم ذلك العنوان مباشرة.")
        if response.status != 200:
            raise ConnectorError(f"The source answered {response.status}.",
                                 f"أجاب المصدر بالرمز {response.status}.", status=502)
        declared = response.getheader("Content-Length") or ""
        if declared.isdigit() and int(declared) > limit:
            raise _too_large()
        chunks, size = [], 0
        while True:
            remaining = deadline - clock()
            if remaining <= 0:
                raise _too_slow(timeout)
            sock = getattr(connection, "sock", None)
            if sock is not None:
                # No single wait outlives the whole budget.
                sock.settimeout(remaining)
            # read1 returns what one receive brought, so a source that
            # trickles a byte at a time still meets the deadline above.
            chunk = response.read1(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise _too_large()
            chunks.append(chunk)
        return b"".join(chunks)
    except ConnectorError:
        raise
    except TimeoutError:
        raise _too_slow(timeout)
    except (OSError, UnicodeError, http.client.HTTPException) as error:
        raise ConnectorError(f"The source could not be read ({type(error).__name__}).",
                             f"تعذّرت قراءة المصدر ({type(error).__name__}).", status=502)
    finally:
        connection.close()


def _fixture(path, env, limit):
    """End-to-end tests only: a file in AGENTIC_OS_CONNECTOR_FIXTURES."""
    folder = env.get("AGENTIC_OS_CONNECTOR_FIXTURES")
    name = path.lstrip("/").split("?", 1)[0]
    if not folder:
        raise ConnectorError(f"{FIXTURE_HOST} could not be found.",
                             f"تعذّر العثور على {FIXTURE_HOST}.", status=502)
    root = Path(folder).resolve()
    target = (root / name).resolve()
    if not FIXTURE_NAME.match(name) or target.parent != root or not target.is_file():
        raise ConnectorError("The source answered 404.", "أجاب المصدر بالرمز 404.", status=502)
    data = target.read_bytes()
    if len(data) > limit:
        raise _too_large()
    return data


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------

PUBLIC_FIELDS = ("id", "name", "url", "format", "sheet", "every_minutes", "goal", "language",
                 "profile", "enabled", "last_status", "last_error", "last_checked_at",
                 "last_dataset_id", "last_run_id", "next_due_at", "failures", "created_at",
                 "updated_at")


def summary(row):
    """A connector as the API shows it: never the lease or the hash."""
    out = {key: row.get(key) for key in PUBLIC_FIELDS}
    out["enabled"] = bool(row.get("enabled"))
    return out


def check_every(every):
    if every is None:
        return None
    if isinstance(every, bool) or not isinstance(every, int) or not (
            MIN_EVERY_MINUTES <= every <= MAX_EVERY_MINUTES):
        raise ConnectorError(
            f"Refresh every {MIN_EVERY_MINUTES} minutes to a week, or only when asked.",
            f"التحديث كل {MIN_EVERY_MINUTES} دقيقة إلى أسبوع، أو عند الطلب فقط.")
    return every


def _filename(row):
    base = urlsplit(row["url"]).path.rsplit("/", 1)[-1] or row["name"]
    if row.get("format") and not base.lower().endswith("." + row["format"]):
        base = f"{base}.{row['format']}"
    return base[:100]


def _guarded(lock, action):
    if lock is None:
        return action()
    with lock:
        return action()


class Connectors:
    """Every owner's connectors, over the run engine's store."""

    def __init__(self, engine, env=None, fetcher=None, clock=_utcnow, cooldown=None):
        self.engine = engine
        self.store = engine.store
        self.env = os.environ if env is None else env
        self.fetcher = fetcher or (lambda url: fetch(url, self.env))
        self.clock = clock
        if cooldown is None:
            cooldown = int(self.env.get("AGENTIC_OS_CONNECTOR_COOLDOWN") or COOLDOWN_SECONDS)
        self.cooldown = max(0, cooldown)

    def _now(self):
        return _stamp(self.clock())

    def _owned(self, connector_id, owner):
        row = self.store.get_connector(connector_id)
        if row is None or row["owner"] != owner:
            raise KeyError(connector_id)
        return row

    # -- managing ------------------------------------------------------------
    def create(self, owner, name, url, goal, language="en", format=None, sheet=None,
               every_minutes=None, profile=None):
        _parts(url, self.env)  # the form now; the address at every fetch
        if format is not None and format not in FORMATS:
            raise ConnectorError(f"“{format}” is not a format a connector reads.",
                                 f"«{format}» ليس صيغة يقرؤها الموصل.")
        every = check_every(every_minutes)
        if profile is not None:
            self.engine.custom_roles_for(profile)  # an unknown profile is refused now
        if self.store.count_connectors(owner) >= MAX_PER_OWNER:
            raise ConnectorError(
                f"An account can keep {MAX_PER_OWNER} live sources. Delete one first.",
                f"يمكن للحساب الاحتفاظ بـ {MAX_PER_OWNER} مصادر حية. احذف واحداً أولاً.",
                status=429)
        now = self._now()
        connector_id = uuid.uuid4().hex[:12]
        self.store.insert("connectors", {
            "id": connector_id, "owner": owner, "name": name.strip(), "url": url.strip(),
            "format": format, "sheet": sheet, "every_minutes": every, "goal": goal.strip(),
            "language": language, "profile": profile, "enabled": 1, "failures": 0,
            "last_status": None, "last_error": None, "last_checked_at": None,
            "last_dataset_id": None, "last_sha256": None, "last_run_id": None,
            # A scheduled source is due at once, so it has data to show.
            "next_due_at": now if every else None, "lease_owner": None,
            "lease_expires_at": None, "created_at": now, "updated_at": now})
        return summary(self.store.get_connector(connector_id))

    def list(self, owner):
        return [summary(row) for row in self.store.list_connectors(owner)]

    def update(self, connector_id, owner, enabled=None, every_minutes="keep"):
        row = self._owned(connector_id, owner)
        fields = {"updated_at": self._now()}
        if enabled is not None:
            fields["enabled"] = 1 if enabled else 0
        if every_minutes != "keep":
            fields["every_minutes"] = check_every(every_minutes)
        if len(fields) > 1:
            every = fields.get("every_minutes", row.get("every_minutes"))
            on = fields.get("enabled", row.get("enabled"))
            # Resuming, or a new interval, makes it due now; pausing, never.
            fields["next_due_at"] = fields["updated_at"] if (on and every) else None
            fields["failures"] = 0
        self.store.update("connectors", connector_id, fields)
        return summary(self.store.get_connector(connector_id))

    def delete(self, connector_id, owner):
        """The connector goes; its snapshots and runs stay, as uploads do."""
        self._owned(connector_id, owner)
        self.store.delete_connector(connector_id)

    # -- refreshing -----------------------------------------------------------
    def refresh_now(self, connector_id, owner, lock=None):
        """A refresh the owner asked for. Raises KeyError for another
        owner's connector and Busy when one is already under way."""
        holder = f"ask-{uuid.uuid4().hex[:8]}"

        def take():
            row = self._owned(connector_id, owner)
            now = self.clock()
            if row.get("last_checked_at") and self.cooldown:
                waited = (now - datetime.fromisoformat(row["last_checked_at"])).total_seconds()
                if waited < self.cooldown:
                    raise TooSoon(int(self.cooldown - waited) + 1)
            if not self.store.take_connector(
                    connector_id, holder, _stamp(now),
                    _stamp(now + timedelta(seconds=LEASE_SECONDS))):
                raise Busy(connector_id)
        _guarded(lock, take)
        try:
            return self.refresh(connector_id, lock)
        finally:
            _guarded(lock, lambda: self.store.release_connector(connector_id, holder))

    def refresh(self, connector_id, lock=None):
        """Fetch, snapshot and analyse, by whoever holds the lease. The
        network and the parsing happen outside `lock`."""
        row = _guarded(lock, lambda: self.store.get_connector(connector_id))
        if row is None:
            raise KeyError(connector_id)
        language = row.get("language") or "en"
        started = self.clock()
        try:
            parsed = reader.read(self.fetcher(row["url"]), _filename(row), row.get("format"),
                                 row.get("sheet"))
        except (ConnectorError, reader.DatasetError) as error:
            return _guarded(lock, lambda: self._failed(row, error.message(language), started))
        except Exception as error:  # e.g. a file nested too deeply to read
            text = (f"تعذّرت قراءة المصدر ({type(error).__name__})." if language == "ar" else
                    f"The source could not be read ({type(error).__name__}).")
            return _guarded(lock, lambda: self._failed(row, text, started))
        return _guarded(lock, lambda: self._snapshot(row, parsed, started))

    def _failed(self, row, text, started):
        failures = int(row.get("failures") or 0) + 1
        fields = {"last_status": "failed", "last_error": text,
                  "last_checked_at": _stamp(started), "failures": failures,
                  "updated_at": self._now()}
        if row.get("every_minutes") and row.get("enabled"):
            # Twice the wait after each failure in a row, up to a day.
            wait = min(row["every_minutes"] * 2 ** failures, MAX_FAILURE_WAIT_MINUTES)
            fields["next_due_at"] = _stamp(started + timedelta(minutes=wait))
        self.store.update("connectors", row["id"], fields)
        return {"connector": summary(self.store.get_connector(row["id"])),
                "status": "failed", "error": text, "dataset": None, "run": None, "note": None}

    def _snapshot(self, row, parsed, started):
        language = row.get("language") or "en"
        try:
            dataset, _ = self.engine.store_upload(parsed, _filename(row), row["owner"])
        except QuotaExceeded as error:
            return self._failed(row, error.message, started)
        fields = {"last_checked_at": _stamp(started), "failures": 0, "last_error": None,
                  "updated_at": self._now()}
        if row.get("every_minutes") and row.get("enabled"):
            fields["next_due_at"] = _stamp(started + timedelta(minutes=row["every_minutes"]))
        if dataset["sha256"] == row.get("last_sha256"):
            fields["last_status"] = "unchanged"
            self.store.update("connectors", row["id"], fields)
            return {"connector": summary(self.store.get_connector(row["id"])),
                    "status": "unchanged", "error": None, "dataset": dataset["id"],
                    "run": None, "note": None}
        note = self._carry_mapping(row, dataset, language)
        try:
            run = self.engine.create_run(row["goal"], owner=row["owner"],
                                         dataset_id=dataset["id"], profile=row.get("profile"),
                                         language=language)
        except QuotaExceeded as error:
            return self._failed(row, error.message, started)
        except ValueError as error:  # a profile that has since been removed
            return self._failed(row, str(error), started)
        self.store.update("runs", run["id"], {"connector_id": row["id"]})
        fields.update(last_status="updated", last_dataset_id=dataset["id"],
                      last_sha256=dataset["sha256"], last_run_id=run["id"], last_error=note)
        self.store.update("connectors", row["id"], fields)
        return {"connector": summary(self.store.get_connector(row["id"])),
                "status": "updated", "error": None, "dataset": dataset["id"],
                "run": run["id"], "note": note}

    def _carry_mapping(self, row, dataset, language):
        """Give the new snapshot the previous one's mapping when it still
        fits every row; otherwise say why it runs unmapped."""
        previous = (self.store.get_dataset(row["last_dataset_id"])
                    if row.get("last_dataset_id") else None)
        if not previous or not previous.get("mapping_json") or dataset.get("mapping_json"):
            return None
        columns, rows = colmap.table(dataset["content"])
        try:
            clean = colmap.validate(json.loads(previous["mapping_json"]), columns, rows)
        except colmap.MappingError as error:
            detail = error.detail(language)
            reason = detail["errors"][0]["message"] if detail["errors"] else detail["message"]
            if language == "ar":
                return "لم يعد الربط السابق يناسب اللقطة الجديدة، فحُلّلت دون ربط: " + reason
            return ("The previous mapping no longer fits the new snapshot, so it ran "
                    "unmapped: " + reason)
        self.store.update("datasets", dataset["id"], {
            "mapping_json": json.dumps(clean, ensure_ascii=False),
            "mapping_updated_at": self._now()})
        return None

    # -- the worker's side ------------------------------------------------------
    def step(self, worker_id):
        """Refresh one connector that is due. Returns its id, or None."""
        now = self.clock()
        connector_id = self.store.claim_connector(
            worker_id, _stamp(now), _stamp(now + timedelta(seconds=LEASE_SECONDS)))
        if connector_id is None:
            return None
        try:
            self.refresh(connector_id)
        finally:
            self.store.release_connector(connector_id, worker_id)
        return connector_id
