"""scripts/consult.py: free local models for a second opinion.

A stub server stands in for Ollama and for an OpenAI-compatible server,
so the routing, the fallbacks, the refusals and the "skipped, not failed"
behaviour are tested without downloading a model.
"""

import contextlib
import io
import json
import sys
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consult  # noqa: E402

CONFIG = {"tasks": {
    "summarise": {"models": ["qwen3:4b", "qwen3:1.7b"], "max_tokens": 50, "system": "Summarise."},
    "code-review": {"models": ["qwen3-coder:30b", "qwen2.5-coder:7b"], "max_tokens": 50, "system": "Review."},
}}


class Stub(BaseHTTPRequestHandler):
    installed = ["qwen3:1.7b", "llama3.1:latest"]
    answer = "<think>planning</think>Three points."
    seen = []

    def log_message(self, *args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": n} for n in self.installed]})
        elif self.path == "/v1/models":
            self._send({"data": [{"id": n} for n in self.installed]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.seen.append((self.path, payload))
        if self.path == "/api/chat":
            self._send({"message": {"content": self.answer}, "prompt_eval_count": 40, "eval_count": 9})
        elif self.path == "/v1/chat/completions":
            self._send({"choices": [{"message": {"content": "OpenAI-style answer."}}],
                        "usage": {"prompt_tokens": 30, "completion_tokens": 4}})


class ConsultTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Stub)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Stub.seen = []

    def backend(self, **env):
        return consult.Backend({"OLLAMA_HOST": self.url, **env})

    def test_the_first_installed_model_in_the_list_answers(self):
        result = consult.consult("summarise", "A long note.", config=CONFIG, backend=self.backend())
        self.assertEqual(result["model"], "qwen3:1.7b")  # qwen3:4b is not installed
        self.assertEqual(result["answer"], "Three points.")  # thinking removed
        self.assertEqual((result["prompt_tokens"], result["output_tokens"], result["cost"]), (40, 9, 0))
        path, payload = Stub.seen[0]
        self.assertEqual(path, "/api/chat")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "Summarise."})
        self.assertEqual(payload["options"]["num_predict"], 50)

    def test_a_question_goes_before_the_text(self):
        consult.consult("summarise", "Body.", "What matters?", config=CONFIG, backend=self.backend())
        self.assertEqual(Stub.seen[0][1]["messages"][1]["content"], "What matters?\n\n---\n\nBody.")

    def test_no_listed_model_means_skipped_with_the_command_to_fix_it(self):
        with self.assertRaises(consult.Unavailable) as caught:
            consult.consult("code-review", "def f(): pass", config=CONFIG, backend=self.backend())
        self.assertIn("ollama pull qwen3-coder:30b", str(caught.exception))

    def test_no_server_means_skipped_not_failed(self):
        backend = consult.Backend({"OLLAMA_HOST": "http://127.0.0.1:9"})
        with self.assertRaises(consult.Unavailable):
            consult.consult("summarise", "text", config=CONFIG, backend=backend)

    def test_an_openai_compatible_server_works_too(self):
        backend = consult.Backend({"CONSULT_API": "openai", "CONSULT_BASE_URL": self.url + "/v1"})
        result = consult.consult("summarise", "text", config=CONFIG, backend=backend)
        self.assertEqual((result["model"], result["answer"]), ("qwen3:1.7b", "OpenAI-style answer."))
        self.assertEqual(Stub.seen[0][0], "/v1/chat/completions")

    def test_raw_rows_are_refused_before_any_call(self):
        rows = "region,month,revenue\n" + "\n".join(f"North,2025-{m:02d},{1000 + m}" for m in range(1, 13))
        with self.assertRaises(ValueError) as caught:
            consult.consult("summarise", rows, config=CONFIG, backend=self.backend())
        self.assertIn("Raw data never goes to a model", str(caught.exception))
        self.assertEqual(Stub.seen, [])

    def test_summaries_prose_and_small_tables_are_not_raw(self):
        summary = ("| Region | Revenue |\n| --- | --- |\n| North | 1,935,057 |\n| South | 1,648,382 |\n\n"
                   "Revenue rose 45% from January to December, 2025, across 72 rows, 2 regions, 3 categories.")
        self.assertFalse(consult.looks_like_raw_rows(summary))
        dump = "\n".join(f"| r{i} | {i} | {i * 2} |" for i in range(40))
        self.assertTrue(consult.looks_like_raw_rows(dump))
        tabs = "\n".join(f"a{i}\t{i}\t{i}" for i in range(10))
        self.assertTrue(consult.looks_like_raw_rows(tabs))

    def test_oversized_input_and_unknown_tasks_are_refused(self):
        with self.assertRaises(ValueError):
            consult.consult("summarise", "x" * (consult.MAX_INPUT_CHARS + 1), config=CONFIG,
                            backend=self.backend())
        with self.assertRaises(ValueError):
            consult.consult("poetry", "x", config=CONFIG, backend=self.backend())

    def test_a_dry_run_calls_nothing(self):
        result = consult.consult("summarise", "text", config=CONFIG, dry_run=True)
        self.assertEqual(result["candidates"], ["qwen3:4b", "qwen3:1.7b"])
        self.assertEqual(Stub.seen, [])

    def test_the_shipped_routing_table_uses_only_known_open_models(self):
        config = consult.load_config()
        families = ("qwen3:", "qwen3-coder:", "qwen2.5-coder:", "gpt-oss:")
        for task, spec in config["tasks"].items():
            with self.subTest(task=task):
                self.assertTrue(spec["models"])
                self.assertTrue(all(m.startswith(families) for m in spec["models"]), spec["models"])
                self.assertTrue(spec["system"] and spec["max_tokens"] > 0)

    def test_the_cli_exits_3_when_nothing_can_answer(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, \
                unittest.mock.patch.dict("os.environ", {"OLLAMA_HOST": "http://127.0.0.1:9"}), \
                unittest.mock.patch("sys.stdin", io.StringIO("Some text.")):
            self.assertEqual(consult.main(["--task", "summarise"]), consult.UNAVAILABLE)
        self.assertIn("Consultation skipped", err.getvalue())


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
