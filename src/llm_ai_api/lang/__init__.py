"""エラーメッセージの多言語化。

メッセージは `lang/<言語コード>.py` の `MESSAGES`（メッセージ ID → テンプレート）に置く。
言語を足すときは、そのファイルを 1 つ追加するだけでよい（登録処理は不要）。

メッセージの引き方（フォールバック）:
    指定された言語 → 英語（en） → メッセージ ID そのもの

使う言語の決め方（優先順）:
    1. `t(..., lang=)` / クライアントの `lang=` 引数
    2. `set_language()` で設定した値
    3. 環境変数 `LLM_AI_API_LANG`
    4. 環境変数 `LANGUAGE`（`ja:en` のようなコロン区切りで、対応している最初のもの）
    5. 環境変数 `LC_ALL` → `LC_MESSAGES` → `LANG` のうち、最初に設定されているもの
    6. `locale.getlocale()`（Windows では OS の表示言語）
    7. 英語
"""

from __future__ import annotations

import importlib
import locale as _stdlib_locale
import os
import re
from typing import Dict, Optional

DEFAULT_LANGUAGE = "en"
ENV_VAR = "LLM_AI_API_LANG"

_CODE_RE = re.compile(r"^[a-z]{2,3}$")
_catalogs: Dict[str, Optional[Dict[str, str]]] = {}
_override: Optional[str] = None


def normalize_language(value: Optional[str]) -> Optional[str]:
    """`ja_JP.UTF-8` や `ja-JP` を `ja` にする。`C` / `POSIX` や不正な値は None。"""
    if not value:
        return None
    code = re.split(r"[_.@\-]", value.strip().lower(), maxsplit=1)[0]
    return code if _CODE_RE.match(code) else None


def _catalog(code: str) -> Optional[Dict[str, str]]:
    """言語コードのカタログを読み込む。ファイルがなければ None。"""
    if code not in _catalogs:
        try:
            mod = importlib.import_module("%s.%s" % (__name__, code))
            _catalogs[code] = dict(mod.MESSAGES)
        except ImportError:
            _catalogs[code] = None
    return _catalogs[code]


def is_supported(code: str) -> bool:
    """その言語のメッセージファイルがあるか。"""
    return _catalog(code) is not None


def set_language(lang: Optional[str]) -> None:
    """プロセス全体で使う言語を設定する。None で自動判定に戻す。"""
    global _override
    _override = normalize_language(lang) if lang else None


def detect_language() -> str:
    """環境から言語を判定する（`lang=` 引数と `set_language()` は見ない）。"""
    code = normalize_language(os.environ.get(ENV_VAR))
    if code:
        return code
    for part in os.environ.get("LANGUAGE", "").split(":"):
        code = normalize_language(part)
        if code and is_supported(code):
            return code
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return normalize_language(value) or DEFAULT_LANGUAGE  # C / POSIX は英語
    try:
        code = normalize_language(_stdlib_locale.getlocale()[0])
    except Exception:
        code = None
    return code or DEFAULT_LANGUAGE


def get_language(lang: Optional[str] = None) -> str:
    """実際に使う言語コードを返す。"""
    return normalize_language(lang) or _override or detect_language()


def t(msg_id: str, lang: Optional[str] = None, **params: object) -> str:
    """メッセージ ID から文言を作る。見つからなければ英語、それも無ければ ID を返す。"""
    for code in (get_language(lang), DEFAULT_LANGUAGE):
        catalog = _catalog(code)
        if catalog and msg_id in catalog:
            try:
                return catalog[msg_id].format(**params)
            except (KeyError, IndexError, ValueError):
                continue  # テンプレートが壊れていたら次の言語へ
    return msg_id
