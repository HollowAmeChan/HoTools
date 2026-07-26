"""物理世界 slot id、指针和短 hash 的通用辅助函数。"""

from __future__ import annotations

import hashlib


def as_pointer(value) -> int:
    pointer_fn = getattr(value, "as_pointer", None)
    if callable(pointer_fn):
        try:
            return int(pointer_fn())
        except Exception:
            return 0
    return 0


def data_pointer(obj) -> int:
    return as_pointer(getattr(obj, "data", None))


def stable_short_hash(parts, length: int = 12) -> str:
    text = "|".join(str(part) for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:max(1, int(length))]


def make_typed_slot_id(kind: str, *parts) -> str:
    head = str(kind or "").strip()
    body = ":".join(str(part) for part in parts)
    return f"{head}:{body}" if body else head
