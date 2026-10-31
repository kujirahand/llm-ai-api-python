"""共通インターフェイス `llm("プロバイダー:モデル")`。"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from ._http import BaseClient
from .anthropic import AnthropicClient
from .errors import LLMConfigError
from .lang import t
from .openai import OpenAIClient
from .openrouter import OpenRouterClient
from .types import ChatResult

_PROVIDERS = {
    "openai": OpenAIClient,
    "openrouter": OpenRouterClient,
    "anthropic": AnthropicClient,
    "claude": AnthropicClient,
}


def parse_model_spec(spec: str, lang: Optional[str] = None) -> "tuple[str, str]":
    """`"provider:model"` を (provider, model) に分ける。最初の `:` で分割する。"""
    provider, sep, model = spec.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if not sep or not provider or not model:
        raise LLMConfigError(t("invalid_model_spec", lang, spec=spec), code="invalid_model_spec")
    if provider not in _PROVIDERS:
        raise LLMConfigError(
            t("unknown_provider", lang, provider=provider, supported=", ".join(sorted(_PROVIDERS))),
            code="unknown_provider",
        )
    return provider, model


class LLM:
    """プロバイダーの違いを意識せずに使える共通インターフェイス。会話履歴は持たない。"""

    def __init__(
        self,
        spec: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        **client_options: Any,
    ) -> None:
        provider, model = parse_model_spec(spec, client_options.get("lang"))
        self.provider = "anthropic" if provider == "claude" else provider
        self.model = model
        self.system = system
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra = extra
        self.client: BaseClient = _PROVIDERS[provider](**client_options)

    def __repr__(self) -> str:
        return "LLM(%r)" % ("%s:%s" % (self.provider, self.model))

    def close(self) -> None:
        """下位クライアントを閉じる。"""
        self.client.close()

    def __enter__(self) -> "LLM":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _prepare(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float],
        extra: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        system = system if system is not None else self.system
        merged: Optional[Dict[str, Any]] = None
        if self.extra or extra:
            merged = dict(self.extra or {})
            merged.update(extra or {})
        msgs = list(messages)
        if system is not None:
            msgs.insert(0, {"role": "system", "content": system})
        return {
            "model": self.model,
            "messages": msgs,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "extra": merged,
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ChatResult:
        """messages を渡して `ChatResult`（stop_reason や raw を含む）を受け取る。"""
        kw = self._prepare(messages, system, max_tokens, temperature, extra)
        return self.client.chat(**kw)  # type: ignore[attr-defined]

    def ask(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """1 つの質問を送り、回答のテキストだけを返す。"""
        msgs = [{"role": "user", "content": prompt}]
        return self.chat(
            msgs, system=system, max_tokens=max_tokens, temperature=temperature, extra=extra
        ).text

    def stream(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Iterator[str]:
        """1 つの質問を送り、回答のテキスト差分を順に返す。"""
        msgs = [{"role": "user", "content": prompt}]
        kw = self._prepare(msgs, system, max_tokens, temperature, extra)
        chunks = self.client.stream_chat(**kw)  # type: ignore[attr-defined]
        return (c.text for c in chunks if c.text)


def llm(spec: str, **options: Any) -> LLM:
    """`llm("openai:gpt-6-luna")` のようにモデルを指定して `LLM` を作る。"""
    return LLM(spec, **options)
