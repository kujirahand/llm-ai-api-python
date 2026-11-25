"""Tool-call helpers (internal): argument parsing, `tools=` mapping, `tool_results()`.

Depends only on `types`, `errors`, and `lang`, so the provider modules can import it.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Tuple

from .errors import LLMConfigError
from .lang import t
from .types import ToolCall

_TOOL_KEYS = ("name", "description", "parameters")


def _invalid(lang: Optional[str]) -> LLMConfigError:
    return LLMConfigError(t("invalid_tools", lang), code="invalid_tools")


def _parse_arguments(value: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return `(parsed dict or None, raw JSON string)` for a tool-call arguments value.

    Never raises: unparsable or non-object arguments give `None`.
    """
    if isinstance(value, str):
        if not value.strip():
            return {}, value
        try:
            parsed = json.loads(value)
        except ValueError:
            return None, value
        return (parsed if isinstance(parsed, dict) else None), value
    if isinstance(value, dict):
        return copy.deepcopy(value), json.dumps(value, ensure_ascii=False)
    if value is None:
        return None, ""
    try:
        return None, json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None, ""


def make_tool_call(
    id_value: Any, name: Any, arguments: Any, type_value: str, raw: Dict[str, Any]
) -> Optional[ToolCall]:
    """Build a `ToolCall`, or None when `name` is not a non-empty string."""
    if not isinstance(name, str) or not name:
        return None
    parsed, raw_text = _parse_arguments(arguments)
    return ToolCall(
        id=id_value if isinstance(id_value, str) else None,
        name=name,
        arguments=parsed,
        arguments_raw=raw_text,
        type=type_value,
        raw=raw,
    )


def interpret_tools(tools: Any, lang: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Validate `tools=` and return normalized dicts (None when `tools` is None)."""
    if tools is None:
        return None
    if not isinstance(tools, (list, tuple)):
        raise _invalid(lang)
    normalized: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or any(k not in _TOOL_KEYS for k in tool):
            raise _invalid(lang)
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise _invalid(lang)
        item: Dict[str, Any] = {"name": name}
        if "description" in tool:
            if not isinstance(tool["description"], str):
                raise _invalid(lang)
            item["description"] = tool["description"]
        parameters = tool.get("parameters")
        if "parameters" in tool and not isinstance(parameters, dict):
            raise _invalid(lang)
        item["parameters"] = (
            parameters if parameters is not None else {"type": "object", "properties": {}}
        )
        normalized.append(item)
    return normalized


def inject_tools_extra(
    api_format: str,
    extra: Optional[Dict[str, Any]],
    normalized: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Add the provider-format `tools` field; a `tools` key in the user's extra wins."""
    if not normalized:
        return extra
    mapped: List[Dict[str, Any]] = []
    for tool in normalized:
        if api_format == "anthropic":
            entry: Dict[str, Any] = {"name": tool["name"], "input_schema": tool["parameters"]}
            if "description" in tool:
                entry["description"] = tool["description"]
        else:
            function: Dict[str, Any] = {"name": tool["name"], "parameters": tool["parameters"]}
            if "description" in tool:
                function["description"] = tool["description"]
            entry = {"type": "function", "function": function}
        mapped.append(entry)
    injected: Dict[str, Any] = {"tools": mapped}
    injected.update(extra or {})
    return injected


def build_tool_results(
    api_format: str, outputs: Any, lang: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Build provider-format tool-result messages from `(call_or_id, output[, is_error])`."""
    if not isinstance(outputs, (list, tuple)) or not outputs:
        raise _invalid(lang)
    entries: List[Tuple[Optional[str], str, bool]] = []
    for item in outputs:
        if not isinstance(item, (list, tuple)) or len(item) not in (2, 3):
            raise _invalid(lang)
        call, output = item[0], item[1]
        is_error = item[2] if len(item) == 3 else False
        if not isinstance(is_error, bool):
            raise _invalid(lang)
        if isinstance(call, ToolCall):
            call_id = call.id
        elif call is None or isinstance(call, str):
            call_id = call
        else:
            raise _invalid(lang)
        if isinstance(output, str):
            text = output
        else:
            try:
                text = json.dumps(output, ensure_ascii=False)
            except (TypeError, ValueError):
                raise _invalid(lang) from None
        entries.append((call_id, text, is_error))

    if api_format == "anthropic":
        blocks: List[Dict[str, Any]] = []
        for call_id, text, is_error in entries:
            block: Dict[str, Any] = {"type": "tool_result"}
            if call_id is not None:
                block["tool_use_id"] = call_id
            block["content"] = text
            if is_error:
                block["is_error"] = True
            blocks.append(block)
        return [{"role": "user", "content": blocks}]

    messages: List[Dict[str, Any]] = []
    for call_id, text, _ in entries:
        msg: Dict[str, Any] = {"role": "tool"}
        if call_id is not None:
            msg["tool_call_id"] = call_id
        msg["content"] = text
        messages.append(msg)
    return messages
