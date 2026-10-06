"""结构化运行日志：上下文隔离、脱敏、滚动文件；日志失败不改变业务结果。"""

from collections.abc import Mapping, Callable, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import time
from uuid import uuid4
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

LOGGER = logging.getLogger("agent_lab.trace")
LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False
_CONTEXT: ContextVar[dict[str, object]] = ContextVar("agent_trace", default={})
_SECRETS: ContextVar[tuple[object, ...]] = ContextVar("agent_trace_secrets", default=())
_SECRET = re.compile(
    r"password|passwd|secret|authorization|cookie|api.?key|access.?token|refresh.?token|"
    r"session.?key|session.?id|business.?session|csrf|confirmation_id|^token$",
    re.I,
)
_PRIVATE = {"phone", "recipient", "detail"}


def redact(value, *, depth=0):
    """创建脱敏副本；不修改真正发送给模型或业务服务的数据。"""
    if depth > 40:
        return "[DEPTH_LIMIT]"
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _SECRET.search(str(key)) or str(key).lower() in _PRIVATE
            else redact(item, depth=depth + 1)
            for key, item in value.items()
            if str(key).lower() not in {"thinking", "reasoning", "reasoning_content"}
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        for secret in _SECRETS.get():
            if isinstance(secret, str) and secret:
                value = value.replace(secret, "[REDACTED]")
        # tool 消息的 content 本身是 JSON 字符串，也需要检查其中的字段。
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                return json.dumps(redact(parsed, depth=depth + 1), ensure_ascii=False)
        value = re.sub(r"(?i)\bBearer\s+[^\s\"',;]+", "Bearer [REDACTED]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
        value = re.sub(
            r"(?i)((?:password|passwd|api[_-]?key|token|sessionid|密码|密钥)\s*[:=：]\s*)[^\s,;，；]+",
            r"\1[REDACTED]",
            value,
        )
        return re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[PHONE]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"[{type(value).__name__}]"


def emit(event, **data):
    try:
        record = redact(
            {
                "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                **_CONTEXT.get(),
                "event": event,
                **data,
            }
        )
        LOGGER.info(json.dumps(record, ensure_ascii=False, allow_nan=False))
    except Exception:
        # 包括磁盘/编码/异常参数问题；不能令已发生的业务写入变成失败重试。
        pass


@contextmanager
def trace_context(*, sensitive_values=(), **fields):
    secret_token = _SECRETS.set((*_SECRETS.get(), *sensitive_values))
    token = _CONTEXT.set({**_CONTEXT.get(), **fields})
    try:
        yield
    finally:
        _CONTEXT.reset(token)
        _SECRETS.reset(secret_token)


def set_context(**fields):
    """仅在 trace_context 内补充已知的任务编号。"""
    _CONTEXT.set({**_CONTEXT.get(), **fields})


@contextmanager
def span(name, **request):
    step_id = uuid4().hex
    started = time.monotonic()
    emit(name + ".request", step_id=step_id, **request)

    def finish(result):
        emit(
            name + ".response",
            step_id=step_id,
            result=result,
            elapsed_ms=round((time.monotonic() - started) * 1000, 2),
        )

    try:
        yield finish
    except Exception as error:
        emit(
            name + ".error",
            step_id=step_id,
            error_type=type(error).__name__,
            error_code=getattr(error, "code", None),
            elapsed_ms=round((time.monotonic() - started) * 1000, 2),
        )
        raise


def traced(name: str, fields: Sequence[str]) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """记录有多个提前返回分支的执行器，避免漏掉拒绝或去重结果。"""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            arguments = signature.bind(*args, **kwargs).arguments
            with span(name, **{key: arguments[key] for key in fields if key in arguments}) as done:
                result = function(*args, **kwargs)
                done(result)
                return result

        return wrapped

    return decorate


def configure_logging(log_dir):
    """由应用入口调用一次；子模块不读取环境，也不擅自创建日志文件。"""
    directory = Path(log_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "agent.jsonl"
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    file_handler = _PrivateRotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8", delay=True
    )
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    for handler in (logging.StreamHandler(), file_handler):
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    return path


class _PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        # 包含首次写入和轮转后重新创建文件。
        path = Path(self.baseFilename)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        return super()._open()
