"""PropertyCurve 预设图标加载与路径管理。"""

from __future__ import annotations

from pathlib import Path

try:
    import bpy  # type: ignore
except Exception:
    bpy = None


PROPERTY_CURVE_ICON_SIZE = 64
PROPERTY_CURVE_ICON_DIR = Path(__file__).resolve().parent / "icons"

_PREVIEW_COLLECTION = None


def _safe_icon_name(identifier) -> str:
    raw = str(identifier or "UNKNOWN").strip() or "UNKNOWN"
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)


def curve_preset_icon_path(identifier, curve_kind="float_curve", size=PROPERTY_CURVE_ICON_SIZE) -> Path:
    return PROPERTY_CURVE_ICON_DIR / str(curve_kind) / f"{_safe_icon_name(identifier)}_{int(size)}.png"


def _preview_module():
    if bpy is None:
        return None

    try:
        return bpy.utils.previews
    except Exception:
        return None


def _preview_collection():
    global _PREVIEW_COLLECTION
    if _PREVIEW_COLLECTION is not None:
        return _PREVIEW_COLLECTION

    previews = _preview_module()
    if previews is None:
        return None
    _PREVIEW_COLLECTION = previews.new()
    return _PREVIEW_COLLECTION


def curve_preset_icon_id(identifier, curve_kind="float_curve", size=PROPERTY_CURVE_ICON_SIZE) -> int:
    path = curve_preset_icon_path(identifier, curve_kind=curve_kind, size=size)
    if not path.exists():
        return 0

    collection = _preview_collection()
    if collection is None:
        return 0

    key = f"{curve_kind}:{identifier}:{int(size)}"
    if key not in collection:
        try:
            collection.load(key, str(path), "IMAGE")
        except Exception:
            return 0
    return int(collection[key].icon_id)


def register_icon_previews():
    _preview_collection()


def unregister_icon_previews():
    global _PREVIEW_COLLECTION
    if _PREVIEW_COLLECTION is None:
        return

    previews = _preview_module()
    if previews is not None:
        try:
            previews.remove(_PREVIEW_COLLECTION)
        except Exception:
            pass
    _PREVIEW_COLLECTION = None
