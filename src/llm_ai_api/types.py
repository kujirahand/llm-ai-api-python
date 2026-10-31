"""戻り値の型。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .errors import LLMError
from .lang import t


@dataclass
class Usage:
    """トークン使用量。"""

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass
class ChatResult:
    """チャットの結果。`raw` にレスポンス JSON 全体が入る。"""

    text: str
    model: Optional[str] = None
    stop_reason: Optional[str] = None
    usage: Optional[Usage] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatChunk:
    """ストリーミングの 1 イベント。`text` はテキスト差分（なければ空文字）。"""

    text: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SSEEvent:
    """Server-Sent Events の 1 イベント。`data` は生の文字列。"""

    event: Optional[str]
    data: str

    def json(self) -> Dict[str, Any]:
        """`data` を JSON として解釈して返す。"""
        try:
            return json.loads(self.data)
        except ValueError as e:
            raise LLMError(
                t("invalid_json_response", preview=self.data[:200]),
                code="invalid_json_response",
            ) from e
