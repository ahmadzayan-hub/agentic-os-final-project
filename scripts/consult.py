#!/usr/bin/env python3
"""Ask a free, open-source model on this machine for a second opinion.

    python scripts/consult.py --task prose-review --input draft.md
    echo "..." | python scripts/consult.py --task summarise
    python scripts/consult.py --list          # tasks, chosen models, what is installed
    python scripts/consult.py --task reason --input brief.md --dry-run

Tier 1 of docs/AGENT_TEAM.md: zero cost, and nothing leaves the machine.
It talks to Ollama (OLLAMA_HOST, default http://127.0.0.1:11434), the
same setting the app's model gateway uses. Any OpenAI-compatible local
server (llama.cpp, LM Studio, vLLM) also works with CONSULT_API=openai
and CONSULT_BASE_URL. Each task names models in order of preference in
.claude/consult-models.json; the first one installed answers.

A consultation is optional. With no server or no listed model it exits 3
and says so; it never blocks a review. It refuses text that looks like
raw table rows, because raw data never goes to a model (brain/Soul.md).
Standard library only.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".claude" / "consult-models.json"
DEFAULT_HOST = "http://127.0.0.1:11434"
MAX_INPUT_CHARS = 24_000
TIMEOUT_S = 300
UNAVAILABLE = 3  # exit code: no local model to ask; the caller carries on
THINKING = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class Unavailable(Exception):
    """No server, or no listed model installed."""


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text(encoding="utf-8"))


RAW_RUN = 8         # consecutive delimited lines that make a data block
TABLE_RUN = 30      # rows that make a Markdown table a data dump, not a summary


def _records_in_json(text):
    """Records a text holds as JSON: an array of objects (anywhere in the
    text), or JSON Lines, one object per line."""
    start, end = text.find("["), text.rfind("]")
    if 0 <= start < end:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, list):
                return sum(isinstance(item, dict) for item in data)
        except ValueError:
            pass
    run = best = 0
    for line in text.splitlines():
        try:
            run = run + 1 if isinstance(json.loads(line), dict) else 0
        except ValueError:
            run = 0
        best = max(best, run)
    return best


def _same_shape_run(lines, fields):
    """The longest run of consecutive lines with the same field count (at
    least three, and digits among them), fields being a line's parts."""
    run, width, best = 0, None, 0
    for line in lines:
        parts = fields(line)
        rowlike = parts is not None and len(parts) >= 3 and re.search(r"\d", line) is not None
        if rowlike and len(parts) == width:
            run += 1
        elif rowlike:
            run, width = 1, len(parts)
        else:
            run, width = 0, None
        best = max(best, run)
    return best


def looks_like_raw_rows(text):
    """True when the text holds a block of data rows, in any of the shapes
    data travels in (ADR 0027 measured the misses):

    - RAW_RUN or more consecutive lines with the same number of commas,
      tabs or semicolons, with digits in them;
    - a Markdown table of TABLE_RUN rows or more;
    - RAW_RUN or more records as JSON: an array of objects, or JSON Lines;
    - RAW_RUN or more lines of a space-aligned table (columns two or more
      spaces apart);
    - RAW_RUN or more lines of "key: value, key: value" pairs.

    A summary table of a few figures, prose, code and short logs are not
    refused."""
    lines = text.splitlines()
    table = 0
    for line in lines:
        table = table + 1 if line.lstrip().startswith("|") else 0
        if table >= TABLE_RUN:
            return True
    for delimiter in (",", "\t", ";"):
        run, width = 0, None
        for line in lines:
            count = line.count(delimiter)
            rowlike = count >= 2 and re.search(r"\d", line) is not None
            if rowlike and count == width:
                run += 1
            elif rowlike:
                run, width = 1, count
            else:
                run, width = 0, None
            if run >= RAW_RUN:
                return True
    if _records_in_json(text) >= RAW_RUN:
        return True
    if _same_shape_run(lines, lambda line: re.split(r" {2,}", line.strip()) if "  " in line.strip() else None) >= RAW_RUN:
        return True
    pairs = lambda line: re.findall(r"[\w ]{1,30}:\s*[^,;]+", line) if line.count(":") >= 2 else None
    return _same_shape_run(lines, lambda line: (pairs(line) or None) and [*pairs(line), ""]) >= RAW_RUN


