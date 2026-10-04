"""登录、登出、CSRF 和当前身份 API。"""

from typing import Literal, TypedDict, cast

from .pojo import ApiRequest, ApiResponse
from .transport import BusinessApiTransport


class CsrfResponse(TypedDict):
    csrf_token: str


class LoginRequest(TypedDict):
    username: str
    password: str


class LoginResponse(TypedDict):
    username: str
    csrf_token: str


class LogoutResponse(TypedDict):
    status: Literal["logged_out"]


class CurrentUserResponse(TypedDict):
    username: str
    is_staff: bool


class AuthApi:
    """提供登录会话及当前用户身份查询接口。"""

    def __init__(self, transport: BusinessApiTransport) -> None:
        self._transport = transport

    def get_csrf(self) -> ApiResponse[CsrfResponse]:
        """获取 CSRF token；登录和所有受保护的写请求都会使用它。"""
        return cast(ApiResponse[CsrfResponse], self._transport.get_csrf())

    def login(self, username: str, password: str) -> ApiResponse[LoginResponse]:
        """使用用户名和密码登录，并保存服务端轮换后的会话 Cookie 与 CSRF token。
        """
        body: LoginRequest = {"username": username, "password": password}
        return cast(
            ApiResponse[LoginResponse],
            self._transport.send(
                ApiRequest("POST", "auth/login", body=body, requires_csrf=True)
            ),
        )

    def logout(self) -> ApiResponse[LogoutResponse]:
        """退出当前登录会话并清除本地缓存的 CSRF token。"""
        return cast(
            ApiResponse[LogoutResponse],
            self._transport.send(
                ApiRequest("POST", "auth/logout", body={}, requires_csrf=True)
            ),
        )

    def current_user(self) -> ApiResponse[CurrentUserResponse]:
        """查询当前会话对应的用户名及管理员标记。"""
        return cast(
            ApiResponse[CurrentUserResponse],
            self._transport.send(ApiRequest("GET", "me")),
        )
