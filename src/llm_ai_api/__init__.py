"""OpenAI / OpenRouter / Claude の API を呼び出す、薄くて壊れにくい HTTP ラッパー。"""

__version__ = "0.6.0"

from . import models
from .anthropic import AnthropicClient
from ._connection import get_connection, set_connection
from .cache import SQLiteCache, clear_cache, get_cache, set_cache
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
    StructuredOutputError,
)
from .google import GoogleClient
from .llm import LLM, llm
from .log import JSONLLog, get_log, set_log
from .lang import get_language, set_language
from .openai import OpenAIClient
from .openrouter import OpenRouterClient
from .types import ChatChunk, ChatResult, SSEEvent, Usage

__all__ = [
    "__version__",
    "llm",
    "models",
    "clear_cache",
    "SQLiteCache",
    "set_cache",
    "get_cache",
    "JSONLLog",
    "set_log",
    "get_log",
    "set_connection",
    "get_connection",
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
    "StructuredOutputError",
]
