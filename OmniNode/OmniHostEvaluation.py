"""OmniNode 与 Blender 宿主帧求值之间的最小生命周期边界。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import bpy


@dataclass
class _FrameEvaluationState:
    active: bool = False
    depsgraph: object | None = None


_STATE = _FrameEvaluationState()
_RENDERING = False


def is_frame_evaluation_active() -> bool:
    """当前是否处于 OmniNode 的 frame_change_post 执行区间。"""
    return _STATE.active


def current_frame_depsgraph():
    """返回当前 handler 收到的短生命周期 depsgraph；帧外返回 None。"""
    return _STATE.depsgraph if _STATE.active else None


@contextmanager
def frame_evaluation_scope(depsgraph) -> Iterator[None]:
    """发布一帧宿主求值上下文，并保证异常路径清空 Blender 引用。"""
    if _STATE.active:
        raise RuntimeError("OmniNode frame evaluation 不允许重入")
    _STATE.active = True
    _STATE.depsgraph = depsgraph
    try:
        yield
    finally:
        _STATE.depsgraph = None
        _STATE.active = False


def get_evaluated_depsgraph(context=None):
    """帧内复用宿主 depsgraph，帧外才请求 Blender 主动求值。"""
    if _STATE.active:
        return _STATE.depsgraph
    target = bpy.context if context is None else context
    try:
        return target.evaluated_depsgraph_get()
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def update_view_layer_if_allowed(view_layer=None) -> bool:
    """只在帧外同步 ViewLayer；帧内返回 False 并保持宿主求值边界。"""
    if _STATE.active:
        return False
    target = (
        getattr(bpy.context, "view_layer", None)
        if view_layer is None
        else view_layer
    )
    if target is None:
        return False
    try:
        target.update()
        return True
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def is_rendering() -> bool:
    """当前是否处于 Blender 渲染生命周期。"""
    return _RENDERING


def set_rendering(active: bool) -> None:
    """由 render_pre/complete/cancel handler 更新渲染状态。"""
    global _RENDERING
    _RENDERING = bool(active)


def refresh_frame_references(reason: str):
    """在渲染帧边界刷新 committed owner 的 Blender 数据块引用。"""
    try:
        from .OmniReferenceGuard import refresh_persistent_references

        return refresh_persistent_references(reason)
    except Exception:
        return None


__all__ = [
    "current_frame_depsgraph",
    "frame_evaluation_scope",
    "get_evaluated_depsgraph",
    "is_rendering",
    "is_frame_evaluation_active",
    "refresh_frame_references",
    "set_rendering",
    "update_view_layer_if_allowed",
]
