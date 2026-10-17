"""Live data (ADR 0034): connectors, the fence around them, scheduled
refreshes, and the event stream.

The fence is tested on what server-side request forgery needs: a private
or reserved address however it is written, one private answer among
public ones, a redirect, a source that never stops sending. Refreshes are
tested on SQLite and PostgreSQL for what makes live data wrong: a run
started for content that did not change, a mapping carried onto data it
no longer fits, two workers refreshing one source, and another owner's
connector or events.
"""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server import connectors as c
from server import live
from server.erasure import erase
from server.model_gateway import ModelGateway
from server.runs import RunEngine, _stamp
from server.storage import open_store
from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

from server.auth import issue_local_test_token

SECRET = "connector-test-secret-not-used-anywhere-else"


def source(months=12, measure="revenue"):
    lines = [f"month,region,{measure}"]
    for i in range(months):
        year, month = 2025 + i // 12, i % 12 + 1
        lines.append(f"{year}-{month:02d},North,{100 + 7 * i}")
        lines.append(f"{year}-{month:02d},South,{80 + 3 * i}")
    return ("\n".join(lines) + "\n").encode()


MAPPING = {"roles": {"month": "date", "region": "dimension", "revenue": "measure"},
           "measure": "revenue", "dimension": "region", "date_order": "auto", "grain": "auto"}


def resolver(*addresses):
    return lambda host, port, type=None: [(2, 1, 6, "", (a, port)) for a in addresses]


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, chunk=None):
        self.status, self.body, self.headers = status, body, headers or {}
        self.chunk = chunk

    def getheader(self, name):
        return self.headers.get(name)

    def read1(self, amount):
        if self.chunk is not None:
            return self.chunk  # never ends
        piece, self.body = self.body[:amount], self.body[amount:]
        return piece


def connection(response, seen):
    class FakeConnection:
        def __init__(self, host, address, port, timeout):
            seen.append((host, address, port))

        def request(self, method, path, headers=None):
            seen.append((method, path))

        def getresponse(self):
            return response

        def close(self):
            pass
    return FakeConnection


