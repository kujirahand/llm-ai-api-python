"""Shared provider model-list parsing and pagination state."""

from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from .errors import LLMConfigError, LLMError
from .lang import t


class ModelPages:
    """Advance a listing one response at a time, independent of the I/O method."""

    limit = 100
    compatible = frozenset(("openai", "openrouter", "grok", "muse", "lmstudio", "strata", "ollama", "google"))

    def __init__(self, provider: str, client: Any, raw: bool) -> None:
        self.lang = client.lang
        self.native = provider == "google" and client.base_url.endswith("/openai")
        if provider == "anthropic":
            self.base_path = "/v1/models"
        elif self.native:
            self.base_path = "../models"
        elif provider in self.compatible:
            self.base_path = "/models"
        else:
            raise LLMConfigError(t("unsupported_models", self.lang, provider=provider), code="unsupported_models")
        self.path: Optional[str] = self.base_path
        self.headers: Optional[Dict[str, str]] = {"x-goog-api-key": client._api_key} if self.native else None
        self.raw = raw
        self.items: List[Any] = []
        self.count = 0

    def accept(self, response: Dict[str, Any]) -> None:
        field = "models" if self.native else "data"
        values = response.get(field)
        if not isinstance(values, list):
            raise LLMError(t("invalid_models_response", self.lang, field=field, kind=type(values).__name__), code="invalid_json_response")
        for item in values:
            if not isinstance(item, dict):
                continue
            if self.raw:
                self.items.append(item)
            else:
                identifier = item.get("name" if self.native else "id")
                if isinstance(identifier, str):
                    if self.native and identifier.startswith("models/"):
                        identifier = identifier[len("models/"):]
                    self.items.append(identifier)
        token = response.get("nextPageToken") if self.native else (response.get("last_id") if response.get("has_more") else None)
        self.count += 1
        if token:
            if self.count >= self.limit:
                raise LLMError(t("models_page_limit", self.lang, limit=self.limit), code="models_pagination_limit")
            self.path = self.base_path + "?" + urlencode({"pageToken" if self.native else "after_id": token})
        else:
            self.path = None
