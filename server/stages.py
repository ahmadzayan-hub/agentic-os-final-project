"""Custom agents: stages written outside this repository, run inside its
governance.

The pipeline was a literal list in analytics.py, so pointing the system
at a new domain meant editing that file. This module is the seam that
turns "edit analytics.py" into "add a file": a registry of stages loaded
by dotted path, the way a router is (ADR 0017), and a contract that a
stage's result is checked against before anything is recorded.

What a plugin provides — a class, or an instance, with:

    role          a slug, unique, not a built-in stage's name
    title         what the pipeline list and the run log call it
    after         which built-in stage it follows (default: sensitivity)
    question      optional; set, the stage gets its own report section
    can_fail_run  optional; True means its failure fails the run
    run(ctx)      the stage: a dict in, a result dict out

What the run gives it: a **copy** of the context every built-in stage
sees — the prepared data, every earlier result — so it can read
everything and change nothing. What it must return: the same result
shape every built-in stage returns

    status · summary · claims · calculations · quality_checks · output

and that shape is validated here, field by field, because a stage that
returns something else is a stage the validator cannot audit.

What being admitted means: the stage runs before provenance, validation
and reporting, so its claims are checked for evidence and jargon by the
same validator, its calculations appear in the same provenance chain,
and its section is embedded in the same report that the approval gate
binds to. A custom stage cannot bypass any of that, because there is no
placement after them.

What this is not: a sandbox. A plugin is Python running in this process,
trusted the way the router is. The contract catches mistakes, not
malice; the operator decides what to register.
"""

import importlib
import json
import os
import re
import sys
from pathlib import Path

from server import analytics

ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
BUILT_IN_ROLES = tuple(role for role, _ in analytics.PIPELINE) + ("publish",)
# Provenance, validation, reporting, publishing. Nothing may run after
# these, so everything that runs is audited by them.
GUARDED_TAIL = ("lineage", "validator", "reporter", "publish")
PLACEMENTS = tuple(role for role in BUILT_IN_ROLES if role not in GUARDED_TAIL)
DEFAULT_AFTER = "sensitivity"

STATUSES = ("succeeded", "failed")
CLAIM_TYPES = ("calculation", "fact", "limitation", "warning",
               "recommendation", "assumption", "forecast")
CLAIM_STATUSES = ("verified", "unverified")
MAX_CLAIMS, MAX_CALCULATIONS, MAX_CHECKS = 50, 200, 50
MAX_TEXT = 1000
MAX_SUMMARY = 500


