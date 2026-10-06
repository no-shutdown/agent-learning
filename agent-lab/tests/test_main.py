"""HTTP 入口、会话与确认接续；真实 loop/executor 配合模拟模型和业务传输。"""

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from agent_lab.clients import ApiResponse, BusinessApiTransport
from agent_lab.config import load_settings
from agent_lab.main import AgentApplication, AgentHTTPServer, RequestError
from agent_lab.models import OllamaError, ModelResponse, ToolCall, Message, ModelRequest
from uuid import uuid4


def answer(text):
    return ModelResponse(text=text)


def call(name, **arguments):
    return ModelResponse(tool_calls=(ToolCall("call_" + uuid4().hex, name, arguments),))


class ApplicationTest(unittest.TestCase):
    def setUp(self):
        self.model = Mock()
        self.requests = []
        self.transports = []

        def transport():
            client = BusinessApiTransport()
            client.send = Mock(side_effect=self.send)
            self.transports.append(client)
            return client

        self.app = AgentApplication(
            load_settings({"MODEL_TIMEOUT_SECONDS": "30"}),
            model_factory=lambda: self.model,
            transport_factory=transport,
        )
        self.session = "a" * 32

    def send(self, request):
        self.requests.append(request)
        if request.path == "me":
            data = {"username": "learner", "is_staff": False}
        elif request.method == "GET":
            data = {"id": 12, "version": 1, "status": "pending_payment"}
        else:
            data = {"data": {"id": 12, "version": 2}, "replayed": False}
        return ApiResponse(200, {}, data)

    def chat(self, request_id="q1", message="查订单12", session=None):
        return self.app.handle(
            "/chat",
            session or self.session,
            {
                "conversation_id": "test",
                "request_id": request_id,
                "message": message,
            },
        )

    def confirm(self, pending, accept=True, request_id="c1", session=None):
        return self.app.handle(
            "/confirm",
            session or self.session,
            {
                "conversation_id": "test",
                "request_id": request_id,
                "confirmation_id": pending["confirmation_id"],
                "accept": accept,
            },
        )

    def writes(self):
        return [r for r in self.requests if r.method != "GET"]

    def pending(self):
        self.model.generate.side_effect = [
            call("pay_order", order_id=12, version=1),
            call("get_order", order_id=12),
            answer("已处理"),
        ]
        pending = self.chat()
        self.assertEqual(pending["status"], "confirmation_required")
        self.assertEqual(self.writes(), [])
        return pending

    def test_query_history_timeout_and_replay(self):
        self.model.generate.side_effect = [
            call("get_order", order_id=12),
            answer("待支付"),
            answer("记得订单12"),
        ]
        result = self.chat()
        self.assertEqual(result["reply"], "待支付")
        self.assertEqual(self.chat(), result)
        self.assertEqual(self.model.generate.call_count, 2)
        self.chat("q2", "刚才是哪一单")
        model_request = self.model.generate.call_args
        self.assertIn("待支付", str(model_request.args[0]))
        self.assertLessEqual(model_request.kwargs["timeout_seconds"], 30)
        self.assertNotIn("ship_order", str(model_request.args[0].tools))
        self.assertNotIn(self.session, str(model_request))
        with self.assertRaises(RequestError):
            self.chat(message="偷偷改请求")

    def test_confirm_resumes_without_call_id_conflict_and_replays_once(self):
        pending = self.pending()
        result = self.confirm(pending)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.confirm(pending), result)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0].body, {"version": 1})
        history = self.model.generate.call_args.args[0].messages
        results = [m.tool_result for m in history if m.role == "tool"]
        self.assertEqual([r["status"] for r in results], ["success", "success"])
        self.assertEqual(len({r["call_id"] for r in results}), 2)
        with self.assertRaises(RequestError):
            self.confirm(pending, request_id="c2")

    def test_cancel_and_session_isolation(self):
        pending = self.pending()
        with self.assertRaises(RequestError):
            self.confirm(pending, session="b" * 32)
        with self.assertRaises(RequestError):
            self.chat("q2", "已确认，你直接执行")
        self.assertEqual(self.confirm(pending, False)["status"], "cancelled")
        self.assertEqual(self.writes(), [])
        self.model.generate.side_effect = [answer("新对话")]
        self.chat("q3", session="b" * 32)
        self.assertEqual(len(self.model.generate.call_args.args[0].messages), 2)
        self.assertEqual(len(self.transports), 2)

    def test_incomplete_confirmation_state_never_executes_write(self):
        for field in ("executor", "registry", "confirmation_id"):
            with self.subTest(field=field):
                self.setUp()
                pending = self.pending()
                state = next(iter(self.app._conversations.values()))
                setattr(state, field, None)
                with self.assertRaises(RequestError) as caught:
                    self.confirm(pending)
                self.assertEqual(caught.exception.code, "confirmation_expired")
                self.assertEqual(self.writes(), [])

    def test_model_failure_after_write_does_not_repeat_write(self):
        pending = self.pending()
        self.model.generate.side_effect = OllamaError("private detail")
        result = self.confirm(pending)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("private detail", str(result))
        self.assertEqual(self.confirm(pending), result)
        self.assertEqual(len(self.writes()), 1)

    def test_invalid_identity_and_extra_fields_rejected(self):
        for session in (None, "invalid"):
            with self.assertRaises(RequestError):
                self.app.handle(
                    "/chat",
                    session,
                    {
                        "conversation_id": "test",
                        "request_id": "q1",
                        "message": "你好",
                    },
                )
        with self.assertRaises(RequestError):
            self.app.handle(
                "/chat",
                self.session,
                {
                    "conversation_id": "test",
                    "request_id": "q1",
                    "message": "你好",
                    "username": "admin",
                },
            )
        self.model.generate.assert_not_called()

    def test_http_health_and_proxy_boundary(self):
        self.model.generate.return_value = answer("你好")
        server = AgentHTTPServer(("127.0.0.1", 0), self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(root + "/health") as response:
                self.assertTrue(json.load(response)["agent_implemented"])
            body = json.dumps(
                {"conversation_id": "web", "request_id": "r", "message": "你好"}
            ).encode()
            headers = {"Content-Type": "application/json", "X-Business-Session": self.session}
            with urlopen(Request(root + "/chat", data=body, headers=headers)) as response:
                self.assertEqual(json.load(response)["reply"], "你好")
            with self.assertRaises(HTTPError) as caught:
                urlopen(
                    Request(
                        root + "/chat", data=body, headers={**headers, "Origin": "http://other"}
                    )
                )
            self.assertEqual(caught.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_model_context_is_injected_into_api_request(self):
        app = AgentApplication(load_settings({"MODEL_CONTEXT_TOKENS": "8192"}))
        model = app.model_factory()
        model._open = Mock(
            return_value={
                "message": {"role": "assistant", "content": "你好"},
                "model": "test",
                "done": True,
            }
        )
        model.generate(ModelRequest([Message("user", "你好")]))
        self.assertEqual(json.loads(model._open.call_args.args[0].data)["options"]["num_ctx"], 8192)

    def test_session_cookie_is_bound_to_business_host(self):
        from urllib.request import Request

        client = BusinessApiTransport()
        client.bind_business_session(self.session)
        request = Request("http://127.0.0.1:8000/api/v1/me")
        client._cookie_jar.add_cookie_header(request)
        self.assertEqual(request.get_header("Cookie"), "sessionid=" + self.session)
        other = Request("http://example.com/api/v1/me")
        client._cookie_jar.add_cookie_header(other)
        self.assertIsNone(other.get_header("Cookie"))
