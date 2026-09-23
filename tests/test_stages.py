"""Custom stages run inside the governance, or they do not run.

Three things have to be true for "add a file" to be a safe way to extend
the pipeline, and each has its own tests here:

- **Loading refuses what it cannot govern.** A stage that shadows a
  built-in role, asks to run after the auditors, has no title or no
  `run`, or cannot be imported, is refused with a sentence — and the
  pipeline runs without it rather than not at all.
- **The contract is enforced, not trusted.** A result is checked field
  by field; ids must carry the stage's role so a custom calculation can
  never be mistaken for a built-in one.
- **Admission means audit.** A custom claim without evidence, or in
  jargon, is caught by the same validator and rejects the run. A custom
  stage cannot change what the built-in stages found (every stage's
  context is rebuilt from the stored results) and cannot rewrite the
  glossary the whole process shares (it is handed a copy). Its failure
  is its own unless it said otherwise, and the report says it failed
  rather than silently lacking it.
"""

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from examples.stages.target_attainment import TargetAttainment
from server import analytics
from server.model_gateway import ModelGateway
from server.runs import RunEngine
from server.stages import (ContractViolation, check_descriptor, describe,
                           load_stages, validate_result)
from server.storage import open_store


def ok(role, **overrides):
    """A minimal well-formed result for `role`."""
    result = {"status": "succeeded", "summary": f"{role} ran.",
              "claims": [{"id": f"{role}.cl_1", "type": "fact",
                          "text": "Something plain was found.",
                          "evidence": [f"{role}.c_1"], "status": "verified"}],
              "calculations": [{"id": f"{role}.c_1", "name": "a_figure",
                                "value": 1, "method": "counted"}],
              "quality_checks": [{"name": "ran", "passed": True, "detail": "yes"}],
              "output": {}}
    result.update(overrides)
    return result


class Stage:
    """A stage in three lines, which is the point."""

    after = "sensitivity"
    can_fail_run = False
    question = None

    def __init__(self, role="custom_stage", title=None, **attributes):
        self.role = role
        self.title = title or f"{role} stage"
        for key, value in attributes.items():
            setattr(self, key, value)

    def run(self, ctx):
        return ok(self.role)


class BadEvidence(Stage):
    def run(self, ctx):
        return ok(self.role, claims=[{
            "id": f"{self.role}.cl_1", "type": "fact", "text": "Costs doubled.",
            "evidence": [f"{self.role}.c_missing"], "status": "verified"}])


class Jargon(Stage):
    def run(self, ctx):
        return ok(self.role, claims=[{
            "id": f"{self.role}.cl_1", "type": "fact",
            "text": "The p-value is below 0.05 so the result is statistically significant.",
            "evidence": [f"{self.role}.c_1"], "status": "verified"}])


class Mutator(Stage):
    """Tries to rewrite what the built-in stages found."""

    def run(self, ctx):
        ctx["preparer"]["total"] = 0
        ctx["preparer"]["groups"] = {}
        ctx["descriptive_result"]["claims"] = []
        return ok(self.role)


class Recorder(Stage):
    """Records what it was shown, so a test can see the context is intact."""

    def run(self, ctx):
        return ok(self.role, output={"total_seen": ctx["preparer"]["total"],
                                     "claims_seen": len(ctx["descriptive_result"]["claims"])})


class GlossaryHijacker(Stage):
    """Certifies its own definition of revenue — for every later run."""

    def run(self, ctx):
        ctx["glossary"]["metrics"].append({
            "name": "revenue", "title": "Planted Revenue",
            "definition": "Whatever the plugin says.", "owner": "the plugin",
            "unit": None, "certified": True, "certified_on": None,
            "columns": ["revenue"], "formula": None})
        ctx["glossary"]["problems"].append("planted by a plugin")
        return ok(self.role)


class Raiser(Stage):
    def run(self, ctx):
        raise RuntimeError("boom")


class Malformed(Stage):
    def run(self, ctx):
        return {"status": "succeeded"}


class Publisher(Stage):
    """Asks to run after publishing. Refused at load time."""

    after = "publish"


def engine_in(directory, stages=None, profiles=None):
    store = open_store(None, Path(directory) / "agentic.db")
    return RunEngine(store, Path(directory) / "vault", ModelGateway(env={}),
                     stages=stages or {}, profiles=profiles or {})


def registry(*stages):
    return {stage.role: stage for stage in stages}


