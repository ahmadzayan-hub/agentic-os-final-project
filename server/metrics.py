"""The metric glossary: what a number is allowed to mean.

Every run so far picked its measure by guessing — a column called
"revenue", or failing that the first numeric column. The guess is usually
right and always unaccountable, which is how two reports come to disagree
about revenue and the meeting becomes an argument about the number
instead of a decision about the business.

A glossary makes that choice explicit. It says which column carries which
metric, what the metric means in words, who owns the definition, and —
where the metric is derived — the arithmetic it is supposed to satisfy.
That last part is why this is more than a document: a definition written
as arithmetic can be checked against the data, row by row, and a column
that does not match its own definition is a finding.

The glossary lives in `metrics.json` beside `config.json`, and no file
ships with the repository. That is deliberate. Certifying a metric is a
statement about an organisation — that this definition is agreed and this
person owns it — and inventing a default owner would be fabricating one.
An install with no glossary is uncertified, the runs say so, and that is
the truthful state of affairs rather than a gap to paper over.

Changing a certified definition is therefore a reviewed commit, which is
a stronger control than an edit box. The cost is that a hosted install
cannot give each tenant its own glossary; see docs/adr/0011.
"""

import json
import os
from pathlib import Path

GLOSSARY_VERSION = 1
DEFAULT_FILENAME = "metrics.json"
ENV_VAR = "AGENTIC_OS_METRICS"

# A recorded value is treated as matching its definition within half a
# percent, or one hundredth of a unit for small numbers. Exact equality
# would flag ordinary rounding in a currency column and teach people to
# ignore the check.
RELATIVE_TOLERANCE = 0.005
ABSOLUTE_TOLERANCE = 0.01

# Used only when the glossary says nothing. Kept here rather than in the
# pipeline so that every way of choosing a measure sits in one file and
# can be reported as a decision with a reason.
MEASURE_NAME_HINTS = ("revenue", "sales", "amount", "value", "total")

OPERATIONS = {
    "sum": (2, None),
    "multiply": (2, None),
    "subtract": (2, 2),
    "divide": (2, 2),
}


def glossary_path(env=None, root=None):
    """Where the glossary is read from. Absent is a normal state."""
    env = os.environ if env is None else env
    override = env.get(ENV_VAR)
    if override:
        return Path(override)
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    return root / DEFAULT_FILENAME


def load_glossary(env=None, root=None, path=None):
    """Read the glossary. Returns (metrics, problems) and never raises.

    A broken glossary must not take the run down with it — but it must
    not pass unnoticed either, which is why the problems come back
    alongside the metrics instead of being logged and forgotten. The
    stage turns each one into a failed quality check.
    """
    path = Path(path) if path else glossary_path(env, root)
    if not path.exists():
        return [], []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return [], [f"{path.name} could not be read: {error}"]
    if not isinstance(document, dict):
        return [], [f"{path.name} must contain a JSON object."]
    version = document.get("version")
    if version != GLOSSARY_VERSION:
        return [], [f"{path.name} declares version {version!r}; this build "
                    f"reads version {GLOSSARY_VERSION}."]
    entries = document.get("metrics")
    if not isinstance(entries, list):
        return [], [f"{path.name} has no \"metrics\" list."]

    metrics, problems, seen = [], [], set()
    for index, entry in enumerate(entries):
        metric, problem = _validate(entry, index)
        if problem:
            problems.append(problem)
            continue
        if metric["name"].lower() in seen:
            problems.append(f"metric “{metric['name']}” is defined more than "
                            "once; only the first definition is used.")
            continue
        seen.add(metric["name"].lower())
        metrics.append(metric)
    return metrics, problems


def _validate(entry, index):
    """One entry, or a sentence explaining why it was not accepted."""
    where = f"metric #{index + 1}"
    if not isinstance(entry, dict):
        return None, f"{where} is not an object."
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, f"{where} has no name."
    where = f"metric “{name}”"
    definition = entry.get("definition")
    if not isinstance(definition, str) or not definition.strip():
        # A name with no definition is the problem this file exists to
        # solve, restated in a nicer font.
        return None, f"{where} has no definition, so it defines nothing."
    columns = entry.get("columns")
    if not isinstance(columns, list) or not columns or not all(
            isinstance(c, str) and c.strip() for c in columns):
        return None, f"{where} lists no column it appears as."
    certified = bool(entry.get("certified"))
    owner = entry.get("owner")
    if certified and (not isinstance(owner, str) or not owner.strip()):
        # Certification without a named owner is a rubber stamp: there is
        # nobody to ask when the definition is wrong.
        return None, (f"{where} is marked certified but names no owner. "
                      "A certified metric needs someone accountable for it.")
    formula = entry.get("formula")
    if formula is not None:
        problem = _validate_formula(formula, where)
        if problem:
            return None, problem
    return {
        "name": name.strip(),
        "title": (entry.get("title") or name).strip(),
        "definition": definition.strip(),
        "owner": owner.strip() if isinstance(owner, str) else None,
        "unit": entry.get("unit") or None,
        "certified": certified,
        "certified_on": entry.get("certified_on") or None,
        "columns": [c.strip() for c in columns],
        "formula": formula,
    }, None


