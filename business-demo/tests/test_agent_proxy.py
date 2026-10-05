"""网站代理只使用已登录会话；不连接真实 Agent。"""

import json
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings


class AgentProxyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="proxy-test")
        self.client.force_login(self.user)
        self.body = {"conversation_id": "page1", "request_id": "req1", "message": "你好"}

    def post(self, data=None, route="chat", client=None):
        return (client or self.client).post(
            "/api/v1/assistant/" + route,
            data=json.dumps(self.body if data is None else data),
            content_type="application/json",
        )

    @patch("shop.agent_proxy.open_agent")
    def test_auth_csrf_and_injected_identity(self, network):
        self.assertEqual(self.post(client=Client()).status_code, 401)
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        self.assertEqual(self.post(client=browser).status_code, 403)
        self.assertEqual(self.post({**self.body, "username": "admin"}).status_code, 400)
        network.assert_not_called()

    @override_settings(AGENT_TIMEOUT_SECONDS=150, AGENT_URL="http://127.0.0.1:8001")
    @patch("shop.agent_proxy.open_agent")
    def test_verified_session_timeout_and_confirmation_forwarding(self, network):
        response = network.return_value
        response.code = 200
        response.read.return_value = b'{"reply":"ok","status":"completed"}'
        self.assertEqual(self.post().status_code, 200)
        request = network.call_args.args[0]
        self.assertEqual(request.get_header("X-business-session"), self.client.session.session_key)
        self.assertEqual(json.loads(request.data), self.body)
        self.assertEqual(network.call_args.kwargs["timeout"], 150)
        confirm = {
            "conversation_id": "page1",
            "request_id": "confirm1",
            "confirmation_id": "opaque",
            "accept": True,
        }
        self.assertEqual(self.post(confirm, route="confirm").status_code, 200)
        self.assertEqual(network.call_args.args[0].full_url, "http://127.0.0.1:8001/confirm")
        self.assertEqual(json.loads(network.call_args.args[0].data), confirm)

    @override_settings(AGENT_URL="https://example.com")
    @patch("shop.agent_proxy.open_agent")
    def test_remote_agent_cannot_receive_session(self, network):
        self.assertEqual(self.post().status_code, 503)
        network.assert_not_called()
