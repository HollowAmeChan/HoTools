"""Physics World 的 Blender 输出时间换算。

只有这个公共边界解释 ``Scene.render``。solver、Field sampler 和可视化只消费
这里产生的秒数，避免各自维护 fps fallback 或忽略 ``fps_base``。
"""

from __future__ import annotations

import math


DEFAULT_OUTPUT_FPS = 24.0
_MIN_OUTPUT_FPS = 1.0e-7


def scene_output_fps(scene) -> float:
    """返回 Blender 输出帧率；无效设置统一降级到 24 fps。"""
    try:
        fps = float(scene.render.fps)
        fps_base = float(scene.render.fps_base)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return DEFAULT_OUTPUT_FPS
    if (
        not math.isfinite(fps)
        or not math.isfinite(fps_base)
        or fps <= _MIN_OUTPUT_FPS
        or fps_base <= _MIN_OUTPUT_FPS
    ):
        return DEFAULT_OUTPUT_FPS
    output_fps = fps / fps_base
    if math.isfinite(output_fps) and output_fps > _MIN_OUTPUT_FPS:
        return output_fps
    return DEFAULT_OUTPUT_FPS


def scene_raw_dt_seconds(scene) -> float:
    """返回一个 Blender 输出帧对应的未缩放秒数。"""
    return 1.0 / scene_output_fps(scene)


def scene_timeline_time_seconds(scene, *, frame=None, origin_frame=None) -> float:
    """把输出帧映射成从指定起点开始的非负时间轴秒数。

    Field 的无 consumer 预览以 ``scene.frame_start`` 为零点。正式模拟仍由
    ``PhysicsFrameContext.sample_time_seconds`` 处理暂停、重启和连续推进。
    """
    current = int(getattr(scene, "frame_current", 0) if frame is None else frame)
    origin = int(
        getattr(scene, "frame_start", current)
        if origin_frame is None
        else origin_frame
    )
    return max(current - origin, 0) * scene_raw_dt_seconds(scene)


__all__ = [
    "DEFAULT_OUTPUT_FPS",
    "scene_output_fps",
    "scene_raw_dt_seconds",
    "scene_timeline_time_seconds",
]
