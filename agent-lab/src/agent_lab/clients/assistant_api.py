"""网站 AI 面板的聊天代理 API。"""

from typing import TypedDict, cast

from .pojo import ApiRequest, ApiResponse
from .transport import BusinessApiTransport


class ChatRequest(TypedDict):
    message: str


class ChatResponse(TypedDict):
    reply: str
    implemented: bool


class AssistantApi:
    """提供 business-demo 网站 AI 面板的聊天代理接口。"""

    def __init__(self, transport: BusinessApiTransport) -> None:
        self._transport = transport

    def chat(self, message: str) -> ApiResponse[ChatResponse]:
        """把一条聊天消息发送给网站配置的 Agent 空服务。"""
        body: ChatRequest = {"message": message}
        return cast(
            ApiResponse[ChatResponse],
            self._transport.send(
                ApiRequest("POST", "assistant/chat", body=body, requires_csrf=True)
            ),
        )
