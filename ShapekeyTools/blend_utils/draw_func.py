"""视口 2D 绘制工具：GPU 图元、文字、坐标系映射与配色。

只提供“怎么画”，不持有任何绘件状态（状态在 ``blend_overlay.WIDGET``）。所有函数都
可以直接在 ``POST_PIXEL`` 绘制回调里调用；没有 GPU 上下文时（后台 Blender）会静默
降级，不抛异常。
"""

from __future__ import annotations

import math

import blf
import gpu

try:
    from . import blend_space_math as _math
except ImportError:  # 兼容旧工具直接导入脚本
    import blend_space_math as _math


# region 配色与字号


FONT_SIZE = 11
FONT_SIZE_SMALL = 10

COLOR_BACKDROP = (0.05, 0.06, 0.08, 0.78)
COLOR_BORDER = (0.42, 0.46, 0.52, 1.0)
COLOR_GRID = (1.0, 1.0, 1.0, 0.09)
COLOR_AXIS = (0.62, 0.72, 0.86, 0.75)
COLOR_TEXT = (0.92, 0.94, 0.97, 1.0)
COLOR_TEXT_DIM = (0.62, 0.66, 0.72, 1.0)
COLOR_CENTER = (1.0, 0.85, 0.25, 1.0)
COLOR_DISABLED = (0.55, 0.55, 0.58, 1.0)
COLOR_HOVER = (1.0, 1.0, 1.0, 1.0)
COLOR_IDLE_POINT = (0.35, 0.38, 0.42, 1.0)

_WEIGHT_COLD = (0.24, 0.45, 0.85)
_WEIGHT_HOT = (0.98, 0.35, 0.25)


def weight_color(weight: float, enabled: bool = True):
    """按权重从冷到暖着色，权重为 0 时是暗灰，被禁用的点位是中性灰。"""
    if not enabled:
        return COLOR_DISABLED
    if weight <= 1e-6:
        return COLOR_IDLE_POINT
    ratio = max(0.0, min(1.0, weight))
    return (
        _WEIGHT_COLD[0] + (_WEIGHT_HOT[0] - _WEIGHT_COLD[0]) * ratio,
        _WEIGHT_COLD[1] + (_WEIGHT_HOT[1] - _WEIGHT_COLD[1]) * ratio,
        _WEIGHT_COLD[2] + (_WEIGHT_HOT[2] - _WEIGHT_COLD[2]) * ratio,
        1.0,
    )


# endregion


# region GPU 图元


_SHADER = None


def get_shader():
    """取 2D 单色着色器；没有 GPU 上下文时返回 ``None``。"""
    global _SHADER
    if _SHADER is None:
        try:
            _SHADER = gpu.shader.from_builtin('UNIFORM_COLOR')
        except Exception:  # noqa: BLE001 - 无 GPU 上下文时静默降级
            _SHADER = False
    return _SHADER or None


def reset_shader():
    """丢弃缓存的着色器（绘制异常或上下文切换后重新获取）。"""
    global _SHADER
    _SHADER = None


def has_gpu() -> bool:
    return get_shader() is not None


def _batch(primitive, coords):
    shader = get_shader()
    if shader is None:
        return None
    from gpu_extras.batch import batch_for_shader
    return batch_for_shader(
        shader, primitive, {"pos": [(x, y, 0.0) for x, y in coords]})


def _submit(batch, color) -> None:
    shader = get_shader()
    if shader is None or batch is None:
        return
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def draw_quad(a, b, c, d, color) -> None:
    _submit(_batch('TRIS', (a, b, c, a, c, d)), color)


def draw_rect(x, y, width, height, color) -> None:
    """画一个填充矩形（左下角 + 宽高）。"""
    draw_quad((x, y), (x + width, y), (x + width, y + height), (x, y + height), color)


def draw_frame(x, y, width, height, color, line_width=1.0) -> None:
    """画一个矩形边框。"""
    draw_line_strip(
        ((x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)),
        color, line_width)


def draw_line_strip(points, color, width=1.0) -> None:
    """把一串点连成折线。"""
    if len(points) < 2:
        return
    coords = []
    for index in range(len(points) - 1):
        coords.append(points[index])
        coords.append(points[index + 1])
    batch = _batch('LINES', coords)
    if batch is None:
        return
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    shader = get_shader()
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_square(cx, cy, radius, color) -> None:
    """以 ``(cx, cy)`` 为中心画一个填充方块。"""
    draw_rect(cx - radius, cy - radius, radius * 2.0, radius * 2.0, color)


def draw_ring(cx, cy, radius, color, width=1.6, segments=28) -> None:
    """画一个空心圆环。"""
    points = [
        (cx + radius * math.cos(math.tau * index / segments),
         cy + radius * math.sin(math.tau * index / segments))
        for index in range(segments + 1)
    ]
    draw_line_strip(points, color, width)


# endregion


# region 文字


def _rgba(color, alpha=1.0):
    if len(color) == 4:
        return (color[0], color[1], color[2], color[3] * alpha)
    return (color[0], color[1], color[2], alpha)


def text_width(text, size=FONT_SIZE) -> float:
    """量一段文字的像素宽度（会临时改 blf 字号，调用方无需恢复）。"""
    blf.size(0, size)
    return blf.dimensions(0, str(text))[0]


def draw_text(text, x, y, color, size=FONT_SIZE) -> None:
    """在区域像素坐标 ``(x, y)`` 画一段文字（左下角对齐）。"""
    blf.size(0, size)
    blf.color(0, *_rgba(color))
    blf.position(0, x, y, 0)
    blf.draw(0, str(text))


# endregion


# region 坐标系映射


def clamp_to_rect(px, py, rect):
    """把点夹进 ``(x, y, width, height)``。"""
    x, y, width, height = rect
    return (
        max(x, min(px, x + width)),
        max(y, min(py, y + height)),
    )


def uv_to_plot(u, v, rect, axis_range):
    """混合坐标 → 区域像素坐标。"""
    return _math.uv_to_pixel(u, v, rect, axis_range)


def plot_to_uv(px, py, rect, axis_range):
    """区域像素坐标 → 混合坐标。"""
    return _math.pixel_to_uv(px, py, rect, axis_range)


# endregion
