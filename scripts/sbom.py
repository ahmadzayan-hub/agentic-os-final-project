#!/usr/bin/env python3
"""Produce a CycloneDX software bill of materials, and check its licences.

    python scripts/sbom.py                      # write sbom.json, print a summary
    python scripts/sbom.py --output -           # to stdout
    python scripts/sbom.py --check              # non-zero exit if a licence breaks policy

Two sources, each taken from the most truthful place available:

* **npm** from `frontend/package-lock.json` — the resolved tree, with the
  integrity hash and licence npm recorded for every package. It is the
  exact set `npm ci` installs, which is what the build consumes.
* **Python** from the installed distributions (`importlib.metadata`),
  narrowed to the closure `requirements.txt` actually reaches. Reading
  versions from the installed packages matters because requirements.txt
  states ranges and an SBOM has to state facts; narrowing to the closure
  matters because a developer's container also carries system packages
  this application has never heard of. This is why the file is generated
  per build rather than committed — a committed SBOM describes the
  machine that last ran the script, which is nobody's machine.

Nothing here reaches the network. An SBOM that needs a package registry
to be reachable is useless in exactly the situation you want one — an
incident, offline, with the registry in question under suspicion.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE = ROOT / "frontend" / "package-lock.json"
REQUIREMENTS = ROOT / "requirements.txt"

# Licences that place conditions on distributing a work that includes
# them. Their presence is not a verdict — it is a question for whoever
# ships the result, and the point of the check is that the question gets
# asked before release rather than after.
STRONG_COPYLEFT = ("GPL-2.0", "GPL-3.0", "AGPL-1.0", "AGPL-3.0", "SSPL",
                   "EUPL", "OSL-3.0", "CPAL")
WEAK_COPYLEFT = ("LGPL", "MPL-2.0", "EPL-1.0", "EPL-2.0", "CDDL")


def _classify(licence):
    """Strong copyleft, weak copyleft, permissive, or unknown."""
    if not licence:
        return "unknown"
    text = licence.upper().replace(" ", "")
    for name in STRONG_COPYLEFT:
        # The leading boundary is what keeps LGPL out of this branch:
        # "GPL-3.0" appears inside "LGPL-3.0", and the letter before it is
        # a letter, so the match fails and LGPL falls through to the weak
        # family below — which is where it belongs, and where psycopg2
        # needs it to be for the gate to stay credible.
        if re.search(rf"(^|[^A-Z]){re.escape(name.upper())}", text):
            return "strong-copyleft"
    for name in WEAK_COPYLEFT:
        if name.upper() in text:
            return "weak-copyleft"
    return "permissive"


def direct_python_requirements():
    """What requirements.txt asks for: {name: {extras}}.

    `pyjwt[crypto]` and `pyjwt` install different trees, so the extras
    are part of the question, not decoration.
    """
    if not REQUIREMENTS.exists():
        return {}
    wanted = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)(?:\[([^\]]*)\])?", line)
        if not match:
            continue
        extras = {e.strip() for e in (match.group(2) or "").split(",") if e.strip()}
        wanted[_normalise(match.group(1))] = extras
    return wanted


def _normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def python_closure(direct):
    """The packages requirements.txt actually pulls in, transitively.

    Listing everything installed would describe the machine rather than
    the project: a developer's container carries system packages
    (launchpadlib, PyGObject) that this application has never heard of,
    and an SBOM naming them is worse than useless — it sends whoever
    reads it chasing dependencies that are not there.

    Extras are honoured where requirements.txt asked for them, because
    `uvicorn[standard]` and plain `uvicorn` install different trees.
    """
    from importlib import metadata

    installed = {}
    for distribution in metadata.distributions():
        try:
            name = distribution.metadata["Name"]
        except Exception:
            continue
        if name:
            installed.setdefault(_normalise(name), distribution)

    wanted, seen = list(direct.items()), {}
    while wanted:
        name, extras = wanted.pop()
        key = _normalise(name)
        if key in seen or key not in installed:
            continue
        distribution = installed[key]
        seen[key] = distribution
        for requirement in distribution.metadata.get_all("Requires-Dist") or []:
            spec, _, marker = requirement.partition(";")
            dependency = re.split(r"[<>=!~\[ (]", spec.strip(), maxsplit=1)[0]
            if not dependency:
                continue
            extra = re.search(r'extra\s*==\s*[\'"]([^\'"]+)[\'"]', marker)
            if extra and extra.group(1) not in extras:
                continue  # an optional feature nobody asked for
            wanted.append((dependency, set()))
    return seen


def python_components(environment=False):
    """The project's Python dependencies, or everything installed."""
    from importlib import metadata

    direct = direct_python_requirements()
    if environment:
        chosen = {}
        for distribution in metadata.distributions():
            try:
                name = distribution.metadata["Name"]
            except Exception:
                continue
            if name:
                chosen.setdefault(_normalise(name), distribution)
    else:
        chosen = python_closure(direct)

    components = []
    for distribution in chosen.values():
        name = distribution.metadata["Name"]
        version = distribution.version or "unknown"
        licence = _python_licence(distribution)
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower()}@{version}",
            "scope": ("required" if _normalise(name) in direct
                      else "optional"),
            "licenses": _licence_entry(licence),
            "properties": [
                {"name": "agentic:ecosystem", "value": "pypi"},
                {"name": "agentic:direct",
                 "value": str(_normalise(name) in direct).lower()},
                {"name": "agentic:licence-class", "value": _classify(licence)},
            ],
        })
    return sorted(components, key=lambda c: c["name"].lower())


