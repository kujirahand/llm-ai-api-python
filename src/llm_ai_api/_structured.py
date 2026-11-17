"""Structured-output support used by the LLM convenience layer."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from .errors import LLMConfigError, StructuredOutputError
from .lang import t
from .types import ChatResult


_MAX_SCHEMA_DEPTH = 128


@dataclass(frozen=True)
class _Schema:
    schema: Dict[str, Any]
    model: Any = None
    name_source: Optional[str] = None


def interpret_schema(value: Any, lang: Optional[str] = None) -> Optional[_Schema]:
    """Return an interpreted schema, or None when structured output is disabled."""
    if value is None:
        return None
    if isinstance(value, dict):
        return _Schema(value, name_source=value.get("title"))
    schema_method = getattr(value, "model_json_schema", None)
    validate_method = getattr(value, "model_validate_json", None)
    if not callable(schema_method) or not callable(validate_method):
        raise LLMConfigError(
            t("invalid_schema", lang),
            code="invalid_schema",
        )
    schema = schema_method()
    if not isinstance(schema, dict):
        raise LLMConfigError(
            t("invalid_schema", lang),
            code="invalid_schema",
        )
    return _Schema(
        normalize_schema(schema, lang),
        model=value,
        name_source=schema.get("title") or getattr(value, "__name__", None),
    )


def schema_name(schema: _Schema) -> str:
    """Return an OpenAI-compatible JSON-schema name."""
    source = schema.schema.get("title") or schema.name_source or "response"
    name = re.sub(r"[^A-Za-z0-9_-]", "_", str(source))[:64]
    return name or "response"


def normalize_schema(
    schema: Dict[str, Any], lang: Optional[str] = None
) -> Dict[str, Any]:
    """Copy and normalize a model-generated schema for strict JSON Schema mode."""
    try:
        result = copy.deepcopy(schema)
        _check_schema_graph(result, lang)
        _normalize_node(result, set(), set(), 1, lang)
        return result
    except RecursionError as exc:
        raise LLMConfigError(
            t("invalid_schema_too_deep", lang, limit=_MAX_SCHEMA_DEPTH),
            code="invalid_schema",
        ) from exc


def _check_schema_graph(schema: Any, lang: Optional[str]) -> None:
    visiting: Set[int] = set()
    stack = [(schema, 0, False)]
    while stack:
        node, depth, leaving = stack.pop()
        if not isinstance(node, (dict, list, tuple)):
            continue
        identity = id(node)
        if leaving:
            visiting.remove(identity)
            continue
        if identity in visiting:
            raise LLMConfigError(t("invalid_schema_cyclic", lang), code="invalid_schema")
        depth += isinstance(node, dict)
        if depth > _MAX_SCHEMA_DEPTH:
            raise LLMConfigError(
                t("invalid_schema_too_deep", lang, limit=_MAX_SCHEMA_DEPTH),
                code="invalid_schema",
            )
        visiting.add(identity)
        stack.append((node, depth, True))
        children = node.values() if isinstance(node, dict) else node
        stack.extend((child, depth, False) for child in children)


def _normalize_node(
    node: Any, visiting: Set[int], finished: Set[int], depth: int,
    lang: Optional[str],
) -> None:
    if not isinstance(node, dict):
        return
    identity = id(node)
    if identity in visiting:
        raise LLMConfigError(t("invalid_schema_cyclic", lang), code="invalid_schema")
    if depth > _MAX_SCHEMA_DEPTH:
        raise LLMConfigError(
            t("invalid_schema_too_deep", lang, limit=_MAX_SCHEMA_DEPTH),
            code="invalid_schema",
        )
    if identity in finished:
        return
    visiting.add(identity)
    try:
        properties = node.get("properties")
        if node.get("type") == "object" and isinstance(properties, dict):
            originally_required = set(node.get("required", []))
            node["additionalProperties"] = False
            node["required"] = list(properties.keys())
            for key, child in list(properties.items()):
                if isinstance(child, dict):
                    child.pop("default", None)
                    if key not in originally_required:
                        properties[key] = _nullable(child)

        properties = node.get("properties")
        if isinstance(properties, dict):
            for child in properties.values():
                _normalize_node(child, visiting, finished, depth + 1, lang)

        _normalize_node(node.get("items"), visiting, finished, depth + 1, lang)
        if isinstance(node.get("items"), list):
            for child in node["items"]:
                _normalize_node(child, visiting, finished, depth + 1, lang)
        if isinstance(node.get("prefixItems"), list):
            for child in node["prefixItems"]:
                _normalize_node(child, visiting, finished, depth + 1, lang)

        for key in ("anyOf", "oneOf", "allOf"):
            value = node.get(key)
            if isinstance(value, list):
                for child in value:
                    _normalize_node(child, visiting, finished, depth + 1, lang)

        for key in ("$defs", "definitions"):
            value = node.get(key)
            if isinstance(value, dict):
                for child in value.values():
                    _normalize_node(child, visiting, finished, depth + 1, lang)

        if isinstance(node.get("additionalProperties"), dict):
            _normalize_node(node["additionalProperties"], visiting, finished, depth + 1, lang)
    finally:
        visiting.remove(identity)
    finished.add(identity)


def _nullable(schema: Dict[str, Any]) -> Dict[str, Any]:
    type_value = schema.get("type")
    if type_value == "null":
        return schema
    if isinstance(type_value, list):
        if "null" not in type_value:
            schema["type"] = type_value + ["null"]
        return schema
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        if not any(
            isinstance(item, dict) and item.get("type") == "null" for item in any_of
        ):
            any_of.append({"type": "null"})
        return schema
    # Any other shape ($ref, enum, oneOf, allOf, a plain typed schema, ...):
    # wrap it so null is allowed alongside the original schema.
    return {"anyOf": [schema, {"type": "null"}]}


def inject_schema_extra(
    provider: str,
    extra: Optional[Dict[str, Any]],
    structured: Optional[_Schema],
) -> Optional[Dict[str, Any]]:
    """Add provider structured-output fields before user extra takes precedence."""
    if structured is None:
        return extra

    user_extra = dict(extra or {})
    if provider == "anthropic":
        supplied = user_extra.get("output_config")
        if supplied is not None and not isinstance(supplied, dict):
            return user_extra  # not mergeable: the user's value wins as-is
        output_config: Dict[str, Any] = {
            "format": {"type": "json_schema", "schema": structured.schema}
        }
        if isinstance(supplied, dict):
            output_config.update(supplied)
        injected = dict(user_extra)
        injected["output_config"] = output_config
        return injected

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name(structured),
            "strict": True,
            "schema": structured.schema,
        },
    }
    injected = {"response_format": response_format}
    injected.update(user_extra)
    return injected


def parse_structured_result(
    result: ChatResult,
    provider: str,
    structured: Optional[_Schema],
    lang: Optional[str] = None,
) -> ChatResult:
    """Set result.parsed, or raise StructuredOutputError for unusable output."""
    if structured is None:
        return result

    code = _result_error_code(result, provider)
    if code is not None:
        raise StructuredOutputError(
            t(code, lang, provider=provider),
            code=code,
            result=result,
            provider=provider,
        )

    try:
        if structured.model is not None:
            result.parsed = structured.model.model_validate_json(result.text)
        else:
            result.parsed = json.loads(result.text)
    except Exception as exc:
        raise StructuredOutputError(
            t("invalid_structured_output", lang, provider=provider),
            code="invalid_structured_output",
            result=result,
            provider=provider,
        ) from exc
    return result


def _result_error_code(result: ChatResult, provider: str) -> Optional[str]:
    if provider == "anthropic":
        if result.stop_reason == "refusal":
            return "output_refused"
        if result.stop_reason in ("max_tokens", "model_context_window_exceeded"):
            return "output_incomplete"
        return None

    choices = result.raw.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and message.get("refusal"):
            return "output_refused"
    if result.stop_reason == "content_filter":
        return "output_refused"
    if result.stop_reason == "length":
        return "output_incomplete"
    return None
