"""日志可追溯、隔离与脱敏；不调用真实模型或修改业务数据。"""

from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from agent_lab.models import OllamaClient
from agent_lab.runtime import tracing
import test_main


class TracingTest(unittest.TestCase):
    def events(self, captured):
        return [json.loads(record.getMessage()) for record in captured.records]

    def test_llm_payload_response_and_redaction_do_not_change_request(self):
        client = OllamaClient(context_tokens=8192)
        response = {
            "model": "test",
            "done": True,
            "message": {
                "role": "assistant",
                "content": "查到了",
                "thinking": "hidden-reasoning",
            },
            "eval_count": 12,
        }
        client._open = Mock(return_value=response)
        messages = [
            {"role": "user", "content": "password=private-password 13812345678"},
            {
                "role": "tool",
                "content": json.dumps(
                    {"phone": "13812345678", "detail": "private-address", "id": 12}
                ),
            },
        ]
        with self.assertLogs(tracing.LOGGER, level="INFO") as captured:
            result = client.chat(messages, tools=[], options={"temperature": 0.1})
        events = self.events(captured)
        self.assertEqual([e["event"] for e in events], ["llm.request", "llm.response"])
        self.assertEqual(events[0]["payload"]["options"], {"num_ctx": 8192, "temperature": 0.1})
        self.assertEqual(events[0]["step_id"], events[1]["step_id"])
        self.assertGreaterEqual(events[1]["elapsed_ms"], 0)
        for secret in ("private-password", "13812345678", "private-address", "hidden-reasoning"):
            self.assertNotIn(secret, str(events))
        self.assertEqual(json.loads(client._open.call_args.args[0].data)["messages"], messages)
        self.assertIs(result, response)

    def test_confirmation_trace_keeps_task_and_replay_does_not_log_another_tool(self):
        harness = test_main.ApplicationTest()
        harness.setUp()
        with self.assertLogs(tracing.LOGGER, level="INFO") as captured:
            pending = harness.pending()
            harness.confirm(pending)
            harness.confirm(pending)
        events = self.events(captured)
        tools = [e for e in events if e["event"] == "tool.response"]
        self.assertEqual(
            [e["result"]["status"] for e in tools], ["confirmation_required", "success", "success"]
        )
        self.assertEqual(len({e["task_id"] for e in tools}), 1)
        self.assertEqual(len({e["trace_id"] for e in events if e["event"] == "request.request"}), 3)
        self.assertEqual(sum(e["event"] == "request.replayed" for e in events), 1)
        self.assertNotIn(harness.session, str(events))
        self.assertNotIn(pending["confirmation_id"], str(events))
        self.assertEqual(len(harness.writes()), 1)

    def test_concurrent_contexts_and_cleanup(self):
        barrier = threading.Barrier(2)

        def run(identifier):
            with tracing.trace_context(trace_id=identifier, sensitive_values=("private-value",)):
                barrier.wait()
                tracing.emit("test", input=identifier + " private-value")

        with self.assertLogs(tracing.LOGGER, level="INFO") as captured:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(run, ("first", "second")))
            tracing.emit("outside")
        events = self.events(captured)
        for event in events[:2]:
            self.assertEqual(event["input"], event["trace_id"] + " [REDACTED]")
        self.assertNotIn("trace_id", events[-1])

    def test_nested_credentials_are_redacted(self):
        payload = {
            "token": "opaque-token",
            "headers": {"Authorization": "Bearer opaque-auth"},
            "content": json.dumps({"session_id": "opaque-session", "password": "opaque-password"}),
        }
        safe = tracing.redact(payload)
        for value in ("opaque-token", "opaque-auth", "opaque-session", "opaque-password"):
            self.assertNotIn(value, str(safe))
        self.assertEqual(payload["token"], "opaque-token")

    def test_failure_logged_and_original_exception_preserved(self):
        client = OllamaClient()
        failure = RuntimeError("private exception text")
        client._open = Mock(side_effect=failure)
        with self.assertLogs(tracing.LOGGER, level="INFO") as captured:
            with self.assertRaises(RuntimeError) as caught:
                client.chat([{"role": "user", "content": "你好"}])
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.events(captured)[-1]["error_type"], "RuntimeError")
        self.assertNotIn("private exception text", str(captured.output))
        with patch.object(tracing.LOGGER, "info", side_effect=OSError("disk full")):
            with tracing.span("test") as done:
                done({"status": "success"})

    def test_file_console_rotation_and_private_permissions(self):
        handlers, level = tracing.LOGGER.handlers[:], tracing.LOGGER.level
        tracing.LOGGER.handlers = []
        try:
            with TemporaryDirectory() as directory, patch("sys.stderr") as console:
                path = tracing.configure_logging(directory)
                file_handler = next(
                    h for h in tracing.LOGGER.handlers if isinstance(h, logging.FileHandler)
                )
                file_handler.maxBytes = 200
                for n in range(5):
                    tracing.emit("test", n=n, cookie="private-cookie", value="x" * 40)
                self.assertTrue(console.write.called)
                files = list(Path(directory).glob("agent.jsonl*"))
                self.assertGreater(len(files), 1)
                self.assertTrue(path.exists())
                for log_file in files:
                    self.assertEqual(log_file.stat().st_mode & 0o777, 0o600)
                    for line in log_file.read_text().splitlines():
                        self.assertEqual(json.loads(line)["cookie"], "[REDACTED]")
        finally:
            for handler in tracing.LOGGER.handlers:
                handler.close()
            tracing.LOGGER.handlers = handlers
            tracing.LOGGER.setLevel(level)
