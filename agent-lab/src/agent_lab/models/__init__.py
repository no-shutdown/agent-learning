"""Model API clients."""

from .ollama import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    OllamaChatResponse,
    OllamaClient,
    OllamaConnectionError,
    OllamaError,
    OllamaHttpError,
    OllamaMessage,
    OllamaProtocolError,
    OllamaToolCall,
    OllamaToolCallFunction,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_RESPONSE_BYTES",
    "OllamaChatResponse",
    "OllamaClient",
    "OllamaConnectionError",
    "OllamaError",
    "OllamaHttpError",
    "OllamaMessage",
    "OllamaProtocolError",
    "OllamaToolCall",
    "OllamaToolCallFunction",
]

from .contracts import (
    ChatModel,
    Message,
    ModelRequest,
    ModelResponse,
    ModelError,
    ModelProtocolError,
    ToolCall,
)

__all__ += [
    "ChatModel",
    "Message",
    "ModelRequest",
    "ModelResponse",
    "ModelError",
    "ModelProtocolError",
    "ToolCall",
]
