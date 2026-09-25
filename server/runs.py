"""Durable run engine: goal -> plan -> tasks -> approval -> artifact.

State is persisted through a storage adapter (SQLite locally, hosted
PostgreSQL via DATABASE_URL — see server/storage.py) after every
transition, so runs survive an application restart and can be resumed,
cancelled, or approved later. Execution is client-stepped: each
`advance()` call executes exactly one bounded task under a lock, which
gives honest pause (stop advancing), cancel, and recovery semantics
without a background worker.

The publish step writes the approved report into an Obsidian-compatible
vault folder (markdown + provenance frontmatter + [[wikilinks]]) and is
gated by a server-enforced approval bound to the exact artifact hash —
a manipulated client cannot publish unapproved or altered content.
"""

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from server import analytics, metrics, quota
from server import stages as stage_registry

RUN_STATES = {"queued", "running", "awaiting_approval", "verifying",
              "completed", "partially_completed", "failed", "cancelled"}
TASK_STATES = {"pending", "running", "succeeded", "failed", "skipped",
               "awaiting_approval", "cancelled"}

RUN_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"running", "awaiting_approval", "completed",
                "partially_completed", "failed", "cancelled"},
    "awaiting_approval": {"running", "completed", "partially_completed",
                          "cancelled"},
    "completed": set(), "partially_completed": set(), "failed": set(),
    "cancelled": set(),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _utcnow():
    return datetime.now(timezone.utc)


