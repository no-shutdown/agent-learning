"""登录网站到本机 Agent 的代理；不包含提示词或 Agent 业务编排。"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from django.conf import settings
from django.http import JsonResponse

from . import services as s


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


open_agent = build_opener(ProxyHandler({}), NoRedirect()).open


def proxy_agent(request, data, *, confirm=False):
    fields = (
        ("conversation_id", "request_id", "confirmation_id", "accept")
        if confirm
        else ("conversation_id", "request_id", "message")
    )
    s.fields(data, fields, fields if confirm else ("message",))
    outgoing = {
        "conversation_id": s.text(data.get("conversation_id", "default"), "conversation_id", 100),
        "request_id": s.text(data.get("request_id", str(uuid4())), "request_id", 100),
    }
    if confirm:
        if type(data["accept"]) is not bool:
            raise s.BusinessError("invalid_input", "accept 必须是布尔值")
        outgoing.update(
            confirmation_id=s.text(data["confirmation_id"], "confirmation_id", 100),
            accept=data["accept"],
        )
    else:
        outgoing["message"] = s.text(data["message"], "message", 2000)
    target = urlsplit(settings.AGENT_URL)
    if (
        target.scheme not in ("http", "https")
        or target.hostname not in ("127.0.0.1", "localhost", "::1")
        or target.username
        or target.password
        or target.query
        or target.fragment
    ):
        raise s.BusinessError("agent_config", "Agent 地址必须是本机地址", 503)
    if not request.session.session_key:
        raise s.BusinessError("unauthenticated", "请重新登录", 401)
    path = "/confirm" if confirm else "/chat"
    url = urlunsplit((target.scheme, target.netloc, path, "", ""))
    req = Request(
        url,
        data=json.dumps(outgoing).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            # 仅转发当前请求已验证的 Django 会话，绝不从 JSON 接收用户名或 Cookie。
            "X-Business-Session": request.session.session_key,
        },
    )
    try:
        try:
            response = open_agent(req, timeout=settings.AGENT_TIMEOUT_SECONDS)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized response")
            result = json.loads(raw)
            status = response.code
        if not isinstance(result, dict):
            raise ValueError("invalid response")
        if status != 200:
            # 不透传服务栈信息或响应头，只返回 Agent 定义的公开错误。
            error = result.get("error", {})
            if not isinstance(error, dict) or not isinstance(error.get("message"), str):
                raise ValueError("invalid error")
            return JsonResponse(
                {"error": {"code": "agent_request_failed", "message": error["message"][:400]}},
                status=status if status in (400, 401, 403, 409, 415, 503) else 502,
            )
        if not isinstance(result.get("reply"), str):
            raise ValueError("invalid reply")
        return JsonResponse(result)
    except (URLError, OSError, ValueError):
        raise s.BusinessError(
            "agent_unavailable", "Agent 不可用或响应超时；若涉及写入请先核实操作记录", 503
        ) from None