def settle(engine, run_id):
    for _ in range(60):
        run = engine.advance(run_id)
        if run["state"] not in ("queued", "running"):
            return run
    raise AssertionError("the run did not settle")


def task(run, role):
    return next(t for t in run["tasks"] if t["role"] == role)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class RegistryTestCase(unittest.TestCase):
    def test_loads_a_stage_from_config_with_options(self):
        stages, problems = load_stages(env={}, config={"stages": [
            {"path": "examples.stages.target_attainment.TargetAttainment",
             "options": {"target": 250000}}]})
        self.assertEqual(problems, [])
        self.assertEqual(list(stages), ["target_attainment"])
        self.assertEqual(stages["target_attainment"].target, 250000.0)
        self.assertEqual(describe(stages["target_attainment"]), {
            "role": "target_attainment",
            "title": "Target Attainment Agent — how far from the target?",
            "after": "sensitivity", "question": "Did we hit the target?",
            "can_fail_run": False})

    def test_loads_from_the_environment_variable(self):
        stages, problems = load_stages(
            env={"AGENTIC_OS_STAGES": "tests.test_stages.EnvStage, tests.test_stages.EnvStage2"},
            config={})
        self.assertEqual(problems, [])
        self.assertEqual(list(stages), ["env_stage", "env_stage_2"])

    def test_an_unloadable_path_is_a_sentence_not_a_crash(self):
        stages, problems = load_stages(env={"AGENTIC_OS_STAGES": "nowhere.Nothing"},
                                       config={"stages": ["examples.stages.NotThere",
                                                          {"options": {}}]})
        self.assertEqual(stages, {})
        self.assertEqual(len(problems), 3)
        self.assertIn("could not be loaded", problems[0])
        self.assertIn("runs without it", problems[0])
        self.assertIn("neither a dotted path", problems[2])

    def test_a_built_in_role_cannot_be_shadowed(self):
        self.assertIn("built-in stage's name",
                      check_descriptor(Stage("validator"), {}))
        self.assertIn("built-in stage's name",
                      check_descriptor(Stage("publish"), {}))

    def test_a_stage_cannot_sit_in_the_governed_tail(self):
        for after in ("lineage", "validator", "reporter", "publish"):
            with self.subTest(after=after):
                reason = check_descriptor(Stage("late", after=after), {})
                self.assertIn("governed stages", reason)
        self.assertIn("not a built-in stage",
                      check_descriptor(Stage("lost", after="nowhere"), {}))

    def test_a_duplicate_role_is_refused(self):
        self.assertIn("already registered",
                      check_descriptor(Stage("twice"), {"twice": Stage("twice")}))

    def test_a_stage_needs_a_slug_a_title_and_a_run(self):
        self.assertIn("not a slug", check_descriptor(Stage("Bad Role!"), {}))
        self.assertIn("no title", check_descriptor(Stage("fine", title="  "), {}))
        no_run = Stage("norun")
        no_run.run = None
        self.assertIn("no run(ctx)", check_descriptor(no_run, {}))
        self.assertIsNone(check_descriptor(Stage("fine"), {}))

    def test_a_refused_stage_is_reported_and_the_others_still_load(self):
        stages, problems = load_stages(env={}, config={"stages": [
            "tests.test_stages.Publisher", "tests.test_stages.EnvStage"]})
        self.assertEqual(list(stages), ["env_stage"])
        self.assertEqual(len(problems), 1)
        self.assertIn("was refused", problems[0])
        self.assertIn("governed stages", problems[0])

    def test_a_plain_folder_becomes_importable_through_stages_path(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "my_stage.py").write_text(textwrap.dedent('''
                class MyStage:
                    role = "my_stage"
                    title = "My Stage"
                    def run(self, ctx):
                        return {"status": "succeeded", "summary": "ran"}
            '''), encoding="utf-8")
            stages, problems = load_stages(
                env={}, config={"stages_path": folder, "stages": ["my_stage.MyStage"]})
            self.assertEqual(problems, [])
            self.assertEqual(list(stages), ["my_stage"])
            sys.modules.pop("my_stage", None)


class EnvStage(Stage):
    def __init__(self):
        super().__init__("env_stage")


class EnvStage2(Stage):
    def __init__(self):
        super().__init__("env_stage_2")


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