class FenceTests(unittest.TestCase):

    def refused(self, url, resolve=resolver("93.184.216.34"), env=None):
        with self.assertRaises(c.ConnectorError) as caught:
            c.check_address(url, env or {}, resolve)
        return caught.exception

    def test_only_https_with_a_host_and_no_credentials(self):
        for url in ("http://example.com/a.csv", "ftp://example.com/a.csv", "https://",
                    "example.com/a.csv", "https://user:secret@example.com/a.csv",
                    "file:///etc/passwd", "https://example.com:99999/"):
            with self.subTest(url=url):
                self.refused(url)

    def test_private_and_reserved_addresses_are_refused_however_written(self):
        for address in ("127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1",
                        "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1",
                        "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1"):
            with self.subTest(address=address):
                error = self.refused("https://data.example.com/a.csv", resolver(address))
                self.assertIn("private or reserved", error.message())
                self.assertIn("خاص أو محجوز", error.message("ar"))

    def test_an_ipv4_address_inside_nat64_is_checked_as_ipv4(self):
        for address in ("64:ff9b::a9fe:a9fe", "64:ff9b::7f00:1", "64:ff9b:1::1"):
            with self.subTest(address=address):
                self.refused("https://data.example.com/a.csv", resolver(address))
        c.check_address("https://data.example.com/a.csv", {}, resolver("64:ff9b::5db8:d822"))

    def test_an_address_carrying_a_credential_is_refused(self):
        for query in ("api_key=abc", "token=abc", "X-Amz-Signature=abc", "access_token=x",
                      "sig=1&page=2", "password=p"):
            with self.subTest(query=query):
                error = self.refused(f"https://data.example.com/a.csv?{query}")
                self.assertIn("credential", error.message())
        c.check_address("https://data.example.com/a.csv?page=2&monkey=1", {},
                        resolver("93.184.216.34"))

    def test_a_non_ascii_address_is_sent_percent_encoded(self):
        _, _, path, _ = c.check_address("https://data.example.com/مبيعات 2025.csv?منطقة=شمال",
                                        {}, resolver("93.184.216.34"))
        self.assertTrue(path.isascii())
        self.assertTrue(path.startswith("/%D9%85"))

    def test_one_private_answer_among_public_ones_is_enough(self):
        self.refused("https://data.example.com/a.csv", resolver("93.184.216.34", "10.1.1.1"))

    def test_a_name_that_cannot_be_found(self):
        def fail(*args, **kwargs):
            raise OSError("no such host")
        self.assertEqual(self.refused("https://nowhere.example/a.csv", fail).status, 502)

    def test_the_allowed_hosts_list_closes_it_further(self):
        env = {"AGENTIC_OS_CONNECTOR_HOSTS": "data.example.com"}
        self.refused("https://other.example.com/a.csv", env=env)
        host, _, path, address = c.check_address(
            "https://DATA.example.com/a.csv?x=1", env, resolver("93.184.216.34"))
        self.assertEqual((host, path, address), ("data.example.com", "/a.csv?x=1", "93.184.216.34"))

    def test_the_checked_address_is_the_one_connected_to(self):
        seen = []
        body = c.fetch("https://data.example.com/a.csv", {}, resolver("93.184.216.34"),
                       connection_class=connection(FakeResponse(body=b"a,b\n1,2\n"), seen))
        self.assertEqual(body, b"a,b\n1,2\n")
        self.assertEqual(seen[0], ("data.example.com", "93.184.216.34", 443))
        self.assertEqual(seen[1], ("GET", "/a.csv"))

    def test_a_redirect_is_refused_and_named(self):
        response = FakeResponse(302, headers={"Location": "https://10.0.0.1/a.csv"})
        with self.assertRaises(c.ConnectorError) as caught:
            c.fetch("https://data.example.com/a.csv", {}, resolver("93.184.216.34"),
                    connection_class=connection(response, []))
        self.assertIn("redirects to https://10.0.0.1/a.csv", caught.exception.message())

    def test_an_error_status_is_reported(self):
        with self.assertRaises(c.ConnectorError) as caught:
            c.fetch("https://data.example.com/a.csv", {}, resolver("93.184.216.34"),
                    connection_class=connection(FakeResponse(500), []))
        self.assertEqual(caught.exception.status, 502)
        self.assertIn("500", caught.exception.message("ar"))

    def test_too_large_declared_or_sent(self):
        for response in (FakeResponse(headers={"Content-Length": "5000"}, body=b"x"),
                         FakeResponse(body=b"x" * 5000)):
            with self.subTest(headers=response.headers):
                with self.assertRaises(c.ConnectorError) as caught:
                    c.fetch("https://data.example.com/a.csv", {}, resolver("93.184.216.34"),
                            limit=1000, connection_class=connection(response, []))
                self.assertEqual(caught.exception.status, 413)

    def test_a_source_that_trickles_is_cut_off_in_time(self):
        response = FakeResponse(body=b"x" * 100)
        response.read1 = lambda amount: b"x"  # one byte per receive
        ticks = iter(range(0, 1000))
        with self.assertRaises(c.ConnectorError) as caught:
            c.fetch("https://data.example.com/a.csv", {}, resolver("93.184.216.34"),
                    timeout=15, clock=lambda: next(ticks),
                    connection_class=connection(response, []))
        self.assertEqual(caught.exception.status, 504)

    def test_a_source_that_never_stops_is_cut_off_in_time(self):
        ticks = iter(range(0, 1000, 4))
        with self.assertRaises(c.ConnectorError) as caught:
            c.fetch("https://data.example.com/a.csv", {}, resolver("93.184.216.34"),
                    timeout=15, clock=lambda: next(ticks),
                    connection_class=connection(FakeResponse(chunk=b"x" * 10), []))
        self.assertEqual(caught.exception.status, 504)

    def test_the_fixture_seam_is_closed_unless_configured_and_stays_in_its_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "sales.csv").write_bytes(b"a\n1\n")
            (Path(folder).parent / "outside.csv").write_bytes(b"secret\n")
            self.addCleanup((Path(folder).parent / "outside.csv").unlink)
            with self.assertRaises(c.ConnectorError):
                c.fetch("https://fixtures.invalid/sales.csv", {})
            env = {"AGENTIC_OS_CONNECTOR_FIXTURES": folder}
            self.assertEqual(c.fetch("https://fixtures.invalid/sales.csv", env), b"a\n1\n")
            for name in ("../outside.csv", "..%2Foutside.csv", ".hidden", "missing.csv"):
                with self.subTest(name=name):
                    with self.assertRaises(c.ConnectorError):
                        c.fetch(f"https://fixtures.invalid/{name}", env)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class ConnectorEngineTestCase(unittest.TestCase):
    """Connectors over the run engine, on SQLite."""

    def make_store(self):
        return open_store(None, self.root / "agentic.db")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.make_store()
        self.engine = RunEngine(self.store, self.root / "vault", ModelGateway(),
                                glossary={"metrics": [], "problems": []})
        self.content = {"https://data.example.com/sales.csv": source()}
        self.clock = Clock()
        self.connectors = c.Connectors(self.engine, env={}, fetcher=self.fetch,
                                       clock=self.clock, cooldown=0)

    def fetch(self, url):
        value = self.content[url]
        if isinstance(value, Exception):
            raise value
        return value

    def make(self, owner="alice", **extra):
        return self.connectors.create(owner, "Sales", "https://data.example.com/sales.csv",
                                      "Revenue by region", **extra)

    def run_to_gate(self, run_id):
        for _ in range(80):
            run = self.engine.advance(run_id)
            if run["state"] not in ("queued", "running"):
                return run
        return run

    def test_a_refresh_snapshots_analyses_and_stops_at_the_gate(self):
        connector = self.make()
        result = self.connectors.refresh_now(connector["id"], "alice")
        self.assertEqual(result["status"], "updated")
        run = self.store.get_run(result["run"])
        self.assertEqual(run["connector_id"], connector["id"])
        self.assertEqual(run["dataset_id"], result["dataset"])
        self.assertEqual(run["owner"], "alice")
        # Nothing publishes itself: a person decides at the gate.
        self.assertEqual(self.run_to_gate(result["run"])["state"], "awaiting_approval")
        shown = self.connectors.list("alice")[0]
        self.assertEqual((shown["last_status"], shown["last_run_id"]), ("updated", result["run"]))
        self.assertNotIn("last_sha256", shown)
        self.assertNotIn("lease_owner", shown)

    def test_the_same_content_is_unchanged_and_starts_nothing(self):
        connector = self.make()
        first = self.connectors.refresh_now(connector["id"], "alice")
        second = self.connectors.refresh_now(connector["id"], "alice")
        self.assertEqual(second["status"], "unchanged")
        self.assertIsNone(second["run"])
        self.assertEqual(second["dataset"], first["dataset"])
        self.assertEqual(len(self.store.list_runs("alice")), 1)

    def test_a_mapping_that_still_fits_is_carried_to_the_new_snapshot(self):
        connector = self.make()
        first = self.connectors.refresh_now(connector["id"], "alice")
        self.engine.save_mapping(first["dataset"], "alice", MAPPING)
        self.content["https://data.example.com/sales.csv"] = source(months=13)
        second = self.connectors.refresh_now(connector["id"], "alice")
        self.assertEqual(second["status"], "updated")
        self.assertIsNone(second["note"])
        dataset = self.store.get_dataset(second["dataset"])
        self.assertEqual(json.loads(dataset["mapping_json"])["measure"], "revenue")
        # The run took its own copy, as every run does (ADR 0025).
        self.assertEqual(json.loads(self.store.get_run(second["run"])["mapping_json"])["measure"],
                         "revenue")

    def test_a_mapping_that_no_longer_fits_is_dropped_and_the_reason_given(self):
        connector = self.make(language="ar")
        first = self.connectors.refresh_now(connector["id"], "alice")
        self.engine.save_mapping(first["dataset"], "alice", MAPPING)
        self.content["https://data.example.com/sales.csv"] = source(measure="sales")
        second = self.connectors.refresh_now(connector["id"], "alice")
        self.assertEqual(second["status"], "updated")
        self.assertIn("لم يعد الربط السابق يناسب", second["note"])
        self.assertIsNone(self.store.get_dataset(second["dataset"])["mapping_json"])
        self.assertEqual(self.connectors.list("alice")[0]["last_error"], second["note"])

    def test_a_failure_is_recorded_and_waits_twice_as_long_each_time(self):
        connector = self.make(every_minutes=60)
        self.content["https://data.example.com/sales.csv"] = c.ConnectorError(
            "The source answered 503.", "أجاب المصدر بالرمز 503.", status=502)
        waits = []
        for _ in range(6):
            result = self.connectors.refresh(connector["id"])
            row = self.store.get_connector(connector["id"])
            waits.append(datetime.fromisoformat(row["next_due_at"]) - self.clock.now)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(row["failures"], 6)
        self.assertEqual([w.total_seconds() / 60 for w in waits],
                         [120, 240, 480, 960, 1440, 1440])
        self.assertEqual(self.store.list_runs("alice"), [])
        # A good refresh clears the count and returns to the interval.
        self.content["https://data.example.com/sales.csv"] = source()
        self.connectors.refresh(connector["id"])
        row = self.store.get_connector(connector["id"])
        self.assertEqual(row["failures"], 0)
        self.assertEqual(datetime.fromisoformat(row["next_due_at"]) - self.clock.now,
                         timedelta(minutes=60))

    def test_any_error_while_reading_is_a_recorded_failure_not_a_loop(self):
        connector = self.make(every_minutes=60)
        self.content["https://data.example.com/sales.csv"] = RecursionError("too deep")
        self.assertEqual(self.connectors.step("w1"), connector["id"])
        row = self.store.get_connector(connector["id"])
        self.assertEqual((row["last_status"], row["failures"]), ("failed", 1))
        self.assertIn("RecursionError", row["last_error"])
        self.assertIsNone(self.connectors.step("w1"))  # waits, rather than fetching again

    def test_refresh_now_waits_for_the_cooldown(self):
        connector = self.make()
        connectors = c.Connectors(self.engine, env={}, fetcher=self.fetch, clock=self.clock)
        self.assertEqual(connectors.cooldown, c.COOLDOWN_SECONDS)
        connectors.refresh_now(connector["id"], "alice")
        self.clock.advance(seconds=20)
        with self.assertRaises(c.TooSoon) as caught:
            connectors.refresh_now(connector["id"], "alice")
        self.assertEqual(caught.exception.seconds, 41)
        self.clock.advance(seconds=41)
        self.assertEqual(connectors.refresh_now(connector["id"], "alice")["status"], "unchanged")

    def test_unreadable_content_is_a_failure_in_the_connector_language(self):
        connector = self.make(language="ar")
        self.content["https://data.example.com/sales.csv"] = b"\x00\x01binary"
        result = self.connectors.refresh_now(connector["id"], "alice")
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("؀" <= ch <= "ۿ" for ch in result["error"]))

    def test_the_worker_refreshes_only_what_is_due(self):
        scheduled = self.make(every_minutes=60)
        self.connectors.create("alice", "Manual", "https://data.example.com/sales.csv",
                               "Revenue")  # manual: never due
        self.assertEqual(self.connectors.step("w1"), scheduled["id"])
        self.assertIsNone(self.connectors.step("w1"))
        self.clock.advance(minutes=59)
        self.assertIsNone(self.connectors.step("w1"))
        self.clock.advance(minutes=2)
        self.assertEqual(self.connectors.step("w1"), scheduled["id"])
        self.assertIsNone(self.store.get_connector(scheduled["id"])["lease_owner"])

    def test_the_worker_refreshes_then_takes_the_new_run_to_the_gate(self):
        from server.worker import RunWorker

        connector = self.make(every_minutes=60)
        worker = RunWorker(self.engine, self.store, worker_id="w1", connectors=self.connectors)
        self.assertEqual(worker.refresh_due(), connector["id"])
        self.assertIsNone(worker.refresh_due())
        run_id = self.store.get_connector(connector["id"])["last_run_id"]
        self.assertEqual(worker.step(), run_id)
        self.assertEqual(self.store.get_run(run_id)["state"], "awaiting_approval")

    def test_two_workers_never_refresh_the_same_source(self):
        connector = self.make(every_minutes=60)
        now = self.clock.now
        later = _stamp(now + timedelta(seconds=c.LEASE_SECONDS))
        self.assertEqual(self.store.claim_connector("w1", _stamp(now), later), connector["id"])
        self.assertIsNone(self.store.claim_connector("w2", _stamp(now), later))
        with self.assertRaises(c.Busy):
            self.connectors.refresh_now(connector["id"], "alice")
        # A worker that died stops holding it once the lease runs out.
        after = now + timedelta(seconds=c.LEASE_SECONDS + 1)
        self.assertEqual(self.store.claim_connector(
            "w2", _stamp(after), _stamp(after + timedelta(minutes=2))), connector["id"])

    def test_pausing_stops_the_schedule_and_resuming_makes_it_due(self):
        connector = self.make(every_minutes=60)
        paused = self.connectors.update(connector["id"], "alice", enabled=False)
        self.assertFalse(paused["enabled"])
        self.assertIsNone(paused["next_due_at"])
        self.assertIsNone(self.connectors.step("w1"))
        resumed = self.connectors.update(connector["id"], "alice", enabled=True)
        self.assertEqual(resumed["next_due_at"], _stamp(self.clock.now))
        self.assertEqual(self.connectors.step("w1"), connector["id"])
        manual = self.connectors.update(connector["id"], "alice", every_minutes=None)
        self.assertIsNone(manual["next_due_at"])

    def test_what_a_connector_may_be(self):
        for extra in ({"every_minutes": 5}, {"every_minutes": 60 * 24 * 8},
                      {"every_minutes": True}, {"format": "xls"}):
            with self.subTest(extra=extra):
                with self.assertRaises(c.ConnectorError):
                    self.make(**extra)
        with self.assertRaises(c.ConnectorError):
            self.connectors.create("alice", "Bad", "http://data.example.com/a.csv", "Goal")
        with self.assertRaises(ValueError):
            self.make(profile="no-such-profile")
        for _ in range(c.MAX_PER_OWNER):
            self.make(owner="bob")
        with self.assertRaises(c.ConnectorError) as caught:
            self.make(owner="bob")
        self.assertEqual(caught.exception.status, 429)

    def test_another_owner_cannot_see_or_touch_a_connector(self):
        connector = self.make()
        self.assertEqual(self.connectors.list("mallory"), [])
        for action in (lambda: self.connectors.update(connector["id"], "mallory", enabled=False),
                       lambda: self.connectors.delete(connector["id"], "mallory"),
                       lambda: self.connectors.refresh_now(connector["id"], "mallory")):
            with self.assertRaises(KeyError):
                action()
        self.assertTrue(self.store.get_connector(connector["id"])["enabled"])

    def test_deleting_keeps_the_snapshots_and_runs(self):
        connector = self.make()
        result = self.connectors.refresh_now(connector["id"], "alice")
        self.connectors.delete(connector["id"], "alice")
        self.assertIsNone(self.store.get_connector(connector["id"]))
        self.assertIsNotNone(self.store.get_run(result["run"]))
        self.assertIsNotNone(self.store.get_dataset(result["dataset"]))

    def test_erasing_an_owner_removes_their_connectors(self):
        self.make()
        self.make(owner="bob")
        report = erase(self.store, "alice")
        self.assertEqual(report["deleted"]["connectors"], 1)
        self.assertEqual(len(self.store.list_connectors("bob")), 1)

    def test_the_event_reader_sends_each_change_once_and_resumes_after_its_cursor(self):
        connector = self.make()
        reader = live.Reader(self.store, "alice", live.cursor_now(lambda: self.clock.now
                                                                  - timedelta(seconds=1)))
        self.assertEqual([kind for _, kind, _ in reader.poll()], ["connector"])
        self.assertEqual(reader.poll(), [])
        self.clock.advance(seconds=1)
        result = self.connectors.refresh_now(connector["id"], "alice")
        events = reader.poll()
        kinds = {(kind, data["id"]) for _, kind, data in events}
        self.assertIn(("run", result["run"]), kinds)
        self.assertIn(("connector", connector["id"]), kinds)
        # A new connection from the last id receives nothing it already had.
        resumed = live.Reader(self.store, "alice", live.parse_cursor(events[-1][0]))
        self.assertEqual(resumed.poll(), [])
        # And another owner's stream never carries alice's changes.
        other = live.Reader(self.store, "mallory", ("2000-01-01T00:00:00.000000+00:00", "run", "0"))
        self.assertEqual(other.poll(), [])


