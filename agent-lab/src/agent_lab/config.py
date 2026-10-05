"""应用配置入口：读取环境变量并校验，不创建网络连接或保存全局实例。"""

from collections.abc import Mapping
from dataclasses import dataclass
import math
import os

from .clients import BusinessApiTransport, DEFAULT_API_BASE_URL
from .clients import DEFAULT_TIMEOUT_SECONDS as BUSINESS_TIMEOUT
from .models import DEFAULT_BASE_URL, DEFAULT_MODEL, OllamaClient
from .models import DEFAULT_TIMEOUT_SECONDS as MODEL_TIMEOUT


class ConfigError(ValueError):
    """环境配置不合法；错误只包含变量名，不回显配置值。"""


@dataclass(frozen=True, slots=True)
class Settings:
    agent_port: int
    business_api_base_url: str
    business_api_timeout_seconds: float
    model_base_url: str
    model_name: str
    model_timeout_seconds: float
    model_context_tokens: int = 16384


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """读取已注入进程的环境；.env 由 Makefile 或父目录启动器加载。

    测试可传独立映射，不改全局环境。子模块只接收显式参数，
    不导入本模块或自行读取环境。未设置采用默认值，空值视为错误。
    """
    env = os.environ if environ is None else environ

    def read(name, default, parser):
        try:
            return parser(env.get(name, default))
        except (ValueError, TypeError, OverflowError):
            raise ConfigError(f"配置 {name} 不合法") from None

    def port(value):
        if not isinstance(value, str) or not value.strip().isascii() or not value.strip().isdigit():
            raise ValueError()
        number = int(value)
        if not 1 <= number <= 65535:
            raise ValueError()
        return number

    def timeout(value):
        if not isinstance(value, str):
            raise ValueError()
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError()
        return number

    def context_tokens(value):
        if not isinstance(value, str) or not value.isascii() or not value.isdigit():
            raise ValueError()
        result = int(value)
        if not 1024 <= result <= 131072:
            raise ValueError()
        return result

    return Settings(
        agent_port=read("AGENT_PORT", "8001", port),
        business_api_base_url=read(
            "BUSINESS_API_BASE_URL", DEFAULT_API_BASE_URL, BusinessApiTransport.validate_base_url
        ),
        business_api_timeout_seconds=read(
            "BUSINESS_API_TIMEOUT_SECONDS", str(BUSINESS_TIMEOUT), timeout
        ),
        model_base_url=read("MODEL_BASE_URL", DEFAULT_BASE_URL, OllamaClient.validate_base_url),
        model_context_tokens=read("MODEL_CONTEXT_TOKENS", "16384", context_tokens),
        model_name=read("MODEL_NAME", DEFAULT_MODEL, OllamaClient.validate_model),
        model_timeout_seconds=read("MODEL_TIMEOUT_SECONDS", str(MODEL_TIMEOUT), timeout),
    )
