"""加载并渲染 Agent 提示模板。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_TOOL_LIST_PLACEHOLDER = "{_工具列表}"


class PromptLoadError(RuntimeError):
    """提示模板无法读取或渲染时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class LoadedPrompt:
    """已渲染的提示文本及根据内容生成的版本标识。"""

    text: str
    version: str


def load_prompt(
    tool_list: str = "",
    *,
    template_path: str | Path | None = None,
) -> LoadedPrompt:
    """读取 ``agent.md``，填入可用工具列表，并生成内容版本标识。

    ``version`` 是渲染后提示文本的完整 SHA-256 摘要。模板内容或工具列表变化时，
    版本标识也会变化。默认根据本模块所在目录定位模板，不受进程当前工作目录影响。
    """
    if not isinstance(tool_list, str):
        raise TypeError("tool_list 必须是字符串")

    source = Path(template_path) if template_path is not None else Path(__file__).with_name("agent.md")

    try:
        template = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PromptLoadError(f"无法读取提示模板：{source}") from exc

    if _TOOL_LIST_PLACEHOLDER not in template:
        raise PromptLoadError(f"提示模板缺少工具列表占位符：{_TOOL_LIST_PLACEHOLDER}")

    rendered_tool_list = tool_list.strip() or "（当前没有可用工具。）"
    text = template.replace(_TOOL_LIST_PLACEHOLDER, rendered_tool_list)
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return LoadedPrompt(text=text, version=version)
