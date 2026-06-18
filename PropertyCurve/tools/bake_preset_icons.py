"""批量烘焙 PropertyCurve 预设图标。

用法示例：
    python PropertyCurve/tools/bake_preset_icons.py
    python PropertyCurve/tools/bake_preset_icons.py --curve-kind float_curve --size 64
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import types
import zlib
from pathlib import Path


def _install_fake_bpy():
    try:
        import bpy  # noqa: F401
        return
    except Exception:
        pass

    class _Props:
        def FloatProperty(self, **kwargs):
            return kwargs.get("default", 0.0)

        def EnumProperty(self, **kwargs):
            return kwargs.get("default", "")

        def FloatVectorProperty(self, **kwargs):
            return kwargs.get("default", (0.0, 0.0, 0.0, 0.0))

        def CollectionProperty(self, **_kwargs):
            return []

    bpy = types.ModuleType("bpy")
    bpy.props = _Props()
    bpy_types = types.ModuleType("bpy.types")
    bpy_types.PropertyGroup = object
    bpy.types = bpy_types
    bpy.utils = types.SimpleNamespace(register_class=lambda cls: None, unregister_class=lambda cls: None)
    sys.modules["bpy"] = bpy
    sys.modules["bpy.types"] = bpy_types


def _prepare_package_import():
    repo_root = Path(__file__).resolve().parents[2]
    if "HoTools" not in sys.modules:
        package = types.ModuleType("HoTools")
        package.__path__ = [str(repo_root)]
        sys.modules["HoTools"] = package


def _load_property_curve():
    _install_fake_bpy()
    _prepare_package_import()
    from HoTools.PropertyCurve import (  # noqa: PLC0415
        PropertyCurvePresetRegistry,
        curve_preset_icon_path,
        resolve_color_curve,
        resolve_float_curve,
    )

    return PropertyCurvePresetRegistry, curve_preset_icon_path, resolve_float_curve, resolve_color_curve


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, float(value)))


class _Canvas:
    def __init__(self, width, height):
        self.width = int(width)
        self.height = int(height)
        self.pixels = [0.0] * (self.width * self.height * 4)

    def blend_pixel(self, x, y, color):
        x = int(x)
        y = int(y)
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return

        index = (y * self.width + x) * 4
        src_alpha = _clamp(color[3])
        inv_alpha = 1.0 - src_alpha
        self.pixels[index + 0] = color[0] * src_alpha + self.pixels[index + 0] * inv_alpha
        self.pixels[index + 1] = color[1] * src_alpha + self.pixels[index + 1] * inv_alpha
        self.pixels[index + 2] = color[2] * src_alpha + self.pixels[index + 2] * inv_alpha
        self.pixels[index + 3] = src_alpha + self.pixels[index + 3] * inv_alpha

    def fill_rect(self, left, top, right, bottom, color):
        left = max(0, int(math.floor(left)))
        top = max(0, int(math.floor(top)))
        right = min(self.width, int(math.ceil(right)))
        bottom = min(self.height, int(math.ceil(bottom)))
        for y in range(top, bottom):
            for x in range(left, right):
                self.blend_pixel(x, y, color)

    def draw_line(self, x0, y0, x1, y1, color, width=1.0):
        half = max(0.5, float(width) * 0.5)
        min_x = int(math.floor(min(x0, x1) - half - 1))
        max_x = int(math.ceil(max(x0, x1) + half + 1))
        min_y = int(math.floor(min(y0, y1) - half - 1))
        max_y = int(math.ceil(max(y0, y1) + half + 1))
        dx = x1 - x0
        dy = y1 - y0
        length_sq = dx * dx + dy * dy
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if length_sq <= 0.000001:
                    distance = math.hypot(x - x0, y - y0)
                else:
                    factor = _clamp(((x - x0) * dx + (y - y0) * dy) / length_sq)
                    px = x0 + dx * factor
                    py = y0 + dy * factor
                    distance = math.hypot(x - px, y - py)
                coverage = _clamp(half + 1.0 - distance)
                if coverage > 0.0:
                    self.blend_pixel(x, y, (color[0], color[1], color[2], color[3] * coverage))

    def draw_polyline(self, points, color, width=1.0):
        if len(points) < 2:
            return
        for index in range(len(points) - 1):
            self.draw_line(points[index][0], points[index][1], points[index + 1][0], points[index + 1][1], color, width)

    def draw_circle(self, cx, cy, radius, color):
        radius = float(radius)
        min_x = int(math.floor(cx - radius - 1))
        max_x = int(math.ceil(cx + radius + 1))
        min_y = int(math.floor(cy - radius - 1))
        max_y = int(math.ceil(cy + radius + 1))
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                distance = math.hypot(x - cx, y - cy)
                coverage = _clamp(radius + 1.0 - distance)
                if coverage > 0.0:
                    self.blend_pixel(x, y, (color[0], color[1], color[2], color[3] * coverage))


def _downsample_rgba(canvas, size, scale):
    output = bytearray(size * size * 4)
    divisor = float(scale * scale)
    for y in range(size):
        for x in range(size):
            sums = [0.0, 0.0, 0.0, 0.0]
            for sy in range(scale):
                for sx in range(scale):
                    source_x = x * scale + sx
                    source_y = y * scale + sy
                    source_index = (source_y * canvas.width + source_x) * 4
                    for channel in range(4):
                        sums[channel] += canvas.pixels[source_index + channel]
            target_index = (y * size + x) * 4
            for channel in range(4):
                output[target_index + channel] = int(round(_clamp(sums[channel] / divisor) * 255.0))
    return bytes(output)


def _png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _write_png(path, width, height, rgba):
    rows = []
    stride = width * 4
    for y in range(height):
        rows.append(b"\x00" + rgba[y * stride:(y + 1) * stride])
    raw = b"".join(rows)
    png = b"".join([
        b"\x89PNG\r\n\x1a\n",
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
        _png_chunk(b"IDAT", zlib.compress(raw, 9)),
        _png_chunk(b"IEND", b""),
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def _curve_y_bounds(curve, curve_kind):
    if curve_kind == "color_curve":
        return 0.0, 1.0

    positions = [index / 127.0 for index in range(128)]
    values = [float(curve.sample(position)) for position in positions]
    values.extend(float(point["y"]) for point in curve.points)
    values.extend([0.0, 1.0])
    minimum = min(values)
    maximum = max(values)
    if abs(maximum - minimum) < 0.000001:
        padding = max(abs(maximum) * 0.2, 1.0)
    else:
        padding = (maximum - minimum) * 0.08
    return minimum - padding, maximum + padding


def _draw_icon_frame(canvas, size):
    unit = size / 128.0
    pad = 12.0 * unit
    canvas.fill_rect(0, 0, size, size, (0.035, 0.043, 0.055, 1.0))
    canvas.fill_rect(pad, pad, size - pad, size - pad, (0.018, 0.022, 0.030, 1.0))
    border = (0.38, 0.45, 0.55, 0.75)
    canvas.draw_polyline(
        [(pad, pad), (size - pad, pad), (size - pad, size - pad), (pad, size - pad), (pad, pad)],
        border,
        width=1.3 * unit,
    )


def _draw_grid(canvas, sx, sy, y_min, y_max):
    unit = canvas.width / 128.0
    grid = (0.22, 0.28, 0.36, 0.55)
    axis = (0.62, 0.68, 0.76, 0.75)
    for x_value in (0.0, 1.0):
        x = sx(x_value)
        canvas.draw_line(x, sy(y_min), x, sy(y_max), axis, width=1.0 * unit)
    for y_value in (0.0, 1.0):
        if y_min <= y_value <= y_max:
            y = sy(y_value)
            canvas.draw_line(sx(0.0), y, sx(1.0), y, axis if y_value == 0.0 else grid, width=1.0 * unit)


def _draw_float_curve_icon(canvas, curve, size, curve_kind):
    unit = size / 128.0
    pad = 12.0 * unit
    y_min, y_max = _curve_y_bounds(curve, curve_kind)

    def sx(value):
        return pad + _clamp(value, 0.0, 1.0) * (size - pad * 2.0)

    def sy(value):
        if abs(y_max - y_min) < 0.000001:
            return size * 0.5
        return size - pad - (float(value) - y_min) / (y_max - y_min) * (size - pad * 2.0)

    _draw_grid(canvas, sx, sy, y_min, y_max)
    positions = [index / 127.0 for index in range(128)]
    points = [(sx(position), sy(curve.sample(position))) for position in positions]
    canvas.draw_polyline(points, (0.35, 0.86, 1.0, 1.0), width=2.4 * unit)
    for point in curve.points:
        canvas.draw_circle(sx(point["x"]), sy(point["y"]), 2.0 * unit, (0.82, 0.94, 1.0, 0.95))


def _draw_color_curve_icon(canvas, curve, size):
    unit = size / 128.0
    pad = 12.0 * unit
    y_min, y_max = 0.0, 1.0

    def sx(value):
        return pad + _clamp(value, 0.0, 1.0) * (size - pad * 2.0)

    def sy(value):
        return size - pad - _clamp(value, y_min, y_max) * (size - pad * 2.0)

    _draw_grid(canvas, sx, sy, y_min, y_max)
    colors = [
        (0, (1.0, 0.22, 0.20, 1.0)),
        (1, (0.24, 0.95, 0.38, 1.0)),
        (2, (0.28, 0.55, 1.0, 1.0)),
    ]
    positions = [index / 127.0 for index in range(128)]
    for channel, color in colors:
        points = [(sx(position), sy(curve.sample(position)[channel])) for position in positions]
        canvas.draw_polyline(points, color, width=2.0 * unit)


def render_curve_icon(payload, size=64, supersample=3, resolve_float_curve=None, resolve_color_curve=None):
    scale = max(1, int(supersample))
    canvas_size = int(size) * scale
    canvas = _Canvas(canvas_size, canvas_size)
    _draw_icon_frame(canvas, canvas_size)

    if resolve_float_curve is None or resolve_color_curve is None:
        _registry, _icon_path, resolve_float_curve, resolve_color_curve = _load_property_curve()
    curve_kind = str(payload.get("kind", "float_curve"))
    if curve_kind == "color_curve":
        _draw_color_curve_icon(canvas, resolve_color_curve(payload), canvas_size)
    else:
        _draw_float_curve_icon(canvas, resolve_float_curve(payload), canvas_size, curve_kind)
    return _downsample_rgba(canvas, int(size), scale)


def bake_preset_icons(curve_kinds=None, identifiers=None, size=64, supersample=3, output_root=None):
    registry, icon_path, _resolve_float_curve, _resolve_color_curve = _load_property_curve()
    curve_kinds = curve_kinds or ["float_curve"]
    identifiers = set(identifiers or [])
    results = []

    for curve_kind in curve_kinds:
        for preset_cls in registry.classes(curve_kind):
            if identifiers and preset_cls.identifier not in identifiers:
                continue
            payload = registry.preview_payload(preset_cls.identifier, curve_kind=curve_kind)
            if payload is None:
                continue
            target = icon_path(preset_cls.identifier, curve_kind=curve_kind, size=size)
            if output_root is not None:
                target = Path(output_root) / curve_kind / target.name
            rgba = render_curve_icon(
                payload,
                size=size,
                supersample=supersample,
                resolve_float_curve=_resolve_float_curve,
                resolve_color_curve=_resolve_color_curve,
            )
            _write_png(target, int(size), int(size), rgba)
            results.append(target)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="批量烘焙 PropertyCurve 预设图标")
    parser.add_argument("--curve-kind", action="append", choices=["float_curve", "color_curve"], help="要烘焙的曲线类型，可重复传入")
    parser.add_argument("--identifier", action="append", help="只烘焙指定预设，可重复传入")
    parser.add_argument("--size", type=int, default=64, help="图标分辨率")
    parser.add_argument("--supersample", type=int, default=3, help="抗锯齿超采样倍率")
    parser.add_argument("--output-root", default=None, help="自定义输出目录")
    args = parser.parse_args(argv)

    results = bake_preset_icons(
        curve_kinds=args.curve_kind or ["float_curve"],
        identifiers=args.identifier,
        size=args.size,
        supersample=args.supersample,
        output_root=args.output_root,
    )
    for path in results:
        print(path)
    print(f"baked {len(results)} icons")


if __name__ == "__main__":
    main()
