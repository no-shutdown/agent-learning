"""加载 Agent 系统提示并生成内容版本；工具定义由模型请求单独传入。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class PromptLoadError(RuntimeError):
    """提示模板无法读取或渲染时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class LoadedPrompt:
    """系统提示文本及根据内容生成的版本标识。"""

    text: str
    version: str


def load_prompt(
    *,
    template_path: str | Path | None = None,
) -> LoadedPrompt:
    """读取系统提示，版本是提示文本的 SHA-256 摘要。

    工具定义不进入系统提示，也不计入此版本；实验记录需另外保存工具定义。
    默认路径相对于本模块，不受工作目录影响。
    """
    source = (
        Path(template_path) if template_path is not None else Path(__file__).with_name("agent.md")
    )

    try:
        template = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PromptLoadError(f"无法读取提示模板：{source}") from exc

    if not template.strip():
        raise PromptLoadError("系统提示不能为空")
    version = hashlib.sha256(template.encode("utf-8")).hexdigest()
    return LoadedPrompt(text=template, version=version)