def _python_licence(distribution):
    """The licence a distribution declares, from whichever field it used."""
    metadata = distribution.metadata
    declared = metadata.get("License-Expression") or metadata.get("License")
    if declared and declared.strip() and declared.strip() != "UNKNOWN":
        # Some packages paste the whole licence text into this field.
        first = declared.strip().splitlines()[0]
        if len(first) <= 64:
            return first
    classifiers = metadata.get_all("Classifier") or []
    for classifier in classifiers:
        if classifier.startswith("License ::"):
            return classifier.rsplit("::", 1)[-1].strip()
    return None


def npm_components():
    """Every package `npm ci` would install, from the lock file."""
    if not LOCKFILE.exists():
        return []
    document = json.loads(LOCKFILE.read_text(encoding="utf-8"))
    components = []
    for path, entry in document.get("packages", {}).items():
        if not path:
            continue  # the root project, not a dependency
        name = entry.get("name") or path.split("node_modules/")[-1]
        version = entry.get("version", "unknown")
        licence = entry.get("license")
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:npm/{name}@{version}",
            "scope": "optional" if entry.get("dev") else "required",
            "licenses": _licence_entry(licence),
            "properties": [
                {"name": "agentic:ecosystem", "value": "npm"},
                {"name": "agentic:dev-only",
                 "value": str(bool(entry.get("dev"))).lower()},
                {"name": "agentic:licence-class", "value": _classify(licence)},
            ],
        }
        integrity = entry.get("integrity", "")
        if integrity.startswith("sha512-"):
            # The lock file stores base64; CycloneDX wants hex. Recording
            # it in the form npm verifies against is more useful than a
            # conversion nobody can check by eye, so it goes in a property.
            component["properties"].append(
                {"name": "agentic:integrity", "value": integrity})
        components.append(component)
    return sorted(components, key=lambda c: c["name"].lower())


def _licence_entry(licence):
    if not licence:
        return []
    return [{"license": {"name": licence}}]


def build(now=None, environment=False):
    now = now or datetime.now(timezone.utc)
    components = python_components(environment) + npm_components()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": now.replace(microsecond=0).isoformat(),
            "tools": [{"vendor": "Agentic OS", "name": "scripts/sbom.py",
                       "version": "1.0.0"}],
            "component": {"type": "application", "name": "agentic-os",
                          "version": "1.0.0"},
        },
        "components": components,
    }


def summarise(document):
    """Counts by ecosystem and licence class, and anything to look at."""
    counts, classes, unknown, copyleft = {}, {}, [], []
    for component in document["components"]:
        properties = {p["name"]: p["value"] for p in component["properties"]}
        ecosystem = properties.get("agentic:ecosystem", "?")
        counts[ecosystem] = counts.get(ecosystem, 0) + 1
        classification = properties.get("agentic:licence-class", "unknown")
        classes[classification] = classes.get(classification, 0) + 1
        if classification == "unknown":
            unknown.append(component)
        elif classification == "strong-copyleft":
            copyleft.append(component)
    weak_shipped = [c for c in document["components"]
                    if shipped(c) and {p["name"]: p["value"]
                                       for p in c["properties"]}
                    .get("agentic:licence-class") == "weak-copyleft"]
    return {"counts": counts, "classes": classes, "unknown": unknown,
            "strong_copyleft": copyleft, "weak_shipped": weak_shipped}


def shipped(component):
    """Does this component reach a user, or only a developer?

    Only shipped components can create a distribution obligation, which
    is why the check treats them differently from the build toolchain.
    """
    properties = {p["name"]: p["value"] for p in component["properties"]}
    return (properties.get("agentic:dev-only") != "true"
            and component.get("scope") != "optional")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="sbom.json",
                        help="file to write, or - for stdout")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if a shipped dependency carries a "
                             "strong-copyleft licence")
    parser.add_argument("--environment", action="store_true",
                        help="inventory every installed Python distribution "
                             "rather than this project's dependency closure")
    args = parser.parse_args(argv)

    document = build(environment=args.environment)
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if args.output == "-":
        sys.stdout.write(text)
    else:
        Path(args.output).write_text(text, encoding="utf-8")

    report = summarise(document)
    print(f"  components: {len(document['components'])} "
          + ", ".join(f"{count} {name}"
                      for name, count in sorted(report["counts"].items())),
          file=sys.stderr)
    print("  licences:   "
          + ", ".join(f"{count} {name}"
                      for name, count in sorted(report["classes"].items())),
          file=sys.stderr)
    for component in report["weak_shipped"]:
        licences = ", ".join(entry["license"]["name"]
                             for entry in component["licenses"])
        print(f"    ships with a copyleft licence: {component['name']} "
              f"{component['version']} ({licences})", file=sys.stderr)
    for component in report["unknown"][:10]:
        print(f"    no licence declared: {component['name']} "
              f"{component['version']}", file=sys.stderr)
    if args.output != "-":
        print(f"  written to {args.output}", file=sys.stderr)

    if not args.check:
        return 0
    blocking = [c for c in report["strong_copyleft"] if shipped(c)]
    for component in blocking:
        licences = ", ".join(entry["license"]["name"]
                             for entry in component["licenses"])
        print(f"  BLOCKED {component['name']} {component['version']}: "
              f"{licences} is copyleft and this package ships to users.",
              file=sys.stderr)
    if blocking:
        print("  A copyleft dependency is not automatically wrong — it is a "
              "question for whoever distributes this. Answer it, then either "
              "replace the package or record the decision.", file=sys.stderr)
        return 1
    print("  licence check: no shipped dependency carries a strong-copyleft "
          "licence.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
