"""The conversational assistant: understand, confirm, act.

`assistant.py` at the project root knows what a sentence means without
a model and runs the actions that need only the Agent. This module adds
the two things that need the server: a language model, when one is
configured, for sentences the rules do not catch; and the actions that
need the run engine — start an analysis, say how it is going, quote what
its report found.

What the model may decide, and what it may not (ADR 0019):

- It may decide **which action** a sentence asks for, and its arguments,
  from the same small catalogue the rules use. An action outside that
  catalogue is refused and the rules answer instead.
- It may **phrase a chat reply** — and that is the only text of its
  making a person ever sees. Every action's confirmation is the Agent's
  own deterministic sentence, so the assistant cannot say "saved" about
  a save that failed.
- It never sees a dataset row. It gets memory entries, preferences, the
  last few turns, and the *headlines* of the latest report — sentences
  the pipeline already verified. It never produces a number, because
  nothing it writes reaches a report.
- It never deletes anything. Destructive actions are confirmed in the
  next message, by rule, whoever understood the sentence.

With no provider configured — the default, and always in CI — the rules
do everything, and the reply says so (`source: "rules"`).
"""

import json
import re

from assistant import (ACTIONS, DESTRUCTIVE, PREFERENCE_KEYS, RUN_STATES,
                       SECTION_QUESTIONS, arguments_valid, confirmation_prompt,
                       execute_local, fallback, intent, is_no, is_yes, reply,
                       understand)
from server import quota
from server.tools import ToolBox

MAX_MEMORY_IN_CONTEXT = 20
MAX_TURNS_IN_CONTEXT = 6
MAX_REPLY_CHARS = 600
# Local reasoning models think before they answer; the JSON must not be
# what gets cut off.
LOCAL_TOKENS = 900
HOSTED_TOKENS = 400

SYSTEM_PROMPT = (
    "You are the assistant inside Agentic OS, a governed business-analytics "
    "workspace. Read the person's message and the context, decide what they "
    "want, and answer with ONE JSON object and nothing else:\n"
    '{"action": "<action>", "arguments": {...}, "reply": "<text or empty>"}\n'
    "Allowed actions and their arguments:\n"
    "- chat: no arguments; reply is your answer.\n"
    "- help: no arguments; the system lists what it can do.\n"
    "- remember: information (string), category (general|profile|work|"
    "projects|preferences).\n"
    "- recall: query (string or null).\n"
    "- forget: key (a memory key like memory_3, or \"all\").\n"
    "- clear_history: no arguments.\n"
    "- set_preference: key (tone|language|user_name|save_history), value.\n"
    "- start_run: goal (one sentence), dataset (a stored dataset name, or "
    "\"sample\").\n"
    "- run_status: no arguments.\n"
    "- explain_report: section (descriptive|diagnostic|experiment|predictive|"
    "prescriptive|all).\n"
    "Rules you must follow: you never see data rows, so never state a number "
    "or a finding of your own — for explain_report and run_status the system "
    "quotes the report itself, so leave reply empty. Deleting anything needs "
    "the person's confirmation; the system asks, you do not. Write reply in "
    "{language}, at most two sentences, and never claim an action has already "
    "happened."
)


