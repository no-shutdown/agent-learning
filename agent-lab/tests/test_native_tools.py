"""原生工具协议回归：只测试消息与调用边界，不连接真实业务服务。"""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from agent_lab.models import (
    OllamaClient,
    Message,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ModelProtocolError,
)
from agent_lab.prompts.loader import load_prompt, PromptLoadError
from agent_lab.runtime.loop import run_loop, LoopProtocolError
from agent_lab.tools import ToolRegistry, GET_ORDER


def answer(content="", calls=None):
    return {
        "model": "test",
        "done": True,
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": calls or [],
        },
    }


class NativeToolsTest(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry([GET_ORDER])
        self.model = Mock()
        self.executor = Mock()

    def run_task(self):
        return run_loop(
            "查询订单 12", model=self.model, executor=self.executor, registry=self.registry
        )

    def test_prompt_has_no_tool_placeholder_and_version_is_content_hash(self):
        prompt = load_prompt()
        self.assertNotIn("{_工具列表}", prompt.text)
        self.assertNotIn('"role":"ai"', prompt.text)
        self.assertEqual(prompt.version, hashlib.sha256(prompt.text.encode()).hexdigest())
        with TemporaryDirectory() as directory:
            path = Path(directory) / "agent.md"
            path.write_text("自定义规则", encoding="utf-8")
            self.assertEqual(load_prompt(template_path=path).text, "自定义规则")
            path.write_text(" ", encoding="utf-8")
            with self.assertRaises(PromptLoadError):
                load_prompt(template_path=path)

    def test_client_sends_definitions_through_tools(self):
        client = OllamaClient()
        client._open = Mock(return_value=answer("你好"))
        prompt = load_prompt()
        messages = [
            {"role": "system", "content": prompt.text},
            {"role": "user", "content": "查询订单 12"},
        ]
        client.chat_with_tool_definitions(
            messages, tool_definitions=self.registry.definitions(), timeout_seconds=9
        )
        request = json.loads(client._open.call_args.args[0].data)
        self.assertEqual(request["messages"], messages)
        self.assertNotIn("format", request)
        self.assertEqual(
            request["tools"],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_order",
                        "description": GET_ORDER.description,
                        "parameters": GET_ORDER.parameters,
                    },
                }
            ],
        )
        self.assertEqual(client._open.call_args.kwargs["timeout_seconds"], 9)

    def test_native_call_executor_and_tool_result_round_trip(self):
        self.model.generate.side_effect = [
            ModelResponse(tool_calls=(ToolCall("call_1", "get_order", {"order_id": 12}),)),
            ModelResponse("订单待支付"),
        ]
        self.executor.execute.return_value = {
            "call_id": "call_1",
            "tool_id": "get_order",
            "status": "success",
            "result": {"id": 12, "status": "pending_payment"},
            "error": None,
        }
        result = self.run_task()
        self.assertEqual(result.reply, "订单待支付")
        self.assertEqual((result.model_calls, result.tool_calls), (2, 1))
        self.assertEqual(result.messages[1], Message("user", "查询订单 12"))
        self.assertEqual(result.messages[2].tool_calls[0].tool_id, "get_order")
        tool_message = result.messages[3]
        self.assertEqual(tool_message.role, "tool")
        self.assertEqual(tool_message.tool_result["tool_id"], "get_order")
        self.assertEqual(tool_message.tool_result, self.executor.execute.return_value)
        self.assertEqual(self.executor.execute.call_args.kwargs["arguments"], {"order_id": 12})
        self.assertNotIn('"tool_id": "get_order"', result.messages[0].text)

    def test_old_json_is_text_never_an_execution_request(self):
        legacy = (
            '{"role":"ai","type":"tool","data":{"tool_id":"get_order","arguments":{"order_id":12}}}'
        )
        self.model.generate.return_value = ModelResponse(legacy)
        result = self.run_task()
        self.assertEqual(result.reply, legacy)
        self.executor.execute.assert_not_called()

    def test_empty_answer_is_protocol_error(self):
        self.model.generate.return_value = ModelResponse()
        with self.assertRaises(LoopProtocolError):
            self.run_task()
        self.executor.execute.assert_not_called()

    def test_confirmation_still_stops_loop(self):
        self.model.generate.return_value = ModelResponse(
            tool_calls=(ToolCall("call_1", "get_order", {"order_id": 12}),)
        )
        self.executor.execute.return_value = {
            "call_id": "call_1",
            "tool_id": "get_order",
            "status": "confirmation_required",
            "confirmation": {"message": "请确认"},
        }
        result = self.run_task()
        self.assertEqual(result.status, "confirmation_required")
        self.model.generate.assert_called_once()
        self.assertEqual(result.pending_calls[0].tool_id, "get_order")