def _validate_formula(formula, where):
    if not isinstance(formula, dict) or len(formula) != 1:
        return (f"{where} has a formula that is not a single operation "
                f"({', '.join(sorted(OPERATIONS))}).")
    (operation, operands), = formula.items()
    if operation not in OPERATIONS:
        return (f"{where} uses unknown operation “{operation}”. Supported: "
                f"{', '.join(sorted(OPERATIONS))}.")
    minimum, maximum = OPERATIONS[operation]
    if (not isinstance(operands, list)
            or not all(isinstance(o, str) and o.strip() for o in operands)):
        return f"{where}: “{operation}” takes a list of column names."
    if len(operands) < minimum or (maximum and len(operands) > maximum):
        expected = (f"exactly {maximum}" if maximum else f"at least {minimum}")
        return (f"{where}: “{operation}” takes {expected} columns, "
                f"{len(operands)} given.")
    return None


def formula_columns(formula):
    if not formula:
        return []
    (_, operands), = formula.items()
    return list(operands)


def formula_text(formula):
    """The formula as something a reader can check by hand."""
    if not formula:
        return None
    (operation, operands), = formula.items()
    joiner = {"sum": " + ", "multiply": " × ", "subtract": " − ",
              "divide": " ÷ "}[operation]
    return joiner.join(operands)


def evaluate(formula, row):
    """The formula's value for one row, or None if it cannot be computed."""
    if not formula:
        return None
    (operation, operands), = formula.items()
    values = []
    for column in operands:
        value = row.get(column)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        values.append(float(value))
    if operation == "sum":
        return sum(values)
    if operation == "multiply":
        result = 1.0
        for value in values:
            result *= value
        return result
    if operation == "subtract":
        return values[0] - values[1]
    if not values[1]:
        # Division by zero is a property of the row, not an error in the
        # definition: the row is skipped and counted, never guessed at.
        return None
    return values[0] / values[1]


def matches(recorded, defined):
    return abs(recorded - defined) <= max(RELATIVE_TOLERANCE * abs(defined),
                                          ABSOLUTE_TOLERANCE)


def conformance(metric, rows, column):
    """How often the recorded column equals its own definition.

    Returns None when the formula's inputs are not in this dataset —
    "not checkable here" is a different statement from "checked and
    fine", and reporting them the same way would be a lie of omission.
    """
    formula = metric.get("formula")
    if not formula or not rows:
        return None
    needed = formula_columns(formula)
    if any(name not in rows[0] for name in needed) or column not in rows[0]:
        return None
    checked = matching = skipped = 0
    breaches = []
    for index, row in enumerate(rows):
        recorded = row.get(column)
        if not isinstance(recorded, (int, float)) or isinstance(recorded, bool):
            skipped += 1
            continue
        defined = evaluate(formula, row)
        if defined is None:
            skipped += 1
            continue
        checked += 1
        if matches(float(recorded), defined):
            matching += 1
        else:
            breaches.append({"row": index + 1, "recorded": round(float(recorded), 2),
                             "defined": round(defined, 2),
                             "gap": round(float(recorded) - defined, 2)})
    if not checked:
        return None
    breaches.sort(key=lambda b: -abs(b["gap"]))
    return {"checked": checked, "matching": matching, "skipped": skipped,
            "rate": round(matching / checked, 4), "breaches": breaches[:3],
            "breach_count": len(breaches)}


def resolve(metrics, columns, numeric_columns):
    """Which column this run analyses, and the reason it was chosen.

    Order of authority: a certified metric, then any metric somebody
    wrote down, then a column whose name looks like a measure, then the
    first numeric column. Every step is reported, because "we analysed
    the first numeric column" is a fact the reader is entitled to.
    """
    # Walked in the glossary's order, and within a metric in the order its
    # author listed the columns: a metric that names ["revenue",
    # "net_revenue"] is saying the first one is the canonical carrier,
    # whatever order the file happens to put its columns in.
    candidates, claimed = [], set()
    for metric in metrics:
        for name in metric["columns"]:
            for column in numeric_columns:
                if column.lower() == name.lower() and column not in claimed:
                    claimed.add(column)
                    candidates.append({"column": column, "metric": metric})
    certified = [c for c in candidates if c["metric"]["certified"]]
    if certified:
        chosen = certified[0]
        return (chosen["column"], chosen["metric"], "certified glossary metric",
                candidates)
    if candidates:
        chosen = candidates[0]
        return (chosen["column"], chosen["metric"],
                "glossary metric, not certified", candidates)
    named = next((c for c in numeric_columns if c.lower() in MEASURE_NAME_HINTS),
                 None)
    if named:
        return named, None, "column name", candidates
    return numeric_columns[0], None, "first numeric column", candidates
