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