class AdapterTest(unittest.TestCase):
    def test_native_conversion_and_result_correlation(self):
        client = OllamaClient()
        client._open = Mock(
            return_value=answer(
                calls=[
                    {
                        "id": "provider-call",
                        "function": {"name": "get_order", "arguments": {"order_id": 12}},
                    }
                ]
            )
        )
        first = client.generate(
            ModelRequest([Message("user", "查订单12")], ToolRegistry([GET_ORDER]).definitions())
        )
        self.assertIsInstance(first, ModelResponse)
        self.assertEqual(first.tool_calls[0].call_id, "provider-call")
        result = {
            "call_id": "provider-call",
            "tool_id": "get_order",
            "status": "success",
            "result": {"id": 12},
            "error": None,
        }
        client._open.return_value = answer("订单已找到")
        second = client.generate(
            ModelRequest(
                [
                    Message("user", "查订单12"),
                    Message("assistant", tool_calls=first.tool_calls),
                    Message("tool", tool_result=result),
                ]
            )
        )
        payload = json.loads(client._open.call_args.args[0].data)
        self.assertEqual(payload["messages"][1]["tool_calls"][0]["id"], "provider-call")
        tool = payload["messages"][2]
        self.assertEqual(tool["tool_call_id"], "provider-call")
        self.assertEqual(tool["tool_name"], "get_order")
        self.assertEqual(json.loads(tool["content"]), result)
        self.assertEqual(second.text, "订单已找到")

    def test_missing_ids_are_unique_and_malformed_ids_rejected(self):
        client = OllamaClient()
        raw = answer(calls=[{"function": {"name": "get_order", "arguments": {"order_id": 12}}}])
        client._open = Mock(return_value=raw)
        request = ModelRequest([Message("user", "查订单12")])
        first = client.generate(request)
        second = client.generate(request)
        self.assertNotEqual(first.tool_calls[0].call_id, second.tool_calls[0].call_id)
        raw["message"]["tool_calls"][0]["id"] = 123
        with self.assertRaises(ModelProtocolError):
            client.generate(request)

    def test_loop_accepts_provider_independent_fake(self):
        class FakeModel:
            def generate(self, request, *, timeout_seconds=None):
                assert isinstance(request, ModelRequest)
                assert isinstance(request.messages[0], Message)
                return ModelResponse("统一接口回答")

        result = run_loop("你好", model=FakeModel(), executor=Mock(), registry=ToolRegistry([]))
        self.assertEqual(result.reply, "统一接口回答")

    def test_raw_provider_response_cannot_enter_loop(self):
        model = Mock()
        model.generate.return_value = answer("原始响应")
        with self.assertRaises(LoopProtocolError):
            run_loop("你好", model=model, executor=Mock(), registry=ToolRegistry([]))

    def test_contract_rejects_non_json_arguments_and_invalid_messages(self):
        for args in ({"value": float("nan")}, [], {"value": object()}):
            with self.assertRaises(ModelProtocolError):
                ToolCall("c1", "tool", args)
        with self.assertRaises(ModelProtocolError):
            Message("tool")
        with self.assertRaises(ModelProtocolError):
            ModelRequest([{"role": "user", "content": "raw"}])
