"""执行器边界与循环接入测试；业务 HTTP 使用模拟传输，不写真实数据库。"""

from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from unittest.mock import Mock, patch

from agent_lab.clients import (
    ApiResponse,
    BusinessApiTransport,
    BusinessApiConnectionError,
    BusinessApiHttpError,
)
from agent_lab.runtime.executor import ToolExecutor
from agent_lab.models import ModelResponse, ToolCall
from agent_lab.runtime.loop import run_loop, LoopProtocolError
from agent_lab.tools import ToolRegistry, GET_ORDER, PAY_ORDER, SHIP_ORDER


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.transport = BusinessApiTransport()
        self.transport.send = Mock(side_effect=self.send)
        self.requests = []
        self.username = "learner"
        self.staff = False
        self.failure = None
        self.malformed = False
        self.registry = ToolRegistry([GET_ORDER, PAY_ORDER, SHIP_ORDER])
        self.executor = ToolExecutor(
            self.transport, self.registry, username="learner", max_calls=30
        )
        self.args = {"order_id": 12, "version": 1}

    def send(self, request):
        self.requests.append(request)
        if request.path == "me":
            data = {"username": self.username, "is_staff": self.staff}
        elif self.failure:
            raise self.failure
        elif self.malformed:
            data = {"unexpected": True}
        elif request.method == "GET":
            data = {"id": 12, "status": "pending_payment", "version": 1}
        else:
            data = {"data": {"id": 12, "version": 2}, "replayed": False}
        return ApiResponse(200, {"x-private": "do-not-expose"}, data)

    def execute(self, name="pay_order", args=None, call_id="call_1"):
        return self.executor.execute(
            call_id=call_id,
            tool_id=name,
            arguments=self.args if args is None else args,
            timeout_seconds=5,
        )

    def approve(self):
        pending = self.execute()
        self.assertEqual(pending["status"], "confirmation_required")
        self.executor.confirm("call_1", username="learner")

    def writes(self):
        return [r for r in self.requests if r.method != "GET"]

    def test_allowlist_and_parameters_before_http(self):
        for name, args in [
            ("login", {}),
            ("get_order", {"order_id": True}),
            ("get_order", {"order_id": 12, "url": "arbitrary"}),
            ("pay_order", {**self.args, "confirmed": True}),
        ]:
            with self.subTest(tool=name):
                self.assertEqual(self.execute(name, args)["status"], "error")
        self.assertEqual(self.requests, [])

    def test_identity_and_admin_are_rechecked(self):
        self.username = "other"
        self.assertEqual(
            self.execute("get_order", {"order_id": 12})["error"]["code"], "identity_mismatch"
        )
        self.username = "learner"
        self.assertEqual(
            self.execute("ship_order", {**self.args, "tracking_no": "T"})["error"]["code"],
            "forbidden",
        )
        self.assertTrue(all(r.path == "me" for r in self.requests))

    def test_confirmation_then_write_and_idempotent_replay(self):
        self.approve()
        self.assertEqual(self.writes(), [])
        result = self.execute()
        self.assertEqual(result["status"], "success")
        key = result["result"]["operation_key"]
        self.assertEqual(self.writes()[0].idempotency_key, key)
        self.assertEqual(self.writes()[0].body, {"version": 1})
        self.assertNotIn("do-not-expose", json.dumps(result))
        self.assertEqual(self.execute()["result"], result["result"])
        # 模型换一个调用编号也不能把同一笔写入再发一遍。
        self.assertEqual(self.execute(call_id="call_2")["result"]["operation_key"], key)
        self.assertEqual(len(self.writes()), 1)

    def test_changed_arguments_require_new_confirmation(self):
        self.approve()
        changed = {"order_id": 13, "version": 1}
        self.assertEqual(self.execute(args=changed)["error"]["code"], "call_conflict")
        self.assertEqual(
            self.execute(args=changed, call_id="call_2")["status"], "confirmation_required"
        )
        self.assertEqual(self.writes(), [])

    def test_wrong_identity_or_expired_confirmation_cannot_write(self):
        self.execute()
        with self.assertRaises(ValueError):
            self.executor.confirm("call_1", username="other")
        self.executor.confirm("call_1", username="learner")
        self.username = "other"
        self.assertEqual(self.execute()["error"]["code"], "identity_mismatch")
        self.username = "learner"
        self.executor._calls["call_1"].expires_at = 0
        self.assertEqual(self.execute()["error"]["code"], "confirmation_expired")
        self.assertEqual(self.writes(), [])

    def test_timeout_write_is_unknown_and_not_retried(self):
        self.approve()
        self.failure = BusinessApiConnectionError("hidden details")
        result = self.execute()
        self.assertEqual(result["status"], "unknown")
        self.assertIsNotNone(result["result"]["operation_key"])
        self.assertNotIn("hidden details", str(result))
        self.assertEqual(self.execute(call_id="next")["status"], "unknown")
        self.assertEqual(len(self.writes()), 1)

    def test_business_rejection_is_error_and_server_failure_unknown(self):
        self.approve()
        self.failure = BusinessApiHttpError(409, "version_conflict", "版本过期")
        self.assertEqual(self.execute()["error"]["code"], "version_conflict")
        self.executor = ToolExecutor(self.transport, self.registry, username="learner")
        self.approve()
        self.failure = BusinessApiHttpError(503, "unavailable", "hidden server details")
        result = self.execute()
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("hidden server details", str(result))

    def test_malformed_write_response_is_unknown(self):
        self.approve()
        self.malformed = True
        self.assertEqual(self.execute()["status"], "unknown")

    def test_response_for_another_target_is_not_success(self):
        result = self.execute("get_order", {"order_id": 13})
        self.assertEqual(result["error"]["code"], "protocol_error")

    def test_admin_revocation_after_confirmation_prevents_write(self):
        self.staff = True
        args = {**self.args, "tracking_no": "T"}
        self.assertEqual(self.execute("ship_order", args)["status"], "confirmation_required")
        self.executor.confirm("call_1", username="learner")
        self.staff = False
        self.assertEqual(self.execute("ship_order", args)["error"]["code"], "forbidden")
        self.assertEqual(self.writes(), [])

    def test_read_failure_and_identity_failure_are_not_unknown(self):
        self.failure = BusinessApiConnectionError("test")
        self.assertEqual(self.execute("get_order", {"order_id": 12})["status"], "error")
        self.transport.send = Mock(side_effect=BusinessApiConnectionError("test"))
        self.assertEqual(self.execute()["status"], "error")
        self.assertEqual(self.writes(), [])

    def test_executor_enforces_own_budget(self):
        self.executor = ToolExecutor(self.transport, self.registry, username="learner", max_calls=1)
        self.execute("get_order", {"order_id": 12})
        self.assertEqual(self.execute()["error"]["code"], "budget_exhausted")
        for value in [0, -1, float("nan"), True]:
            with self.assertRaises(ValueError):
                self.executor.execute(
                    call_id="x", tool_id="get_order", arguments={}, timeout_seconds=value
                )

    def test_concurrent_same_confirmed_write_is_sent_once(self):
        self.approve()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.execute(), range(2)))
        self.assertTrue(all(r["status"] == "success" for r in results))
        self.assertEqual(len(self.writes()), 1)

    def test_loop_uses_real_executor(self):
        model = Mock()
        model.generate.side_effect = [
            ModelResponse(tool_calls=(ToolCall("call_1", "get_order", {"order_id": 12}),)),
            ModelResponse(text="订单待支付"),
        ]
        result = run_loop(
            "查订单12", model=model, executor=self.executor, registry=ToolRegistry([GET_ORDER])
        )
        self.assertEqual(result.reply, "订单待支付")
        self.assertEqual(result.messages[3].tool_result["status"], "success")

    def test_loop_rejects_mismatched_executor_result(self):
        model = Mock()
        model.generate.return_value = ModelResponse(
            tool_calls=(ToolCall("call_1", "get_order", {"order_id": 12}),)
        )
        executor = Mock()
        executor.execute.return_value = {
            "call_id": "wrong",
            "tool_id": "get_order",
            "status": "success",
        }
        with self.assertRaises(LoopProtocolError):
            run_loop("查订单12", model=model, executor=executor, registry=self.registry)