class ContractTestCase(unittest.TestCase):
    def test_a_well_formed_result_passes(self):
        result = validate_result("custom", ok("custom"))
        self.assertEqual(result["claims"][0]["id"], "custom.cl_1")
        self.assertEqual(result["calculations"][0]["method"], "counted")

    def test_missing_lists_are_normalised_to_empty(self):
        result = validate_result("custom", {"status": "succeeded", "summary": "ran"})
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["output"], {})

    def test_ids_carry_the_stage_role(self):
        bad = ok("custom", calculations=[{"id": "c_total", "name": "x", "value": 1,
                                          "method": "m"}])
        with self.assertRaises(ContractViolation) as caught:
            validate_result("custom", bad)
        self.assertIn("must start with “custom.”", str(caught.exception))

    def test_each_field_is_checked(self):
        cases = {
            "not a dict": ("did not return a dict", "no"),
            "bad status": ("status must be", ok("c", status="done")),
            "empty summary": ("summary must be", ok("c", summary="  ")),
            "claim type": ("claim type must be", ok("c", claims=[
                {"id": "c.cl_1", "type": "opinion", "text": "x", "evidence": []}])),
            "claim evidence": ("evidence must be a list", ok("c", claims=[
                {"id": "c.cl_1", "type": "fact", "text": "x", "evidence": "c.c_1"}])),
            "claim text": ("claim text must be", ok("c", claims=[
                {"id": "c.cl_1", "type": "fact", "text": "", "evidence": []}])),
            "check passed": ("`passed` must be true or false", ok("c", quality_checks=[
                {"name": "n", "passed": "yes", "detail": ""}])),
            "output": ("output must be a dict", ok("c", output=[1])),
            "duplicate id": ("used twice", ok("c", calculations=[
                {"id": "c.c_1", "name": "a", "value": 1, "method": "m"},
                {"id": "c.c_1", "name": "b", "value": 2, "method": "m"}])),
            "not serialisable": ("not JSON-serialisable", ok("c", output={"s": {1, 2}})),
            "too many claims": ("the limit is 50", ok("c", claims=[
                {"id": f"c.cl_{i}", "type": "fact", "text": "x", "evidence": []}
                for i in range(51)])),
        }
        for name, (message, result) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ContractViolation) as caught:
                    validate_result("c", result)
                self.assertIn(message, str(caught.exception))


# ---------------------------------------------------------------------------
# Under the governance
# ---------------------------------------------------------------------------

class GovernanceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_with(self, *stages, profiles=None, profile=None):
        engine = engine_in(self.tmp.name, registry(*stages), profiles)
        run = engine.create_run("Analyse the sample sales dataset", profile=profile)
        return engine, settle(engine, run["id"])

    def test_a_custom_stage_runs_where_it_was_placed_and_is_audited(self):
        engine, run = self.run_with(TargetAttainment(target=3_000_000))
        roles = [t["role"] for t in run["tasks"]]
        self.assertEqual(roles.index("target_attainment"),
                         roles.index("sensitivity") + 1)
        self.assertLess(roles.index("target_attainment"), roles.index("lineage"))
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertEqual(task(run, "target_attainment")["state"], "succeeded")
        self.assertIn("of the target of 3,000,000", task(run, "target_attainment")["summary"])

        # Audited: provenance recorded its calculations, the validator
        # checked its claim's evidence — including the built-in c_total it
        # cites — and everything passed.
        lineage_row = next(t for t in engine.store.get_tasks(run["id"])
                           if t["role"] == "lineage")
        produced = json.loads(lineage_row["result_json"])["output"]["produced_by_stage"]
        self.assertEqual(produced["target_attainment.c_attainment"], "target_attainment")
        validator_task = task(run, "validator")
        self.assertTrue(all(c["passed"] for c in validator_task["quality_checks"]),
                        validator_task["quality_checks"])

        # Reported: its own tab, and the comprehensive report carries the
        # section, the claim with its evidence, and the calculations.
        section = next(s for s in run["reports"] if s["type"] == "target_attainment")
        self.assertEqual(section["question"], "Did we hit the target?")
        self.assertEqual(section["title"], TargetAttainment.title)
        self.assertIn("of the target", section["headline"])
        report = run["report"]["content"]
        self.assertIn("## Custom stages", report)
        self.assertIn("- **Target Attainment Agent — how far from the target?:** Revenue",
                      report)
        self.assertIn("| target | 3000000.0 | operator-supplied target", report)
        self.assertIn("| target_attainment | 1.1945 | total_revenue / target |", report)
        self.assertIn("| calculation | target_attainment.c_attainment, "
                      "target_attainment.c_gap, c_total | verified |", report)
        self.assertIn("Did we hit the target?", report)

    def test_a_custom_claim_without_evidence_is_caught_by_the_validator(self):
        _, run = self.run_with(BadEvidence("bad_evidence"))
        self.assertEqual(task(run, "bad_evidence")["state"], "succeeded")
        self.assertEqual(run["state"], "partially_completed")
        checks = {c["name"]: c for c in task(run, "validator")["quality_checks"]}
        self.assertFalse(checks["every_claim_has_evidence"]["passed"])
        self.assertIn("bad_evidence.cl_1", checks["every_claim_has_evidence"]["detail"])
        self.assertFalse(checks["provenance_chain_is_complete"]["passed"])
        self.assertEqual(task(run, "publish")["state"], "skipped")

    def test_a_custom_claim_in_jargon_is_caught_by_the_validator(self):
        _, run = self.run_with(Jargon("jargon"))
        self.assertEqual(run["state"], "partially_completed")
        checks = {c["name"]: c for c in task(run, "validator")["quality_checks"]}
        self.assertFalse(checks["claims_avoid_statistical_jargon"]["passed"])
        self.assertIn("jargon.cl_1", checks["claims_avoid_statistical_jargon"]["detail"])

    def test_a_custom_stage_cannot_change_what_the_built_in_stages_found(self):
        # The mutator runs first; the recorder, placed after it, sees the
        # original context — and so does the validator. What guarantees
        # this is the durability design: every stage's context is rebuilt
        # from the stored results, so a write to the dict reaches no later
        # stage. (The copy handed to the stage is not what this test
        # proves; the glossary test below is.)
        engine, run = self.run_with(Mutator("mutator"), Recorder("recorder"))
        roles = [t["role"] for t in run["tasks"]]
        self.assertLess(roles.index("mutator"), roles.index("recorder"))
        self.assertEqual(run["state"], "awaiting_approval")
        recorder_row = next(t for t in engine.store.get_tasks(run["id"])
                            if t["role"] == "recorder")
        seen = json.loads(recorder_row["result_json"])["output"]
        self.assertGreater(seen["total_seen"], 0, "the mutator's zero must not be seen")
        self.assertGreater(seen["claims_seen"], 0, "the mutator's emptied claims must not be seen")
        checks = {c["name"]: c for c in task(run, "validator")["quality_checks"]}
        self.assertTrue(checks["group_totals_reconcile"]["passed"])
        self.assertTrue(checks["every_claim_has_evidence"]["passed"])
        self.assertIn("Total revenue is", run["report"]["content"])

    def test_a_custom_stage_cannot_rewrite_the_glossary_every_run_shares(self):
        # The one live object in a stage's context is the metric glossary,
        # read once per process and shared by every run and every tenant.
        # A stage that appended its own certified "revenue" to it would
        # have every later report say so — unless it was handed a copy.
        # Removing the deepcopy in _advance_custom fails this test.
        store = open_store(None, Path(self.tmp.name) / "agentic.db")
        engine = RunEngine(store, Path(self.tmp.name) / "vault", ModelGateway(env={}),
                           glossary={"metrics": [], "problems": []},
                           stages=registry(GlossaryHijacker("hijacker")))
        first = settle(engine, engine.create_run("Analyse the sample sales dataset")["id"])
        self.assertEqual(task(first, "hijacker")["state"], "succeeded")
        self.assertEqual(engine.glossary, {"metrics": [], "problems": []})

        second = settle(engine, engine.create_run("Analyse the sample sales dataset")["id"])
        governance = task(second, "governance")
        self.assertEqual(governance["state"], "succeeded")
        self.assertNotIn("Planted Revenue", second["report"]["content"])
        self.assertNotIn("the plugin", second["report"]["content"])
        self.assertFalse([c for c in governance["quality_checks"]
                          if c["name"].startswith("glossary_entry_")],
                         "the planted problem must not surface as a failed check")

    def test_a_failing_custom_stage_fails_only_itself_and_is_reported(self):
        _, run = self.run_with(Raiser("raiser"))
        self.assertEqual(task(run, "raiser")["state"], "failed")
        self.assertIn("boom", task(run, "raiser")["summary"])
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertIn("**raiser stage:** failed — Custom stage “raiser” failed: boom",
                      run["report"]["content"])

    def test_a_stage_that_may_fail_the_run_does(self):
        _, run = self.run_with(Raiser("fatal", can_fail_run=True))
        self.assertEqual(run["state"], "failed")
        self.assertIn("boom", run["error"])
        self.assertEqual(task(run, "lineage")["state"], "pending")

    def test_a_malformed_result_fails_the_stage_with_the_reason(self):
        _, run = self.run_with(Malformed("malformed"))
        self.assertEqual(task(run, "malformed")["state"], "failed")
        self.assertIn("summary must be non-empty text", task(run, "malformed")["summary"])
        self.assertEqual(run["state"], "awaiting_approval")

    def test_a_stage_that_reports_failure_is_recorded_as_failed(self):
        _, run = self.run_with(TargetAttainment(target=-5))
        self.assertEqual(task(run, "target_attainment")["state"], "failed")
        self.assertIn("must be a positive number", task(run, "target_attainment")["summary"])
        self.assertEqual(run["state"], "awaiting_approval")

    def test_profiles_choose_which_custom_stages_run(self):
        profiles = {"default": [], "targets": ["target_attainment"]}
        stages = registry(TargetAttainment(target=1))
        engine = engine_in(self.tmp.name, stages, profiles)

        plain = engine.create_run("Goal")
        self.assertNotIn("target_attainment", [t["role"] for t in plain["tasks"]])
        chosen = engine.create_run("Goal", profile="targets")
        self.assertIn("target_attainment", [t["role"] for t in chosen["tasks"]])
        with self.assertRaises(ValueError) as caught:
            engine.create_run("Goal", profile="nope")
        self.assertIn("Unknown pipeline profile", str(caught.exception))
        self.assertIn("targets", str(caught.exception))

        # No profiles configured: every registered stage runs.
        every = engine_in(self.tmp.name + "", stages)
        self.assertEqual(every.custom_roles_for(None), ["target_attainment"])

    def test_a_profile_naming_an_unregistered_stage_is_refused(self):
        engine = engine_in(self.tmp.name, {}, {"default": ["ghost"]})
        with self.assertRaises(ValueError) as caught:
            engine.create_run("Goal")
        self.assertIn("not registered: ghost", str(caught.exception))

    def test_a_run_whose_stage_was_unregistered_says_so(self):
        engine = engine_in(self.tmp.name, registry(Stage("gone")))
        run = engine.create_run("Goal")
        engine.stages.clear()
        for _ in range(40):
            run = engine.advance(run["id"])
            if run["state"] != "running":
                break
        self.assertEqual(run["state"], "failed")
        self.assertIn("not built in and not registered", run["error"])