def _stamp(moment):
    """Lease timestamps are compared as text by the database, so they use
    a fixed width — `isoformat()` drops the fraction on a whole second."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


class RunEngine:
    def __init__(self, store, vault_dir, gateway, limits=None, glossary=None,
                 stages=None, profiles=None):
        self.store = store
        # Custom stages (ADR 0020): role -> descriptor, in registration
        # order, and the named profiles that choose among them.
        self.stages = dict(stages or {})
        self.profiles = dict(profiles or {})
        self.vault_dir = Path(vault_dir)
        self.gateway = gateway
        # None disables quota enforcement entirely (the CLI and tests that
        # are not about quotas); the API always passes limits.
        self.limits = limits
        # The metric glossary is read once at startup rather than per run,
        # so every run in a process agrees about what a metric means and
        # editing the file mid-run cannot change a report halfway through.
        # None means "read the configured file"; pass a dict to override.
        if glossary is None:
            entries, problems = metrics.load_glossary()
            glossary = {"metrics": entries, "problems": problems}
        self.glossary = glossary

    # -- state helpers ----------------------------------------------------
    def _set_run_state(self, run_id, new_state, error=None):
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        current = run["state"]
        if new_state != current and new_state not in RUN_TRANSITIONS[current]:
            raise ValueError(f"Illegal run transition {current} -> {new_state}")
        self.store.update(
            "runs", run_id,
            {"state": new_state, "error": error, "updated_at": _now()})

    def _set_task(self, task_id, state, summary=None, result=None):
        fields = {"state": state, "updated_at": _now()}
        if summary is not None:
            fields["summary"] = summary
        if result is not None:
            fields["result_json"] = json.dumps(result)
        self.store.update("tasks", task_id, fields)

    # -- API --------------------------------------------------------------
    def store_dataset(self, text, name, owner):
        """Content-addressed storage: identical uploads share one row."""
        digest = hashlib.sha256(text.encode()).hexdigest()
        existing = self.store.find_dataset(digest, owner)
        if existing:
            # Already stored: consumes no new space, so no quota applies.
            return existing
        if self.limits:
            quota.check_dataset(self.store, owner, self.limits,
                                len(text.encode()))
        dataset_id = uuid.uuid4().hex[:12]
        self.store.insert("datasets", {
            "id": dataset_id, "sha256": digest, "name": name,
            "content": text, "byte_size": len(text.encode()),
            "owner": owner, "created_at": _now()})
        return self.store.get_dataset(dataset_id)

    def custom_roles_for(self, profile=None):
        """Which registered stages a run includes. A profile names a
        subset; no profile means the "default" profile when one is
        configured, else every registered stage."""
        if profile is None:
            chosen = self.profiles.get("default")
            if chosen is None:
                return list(self.stages)
        else:
            chosen = self.profiles.get(profile)
            if chosen is None:
                available = ", ".join(sorted(self.profiles)) or "none"
                raise ValueError(f"Unknown pipeline profile “{profile}”. "
                                 f"Available: {available}.")
        unknown = [role for role in chosen if role not in self.stages]
        if unknown:
            raise ValueError(f"Profile “{profile or 'default'}” names stages "
                             f"that are not registered: {', '.join(unknown)}.")
        return list(chosen)

    def roles_for(self, profile=None):
        """The run's stage order: the built-in pipeline with each custom
        stage inserted after the built-in stage it asked for. Custom
        stages can only be placed before the governed tail, so every
        one of them runs before provenance, validation and reporting."""
        custom = self.custom_roles_for(profile)
        roles = []
        for role, _ in analytics.PIPELINE:
            roles.append(role)
            roles.extend(r for r in custom
                         if getattr(self.stages[r], "after",
                                    stage_registry.DEFAULT_AFTER) == role)
        return roles + ["publish"]

    def create_run(self, goal, dataset_text=None, dataset_name=None,
                   owner="local-owner", dataset_id=None, profile=None,
                   language="en"):
        # An unknown profile, or a language reports are not written in, is
        # refused before anything is written.
        roles = self.roles_for(profile)
        if language not in analytics.REPORT_LANGUAGES:
            raise ValueError(f"Reports are not written in “{language}”.")
        # Checked before anything is written, so a refused run leaves no
        # half-created rows behind.
        if self.limits:
            quota.check_run(self.store, owner, self.limits)
        run_id = uuid.uuid4().hex[:12]
        if dataset_id:
            dataset = self.store.get_dataset(dataset_id)
            if dataset is None or dataset["owner"] != owner:
                raise KeyError(dataset_id)
        else:
            text = dataset_text or analytics.sample_dataset()
            name = dataset_name or (
                "uploaded dataset" if dataset_text else "sample sales dataset")
            dataset = self.store_dataset(text, name, owner)
        now = _now()
        self.store.insert("runs", {
            "id": run_id, "goal": goal.strip(),
            "dataset_name": dataset["name"],
            # dataset_text stays populated for backward compatibility with
            # rows written before datasets were content-addressed.
            "dataset_text": "", "state": "queued",
            "created_at": now, "updated_at": now, "error": None,
            "owner": owner, "dataset_id": dataset["id"],
            # Fixed for the run's life: the approval gate binds to the hash
            # of one artifact, written in one language (ADR 0022).
            "report_language": language})
        titles = analytics.ROLE_TITLES_AR if language == "ar" else analytics.ROLE_TITLES
        for idx, role in enumerate(roles):
            title = titles.get(role) or self.stages[role].title
            self.store.insert("tasks", {
                "id": uuid.uuid4().hex[:12], "run_id": run_id, "idx": idx,
                "role": role, "title": title,
                "state": "pending", "summary": None, "result_json": None,
                "updated_at": now})
        return self.get_run(run_id)

    def _dataset_text(self, run):
        dataset_id = run.get("dataset_id")
        if dataset_id:
            dataset = self.store.get_dataset(dataset_id)
            if dataset is not None:
                return dataset["content"]
        return run.get("dataset_text") or ""

    def _context(self, run, tasks):
        ctx = {"goal": run["goal"], "dataset_text": self._dataset_text(run),
               "dataset_name": run["dataset_name"], "run_id": run["id"],
               "glossary": self.glossary,
               "report_language": run.get("report_language") or "en"}
        for task in tasks:
            if task["state"] == "succeeded" and task["result_json"]:
                result = json.loads(task["result_json"])
                ctx[task["role"]] = result.get("output", {})
                ctx[task["role"] + "_result"] = result
        # The run declares its custom stages, and provenance, validation
        # and the report audit exactly that list (analytics.evidence_stages).
        custom = [t["role"] for t in tasks
                  if t["role"] not in analytics.ROLE_TITLES]
        ctx["custom_stages"] = custom
        ctx["custom_titles"] = {t["role"]: t["title"] for t in tasks
                                if t["role"] in custom}
        ctx["custom_failures"] = {t["role"]: t["summary"] for t in tasks
                                  if t["role"] in custom and t["state"] == "failed"}
        return ctx

    def _reclaim_orphaned_tasks(self, run_id):
        """Put back any task a crash left marked running.

        A worker killed between tasks leaves nothing behind; killed
        *during* one it leaves that task marked running forever, and the
        engine used to walk straight past it to the next pending task.
        The run then continued without a stage its successors depend on
        and failed several stages later, with an error naming the wrong
        thing entirely — a crash mid-stage silently producing a broken
        run, which is the failure durability was supposed to rule out.

        Reaching this point means nobody holds a live lease on the run
        (the caller's own, or none), so a task marked running is not
        being executed by anyone: it is debris. Re-running it is safe
        because a stage is a pure function of the results before it, and
        a task's result is written once, at the end.
        """
        tasks = self.store.get_tasks(run_id)
        orphans = [t for t in tasks if t["state"] == "running"]
        for task in orphans:
            self.store.update("tasks", task["id"],
                              {"state": "pending", "summary": None,
                               "result_json": None})
        return self.store.get_tasks(run_id) if orphans else tasks

    def advance(self, run_id, lease_owner=None):
        """Execute exactly one bounded task; every transition is durable.

        If a background worker holds a live lease on this run, a client's
        advance is a no-op that simply returns the current state: the two
        never execute the same task. When the worker dies its lease
        expires and clients resume stepping the run themselves.
        """
        run = self._row(run_id)
        if run.get("paused"):
            raise ValueError("Run is paused — resume it before advancing.")
        holder = run.get("lease_owner")
        if (holder and holder != lease_owner
                and (run.get("lease_expires_at") or "") > _stamp(_utcnow())):
            return self.get_run(run_id)
        if run["state"] in ("completed", "partially_completed", "failed", "cancelled"):
            raise ValueError(f"Run is {run['state']} and cannot advance.")
        if run["state"] == "awaiting_approval":
            raise ValueError("Run is awaiting approval — decide the approval first.")
        tasks = self._reclaim_orphaned_tasks(run_id)
        task = next((t for t in tasks if t["state"] == "pending"), None)
        if task is None:
            return self.get_run(run_id)
        self._set_run_state(run_id, "running")

        if task["role"] == "publish":
            return self._request_publish_approval(run_id, task)

        stage = dict(analytics.PIPELINE).get(task["role"])
        custom = self.stages.get(task["role"])
        if stage is None and custom is None:
            # A run created by an earlier pipeline version, or with a
            # custom stage that is no longer registered. Say so plainly
            # rather than failing with an unrelated error later.
            message = (f"This run was created with a pipeline this server does "
                       f"not have (stage “{task['role']}” is not built in and not "
                       "registered) and cannot be resumed. Its stored results "
                       "remain readable; start a new run to analyze the same "
                       "data with the current pipeline.")
            self._set_task(task["id"], "failed", summary=message)
            self._set_run_state(run_id, "failed", error=message)
            return self.get_run(run_id)

        self._set_task(task["id"], "running")
        ctx = self._context(run, tasks)
        if custom is not None:
            return self._advance_custom(run_id, task, custom, ctx)
        try:
            result = (stage(ctx, gateway=self.gateway)
                      if task["role"] in analytics.NARRATED_STAGES else stage(ctx))
        except Exception as error:  # defensive: a stage bug must not hang the run
            self._set_task(task["id"], "failed", summary=f"Stage error: {error}")
            self._set_run_state(run_id, "failed", error=str(error))
            return self.get_run(run_id)

        if result["status"] == "failed" and task["role"] != "validator":
            self._set_task(task["id"], "failed", summary=result["summary"], result=result)
            self._set_run_state(run_id, "failed", error=result["summary"])
            return self.get_run(run_id)

        self._set_task(task["id"], "succeeded", summary=result["summary"], result=result)

        if task["role"] == "validator" and not result["output"]["passed"]:
            # Rejected work: skip publishing, finish as partially completed.
            for t in self.store.get_tasks(run_id):
                if t["state"] == "pending":
                    self._set_task(t["id"], "skipped",
                                   summary="Skipped: validation rejected the work.")
            self._set_run_state(run_id, "partially_completed",
                                error="Validation checks failed.")
            return self.get_run(run_id)

        if task["role"] == "reporter":
            self.store.insert("artifacts", {
                "id": uuid.uuid4().hex[:12], "run_id": run_id,
                "name": "analytics-report", "kind": "markdown", "version": 1,
                "content": result["output"]["report_markdown"],
                "published_path": None, "created_at": _now()})
        return self.get_run(run_id)

    def _advance_custom(self, run_id, task, descriptor, ctx):
        """Run a registered stage under the contract (ADR 0020).

        What the built-in stages found is safe from it because every
        stage's context is rebuilt from the stored results (a write to
        this dict reaches no later stage). The copy is for the one live
        object in the context: the glossary, read once per process and
        shared by every run — a stage must not be able to certify its
        own definition of revenue for everyone who runs after it. Its
        result is checked against the contract before anything is
        recorded. A failure is the stage's, not the run's, unless the
        stage declared otherwise — and the report then says the stage
        failed rather than silently lacking it.
        """
        try:
            result = descriptor.run(copy.deepcopy(ctx))
            result = stage_registry.validate_result(task["role"], result)
        except Exception as error:
            message = f"Custom stage “{task['role']}” failed: {error}"
            return self._custom_failed(run_id, task, descriptor, message)
        if result["status"] == "failed":
            return self._custom_failed(run_id, task, descriptor,
                                       result["summary"], result)
        self._set_task(task["id"], "succeeded", summary=result["summary"],
                       result=result)
        return self.get_run(run_id)

    def _custom_failed(self, run_id, task, descriptor, message, result=None):
        self._set_task(task["id"], "failed", summary=message, result=result)
        if getattr(descriptor, "can_fail_run", False):
            self._set_run_state(run_id, "failed", error=message)
        return self.get_run(run_id)

    def _request_publish_approval(self, run_id, task):
        # The approval is read by the same person who reads the report, so
        # it is in the report's language. `risk` stays an enum (ADR 0022).
        arabic = (self._row(run_id).get("report_language") or "en") == "ar"
        artifact = self.store.latest_artifact(run_id)
        if artifact is None:
            self._set_task(task["id"], "skipped",
                           summary="لا يوجد ما يُنشر." if arabic
                           else "No artifact to publish.")
            self._set_run_state(run_id, "completed")
            return self.get_run(run_id)
        if self.store.pending_approval(run_id) is None:
            content_hash = hashlib.sha256(artifact["content"].encode()).hexdigest()
            self.store.insert("approvals", {
                "id": uuid.uuid4().hex[:12], "run_id": run_id,
                "action": ("نشر تقرير التحليل في مخزن Obsidian" if arabic else
                           "Publish the analytics report to the Obsidian vault"),
                "target": str(self.vault_dir / "Reports"), "risk": "high",
                "impact": ("يكتب ملاحظتين بصيغة Markdown (التقرير وسجل التشغيل) في "
                           "المخزن المحلي." if arabic else
                           "Writes two markdown notes (report + run log) to the local vault."),
                "reversibility": ("قابل للتراجع: احذف الملاحظتين المنشأتين." if arabic
                                  else "Reversible: delete the created notes."),
                "content_hash": content_hash, "state": "pending",
                "created_at": _now(), "decided_at": None})
        self._set_task(task["id"], "awaiting_approval",
                       summary="بانتظار موافقة بشرية على النشر." if arabic
                       else "Waiting for human approval to publish.")
        self._set_run_state(run_id, "awaiting_approval")
        return self.get_run(run_id)

    def decide_approval(self, run_id, approval_id, decision):
        approval = self.store.get_approval(approval_id, run_id)
        if approval is None:
            raise KeyError(approval_id)
        if approval["state"] != "pending":
            raise ValueError(f"Approval already {approval['state']}.")
        task = next(t for t in self.store.get_tasks(run_id)
                    if t["role"] == "publish")
        artifact = self.store.latest_artifact(run_id)
        # Approval binds to the exact content hash: altered content invalidates it.
        current_hash = hashlib.sha256(artifact["content"].encode()).hexdigest()
        if current_hash != approval["content_hash"]:
            raise ValueError("Artifact changed after approval was requested.")
        if decision == "approve":
            path = self._publish(run_id, artifact)
            self.store.update("approvals", approval_id,
                              {"state": "approved_once", "decided_at": _now()})
            self.store.update("artifacts", artifact["id"],
                              {"published_path": str(path)})
            self._set_task(task["id"], "succeeded",
                           summary=f"Published to {path}.")
            self._set_run_state(run_id, "completed")
        else:
            self.store.update("approvals", approval_id,
                              {"state": "rejected", "decided_at": _now()})
            self._set_task(task["id"], "skipped",
                           summary="Publishing rejected by the user; no note was written.")
            self._set_run_state(run_id, "completed")
        return self.get_run(run_id)

    def _publish(self, run_id, artifact):
        run = self._row(run_id)
        reports = self.vault_dir / "Reports"
        logs = self.vault_dir / "Runs"
        reports.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", run["goal"].lower()).strip("-")[:48] or "report"
        note = reports / f"{slug}-{run_id}.md"
        frontmatter = (
            "---\n"
            f"type: analytics-report\nrun: {run_id}\n"
            f"generated: {_now()}\nstatus: approved\n"
            f"dataset: \"{run['dataset_name']}\"\n"
            f"lang: {run.get('report_language') or 'en'}\n---\n\n"
        )
        note.write_text(frontmatter + artifact["content"]
                        + f"\n\nRun log: [[{run_id}]]\n", encoding="utf-8")
        log_lines = [f"---\ntype: run-log\nrun: {run_id}\ngenerated: {_now()}\n---",
                     f"# Run {run_id}", "", f"**Goal:** {run['goal']}", "",
                     "| Stage | Outcome |", "| --- | --- |"]
        for t in self.store.get_tasks(run_id):
            log_lines.append(f"| {t['title']} | {t['state']}: {t['summary'] or ''} |")
        log_lines.append(f"\nReport: [[{note.stem}]]\n")
        log_note = logs / f"{run_id}.md"
        log_note.write_text("\n".join(log_lines), encoding="utf-8")
        # Durable record: published notes also live in the store, so hosted
        # (stateless) backends keep them and /api/vault can serve them.
        now = _now()
        self.store.upsert_note(f"Reports/{note.name}", run_id,
                               note.read_text(encoding="utf-8"), now)
        self.store.upsert_note(f"Runs/{run_id}.md", run_id,
                               log_note.read_text(encoding="utf-8"), now)
        return note

    def set_paused(self, run_id, paused):
        """Pause is durable, not a client-side toggle: a background worker
        must honour it too, or the button would stop meaning anything."""
        run = self._row(run_id)
        if run["state"] not in ("queued", "running"):
            raise ValueError(f"Run is {run['state']} and cannot be paused.")
        self.store.update("runs", run_id,
                          {"paused": 1 if paused else 0, "updated_at": _now()})
        return self.get_run(run_id)

    def cancel(self, run_id):
        self._set_run_state(run_id, "cancelled")
        for t in self.store.get_tasks(run_id):
            if t["state"] in ("pending", "awaiting_approval"):
                self._set_task(t["id"], "cancelled")
        pending = self.store.pending_approval(run_id)
        if pending is not None:
            self.store.update("approvals", pending["id"],
                              {"state": "cancelled", "decided_at": _now()})
        return self.get_run(run_id)

    # -- reads ------------------------------------------------------------
    def _row(self, run_id):
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def list_runs(self, owner=None):
        return self.store.list_runs(owner=owner)

    def owner_of(self, run_id):
        return self._row(run_id).get("owner") or "local-owner"

    def get_run(self, run_id):
        run = self._row(run_id)
        tasks = []
        charts, report, reports = [], None, []
        questions = dict(analytics.REPORT_SECTIONS)
        for t in self.store.get_tasks(run_id):
            result = json.loads(t["result_json"]) if t["result_json"] else None
            tasks.append({"id": t["id"], "role": t["role"], "title": t["title"],
                          "state": t["state"], "summary": t["summary"],
                          "quality_checks": (result or {}).get("quality_checks", []),
                          "claims": (result or {}).get("claims", [])})
            if result and t["role"] == "visuals":
                charts = result["output"].get("charts", [])
            # One report per analytics type, readable on its own.
            if result and t["role"] in questions:
                content = result["output"].get("report_markdown")
                if content:
                    reports.append({"type": t["role"], "question": questions[t["role"]],
                                    # As stored at creation: in the run's language.
                                    "title": t["title"],
                                    # The one sentence a business reader needs,
                                    # surfaced rather than left inside the markdown.
                                    "headline": result["output"].get("headline", ""),
                                    "content": content})
            # A custom stage that wrote a section gets its own tab too.
            if result and t["role"] not in analytics.ROLE_TITLES:
                content = result["output"].get("report_markdown")
                if content:
                    reports.append({"type": t["role"],
                                    "question": result["output"].get("question") or "",
                                    "title": t["title"],
                                    "headline": result["output"].get("headline", ""),
                                    "content": content})
        artifact = self.store.latest_artifact(run_id)
        if artifact:
            report = {"id": artifact["id"], "name": artifact["name"],
                      "version": artifact["version"], "content": artifact["content"],
                      "published_path": artifact["published_path"]}
        approvals = [
            {key: a[key] for key in ("id", "action", "target", "risk", "impact",
                                     "reversibility", "state", "created_at",
                                     "decided_at")}
            for a in self.store.approvals_for_run(run_id)
        ]
        return {"id": run["id"], "goal": run["goal"],
                "dataset_name": run["dataset_name"], "state": run["state"],
                "report_language": run.get("report_language") or "en",
                "error": run["error"], "created_at": run["created_at"],
                "updated_at": run["updated_at"], "tasks": tasks,
                "paused": bool(run.get("paused")),
                "approvals": approvals, "charts": charts, "report": report,
                "reports": reports}
