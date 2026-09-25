# ADR 0013 — Supply chain: pinned actions and a bill of materials

**Status:** Accepted
**Date:** 2026-09-12

## Context

Every dependency in this project is code somebody else can change after
we chose it. Two places that mattered and were not addressed:

**The CI workflow ran four third-party actions by tag.**
`actions/checkout@v4` is not a version — it is a label GitHub Actions
resolves at run time, and the repository owner can move it. The same line
of YAML before and after a compromise of that repository runs different
code, with a token that can write to this repository. The tag is
convenient exactly because it is mutable, which is the whole problem.

This is not hypothetical: `tj-actions/changed-files` was compromised in
March 2025 by force-pushing malicious code onto existing tags, and it ran
in tens of thousands of workflows within hours. Everyone pinned to a
commit was unaffected. Everyone pinned to a tag was not.

**Nothing said what this project is made of.** 302 packages arrive
through two package managers, and there was no inventory — so "are we
affected by the CVE in X?" had no answer faster than reading two lock
files by hand, and "what are we distributing, and under what licence?"
had no answer at all.

## Decision

**Pin every third-party action to a commit SHA, with the release named
in a comment.**

```yaml
- uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0
```

The SHA is what runs; the comment is what makes an upgrade reviewable. A
bare SHA is unreadable — nobody can tell an upgrade from a substitution
without the version beside it — so both are required, and
`tests/test_sbom.py` fails the build if a `uses:` line carries a tag or
loses its comment. Pinning is a one-line habit that is easy to lose in a
hurry, so it is checked rather than remembered.

The four pins were resolved with `git ls-remote` and each was verified a
second time against its release tag before being written down. They pin
the versions already in use, so nothing about the build changed; newer
majors exist (checkout v7, setup-python v7, setup-node v7,
upload-artifact v7) and upgrading them is a separate change with its own
verification, not something to smuggle in beside a security fix.

**Generate a CycloneDX SBOM on every build** (`scripts/sbom.py`),
uploaded as a CI artifact with a 30-day retention, and fail the build on
a shipped strong-copyleft dependency.

Sources, each taken from the most truthful place available:

- **npm** from `frontend/package-lock.json`: the resolved tree, with the
  integrity hash and licence npm recorded for all 275 packages. It is
  exactly what `npm ci` installs.
- **Python** from the installed distributions, narrowed to the closure
  `requirements.txt` actually reaches, following extras where they were
  asked for (`pyjwt[crypto]`, `uvicorn[standard]`).

Nothing in it touches the network. An SBOM that needs a package registry
to be reachable is useless in the one situation you want one: an
incident, offline, with that registry under suspicion.

## Why the Python side is a closure, not an inventory

The first version listed every installed distribution, which produced 64
Python packages including `launchpadlib`, `PyGObject` and `wadllib` —
Debian's, not this project's — and `PyJWT` twice, at two versions,
because a system package and a pip install both existed. That is an
accurate description of a container and a misleading description of an
application. An incident responder reading it would chase dependencies
that are not there.

Walking the closure from `requirements.txt` gives 27, which is the
project. `--environment` still produces the wider inventory for anyone
auditing a machine rather than the software.

## What the licence gate does and does not do

It fails the build when a package that **ships to users** carries a
strong-copyleft licence (GPL, AGPL, SSPL, EUPL, OSL, CPAL). It reports,
without failing, a shipped weak-copyleft package, anything with no
declared licence, and copyleft in the build toolchain.

That split matters. A GPL linter never leaves a developer's machine and
raises no distribution question; a GPL library inside the shipped
artifact does. Treating the two the same would flag the whole toolchain
and teach everyone to skip the check.

LGPL is classified as weak, deliberately. `psycopg2-binary` — this
project's PostgreSQL driver, and a shipped dependency — is "LGPL with
exceptions". Classifying LGPL as strong would fail every build over a
question that has a well-understood answer for a dynamically-linked
library, and a gate that cries wolf gets switched off. It is named in the
build output instead, every time:

```
ships with a copyleft licence: psycopg2-binary 2.9.13 (LGPL with exceptions)
```

The current result: **302 components — 275 npm, 27 pypi. 286 permissive,
16 weak-copyleft, none strong.** Of the 16, exactly one ships
(psycopg2-binary); the rest are build tooling (axe-core, lightningcss)
that never reaches a user.

## Consequences

- CI does slightly more work and produces an artifact worth keeping: the
  next "are we affected by X?" is a search in `sbom.json`, not an
  afternoon.
- Upgrading an action is now a deliberate act with a visible diff of the
  SHA and the version comment. Dependabot understands this format and
  updates both.
- A new dependency with a strong-copyleft licence stops the build. That
  is the intent — it is a question for whoever distributes this, and the
  point is that it gets asked before release rather than after.

## What is still missing

- **No signed artifacts and no build provenance.** Sigstore/SLSA
  attestation needs a release process, and this project has no releases
  — it has a branch. Adding attestation to a thing nobody downloads
  would be ceremony.
- **The SBOM is not signed either**, so it proves composition, not
  authorship.
- **No vendor register or contingency plan.** Both are documents about an
  organisation, not about this code.
- **`pip-audit` and `npm audit` remain advisory** for Python (ADR-era
  decision: a new transitive CVE should be visible without blocking an
  unrelated change) and blocking at high severity for npm. The SBOM does
  not change that; it makes triage possible.
- **The repository has no LICENSE file.** The gate checks what this
  project *consumes*; what it *grants* is the owner's decision and
  nobody else's to make.
