"""接続設定の解決と httpx 用設定の生成を行う内部モジュール。"""

from __future__ import annotations

import math
import os
import ssl
from typing import Any, Dict, Mapping, Optional, Union
from urllib.parse import urlsplit

import httpx

from .errors import LLMConfigError
from .lang import t


DEFAULT_CONNECTION: Dict[str, Any] = {
    "max_connections": 100,
    "max_keepalive_connections": 20,
    "keepalive_expiry": 5.0,
    "connect_timeout": 10.0,
    "verify": True,
    "cert": None,
    "proxy": None,
}

_global_overrides: Dict[str, Any] = {}


def _error(lang: Optional[str], detail: str) -> LLMConfigError:
    """接続設定エラーを作成する。"""
    return LLMConfigError(
        t("invalid_connection", lang, detail=detail),
        code="invalid_connection",
    )


def _mask_proxy(value: str) -> str:
    """プロキシ URL の userinfo を伏せる。"""
    if "@" in value:
        return "***@" + value.rsplit("@", 1)[1]
    return value


def _validate(effective: Mapping[str, Any], lang: Optional[str]) -> None:
    """有効な接続設定を検証する。"""
    unknown = set(effective) - set(DEFAULT_CONNECTION)
    if unknown:
        raise _error(lang, "unknown key: %r" % sorted(unknown)[0])

    max_connections = effective["max_connections"]
    if (
        isinstance(max_connections, bool)
        or not isinstance(max_connections, int)
        or max_connections < 1
    ):
        raise _error(lang, "max_connections must be an integer greater than or equal to 1")

    max_keepalive_connections = effective["max_keepalive_connections"]
    if (
        isinstance(max_keepalive_connections, bool)
        or not isinstance(max_keepalive_connections, int)
        or max_keepalive_connections < 0
    ):
        raise _error(
            lang,
            "max_keepalive_connections must be an integer greater than or equal to 0",
        )

    for key, minimum, inclusive in (
        ("keepalive_expiry", 0, True),
        ("connect_timeout", 0, False),
    ):
        value = effective[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise _error(lang, "%s must be a number" % key)
        if value < minimum or (not inclusive and value == minimum):
            comparison = "greater than or equal to" if inclusive else "greater than"
            raise _error(lang, "%s must be %s %s" % (key, comparison, minimum))

    verify = effective["verify"]
    if not isinstance(verify, bool):
        if not isinstance(verify, str) or not os.path.exists(verify):
            raise _error(lang, "verify must be a boolean or an existing CA path")

    cert = effective["cert"]
    if cert is not None:
        if isinstance(cert, str):
            if not os.path.isfile(cert):
                raise _error(lang, "cert path does not exist: %s" % cert)
        elif (
            isinstance(cert, (tuple, list))
            and len(cert) == 2
            and all(isinstance(path, str) for path in cert)
            and all(os.path.isfile(path) for path in cert)
        ):
            pass
        else:
            raise _error(lang, "cert must be an existing path or a pair of existing paths")

    proxy = effective["proxy"]
    if proxy is not None:
        if not isinstance(proxy, str):
            raise _error(lang, "proxy must be an http or https URL")
        try:
            parts = urlsplit(proxy)
            port = parts.port
            valid = (
                parts.scheme in ("http", "https")
                and bool(parts.netloc)
                and bool(parts.hostname)
            )
        except ValueError:
            raise _error(
                lang,
                "proxy must be an http or https URL: %s" % _mask_proxy(proxy),
            )

        if not valid:
            raise _error(
                lang,
                "proxy must be an http or https URL: %s" % _mask_proxy(proxy),
            )


def _normalize(effective: Dict[str, Any]) -> Dict[str, Any]:
    """浮動小数点設定を正規化する。"""
    result = dict(effective)
    result["keepalive_expiry"] = float(result["keepalive_expiry"])
    result["connect_timeout"] = float(result["connect_timeout"])
    if isinstance(result["cert"], list):
        result["cert"] = tuple(result["cert"])
    return result


def set_connection(
    *,
    max_connections: Optional[int] = None,
    max_keepalive_connections: Optional[int] = None,
    keepalive_expiry: Optional[float] = None,
    connect_timeout: Optional[float] = None,
    verify: Optional[Union[bool, str]] = None,
    cert: Any = None,
    proxy: Optional[str] = None,
    lang: Optional[str] = None,
) -> Dict[str, Any]:
    """グローバル接続設定を置き換える。引数なしでは既定値へ戻す。"""
    overrides = {
        key: value
        for key, value in {
            "max_connections": max_connections,
            "max_keepalive_connections": max_keepalive_connections,
            "keepalive_expiry": keepalive_expiry,
            "connect_timeout": connect_timeout,
            "verify": verify,
            "cert": cert,
            "proxy": proxy,
        }.items()
        if value is not None
    }
    effective = dict(DEFAULT_CONNECTION)
    effective.update(overrides)
    _validate(effective, lang)
    normalized = _normalize(effective)

    _global_overrides.clear()
    _global_overrides.update({key: normalized[key] for key in overrides})
    return get_connection()


def get_connection() -> Dict[str, Any]:
    """現在の有効なグローバル接続設定のコピーを返す。"""
    effective = dict(DEFAULT_CONNECTION)
    effective.update(_global_overrides)
    return dict(effective)


def resolve_connection(
    value: Optional[Mapping[str, Any]],
    lang: Optional[str] = None,
) -> Dict[str, Any]:
    """インスタンス設定を含む有効な接続設定を解決する。"""
    if value is not None and not isinstance(value, Mapping):
        raise _error(lang, "connection must be a mapping or None")

    instance = {} if value is None else dict(value)
    unknown = set(instance) - set(DEFAULT_CONNECTION)
    if unknown:
        raise _error(lang, "unknown key: %r" % sorted(unknown)[0])

    effective = get_connection()
    for key, item in instance.items():
        effective[key] = DEFAULT_CONNECTION[key] if item is None else item

    _validate(effective, lang)
    return _normalize(effective)


def build_httpx_kwargs(
    resolved: Mapping[str, Any],
    lang: Optional[str] = None,
) -> Dict[str, Any]:
    """解決済み設定から httpx クライアント用の引数を作る。"""
    effective = dict(resolved)
    _validate(effective, lang)
    effective = _normalize(effective)

    kwargs: Dict[str, Any] = {
        "limits": httpx.Limits(
            max_connections=effective["max_connections"],
            max_keepalive_connections=effective["max_keepalive_connections"],
            keepalive_expiry=effective["keepalive_expiry"],
        ),
    }

    if effective["proxy"] is not None:
        kwargs["proxy"] = effective["proxy"]

    verify = effective["verify"]
    cert = effective["cert"]
    if verify is True and cert is None:
        kwargs["verify"] = True
        return kwargs

    try:
        if verify is False:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        elif isinstance(verify, str):
            if os.path.isdir(verify):
                context = ssl.create_default_context(capath=verify)
            else:
                context = ssl.create_default_context(cafile=verify)
        else:
            context = ssl.create_default_context()

        if cert is not None:
            if isinstance(cert, str):
                context.load_cert_chain(cert)
            else:
                context.load_cert_chain(cert[0], cert[1])

        kwargs["verify"] = context
    except (ssl.SSLError, OSError) as exc:
        raise _error(lang, "TLS context could not be created: %s" % exc) from exc

    return kwargs
