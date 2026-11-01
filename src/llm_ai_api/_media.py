"""Image inputs for `LLM.ask()` and friends (internal).

Turns the `images=` list into provider-specific content parts. The provider
layer and the raw layer never see this; they get ready-made message dicts.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from .errors import LLMConfigError
from .lang import t

# A resolved image: ("url", url) or ("data", raw_bytes, media_type).
Resolved = Tuple[Any, ...]

_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _error(reason_id: str, lang: Optional[str], **params: object) -> LLMConfigError:
    reason = t(reason_id, lang, **params)
    return LLMConfigError(t("invalid_media", lang, reason=reason), code="invalid_media")


def _is_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def check_images(images: Any, lang: Optional[str]) -> List[Any]:
    """Validate the shape of `images=` (no I/O). Return the items, or [] for none."""
    if images is None:
        return []
    if not isinstance(images, (list, tuple)):
        raise _error("media_reason_not_list", lang)
    for item in images:
        if not isinstance(item, (str, bytes, os.PathLike)):
            raise _error("media_reason_bad_item", lang, kind=type(item).__name__)
    return list(images)


def check_prompt_for_images(prompt: object, lang: Optional[str]) -> None:
    """images= needs a string prompt; with a messages list the target is ambiguous."""
    if not isinstance(prompt, str):
        raise _error("media_reason_needs_text", lang)


def sniff_media_type(data: bytes) -> Optional[str]:
    """Return the image media type from the leading signature bytes, if known."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def resolve_image(item: Union[str, bytes, "os.PathLike[str]"], lang: Optional[str]) -> Resolved:
    """Read one image (this may touch the disk) and decide its media type."""
    if _is_url(item):
        return ("url", item)
    ext = ""
    if isinstance(item, bytes):
        data, label = item, "bytes"
    else:
        label = str(os.fspath(item))
        ext = os.path.splitext(label)[1].lower()
        try:
            with open(label, "rb") as f:
                data = f.read()
        except OSError as exc:
            raise _error("media_reason_read_error", lang, source=label) from exc
    media_type = sniff_media_type(data) or _EXTENSIONS.get(ext)
    if media_type is None:
        raise _error("media_reason_unknown_type", lang, source=label)
    return ("data", data, media_type)


def resolve_images(images: List[Any], lang: Optional[str]) -> List[Resolved]:
    """Resolve every item of an already checked list (blocking; async code uses a thread)."""
    return [resolve_image(item, lang) for item in images]


def image_part(provider: str, resolved: Resolved) -> Dict[str, Any]:
    """Build the provider's content part for one resolved image."""
    if resolved[0] == "url":
        url = resolved[1]
        if provider == "anthropic":
            return {"type": "image", "source": {"type": "url", "url": url}}
        return {"type": "image_url", "image_url": {"url": url}}
    data = base64.b64encode(resolved[1]).decode("ascii")
    media_type = resolved[2]
    if provider == "anthropic":
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    return {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (media_type, data)}}


def image_messages(provider: str, prompt: str, resolved: List[Resolved]) -> List[Dict[str, Any]]:
    """One user message: the text part followed by the images in the given order."""
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend(image_part(provider, r) for r in resolved)
    return [{"role": "user", "content": content}]


# --- Audio input for `LLM.transcribe()` ---------------------------------------

_AUDIO_EXTENSIONS = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".m4a": "audio/mp4",
}

# media type -> extension of the generated file name for a bytes input.
_AUDIO_NAME_EXT = {
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "audio/mp4": "m4a",
}


def _audio_error(reason_id: str, lang: Optional[str], **params: object) -> LLMConfigError:
    reason = t(reason_id, lang, **params)
    return LLMConfigError(t("invalid_audio", lang, reason=reason), code="invalid_media")


def sniff_audio_type(data: bytes) -> Optional[str]:
    """Return the audio media type from the leading signature bytes, if known."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"ID3") or (
        len(data) >= 2
        and data[0] == 0xFF
        and (data[1] & 0xE0) == 0xE0  # frame sync
        and (data[1] & 0x06) == 0x02  # Layer III, any MPEG version, with or without CRC
    ):
        return "audio/mpeg"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    return None


def check_audio(file: Any, lang: Optional[str]) -> None:
    """Validate the type of `file` (no I/O)."""
    if not isinstance(file, (str, bytes, os.PathLike)):
        raise _audio_error("media_reason_bad_audio", lang, kind=type(file).__name__)


def resolve_audio(file: Any, lang: Optional[str]) -> Tuple[str, bytes, str]:
    """Read the audio (this may touch the disk); return (filename, bytes, media_type)."""
    name: Optional[str] = None
    ext = ""
    if isinstance(file, bytes):
        data, label = file, "bytes"
    else:
        label = str(os.fspath(file))
        name = os.path.basename(label)
        ext = os.path.splitext(label)[1].lower()
        try:
            with open(label, "rb") as f:
                data = f.read()
        except OSError as exc:
            raise _audio_error("media_reason_audio_read_error", lang, source=label) from exc
    media_type = sniff_audio_type(data) or _AUDIO_EXTENSIONS.get(ext)
    if media_type is None:
        raise _audio_error("media_reason_unknown_audio", lang, source=label)
    if name is None:
        name = "audio." + _AUDIO_NAME_EXT[media_type]
    return (name, data, media_type)


def transcription_form(
    model: str, extra: Optional[Dict[str, Any]], lang: Optional[str]
) -> List[Tuple[str, str]]:
    """Build the form fields: model, response_format, then `extra` expanded.

    Scalars become strings (bool: "true" / "false"), lists and tuples repeat `key[]`,
    None is skipped. A scalar in `extra` replaces the default field of the same name.
    """
    if extra is not None and not isinstance(extra, dict):
        raise _audio_error("media_reason_bad_extra_arg", lang, kind=type(extra).__name__)
    fields: List[Tuple[str, str]] = [("model", model), ("response_format", "json")]
    for key, value in (extra or {}).items():
        if value is None:
            continue
        repeated = isinstance(value, (list, tuple))
        for v in value if repeated else [value]:
            if isinstance(v, bool):
                text = "true" if v else "false"
            elif isinstance(v, (str, int, float)):
                text = str(v)
            else:
                raise _audio_error("media_reason_bad_extra", lang, key=key, kind=type(v).__name__)
            if repeated:
                fields.append((key + "[]", text))
            else:
                fields = [f for f in fields if f[0] != key]
                fields.append((key, text))
    return fields
