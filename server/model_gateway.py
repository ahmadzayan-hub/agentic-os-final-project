"""Provider-neutral model gateway.

LLMs may phrase and summarize; they never calculate. Every number in a
report comes from deterministic code, and the gateway is only offered the
already-computed facts — never the dataset. With no provider configured
(the default, and always in tests/CI) a deterministic template is used, so
the application is fully functional offline and no test needs credentials.

Three providers, chosen by environment variable, in priority order:

- **ollama** — a model running on the operator's own machine
  (OLLAMA_MODEL, optional OLLAMA_HOST). No key, no account, and the facts
  never leave the host. Preferred when set, because it is the only option
  that sends nothing anywhere.
- **anthropic** — Claude via ANTHROPIC_API_KEY (+ ANTHROPIC_MODEL).
- **groq** — GROQ_API_KEY (+ GROQ_MODEL).

Keys are read server-side only. They are never logged, stored, or sent to
the browser, and any provider failure degrades to the deterministic
narrator, which is reported honestly as the source in the report itself.
"""

import os
import re

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1"
TIMEOUT_SECONDS = 12
MAX_OUTPUT_TOKENS = 220
# Local models get a larger budget than the metered ones: reasoning models
# (qwen3, deepseek-r1, …) spend tokens thinking before they answer, and a
# 220-token cap would be exhausted by the scratchpad, leaving no summary.
LOCAL_OUTPUT_TOKENS = 600

# Reasoning models wrap their scratchpad in <think> tags. That is working
# out loud, not an executive summary: it never belongs in a report.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# The house style the narrator must follow. A finding that cannot be
# communicated cannot drive action, so plain language is part of the
# contract with the model — and it is checked afterwards regardless
# (analytics.validator.claims_avoid_statistical_jargon).
SYSTEM_PROMPT = (
    "You write two-sentence executive summaries for business readers — a "
    "board, an executive, an investor. Use ONLY the verified facts provided. "
    "Never add numbers, causes, predictions, or claims of your own. Write in "
    "plain business language: say “costs are rising”, never “the mean "
    "increased by 2.3 standard deviations”; say “the data strongly suggests "
    "maintenance is the main cost driver”, never “p < 0.05”. No statistical "
    "vocabulary, no hedging about methodology."
)


class ModelGateway:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.ollama_model = env.get("OLLAMA_MODEL") or None
        self.ollama_host = env.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
        self.anthropic_key = env.get("ANTHROPIC_API_KEY") or None
        self.anthropic_model = env.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
        self.groq_key = env.get("GROQ_API_KEY") or None
        self.groq_model = env.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)

        # Local first: it is the only provider that sends nothing off the
        # machine, so it wins when the operator has configured one.
        if self.ollama_model:
            self.provider, self.model = "ollama", self.ollama_model
        elif self.anthropic_key:
            self.provider, self.model = "anthropic", self.anthropic_model
        elif self.groq_key:
            self.provider, self.model = "groq", self.groq_model
        else:
            self.provider, self.model = "deterministic", None

    def status(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.provider != "deterministic",
            # Stated plainly because it is the question that matters: does
            # anything leave this machine?
            "local_only": self.provider in ("deterministic", "ollama"),
        }

    def providers(self):
        """Every provider this gateway could actually reach, in the order
        it would pick them.

        The constructor collapses these to one by priority, which is the
        right default and the wrong amount of information for anything
        that wants to choose per report (see server/routing.py).
        """
        found = []
        if self.ollama_model:
            found.append({"provider": "ollama", "model": self.ollama_model,
                          "local_only": True})
        if self.anthropic_key:
            found.append({"provider": "anthropic", "model": self.anthropic_model,
                          "local_only": False})
        if self.groq_key:
            found.append({"provider": "groq", "model": self.groq_model,
                          "local_only": False})
        # Always reachable, always last: it needs nothing and never fails.
        found.append({"provider": "deterministic", "model": None,
                      "local_only": True})
        return found

    def narrate(self, goal, facts, provider=None):
        """Return {'text', 'source'}. Facts are short verified statements;
        the model is asked only to phrase them.

        `provider` overrides the priority order for this call. The gateway
        could always reach all three; until now nothing could ask it for
        a particular one.
        """
        callers = {"ollama": self._call_ollama,
                   "anthropic": self._call_anthropic,
                   "groq": self._call_groq}
        caller = callers.get(provider or self.provider)
        if caller:
            text = caller(goal, facts)
            if text:
                return {"text": text, "source": "model"}
        summary = " ".join(facts[:4])
        return {
            "text": f"Analysis of the goal “{goal}”: {summary}",
            "source": "deterministic",
        }

    def _prompt(self, goal, facts):
        return "Goal: " + goal + "\nVerified facts:\n- " + "\n- ".join(facts)

    def _post(self, url, headers, payload):
        try:
            import httpx

            response = httpx.post(url, headers=headers, json=payload,
                                  timeout=TIMEOUT_SECONDS)
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            # Timeouts, network, schema drift: degrade to deterministic.
            return None

    @staticmethod
    def _clean(text):
        if not isinstance(text, str):
            return None
        text = THINK_BLOCK.sub("", text)
        if "<think>" in text.lower():
            # An unclosed block means the reply was cut off mid-thought, so
            # everything present is scratchpad. Degrade to the deterministic
            # narrator rather than printing a model's reasoning as a summary.
            return None
        return text.strip() or None

    def _call_ollama(self, goal, facts):
        body = self._post(
            self.ollama_host.rstrip("/") + "/api/chat", {},
            {"model": self.ollama_model, "stream": False,
             "options": {"num_predict": LOCAL_OUTPUT_TOKENS},
             "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": self._prompt(goal, facts)}]})
        try:
            return self._clean(body["message"]["content"])
        except (TypeError, KeyError, IndexError):
            return None

    def _call_anthropic(self, goal, facts):
        body = self._post(
            ANTHROPIC_URL,
            {"x-api-key": self.anthropic_key,
             "anthropic-version": ANTHROPIC_VERSION,
             "content-type": "application/json"},
            {"model": self.anthropic_model, "max_tokens": MAX_OUTPUT_TOKENS,
             "system": SYSTEM_PROMPT,
             "messages": [{"role": "user", "content": self._prompt(goal, facts)}]})
        try:
            return self._clean(body["content"][0]["text"])
        except (TypeError, KeyError, IndexError):
            return None

    def _call_groq(self, goal, facts):
        body = self._post(
            GROQ_URL, {"Authorization": f"Bearer {self.groq_key}"},
            {"model": self.groq_model, "max_tokens": MAX_OUTPUT_TOKENS,
             "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": self._prompt(goal, facts)}]})
        try:
            return self._clean(body["choices"][0]["message"]["content"])
        except (TypeError, KeyError, IndexError):
            return None
