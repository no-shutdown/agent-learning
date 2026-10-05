"""原生工具协议回归：只测试消息与调用边界，不连接真实业务服务。"""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from agent_lab.models import OllamaClient
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
        calls = [{"function": {"name": "get_order", "arguments": {"order_id": 12}}}]
        self.model.chat_with_tool_definitions.side_effect = [
            answer(calls=calls),
            answer("订单待支付"),
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
        self.assertEqual(result.messages[1], {"role": "user", "content": "查询订单 12"})
        self.assertEqual(result.messages[2]["tool_calls"], calls)
        tool_message = result.messages[3]
        self.assertEqual(tool_message["role"], "tool")
        self.assertEqual(tool_message["tool_name"], "get_order")
        self.assertEqual(json.loads(tool_message["content"]), self.executor.execute.return_value)
        self.assertEqual(self.executor.execute.call_args.kwargs["arguments"], {"order_id": 12})
        self.assertNotIn('"tool_id": "get_order"', result.messages[0]["content"])

    def test_old_json_is_text_never_an_execution_request(self):
        legacy = (
            '{"role":"ai","type":"tool","data":{"tool_id":"get_order","arguments":{"order_id":12}}}'
        )
        self.model.chat_with_tool_definitions.return_value = answer(legacy)
        result = self.run_task()
        self.assertEqual(result.reply, legacy)
        self.executor.execute.assert_not_called()

    def test_empty_answer_is_protocol_error(self):
        self.model.chat_with_tool_definitions.return_value = answer()
        with self.assertRaises(LoopProtocolError):
            self.run_task()
        self.executor.execute.assert_not_called()

    def test_confirmation_still_stops_loop(self):
        self.model.chat_with_tool_definitions.return_value = answer(
            calls=[
                {
                    "function": {"name": "get_order", "arguments": {"order_id": 12}},
                }
            ]
        )
        self.executor.execute.return_value = {
            "call_id": "call_1",
            "tool_id": "get_order",
            "status": "confirmation_required",
            "confirmation": {"message": "请确认"},
        }
        result = self.run_task()
        self.assertEqual(result.status, "confirmation_required")
        self.model.chat_with_tool_definitions.assert_called_once()
        self.assertEqual(result.pending_calls[0].tool_id, "get_order")