class Assistant:
    def __init__(self, gateway, engine, runtime=None, runtime_name=None):
        self.gateway = gateway
        self.engine = engine
        # Optional (ADR 0021): a loop that may call several tools for one
        # sentence. It gets the sentences the rules cannot place, and
        # nothing the rules can — one exact action stays one exact action.
        self.runtime = runtime
        self.runtime_name = runtime_name

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def handle(self, text, session):
        """Answer one message. Returns a dict for the transcript entry:
        text, source, provider, action, result, pending."""
        agent = session.agent
        language = agent.language()

        pending = self._take_pending(session)
        if pending is not None:
            if is_yes(text):
                return self._execute(pending["action"], pending["arguments"],
                                     session, text, source="rules")
            if is_no(text):
                return {"text": reply(language, "cancelled"), "source": "rules",
                        "action": "cancel"}
            # Anything else is a new request; the earlier one is dropped
            # rather than executed on the strength of an unrelated sentence.

        if self.runtime is not None and understand(text)["action"] == "chat":
            outcome = self._via_runtime(text, session)
            if outcome is not None:
                return outcome
            # The runtime declined: the model-or-rules path answers, as
            # if no runtime were configured.

        understood = self.understand(text, session)
        action, arguments = understood["action"], understood["arguments"]
        if action in DESTRUCTIVE:
            prompt = confirmation_prompt(action, arguments, agent)
            if prompt is not None:
                return {"text": prompt, "source": understood["source"],
                        "provider": understood.get("provider"),
                        "action": "confirm",
                        "pending": {"action": action, "arguments": arguments}}
        return self._execute(action, arguments, session, text,
                             source=understood["source"],
                             provider=understood.get("provider"),
                             model_reply=understood.get("reply"))

    # ------------------------------------------------------------------
    # Understanding
    # ------------------------------------------------------------------
    def understand(self, text, session):
        """Model first when one is configured, rules otherwise — and rules
        whenever the model's answer is not a valid intent."""
        status = self.gateway.status()
        if not status.get("configured"):
            return understand(text)
        raw = self.gateway.ask(
            SYSTEM_PROMPT.replace("{language}",
                                  "Arabic" if session.agent.language() == "ar"
                                  else "English"),
            self._context(session) + "\nMessage: " + text,
            max_tokens=LOCAL_TOKENS if status.get("provider") == "ollama"
            else HOSTED_TOKENS,
        )
        parsed = self._parse(raw, session)
        if parsed is None:
            fallback = understand(text)
            fallback["why"] = ("the model's answer was not a valid intent; "
                               "the rules decided instead")
            return fallback
        parsed["provider"] = status.get("provider")
        return parsed

    def _context(self, session):
        """What the model is told. Verified sentences and settings only —
        the dataset is not here, and nothing here is a row of it."""
        agent = session.agent
        lines = ["Context:"]
        memory = agent.memory_entries()[:MAX_MEMORY_IN_CONTEXT]
        if memory:
            lines.append("Memory:")
            lines.extend(f"- {e['key']}: {e['text'][:200]}" for e in memory)
        prefs = {k: agent.preferences.get(k) for k in PREFERENCE_KEYS
                 if agent.preferences.get(k) is not None}
        lines.append("Preferences: " + json.dumps(prefs, ensure_ascii=False))
        datasets = self.engine.store.list_datasets(session.owner)[:10]
        if datasets:
            lines.append("Stored datasets: " + ", ".join(d["name"] for d in datasets))
        latest = self._latest_run(session.owner)
        if latest:
            lines.append(f"Latest analysis {latest['id']} ({latest['state']}): "
                         f"{latest['goal']} — dataset {latest['dataset_name']}")
            for section in latest.get("reports", []):
                if section.get("headline"):
                    lines.append(f"  {section['type']}: {section['headline']}")
        turns = [e for e in session.transcript if e.get("role") in ("user", "agent")]
        for entry in turns[-MAX_TURNS_IN_CONTEXT:]:
            lines.append(f"{entry['role']}: {str(entry.get('text', ''))[:300]}")
        return "\n".join(lines)

    def _parse(self, raw, session):
        """A model's text → a validated intent, or None."""
        if not isinstance(raw, str):
            return None
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        action = str(data.get("action") or "").strip()
        if action not in ACTIONS:
            return None
        allowed = ACTIONS[action]
        given = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        arguments = {k: given[k] for k in allowed if k in given}
        text = data.get("reply")
        text = text.strip()[:MAX_REPLY_CHARS] if isinstance(text, str) else None
        if not self._arguments_valid(action, arguments, session):
            return None
        return intent(action, arguments, text, source="model")

    @staticmethod
    def _arguments_valid(action, arguments, session):
        return arguments_valid(action, arguments)

    # ------------------------------------------------------------------
    # An agent runtime (ADR 0021): several tools for one sentence
    # ------------------------------------------------------------------
    def _via_runtime(self, text, session):
        """Hand the sentence to the configured runtime with the tool box.

        What comes back on screen is every tool's own text, verbatim and
        in order — the same sentences the rules path would have produced
        — and then the runtime's closing line, which is the one piece of
        text of its making, labelled as such. If the runtime raises, the
        rules answer, the transcript says why, and whatever tools it did
        call before failing are still on the record: those happened.
        A runtime that returns None having called nothing has declined,
        and the caller answers the sentence the ordinary way.
        """
        agent = session.agent
        tools = ToolBox(self, session)
        context = {"language": agent.language(), "notes": self._context(session),
                   "thread_id": getattr(session, "id", None),
                   "ask": self.gateway.ask}
        try:
            closing = self.runtime.run(text, tools, context)
        except Exception as error:
            outcome = self._execute("chat", {}, session, text, source="rules")
            outcome["why"] = (f"the agent runtime “{self.runtime_name}” failed "
                              f"({type(error).__name__}: {error}); the rules "
                              "answered instead")
            if tools.steps:
                outcome["steps"] = tools.steps
            return outcome
        if closing is None and not tools.steps:
            return None
        closing = str(closing or "").strip()[:MAX_REPLY_CHARS]
        parts = [step["text"] for step in tools.steps if step["text"]]
        if closing:
            parts.append(closing)
        return {"source": "runtime", "provider": self.runtime_name,
                "action": "runtime", "steps": tools.steps,
                "result": tools.last_result,
                "text": "\n\n".join(parts) or fallback(agent, text)}

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def _execute(self, action, arguments, session, text, source="rules",
                 provider=None, model_reply=None):
        agent = session.agent
        language = agent.language()
        outcome = {"source": source, "provider": provider, "action": action,
                   "result": None}
        if action == "start_run":
            outcome.update(self._start_run(arguments, session, text))
        elif action == "run_status":
            outcome.update(self._run_status(session))
        elif action == "explain_report":
            outcome.update(self._explain(arguments, session))
        else:
            outcome["text"] = execute_local(action, arguments, agent, text,
                                            model_reply=model_reply)
        if outcome.get("provider") is None:
            outcome.pop("provider", None)
        return outcome

    def _start_run(self, arguments, session, text):
        agent = session.agent
        language = agent.language()
        goal = str(arguments.get("goal") or "").strip() or text.strip()
        dataset_id, dataset_name = self._resolve_dataset(
            arguments.get("dataset"), text, session.owner)
        try:
            # The report is written in the language the person is using.
            run = self.engine.create_run(goal, owner=session.owner,
                                         dataset_id=dataset_id,
                                         language="ar" if language == "ar" else "en")
        except quota.QuotaExceeded as error:
            return {"text": error.message, "result": None}
        shown = dataset_name or reply(language, "dataset_sample")
        return {"text": reply(language, "run_started", run_id=run["id"],
                              dataset=shown, goal=goal),
                "result": {"run_id": run["id"]}}

    def _resolve_dataset(self, named, text, owner):
        """A stored dataset the person named, else the sample data."""
        candidates = self.engine.store.list_datasets(owner)
        wanted = str(named or "").strip().lower()
        haystack = text.lower()
        if wanted == "sample":
            return None, None
        for dataset in candidates:
            name = str(dataset["name"]).lower()
            stem = name.rsplit(".", 1)[0]
            if wanted and (wanted == name or wanted == stem):
                return dataset["id"], dataset["name"]
            if stem and len(stem) >= 3 and stem in haystack:
                return dataset["id"], dataset["name"]
        return None, None

    def _latest_run(self, owner):
        runs = self.engine.list_runs(owner=owner)
        if not runs:
            return None
        return self.engine.get_run(runs[0]["id"])

    def _run_status(self, session):
        language = session.agent.language()
        run = self._latest_run(session.owner)
        if run is None:
            return {"text": reply(language, "no_runs"), "result": None}
        done = sum(1 for t in run["tasks"] if t["state"] == "succeeded")
        pending = any(a["state"] == "pending" for a in run["approvals"])
        state = RUN_STATES.get(language, RUN_STATES["en"]).get(
            run["state"], run["state"].replace("_", " "))
        return {"text": reply(language, "run_status", run_id=run["id"],
                              goal=run["goal"], state=state, done=done,
                              total=len(run["tasks"]),
                              approval=reply(language, "run_status_approval")
                              if pending else ""),
                "result": {"run_id": run["id"]}}

    def _explain(self, arguments, session):
        """Quote the report's own headlines. The model is not asked to
        rephrase them: a paraphrase of a verified sentence is no longer a
        verified sentence."""
        language = session.agent.language()
        run = self._latest_run(session.owner)
        if run is None:
            return {"text": reply(language, "no_runs"), "result": None}
        sections = [s for s in run.get("reports", []) if s.get("headline")]
        if not sections:
            state = RUN_STATES.get(language, RUN_STATES["en"]).get(
                run["state"], run["state"].replace("_", " "))
            return {"text": reply(language, "no_report_yet", run_id=run["id"],
                                  state=state),
                    "result": {"run_id": run["id"]}}
        wanted = arguments.get("section") or "all"
        questions = SECTION_QUESTIONS.get(language, SECTION_QUESTIONS["en"])
        chosen = [s for s in sections if wanted == "all" or s["type"] == wanted]
        if not chosen:
            chosen = sections
        lines = [reply(language, "report_intro", run_id=run["id"], goal=run["goal"])]
        for section in chosen:
            question = questions.get(section["type"], section.get("question", ""))
            lines.append(f"• {question} {section['headline']}")
        lines.append(reply(language, "report_outro"))
        return {"text": "\n".join(lines), "result": {"run_id": run["id"]}}

    # ------------------------------------------------------------------
    # Confirmations live on the transcript, so they survive a restart and
    # a change of server instance.
    # ------------------------------------------------------------------
    @staticmethod
    def _take_pending(session):
        for entry in reversed(session.transcript):
            if entry.get("role") != "agent":
                continue
            pending = entry.pop("pending", None)
            return pending if isinstance(pending, dict) else None
        return None