try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class PipelinesApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config_path = root / "config.json"
        self.config_path.write_text(json.dumps({
            "agent_name": "Agentic OS", "version": "1.0.0",
            "memory_file": str(root / "memory.json"),
            "database_file": str(root / "agentic.db"),
            "vault_dir": str(root / "vault"),
            "stages": [
                {"path": "examples.stages.target_attainment.TargetAttainment",
                 "options": {"target": 3000000}},
                "nowhere.Nothing",
            ],
            "profiles": {"default": [], "with-target": ["target_attainment"]},
        }), encoding="utf-8")
        self.client = TestClient(create_app(self.config_path),
                                 raise_server_exceptions=False)

    def test_the_catalogue_lists_stages_profiles_and_problems(self):
        body = self.client.get("/api/pipelines").json()
        self.assertEqual([s["role"] for s in body["stages"]], ["target_attainment"])
        self.assertEqual(body["profiles"], {"default": [], "with-target": ["target_attainment"]})
        self.assertEqual(body["default"], [])
        self.assertEqual(len(body["problems"]), 1)
        self.assertIn("nowhere.Nothing", body["problems"][0])

    def test_health_reports_the_problem_too(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(len(body["stage_problems"]), 1)

    def test_a_run_can_choose_a_profile_and_an_unknown_one_is_refused(self):
        plain = self.client.post("/api/runs", json={"goal": "Goal"}).json()
        self.assertNotIn("target_attainment", [t["role"] for t in plain["tasks"]])
        chosen = self.client.post("/api/runs", json={"goal": "Goal",
                                                     "profile": "with-target"}).json()
        self.assertIn("target_attainment", [t["role"] for t in chosen["tasks"]])
        refused = self.client.post("/api/runs", json={"goal": "Goal", "profile": "nope"})
        self.assertEqual(refused.status_code, 422)
        self.assertIn("Unknown pipeline profile", refused.json()["detail"])


if __name__ == "__main__":
    unittest.main()
