"""健康检查等系统级 API。"""

from typing import TypedDict, cast

from .pojo import ApiRequest, ApiResponse
from .transport import BusinessApiTransport


class HealthResponse(TypedDict):
    status: str
    service: str


class SystemApi:
    """提供健康检查等无需业务身份的系统接口。"""

    def __init__(self, transport: BusinessApiTransport) -> None:
        self._transport = transport

    def health(self) -> ApiResponse[HealthResponse]:
        """查询 business-demo 服务是否正常运行。"""
        return cast(
            ApiResponse[HealthResponse],
            self._transport.send(ApiRequest("GET", "health")),
        )
