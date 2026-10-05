"""配置读取、启动校验及客户端显式注入；不访问网络。"""

import json
import unittest
from unittest.mock import Mock, patch

from agent_lab.clients import ApiResponse, BusinessApiTransport, OrdersApi
from agent_lab.config import ConfigError, load_settings
from agent_lab.main import main
from agent_lab.models import OllamaClient


class ConfigTest(unittest.TestCase):
    def test_defaults_and_empty_mapping_are_independent_of_environment(self):
        with patch.dict("os.environ", {"AGENT_PORT": "invalid"}):
            settings = load_settings({})
        self.assertEqual(settings.agent_port, 8001)
        self.assertEqual(settings.business_api_base_url, "http://127.0.0.1:8000/api/v1")
        self.assertEqual(settings.model_name, "qwen3.5:9b")
        self.assertEqual(settings.business_api_timeout_seconds, 5)
        self.assertEqual(settings.model_timeout_seconds, 120)

    def test_invalid_environment_reports_only_key(self):
        cases = {
            "AGENT_PORT": ["", "0", "65536", "1.5", "-1"],
            "BUSINESS_API_BASE_URL": ["", "ftp://localhost", "http://user:secret@localhost"],
            "MODEL_BASE_URL": ["", "http://localhost:bad", "http://localhost?secret=value"],
            "MODEL_NAME": ["", "   "],
            "AGENT_LOG_DIR": ["", "   ", "bad\0path"],
            "BUSINESS_API_TIMEOUT_SECONDS": ["0", "-1", "nan", "inf", ""],
            "MODEL_CONTEXT_TOKENS": ["0", "1.5", "", "1023", "131073", "nan"],
            "MODEL_TIMEOUT_SECONDS": ["0", "-1", "nan", "inf", ""],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ConfigError) as caught:
                        load_settings({name: value})
                    self.assertEqual(str(caught.exception), f"配置 {name} 不合法")

    def test_settings_reach_client_requests(self):
        settings = load_settings(
            {
                "BUSINESS_API_BASE_URL": "http://localhost:9000/",
                "BUSINESS_API_TIMEOUT_SECONDS": "2.5",
                "MODEL_BASE_URL": "http://localhost:11435/",
                "MODEL_NAME": "test-model",
                "MODEL_TIMEOUT_SECONDS": "30",
            }
        )
        transport = BusinessApiTransport(
            settings.business_api_base_url, timeout_seconds=settings.business_api_timeout_seconds
        )
        transport._open = Mock(return_value=ApiResponse(200, {}, {}))
        OrdersApi(transport).list_orders()
        self.assertEqual(
            transport._open.call_args.args[0].full_url, "http://localhost:9000/api/v1/orders"
        )
        self.assertEqual(transport._timeout_seconds, 2.5)
        model = OllamaClient(
            settings.model_base_url,
            settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
        )
        model._open = Mock(
            return_value={
                "model": "test-model",
                "done": True,
                "message": {"role": "assistant", "content": "ok"},
            }
        )
        model.chat([{"role": "user", "content": "test"}])
        request = model._open.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:11435/api/chat")
        self.assertEqual(json.loads(request.data)["model"], "test-model")
        self.assertEqual(model._timeout_seconds, 30)

    def test_clients_do_not_read_application_environment(self):
        with patch.dict(
            "os.environ",
            {
                "MODEL_NAME": "unexpected",
                "MODEL_BASE_URL": "invalid",
                "BUSINESS_API_BASE_URL": "invalid",
            },
        ):
            self.assertEqual(OllamaClient().model, "qwen3.5:9b")
            self.assertIsInstance(BusinessApiTransport(), BusinessApiTransport)
        with self.assertRaises(ValueError):
            BusinessApiTransport("")
        with self.assertRaises(ValueError):
            OllamaClient(model="")

    def test_startup_validates_before_listening(self):
        with patch.dict("os.environ", {"AGENT_PORT": "invalid"}, clear=True):
            with patch("agent_lab.main.ThreadingHTTPServer") as server:
                with self.assertRaises(ConfigError):
                    main()
                server.assert_not_called()
        with patch.dict("os.environ", {"AGENT_PORT": "8123"}, clear=True):
            with (
                patch("agent_lab.main.ThreadingHTTPServer") as server,
                patch("builtins.print"),
                patch("agent_lab.main.configure_logging"),
            ):
                main()
                self.assertEqual(server.call_args.args[0], ("127.0.0.1", 8123))
                server.return_value.serve_forever.assert_called_once()