class TransportBudgetTest(unittest.TestCase):
    def test_request_timeout_is_capped_and_restored(self):
        transport = BusinessApiTransport(timeout_seconds=5)
        response = Mock()
        response.status = 200
        response.headers = {}
        response.read.return_value = b'{"username":"learner","is_staff":false}'
        transport._opener.open = Mock()
        transport._opener.open.return_value.__enter__ = Mock(return_value=response)
        transport._opener.open.return_value.__exit__ = Mock(return_value=False)
        from agent_lab.clients import AuthApi

        with transport.request_budget(0.5):
            AuthApi(transport).current_user()
        self.assertGreater(transport._opener.open.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(transport._opener.open.call_args.kwargs["timeout"], 0.5)
        self.assertIsNone(transport._deadline)
        self.assertEqual(transport._timeout_seconds, 5)

    def test_exhausted_budget_stops_before_network_and_restores_state(self):
        transport = BusinessApiTransport()
        transport._opener.open = Mock()
        with patch("agent_lab.clients.transport.time.monotonic", side_effect=[1, 3]):
            with self.assertRaises(BusinessApiConnectionError):
                with transport.request_budget(1):
                    self.fail("不应进入已超时的会话")
        transport._opener.open.assert_not_called()
        self.assertIsNone(transport._deadline)