@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class ConnectorEnginePostgresTestCase(ConnectorEngineTestCase):

    def make_store(self):
        import psycopg2

        from server.storage import TABLES

        conn = psycopg2.connect(PG_TEST_URL)
        conn.autocommit = True
        conn.cursor().execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        conn.close()
        return open_store(PG_TEST_URL, None)


class FakeStore:
    def __init__(self):
        self.runs, self.connectors = [], []

    def changes_since(self, owner, since, limit, before=None):
        pick = lambda rows: sorted((r for r in rows if r["updated_at"] >= since
                                    and (before is None or r["updated_at"] < before)),
                                   key=lambda r: r["updated_at"])[:limit]
        return pick(self.runs), pick(self.connectors)


def run_row(run_id, at):
    return {"id": run_id, "goal": "g", "state": "running", "connector_id": None,
            "updated_at": at}


class StreamTests(unittest.TestCase):

    def test_a_late_commit_within_the_overlap_is_still_sent(self):
        store = FakeStore()
        store.runs.append(run_row("b", "2026-10-17T09:00:02.000000+00:00"))
        reader = live.Reader(store, "alice", ("2026-10-17T09:00:00.000000+00:00", "run", "0"))
        self.assertEqual([d["id"] for _, _, d in reader.poll()], ["b"])
        # Stamped before "b" but committed after the poll that sent it.
        store.runs.append(run_row("a", "2026-10-17T09:00:01.000000+00:00"))
        self.assertEqual([d["id"] for _, _, d in reader.poll()], ["a"])
        self.assertEqual(reader.poll(), [])

    def test_a_full_page_is_never_skipped_past(self):
        store = FakeStore()
        for i in range(5):
            store.runs.append(run_row(f"r{i}", f"2026-10-17T09:00:0{i}.000000+00:00"))
        store.connectors.append({"id": "k", "name": "n", "enabled": 1, "last_status": None,
                                 "last_error": None, "last_run_id": None,
                                 "last_checked_at": None, "next_due_at": None,
                                 "updated_at": "2026-10-17T09:00:09.000000+00:00"})
        original, live.MAX_ROWS = live.MAX_ROWS, 2
        self.addCleanup(setattr, live, "MAX_ROWS", original)
        reader = live.Reader(store, "alice", ("2026-10-17T08:00:00.000000+00:00", "run", "0"))
        sent = []
        for _ in range(6):
            sent += [d["id"] for _, _, d in reader.poll()]
        self.assertEqual(sent, ["r0", "r1", "r2", "r3", "r4", "k"])

    def test_a_cursor_must_have_its_exact_shape(self):
        self.assertIsNone(live.parse_cursor("2026-10-17T09:00:00+00:00~run~x y"))
        self.assertIsNone(live.parse_cursor("'; DROP TABLE runs; --"))
        # Exactly the stamp the server writes: six fraction digits.
        self.assertIsNone(live.parse_cursor("2026-10-17T09:00:00.5+00:00~connector~ab12"))
        self.assertEqual(live.parse_cursor("2026-10-17T09:00:00.500000+00:00~connector~ab12"),
                         ("2026-10-17T09:00:00.500000+00:00", "connector", "ab12"))

    def test_the_stream_says_where_to_resume_beats_and_ends(self):
        store = FakeStore()
        store.runs.append(run_row("a", "2026-10-17T09:00:01.000000+00:00"))
        reader = live.Reader(store, "alice", ("2026-10-17T09:00:00.000000+00:00", "run", "0"))
        clock = [0.0]

        async def poll():
            return reader.poll()

        async def sleep(seconds):
            clock[0] += max(seconds, 1.0)

        async def disconnected():
            return False

        async def collect():
            return [part async for part in live.stream(
                reader, poll, sleep, lambda: clock[0], disconnected, max_seconds=40)]

        parts = asyncio.run(collect())
        self.assertEqual(parts[0], "retry: 3000\n\n")
        self.assertTrue(parts[1].startswith("id: 2026-10-17T09:00:00.000000+00:00~run~0\nevent: ready"))
        self.assertTrue(parts[2].startswith("id: 2026-10-17T09:00:01.000000+00:00~run~a\nevent: run\n"))
        self.assertEqual(json.loads(parts[2].split("data: ", 1)[1])["id"], "a")
        self.assertEqual(parts.count(live.heartbeat()), 2)
        self.assertLessEqual(clock[0], 41)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ConnectorApiTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        fixtures = root / "fixtures"
        fixtures.mkdir()
        (fixtures / "sales.csv").write_bytes(source())
        path = root / "config.json"
        path.write_text(json.dumps({"agent_name": "T", "database_file": str(root / "a.db"),
                                    "memory_file": str(root / "m.json"),
                                    "vault_dir": str(root / "v")}), encoding="utf-8")
        self.app = create_app(path, env={
            "AGENTIC_OS_JWT_SECRET": SECRET, "AGENTIC_OS_ENV": "production",
            "AGENTIC_OS_CONNECTOR_FIXTURES": str(fixtures),
            "AGENTIC_OS_CONNECTOR_COOLDOWN": "0"})
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.alice = self.auth("alice")

    def auth(self, subject, role="analyst"):
        return {"Authorization": "Bearer " + issue_local_test_token(
            SECRET, subject=subject, role=role)}

    def create(self, headers=None, **body):
        return self.client.post("/api/connectors", headers=headers or self.alice, json={
            "name": "Sales", "url": "https://fixtures.invalid/sales.csv",
            "goal": "Revenue by region", **body})

    def events(self, headers, last=None):
        response = self.client.get("/api/events?wait=0", headers={
            **headers, **({"Last-Event-ID": last} if last else {})})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["cache-control"], "no-store")
        blocks = [b for b in response.text.split("\n\n") if b.startswith("id:")]
        return [dict(line.split(": ", 1) for line in block.split("\n")) for block in blocks]

    def test_create_refresh_and_see_it_on_the_event_stream(self):
        ready = self.events(self.alice)
        self.assertEqual([e["event"] for e in ready], ["ready"])
        created = self.create(every_minutes=60)
        self.assertEqual(created.status_code, 201)
        connector = created.json()
        self.assertTrue(connector["enabled"])
        refreshed = self.client.post(f"/api/connectors/{connector['id']}/refresh",
                                     headers=self.alice).json()
        self.assertEqual(refreshed["status"], "updated")
        again = self.client.post(f"/api/connectors/{connector['id']}/refresh",
                                 headers=self.alice).json()
        self.assertEqual(again["status"], "unchanged")
        run = self.client.get(f"/api/runs/{refreshed['run']}", headers=self.alice).json()
        self.assertEqual(run["connector_id"], connector["id"])

        events = self.events(self.alice, ready[0]["id"])
        runs = [json.loads(e["data"]) for e in events if e["event"] == "run"]
        self.assertEqual([r["id"] for r in runs], [refreshed["run"]])
        self.assertEqual(runs[0]["connector_id"], connector["id"])
        self.assertIn("connector", {e["event"] for e in events})
        # Resuming from the last event repeats nothing.
        self.assertEqual([e["event"] for e in self.events(self.alice, events[-1]["id"])],
                         ["ready"])

    def test_refresh_now_too_soon_is_429_with_a_wait(self):
        self.app.state.connectors.cooldown = 60
        connector = self.create().json()
        self.client.post(f"/api/connectors/{connector['id']}/refresh", headers=self.alice)
        again = self.client.post(f"/api/connectors/{connector['id']}/refresh?language=ar",
                                 headers=self.alice)
        self.assertEqual(again.status_code, 429)
        self.assertGreater(int(again.headers["retry-after"]), 0)
        self.assertIn("حُدّث هذا المصدر للتو", again.json()["detail"])

    def test_an_owner_may_hold_only_a_few_streams(self):
        import server.live as live_module

        original, live_module.MAX_STREAMS_PER_OWNER = live_module.MAX_STREAMS_PER_OWNER, 0
        self.addCleanup(setattr, live_module, "MAX_STREAMS_PER_OWNER", original)
        response = self.client.get("/api/events?wait=0", headers=self.alice)
        self.assertEqual(response.status_code, 429)
        live_module.MAX_STREAMS_PER_OWNER = original
        # A closed stream gives its place back.
        for _ in range(original + 2):
            self.assertEqual(self.client.get("/api/events?wait=0",
                                             headers=self.alice).status_code, 200)

    def test_an_unreadable_resume_point_starts_from_now(self):
        self.create()
        events = self.events(self.alice, "not-a-cursor")
        self.assertEqual([e["event"] for e in events], ["ready"])

    def test_refusals_in_the_reader_language(self):
        response = self.client.post("/api/connectors?language=ar", headers=self.alice, json={
            "name": "Sales", "url": "http://example.com/a.csv", "goal": "g"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("https://", response.json()["detail"])
        self.assertIn("يجب", response.json()["detail"])
        bad_every = self.create(every_minutes=5)
        self.assertEqual(bad_every.status_code, 422)
        missing = self.client.post("/api/connectors", headers=self.alice, json={
            "name": "Missing", "url": "https://fixtures.invalid/missing.csv", "goal": "g"}).json()
        failed = self.client.post(f"/api/connectors/{missing['id']}/refresh?language=ar",
                                  headers=self.alice).json()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "The source answered 404.")

    def test_pause_resume_and_delete(self):
        connector = self.create(every_minutes=60).json()
        paused = self.client.put(f"/api/connectors/{connector['id']}", headers=self.alice,
                                 json={"enabled": False}).json()
        self.assertFalse(paused["enabled"])
        self.assertEqual(paused["every_minutes"], 60)
        manual = self.client.put(f"/api/connectors/{connector['id']}", headers=self.alice,
                                 json={"every_minutes": None, "enabled": True}).json()
        self.assertIsNone(manual["every_minutes"])
        self.assertEqual(self.client.delete(f"/api/connectors/{connector['id']}",
                                            headers=self.alice).status_code, 204)
        self.assertEqual(self.client.get("/api/connectors", headers=self.alice).json(),
                         {"connectors": []})

    def test_another_owner_sees_nothing_and_touches_nothing(self):
        connector = self.create().json()
        mallory = self.auth("mallory")
        self.assertEqual(self.client.get("/api/connectors", headers=mallory).json(),
                         {"connectors": []})
        for method, path, body in (("put", f"/api/connectors/{connector['id']}", {"enabled": False}),
                                   ("delete", f"/api/connectors/{connector['id']}", None),
                                   ("post", f"/api/connectors/{connector['id']}/refresh", None)):
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(
                    path, headers=mallory, **({"json": body} if body is not None else {}))
                self.assertEqual(response.status_code, 404)
        refreshed = self.client.post(f"/api/connectors/{connector['id']}/refresh",
                                     headers=self.alice).json()
        self.assertEqual([e["event"] for e in self.events(mallory, "2000-01-01T00:00:00.000000+00:00~run~0")],
                         ["ready"])
        self.assertEqual(refreshed["status"], "updated")

    def test_a_viewer_reads_but_cannot_add_or_refresh(self):
        connector = self.create().json()
        viewer = self.auth("alice", role="viewer")
        self.assertEqual(self.client.get("/api/connectors", headers=viewer).status_code, 200)
        self.assertEqual(self.create(headers=viewer).status_code, 403)
        self.assertEqual(self.client.post(f"/api/connectors/{connector['id']}/refresh",
                                          headers=viewer).status_code, 403)


if __name__ == "__main__":
    unittest.main()
