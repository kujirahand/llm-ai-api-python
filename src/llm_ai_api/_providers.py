"""Provider registry (internal), and the public `register_provider()`.

Every provider, built-in or registered, is a name -> (sync class, async class) entry in
one registry. `llm()` resolves a name through it. Providers are declared with class
attributes (URL, environment variables, auth header, `max_tokens` field, ...). The async
class is never written by hand: `_make_async()` builds it from the sync class's
declared attributes, so a provider is described once.

Registration is a process-wide, startup-time action. Entries are replaced atomically
under a lock; an `LLM` keeps the classes it was created with.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Tuple, Type, Union

from ._async_clients import _AsyncAnthropicClient, _AsyncOpenAICompatClient
from .anthropic import AnthropicClient
from .errors import LLMConfigError
from .google import GoogleClient
from .grok import GrokClient
from .lang import t
from .lmstudio import LMStudioClient
from .muse import MuseClient
from .ollama import OllamaClient
from .openai import OpenAIClient, OpenAICompatClient
from .openrouter import OpenRouterClient
from .strata import StrataClient

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
# RFC 9110 token characters: what may appear in a header name.
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
API_FORMATS = ("openai", "anthropic")

# Class attributes that `_make_async()` copies from a sync class to its async twin.
_DECLARED = (
    "provider",
    "default_base_url",
    "api_key_env",
    "api_key_env_fallbacks",
    "base_url_env",
    "api_key_default",
    "api_key_optional",
    "api_format",
    "auth_header",
    "auth_scheme",
    "fixed_headers",
    "header_options",
    "supports_models",
    "supports_audio",
    "models_style",
    "rules_provider",
    "max_tokens_field",
    "stream_include_usage",
)


@dataclass(frozen=True)
class ProviderEntry:
    """One registered provider: its canonical name, aliases and client classes."""

    name: str
    sync: Type[Any]
    async_: Type[Any]
    aliases: Tuple[str, ...]
    builtin: bool


def _make_async(sync_cls: Type[Any]) -> Type[Any]:
    """Build the internal async client class for `sync_cls` from its declared attributes."""
    base = _AsyncAnthropicClient if sync_cls.api_format == "anthropic" else _AsyncOpenAICompatClient
    namespace: Dict[str, Any] = {
        name: getattr(sync_cls, name) for name in _DECLARED if hasattr(sync_cls, name)
    }
    namespace["__module__"] = sync_cls.__module__
    return type("_Async" + sync_cls.__name__, (base,), namespace)


_lock = threading.RLock()
_entries: Dict[str, ProviderEntry] = {}  # canonical name -> entry
_names: Dict[str, str] = {}  # every name and alias -> canonical name


def _install(entry: ProviderEntry) -> None:
    """Add `entry` (the caller holds the lock and has checked for conflicts)."""
    _entries[entry.name] = entry
    _names[entry.name] = entry.name
    for alias in entry.aliases:
        _names[alias] = entry.name


def _register_builtin(sync_cls: Type[Any], aliases: Tuple[str, ...] = ()) -> None:
    entry = ProviderEntry(sync_cls.provider, sync_cls, _make_async(sync_cls), aliases, True)
    with _lock:
        _install(entry)


def lookup(name: str) -> Optional[ProviderEntry]:
    """Return the entry for a provider name or alias (already lowercased), or None."""
    with _lock:
        canonical = _names.get(name)
        return _entries[canonical] if canonical is not None else None


def provider_names() -> "list[str]":
    """Every accepted name, aliases included, sorted."""
    with _lock:
        return sorted(_names)


def builtin_async_class(class_name: str) -> Optional[Type[Any]]:
    """The generated async class of a built-in provider, by class name (`_AsyncGrokClient`)."""
    with _lock:
        for entry in _entries.values():
            if entry.builtin and entry.async_.__name__ == class_name:
                return entry.async_
    return None


class _View(Mapping):  # type: ignore[type-arg]
    """A live read-only mapping over the registry (for the old private tables in llm.py)."""

    def __init__(self, pick: Any) -> None:
        self._pick = pick

    def __getitem__(self, name: str) -> Any:
        entry = lookup(name)
        if entry is None:
            raise KeyError(name)
        return self._pick(entry)

    def __iter__(self) -> Iterator[str]:
        return iter(provider_names())

    def __len__(self) -> int:
        return len(provider_names())


PROVIDER_PAIRS = _View(lambda e: (e.sync, e.async_))
PROVIDERS = _View(lambda e: e.sync)
ASYNC_PROVIDERS = _View(lambda e: e.async_)


def _forget(name: str) -> None:
    """Remove a registered (not built-in) provider. Test helper; there is no public API."""
    with _lock:
        entry = _entries.get(name)
        if entry is None or entry.builtin:
            return
        del _entries[name]
        for key in [k for k, v in _names.items() if v == name]:
            del _names[key]


# --- public register_provider() -------------------------------------------------------


def _invalid(detail: str) -> LLMConfigError:
    return LLMConfigError(t("invalid_provider", None, detail=detail), code="invalid_provider")


def _check_name(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise _invalid("%s must match %s: %r" % (what, _NAME_RE.pattern, value))
    return value


def _check_str(value: Any, what: str, *, empty_ok: bool = False) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or (not value and not empty_ok):
        raise _invalid("%s must be a non-empty string: %r" % (what, value))
    if "\r" in value or "\n" in value:
        raise _invalid("%s must not contain a line break" % what)
    return value


def _check_bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid("%s must be True or False: %r" % (what, value))
    return value


def register_provider(
    name: str,
    *,
    base_url: Optional[str] = None,
    api_format: str = "openai",
    api_key_env: Union[None, str, Sequence[str]] = None,
    base_url_env: Optional[str] = None,
    api_key_default: Optional[str] = None,
    api_key_required: bool = True,
    auth_header: Optional[str] = None,
    auth_scheme: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
    max_tokens_field: Optional[str] = None,
    stream_include_usage: Optional[bool] = None,
    models: bool = True,
    aliases: Union[str, Sequence[str]] = (),
    replace: bool = False,
) -> None:
    """Add a provider so that `llm("<name>:<model>")` works, from a declaration only.

    `api_format` is `"openai"` (a `/chat/completions` API; the default) or
    `"anthropic"` (a `/v1/messages` API). `api_key_env` is one environment variable
    name or a tuple of them (the first has priority). `auth_header` and `auth_scheme`
    default to `Authorization` / `Bearer` (`x-api-key` / no scheme for `"anthropic"`);
    an empty scheme sends the bare key. `headers` are fixed extra headers that the
    caller's `headers=` overrides. `max_tokens_field` (default `"max_tokens"`) and
    `stream_include_usage` (default False) are for `"openai"` only. With
    `models=False`, `models()` raises `unsupported_models`.

    Call it at startup; it affects the whole process. A built-in name or alias can
    never be registered, even with `replace=True`. `replace=True` only replaces a
    provider registered earlier by this function. Errors are `LLMConfigError` with
    code `invalid_provider` or `provider_exists`.
    """
    _check_name(name, "name")
    if isinstance(aliases, str):
        aliases = (aliases,)
    if not isinstance(aliases, (tuple, list)):
        raise _invalid("aliases must be a list of names: %r" % (aliases,))
    alias_list = [_check_name(a, "alias") for a in aliases]
    if len(set(alias_list)) != len(alias_list) or name in alias_list:
        raise _invalid("aliases must be distinct from each other and from the name")

    if not isinstance(base_url, str) or not base_url.strip():
        raise _invalid("base_url is required")
    base_url = _check_str(base_url.strip(), "base_url")
    if api_format not in API_FORMATS:
        raise _invalid("api_format must be one of %s: %r" % (", ".join(API_FORMATS), api_format))

    if api_key_env is None:
        env_names: Tuple[str, ...] = ()
    elif isinstance(api_key_env, str):
        env_names = (api_key_env,)
    elif isinstance(api_key_env, (tuple, list)):
        env_names = tuple(api_key_env)
    else:
        raise _invalid("api_key_env must be a name or a tuple of names: %r" % (api_key_env,))
    for env in env_names:
        _check_str(env, "api_key_env")
        if "=" in env:  # type: ignore[operator]
            raise _invalid("api_key_env must be a variable name: %r" % (env,))
    _check_str(base_url_env, "base_url_env")
    _check_str(api_key_default, "api_key_default")
    _check_bool(api_key_required, "api_key_required")
    _check_bool(models, "models")
    _check_bool(replace, "replace")

    if auth_header is not None and (
        not isinstance(auth_header, str) or not _HEADER_NAME_RE.match(auth_header)
    ):
        raise _invalid("auth_header must be a header name: %r" % (auth_header,))
    _check_str(auth_scheme, "auth_scheme", empty_ok=True)
    fixed: Dict[str, str] = {}
    if headers is not None:
        if not isinstance(headers, Mapping):
            raise _invalid("headers must be a dict of strings")
        for key, value in headers.items():
            if not isinstance(key, str) or not _HEADER_NAME_RE.match(key):
                raise _invalid("headers has an invalid header name: %r" % (key,))
            _check_str(value, "headers[%r]" % key, empty_ok=True)
            fixed[key] = value
    if api_format == "anthropic":
        if max_tokens_field is not None or stream_include_usage is not None:
            raise _invalid(
                'max_tokens_field and stream_include_usage apply to api_format="openai" only'
            )
    else:
        _check_str(max_tokens_field, "max_tokens_field")
        if stream_include_usage is not None:
            _check_bool(stream_include_usage, "stream_include_usage")

    attrs: Dict[str, Any] = {
        "provider": name,
        "default_base_url": base_url.rstrip("/"),
        "api_key_env": env_names[0] if env_names else "",
        "api_key_env_fallbacks": env_names[1:],
        "base_url_env": base_url_env or "",
        "api_key_default": api_key_default,
        "api_key_optional": not api_key_required,
        "fixed_headers": fixed,
        "supports_models": models,
    }
    if auth_header is not None:
        attrs["auth_header"] = auth_header
    if auth_scheme is not None:
        attrs["auth_scheme"] = auth_scheme
    if api_format == "anthropic":
        base: Type[Any] = AnthropicClient
        # The version-dependent drop rule does not depend on the model name, so a
        # compatible endpoint that gets the same version header gets the same rule.
        attrs["rules_provider"] = AnthropicClient.provider
    else:
        base = OpenAICompatClient
        if max_tokens_field is not None:
            attrs["max_tokens_field"] = max_tokens_field
        if stream_include_usage is not None:
            attrs["stream_include_usage"] = stream_include_usage
    parts = [p for p in re.split(r"[-_]", name) if p]
    sync_cls = type("".join(p.capitalize() for p in parts) + "Client", (base,), attrs)
    entry = ProviderEntry(name, sync_cls, _make_async(sync_cls), tuple(alias_list), False)

    with _lock:
        previous = _entries.get(name)
        for claimed in [name] + alias_list:
            owner_name = _names.get(claimed)
            if owner_name is None:
                continue
            owner = _entries[owner_name]
            if owner.builtin or owner_name != name or not replace:
                raise LLMConfigError(
                    t("provider_exists", None, name=claimed), code="provider_exists"
                )
        if previous is not None:
            _forget(name)
        _install(entry)


def _register_builtins() -> None:
    for cls in (
        OpenAIClient,
        OpenRouterClient,
        GrokClient,
        MuseClient,
        GoogleClient,
        LMStudioClient,
        OllamaClient,
        StrataClient,
    ):
        _register_builtin(cls)
    _register_builtin(AnthropicClient, aliases=("claude",))


_register_builtins()
