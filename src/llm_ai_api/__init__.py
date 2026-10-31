"""OpenAI / OpenRouter / Claude の API を呼び出す、薄くて壊れにくい HTTP ラッパー。"""

__version__ = "0.0.1"

from . import models
from .anthropic import AnthropicClient
from .errors import (
    APIConnectionError,
    APIStatusError,
    APIStreamError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    LLMConfigError,
    LLMError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from .google import GoogleClient
from .llm import LLM, llm
from .lang import get_language, set_language
from .openai import OpenAIClient
from .openrouter import OpenRouterClient
from .types import ChatChunk, ChatResult, SSEEvent, Usage

__all__ = [
    "__version__",
    "llm",
    "models",
    "set_language",
    "get_language",
    "LLM",
    "OpenAIClient",
    "OpenRouterClient",
    "AnthropicClient",
    "GoogleClient",
    "ChatResult",
    "ChatChunk",
    "SSEEvent",
    "Usage",
    "LLMError",
    "LLMConfigError",
    "APIConnectionError",
    "APITimeoutError",
    "APIStatusError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "RateLimitError",
    "InternalServerError",
    "APIStreamError",
]