class ContractViolation(ValueError):
    """A result that is not the shape the validator can audit."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def describe(descriptor):
    """The registry entry as the interface and the API see it."""
    return {"role": descriptor.role, "title": descriptor.title,
            "after": getattr(descriptor, "after", DEFAULT_AFTER),
            "question": getattr(descriptor, "question", None) or None,
            "can_fail_run": bool(getattr(descriptor, "can_fail_run", False))}


def check_descriptor(descriptor, registered):
    """Why this object cannot be a stage, or None."""
    role = getattr(descriptor, "role", None)
    if not isinstance(role, str) or not ROLE_PATTERN.match(role):
        return (f"its role {role!r} is not a slug (lowercase letters, digits "
                "and underscores, 2–40 characters, starting with a letter)")
    if role in BUILT_IN_ROLES:
        return f"its role “{role}” is a built-in stage's name and cannot be shadowed"
    if role in registered:
        return f"its role “{role}” is already registered"
    title = getattr(descriptor, "title", None)
    if not isinstance(title, str) or not title.strip():
        return "it has no title"
    if not callable(getattr(descriptor, "run", None)):
        return "it has no run(ctx) method"
    after = getattr(descriptor, "after", DEFAULT_AFTER)
    if after not in PLACEMENTS:
        return (f"it asks to run after “{after}”, which is "
                + ("one of the governed stages — provenance, validation, "
                   "reporting and publishing run after every custom stage, "
                   "so that they audit it"
                   if after in GUARDED_TAIL else
                   "not a built-in stage")
                + f"; choose one of: {', '.join(PLACEMENTS)}")
    question = getattr(descriptor, "question", None)
    if question is not None and not isinstance(question, str):
        return "its question is not text"
    return None


def _instantiate(path, options):
    module_name, _, attribute = str(path).rpartition(".")
    if not module_name:
        raise ValueError("not a dotted path to a class")
    target = getattr(importlib.import_module(module_name), attribute)
    if isinstance(target, type):
        return target(**(options or {}))
    if options:
        raise ValueError("options were given but the target is not a class")
    return target


def _extend_path(entries):
    for entry in entries:
        location = str(Path(entry).expanduser().resolve())
        if location not in sys.path:
            # Ahead of site-packages, behind the project: a plugin folder
            # can shadow nothing this application ships.
            sys.path.insert(1, location)


def load_stages(env=None, config=None):
    """The registered stages, and every reason one could not be.

    Returns `(stages, problems)`: an ordered dict role → descriptor, and
    a list of sentences for an operator. A stage that fails to load
    leaves the pipeline exactly as it was — the run engine, the worker
    and the health endpoint all say so, and none of them stop.

    Sources, in order:

        AGENTIC_OS_STAGES        comma-separated dotted paths (no options)
        config["stages"]         a list of dotted paths, or of
                                 {"path": …, "options": {…}}
        AGENTIC_OS_STAGES_PATH   folders to make importable (os.pathsep)
        config["stages_path"]    the same, a string or a list
    """
    env = os.environ if env is None else env
    config = config or {}
    folders = []
    if env.get("AGENTIC_OS_STAGES_PATH"):
        folders.extend(p for p in env["AGENTIC_OS_STAGES_PATH"].split(os.pathsep) if p)
    configured = config.get("stages_path")
    if isinstance(configured, str):
        folders.append(configured)
    elif isinstance(configured, list):
        folders.extend(str(p) for p in configured)
    _extend_path(folders)

    entries = []
    for path in (env.get("AGENTIC_OS_STAGES") or "").split(","):
        if path.strip():
            entries.append((path.strip(), {}))
    for item in config.get("stages") or []:
        if isinstance(item, str):
            entries.append((item, {}))
        elif isinstance(item, dict) and item.get("path"):
            entries.append((str(item["path"]), item.get("options") or {}))
        else:
            entries.append((repr(item), None))

    stages, problems = {}, []
    for path, options in entries:
        if options is None:
            problems.append(f"Stage entry {path} is neither a dotted path nor "
                            "{\"path\": …, \"options\": {…}}; it was skipped.")
            continue
        try:
            descriptor = _instantiate(path, options)
        except Exception as error:
            problems.append(f"The stage “{path}” could not be loaded "
                            f"({type(error).__name__}: {error}); the pipeline "
                            "runs without it.")
            continue
        reason = check_descriptor(descriptor, stages)
        if reason:
            problems.append(f"The stage “{path}” was refused: {reason}; the "
                            "pipeline runs without it.")
            continue
        stages[descriptor.role] = descriptor
    return stages, problems


# ---------------------------------------------------------------------------
# The result contract
# ---------------------------------------------------------------------------

def _text(value, what, limit=MAX_TEXT, required=True):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ContractViolation(f"{what} must be non-empty text")
    if len(value) > limit:
        raise ContractViolation(f"{what} is longer than {limit} characters")
    return value


def _id(value, role, what, seen):
    if not isinstance(value, str) or not value.startswith(role + "."):
        raise ContractViolation(
            f"{what} id {value!r} must start with “{role}.” — ids carry the "
            "stage they came from, so a custom calculation can never be "
            "mistaken for a built-in one")
    if not re.fullmatch(r"[a-z0-9_.]+", value):
        raise ContractViolation(f"{what} id {value!r} may contain only lowercase "
                                "letters, digits, underscores and dots")
    if value in seen:
        raise ContractViolation(f"{what} id {value!r} is used twice")
    seen.add(value)
    return value


def validate_result(role, result):
    """Check a custom stage's result against the contract and return it
    normalised. Raises ContractViolation with the reason otherwise."""
    if not isinstance(result, dict):
        raise ContractViolation("the stage did not return a dict")
    status = result.get("status")
    if status not in STATUSES:
        raise ContractViolation(f"status must be one of {STATUSES}, not {status!r}")
    summary = _text(result.get("summary"), "summary", MAX_SUMMARY)

    claims = result.get("claims") or []
    calculations = result.get("calculations") or []
    checks = result.get("quality_checks") or []
    for name, value, limit in (("claims", claims, MAX_CLAIMS),
                               ("calculations", calculations, MAX_CALCULATIONS),
                               ("quality_checks", checks, MAX_CHECKS)):
        if not isinstance(value, list):
            raise ContractViolation(f"{name} must be a list")
        if len(value) > limit:
            raise ContractViolation(f"{name} has {len(value)} entries; the limit is {limit}")
    output = result.get("output")
    if output is None:
        output = {}
    if not isinstance(output, dict):
        raise ContractViolation("output must be a dict")

    seen = set()
    clean_calcs = []
    for calc in calculations:
        if not isinstance(calc, dict):
            raise ContractViolation("each calculation must be a dict")
        clean_calcs.append({
            "id": _id(calc.get("id"), role, "calculation", seen),
            "name": _text(calc.get("name"), "calculation name", 200),
            "value": calc.get("value"),
            "method": _text(calc.get("method"), "calculation method"),
        })
    clean_claims = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ContractViolation("each claim must be a dict")
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
            raise ContractViolation("claim evidence must be a list of calculation ids")
        claim_type = claim.get("type")
        if claim_type not in CLAIM_TYPES:
            raise ContractViolation(f"claim type must be one of {CLAIM_TYPES}, "
                                    f"not {claim_type!r}")
        claim_status = claim.get("status", "verified")
        if claim_status not in CLAIM_STATUSES:
            raise ContractViolation(f"claim status must be one of {CLAIM_STATUSES}")
        clean_claims.append({
            "id": _id(claim.get("id"), role, "claim", seen),
            "type": claim_type,
            "text": _text(claim.get("text"), "claim text"),
            "evidence": list(evidence),
            "status": claim_status,
        })
    clean_checks = []
    for check in checks:
        if not isinstance(check, dict):
            raise ContractViolation("each quality check must be a dict")
        if not isinstance(check.get("passed"), bool):
            raise ContractViolation("a quality check's `passed` must be true or false")
        clean_checks.append({
            "name": _text(check.get("name"), "quality check name", 200),
            "passed": check["passed"],
            "detail": _text(check.get("detail"), "quality check detail", required=False),
        })

    clean = {"status": status, "summary": summary, "claims": clean_claims,
             "calculations": clean_calcs, "quality_checks": clean_checks,
             "output": output}
    try:
        json.dumps(clean)
    except (TypeError, ValueError) as error:
        raise ContractViolation(f"the result is not JSON-serialisable ({error})")
    return clean