class Backend:
    """Ollama's own API, or an OpenAI-compatible one."""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.kind = env.get("CONSULT_API", "ollama")
        if self.kind == "openai":
            self.base = (env.get("CONSULT_BASE_URL") or "http://127.0.0.1:8080/v1").rstrip("/")
        else:
            self.base = (env.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.key = env.get("CONSULT_API_KEY")  # a local server rarely needs one

    def _request(self, path, payload=None, timeout=10):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise Unavailable(f"No local model server answered at {self.base} ({error}).") from error

    def installed(self):
        if self.kind == "openai":
            return [m["id"] for m in self._request("/models").get("data", [])]
        return [m["name"] for m in self._request("/api/tags").get("models", [])]

    def chat(self, model, system, user, max_tokens):
        if self.kind == "openai":
            body = self._request("/chat/completions", {
                "model": model, "max_tokens": max_tokens, "temperature": 0.2,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}, timeout=TIMEOUT_S)
            usage = body.get("usage") or {}
            return (body["choices"][0]["message"]["content"],
                    usage.get("prompt_tokens"), usage.get("completion_tokens"))
        body = self._request("/api/chat", {
            "model": model, "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}, timeout=TIMEOUT_S)
        return body["message"]["content"], body.get("prompt_eval_count"), body.get("eval_count")


def choose(task_models, installed):
    """The first model in the task's list that is installed. Ollama names
    'qwen3:4b' and lists 'qwen3:4b'; a bare 'qwen3' means ':latest'."""
    have = set(installed) | {name.removesuffix(":latest") for name in installed}
    return next((m for m in task_models if m in have), None)


def consult(task, text, question=None, config=None, backend=None, dry_run=False):
    config = config or load_config()
    if task not in config["tasks"]:
        raise ValueError(f"Unknown task “{task}”. Tasks: {', '.join(sorted(config['tasks']))}.")
    if looks_like_raw_rows(text):
        raise ValueError("This looks like raw table rows. Raw data never goes to a model: "
                         "send a summary or the figures you want checked instead.")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"The input is {len(text):,} characters; the limit is {MAX_INPUT_CHARS:,}. "
                         "Send the part to review, or summarise it first.")
    spec = config["tasks"][task]
    user = text if not question else f"{question}\n\n---\n\n{text}"
    if dry_run:
        return {"task": task, "candidates": spec["models"], "input_chars": len(user),
                "max_tokens": spec["max_tokens"], "dry_run": True}
    backend = backend or Backend()
    installed = backend.installed()
    model = choose(spec["models"], installed)
    if not model:
        raise Unavailable(f"None of {', '.join(spec['models'])} is installed at {backend.base}. "
                          f"Install the first with: ollama pull {spec['models'][0]}")
    started = time.monotonic()
    answer, prompt_tokens, output_tokens = backend.chat(model, spec["system"], user, spec["max_tokens"])
    return {"task": task, "model": model, "answer": THINKING.sub("", answer).strip(),
            "prompt_tokens": prompt_tokens, "output_tokens": output_tokens,
            "seconds": round(time.monotonic() - started, 1), "cost": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--task", help="a task from .claude/consult-models.json")
    parser.add_argument("--input", help="a text file; standard input when omitted")
    parser.add_argument("--question", help="a question put before the text")
    parser.add_argument("--json", action="store_true", help="print the whole result as JSON")
    parser.add_argument("--dry-run", action="store_true", help="say what would be sent; call nothing")
    parser.add_argument("--list", action="store_true", help="tasks, models and what is installed")
    args = parser.parse_args(argv)
    config = load_config()

    if args.list:
        try:
            installed = Backend().installed()
            where = f"{len(installed)} model(s) installed"
        except Unavailable as error:
            installed, where = [], str(error)
        print(where)
        for task, spec in config["tasks"].items():
            chosen = choose(spec["models"], installed)
            print(f"{task:16} {' > '.join(spec['models'])}  ->  {chosen or 'none installed'}")
        return 0
    if not args.task:
        parser.error("--task is required (or use --list)")
    text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        result = consult(args.task, text, args.question, config, dry_run=args.dry_run)
    except ValueError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 2
    except Unavailable as error:
        print(f"Consultation skipped: {error}", file=sys.stderr)
        return UNAVAILABLE
    if args.json or args.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["answer"])
        print(f"\n[{result['model']} · {result['prompt_tokens']} in / {result['output_tokens']} out "
              f"· {result['seconds']} s · cost 0]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
