"""Drop request fields that a model or API version rejects.

Rules are data. Each one cites the official page it was checked against.
A model with no matching rule is left unchanged. OpenRouter and Google have
no rules here: their chat bodies are not rewritten.

This module removes fields. It does not inject fixed values and it does not
add parameters the caller left out.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class DropRule:
    """Fields to remove from a finished chat body.

    ``models`` is ``None`` for every model of ``provider``. Otherwise each
    entry is a pattern matched with ``fnmatch.fnmatchcase`` (case-sensitive,
    no path normalization) against the model id that will be sent.

    ``anthropic_version`` limits the rule to that ``anthropic-version`` value.
    ``None`` means the rule does not depend on an API version.
    """

    provider: str
    models: Optional[Tuple[str, ...]]
    drop: FrozenSet[str]
    anthropic_version: Optional[str] = None


# Checked 2026-10-31. Model ids below are the ones those pages name.
# Do not add an id that is only inferred from a family prefix.
#
# Anthropic Messages, API version 2026-10-21: temperature, top_p, and top_k
# are removed. Sending any of them returns HTTP 400 on every model.
# https://platform.claude.com/docs/en/api/versioning
# https://platform.claude.com/docs/en/api/migration-2026-10-21
#
# OpenAI Chat Completions:
# - gpt-6-astra does not support custom temperature or top_p, or logprobs
#   (changelog). It also cannot use reasoning effort "none". The GPT-6
#   migration guide says to remove temperature, top_p, and top_logprobs
#   whenever reasoning effort is not "none", and to remove logprobs on
#   Chat Completions as well. Those four fields are therefore always rejected.
#   https://developers.openai.com/api/docs/changelog
#   https://developers.openai.com/api/docs/guides/latest-model
# - gpt-6.1-sol does not support reasoning effort "none" (same migration
#   guide), so the same four fields are always rejected there too.
# - The GPT-5.2 guide says a request to older GPT-5 models (for example
#   gpt-5, gpt-5-mini, or gpt-5-nano) that includes temperature, top_p, or
#   logprobs raises an error. The dated ids are the snapshots grouped with
#   those aliases in the Chat Completions model list. gpt-5.1 and gpt-5.2
#   are not listed: they accept these fields when reasoning effort is "none".
#   https://developers.openai.com/api/docs/guides/latest-model/gpt-5.2
#   https://developers.openai.com/api/reference/resources/chat
# - stop is not supported on reasoning models o3 and o4-mini. The snapshot
#   ids are the ones on each model page. o3-mini is a different model and is
#   not included. Temperature is not dropped for these ids: the pages cited
#   here do not say o3 or o4-mini reject it.
#   https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
#   https://developers.openai.com/api/docs/models/o3
#   https://developers.openai.com/api/docs/models/o4-mini
#
# Not dropped, because support depends on reasoning effort and "none" is
# allowed (sending temperature is valid in that mode): gpt-6-luna, gpt-6-sol,
# gpt-6.1-terra, gpt-5.1, gpt-5.2.

_GPT6_ALWAYS = frozenset({"temperature", "top_p", "logprobs", "top_logprobs"})
_GPT5_NAMED = frozenset({"temperature", "top_p", "logprobs"})

DROP_RULES: Tuple[DropRule, ...] = (
    DropRule(
        provider="anthropic",
        models=None,
        drop=frozenset({"temperature", "top_p", "top_k"}),
        anthropic_version="2026-10-21",
    ),
    DropRule(provider="openai", models=("gpt-6-astra",), drop=_GPT6_ALWAYS),
    DropRule(provider="openai", models=("gpt-6.1-sol",), drop=_GPT6_ALWAYS),
    DropRule(
        provider="openai",
        models=(
            "gpt-5",
            "gpt-5-2025-08-07",
            "gpt-5-mini",
            "gpt-5-mini-2025-08-07",
            "gpt-5-nano",
            "gpt-5-nano-2025-08-07",
        ),
        drop=_GPT5_NAMED,
    ),
    DropRule(
        provider="openai",
        models=("o3", "o3-2025-04-16", "o4-mini", "o4-mini-2025-04-16"),
        drop=frozenset({"stop"}),
    ),
)


def adjust_body(
    provider: str,
    model: str,
    body: Mapping[str, Any],
    *,
    anthropic_version: Optional[str] = None,
    rules: Optional[Sequence[DropRule]] = None,
) -> Dict[str, Any]:
    """Return a copy of ``body`` with rejected fields removed.

    The model id that is checked is ``body["model"]`` when that value is a
    string, so an ``extra`` override of ``model`` is what the rules see.
    Otherwise the ``model`` argument is used. The input mapping is not mutated.
    Every matching rule contributes its ``drop`` set (the sets are united).
    ``rules`` defaults to ``DROP_RULES``.
    """
    chosen = DROP_RULES if rules is None else rules
    sent = body.get("model")
    target = sent if isinstance(sent, str) else model
    drop: Set[str] = set()
    for rule in chosen:
        if rule.provider != provider:
            continue
        if rule.anthropic_version is not None and rule.anthropic_version != anthropic_version:
            continue
        if rule.models is not None and not any(
            fnmatch.fnmatchcase(target, pattern) for pattern in rule.models
        ):
            continue
        drop.update(rule.drop)
    adjusted = dict(body)
    for key in drop:
        adjusted.pop(key, None)
    return adjusted
