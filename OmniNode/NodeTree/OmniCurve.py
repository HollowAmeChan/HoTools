"""OmniNode 曲线数据与统一采样入口。"""

from __future__ import annotations

import bpy
from bpy.types import PropertyGroup


CURVE_INTERPOLATION_ITEMS = [
    ("LINEAR", "线性", "按直线方式插值"),
    ("CONSTANT", "常量", "保持左侧控制点数值不变"),
]

CURVE_EXTEND_ITEMS = [
    ("CLAMP", "钳制", "超出范围时使用边界控制点"),
    ("REPEAT", "重复", "超出范围时按 0 到 1 区间循环"),
    ("MIRROR", "镜像", "超出范围时按 0 到 1 区间来回折返"),
]


def clamp_float(value, minimum=None, maximum=None) -> float:
    value = float(value)
    if minimum is not None and value < minimum:
        return float(minimum)
    if maximum is not None and value > maximum:
        return float(maximum)
    return value


def coerce_interpolation(value) -> str:
    value = str(value or "LINEAR")
    if value not in {"LINEAR", "CONSTANT"}:
        return "LINEAR"
    return value


def coerce_extend(value, fallback="CLAMP") -> str:
    raw = str(value or "").strip()
    fallback_key = str(fallback or "CLAMP").strip().upper()
    if fallback_key not in {"CLAMP", "REPEAT", "MIRROR"}:
        fallback_key = "CLAMP"
    if raw == "":
        return fallback_key

    key = raw.upper()
    if key in {"CLAMP", "REPEAT", "MIRROR"}:
        return key

    aliases = {
        "钳制": "CLAMP",
        "重复": "REPEAT",
        "镜像": "MIRROR",
    }
    return aliases.get(raw, fallback_key)


def use_curve_extend(value) -> bool:
    raw = str(value or "").strip()
    return raw == "" or raw in {"曲线", "默认"} or raw.upper() in {"CURVE", "DEFAULT"}


def extend_position(value, extend="CLAMP") -> float:
    x = float(value)
    extend = coerce_extend(extend)
    if extend == "REPEAT":
        if 0.0 <= x <= 1.0:
            return x
        return x % 1.0
    if extend == "MIRROR":
        if 0.0 <= x <= 1.0:
            return x
        wrapped = x % 2.0
        if wrapped > 1.0:
            return 2.0 - wrapped
        return wrapped
    return clamp_float(x, 0.0, 1.0)


def coerce_color(value) -> tuple[float, float, float, float]:
    if value is None:
        return (1.0, 1.0, 1.0, 1.0)
    try:
        items = list(value)
    except Exception:
        return (1.0, 1.0, 1.0, 1.0)
    while len(items) < 4:
        items.append(1.0)
    return tuple(clamp_float(items[index], 0.0, 1.0) for index in range(4))


def normalize_float_points(points) -> list[dict]:
    result = []
    try:
        iterable = points or ()
    except Exception:
        iterable = ()
    for point in iterable:
        if isinstance(point, dict):
            x = point.get("x", point.get("position", 0.0))
            y = point.get("y", point.get("value", 0.0))
        else:
            try:
                x, y = point[0], point[1]
            except Exception:
                continue
        result.append({"x": clamp_float(x, 0.0, 1.0), "y": float(y)})

    if not result:
        result = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]
    if len(result) == 1:
        only = result[0]
        result.append({"x": 1.0 if only["x"] <= 0.5 else 0.0, "y": only["y"]})
    return sorted(result, key=lambda item: item["x"])


def normalize_color_points(points) -> list[dict]:
    result = []
    try:
        iterable = points or ()
    except Exception:
        iterable = ()
    for point in iterable:
        if isinstance(point, dict):
            x = point.get("x", point.get("position", 0.0))
            color = point.get("color", point.get("value", (1.0, 1.0, 1.0, 1.0)))
        else:
            try:
                x, color = point[0], point[1]
            except Exception:
                continue
        result.append({"x": clamp_float(x, 0.0, 1.0), "color": coerce_color(color)})

    if not result:
        result = [
            {"x": 0.0, "color": (0.0, 0.0, 0.0, 1.0)},
            {"x": 1.0, "color": (1.0, 1.0, 1.0, 1.0)},
        ]
    if len(result) == 1:
        only = result[0]
        result.append({"x": 1.0 if only["x"] <= 0.5 else 0.0, "color": only["color"]})
    return sorted(result, key=lambda item: item["x"])


def float_curve_payload(points=None, value=0.0, interpolation="LINEAR", extend="CLAMP") -> dict:
    points = normalize_float_points(points)
    return {
        "kind": "float_curve",
        "mode": "curve",
        "value": float(value),
        "interpolation": coerce_interpolation(interpolation),
        "extend": coerce_extend(extend),
        "points": [dict(point) for point in points],
    }


def color_curve_payload(points=None, interpolation="LINEAR", extend="CLAMP") -> dict:
    points = normalize_color_points(points)
    return {
        "kind": "color_curve",
        "mode": "color_curve",
        "interpolation": coerce_interpolation(interpolation),
        "extend": coerce_extend(extend),
        "points": [dict(point) for point in points],
    }


def _float_point_dict(point):
    return {
        "x": clamp_float(getattr(point, "x", 0.0), 0.0, 1.0),
        "y": float(getattr(point, "y", 0.0)),
    }


def _color_point_dict(point):
    return {
        "x": clamp_float(getattr(point, "x", 0.0), 0.0, 1.0),
        "color": coerce_color(getattr(point, "color", (1.0, 1.0, 1.0, 1.0))),
    }


class OmniFloatCurvePoint(PropertyGroup):
    x: bpy.props.FloatProperty(name="位置", default=0.0, min=0.0, max=1.0)  # type: ignore
    y: bpy.props.FloatProperty(name="数值", default=0.0)  # type: ignore


class OmniColorCurvePoint(PropertyGroup):
    x: bpy.props.FloatProperty(name="位置", default=0.0, min=0.0, max=1.0)  # type: ignore
    color: bpy.props.FloatVectorProperty(  # type: ignore
        name="颜色",
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        size=4,
        subtype="COLOR",
    )


class OmniFloatCurveData(PropertyGroup):
    interpolation: bpy.props.EnumProperty(  # type: ignore
        name="插值",
        items=CURVE_INTERPOLATION_ITEMS,
        default="LINEAR",
    )
    extend: bpy.props.EnumProperty(name="延伸", items=CURVE_EXTEND_ITEMS, default="CLAMP")  # type: ignore
    value: bpy.props.FloatProperty(name="默认值", default=0.0)  # type: ignore
    points: bpy.props.CollectionProperty(type=OmniFloatCurvePoint)  # type: ignore

    def ensure_defaults(self):
        if len(self.points) > 0:
            return
        first = self.points.add()
        first.x = 0.0
        first.y = 0.0
        second = self.points.add()
        second.x = 1.0
        second.y = 1.0

    def as_payload(self):
        points = None if len(self.points) == 0 else [_float_point_dict(point) for point in self.points]
        return float_curve_payload(
            points,
            value=self.value,
            interpolation=self.interpolation,
            extend=self.extend,
        )

    def from_payload(self, value):
        if isinstance(value, dict):
            points = value.get("points")
            raw_value = value.get("value", self.value)
            if raw_value is not None:
                try:
                    self.value = float(raw_value)
                except Exception:
                    pass
            self.interpolation = coerce_interpolation(value.get("interpolation", self.interpolation))
            self.extend = coerce_extend(value.get("extend", self.extend))
        else:
            points = value
        normalized = normalize_float_points(points)
        self.points.clear()
        for point in normalized:
            item = self.points.add()
            item.x = point["x"]
            item.y = point["y"]


class OmniColorCurveData(PropertyGroup):
    interpolation: bpy.props.EnumProperty(  # type: ignore
        name="插值",
        items=CURVE_INTERPOLATION_ITEMS,
        default="LINEAR",
    )
    extend: bpy.props.EnumProperty(name="延伸", items=CURVE_EXTEND_ITEMS, default="CLAMP")  # type: ignore
    points: bpy.props.CollectionProperty(type=OmniColorCurvePoint)  # type: ignore

    def ensure_defaults(self):
        if len(self.points) > 0:
            return
        first = self.points.add()
        first.x = 0.0
        first.color = (0.0, 0.0, 0.0, 1.0)
        second = self.points.add()
        second.x = 1.0
        second.color = (1.0, 1.0, 1.0, 1.0)

    def as_payload(self):
        points = None if len(self.points) == 0 else [_color_point_dict(point) for point in self.points]
        return color_curve_payload(
            points,
            interpolation=self.interpolation,
            extend=self.extend,
        )

    def from_payload(self, value):
        if isinstance(value, dict):
            points = value.get("points")
            self.interpolation = coerce_interpolation(value.get("interpolation", self.interpolation))
            self.extend = coerce_extend(value.get("extend", self.extend))
        else:
            points = value
        normalized = normalize_color_points(points)
        self.points.clear()
        for point in normalized:
            item = self.points.add()
            item.x = point["x"]
            item.color = point["color"]


curve_property_cls = [
    OmniFloatCurvePoint,
    OmniColorCurvePoint,
    OmniFloatCurveData,
    OmniColorCurveData,
]


def register():
    try:
        for item in curve_property_cls:
            bpy.utils.register_class(item)
    except Exception:
        print(__file__ + " register failed!!!")


def unregister():
    try:
        for item in reversed(curve_property_cls):
            bpy.utils.unregister_class(item)
    except Exception:
        print(__file__ + " unregister failed!!!")


class OmniFloatCurveValue:
    def __init__(self, points=None, value=0.0, interpolation="LINEAR", extend="CLAMP"):
        self.value = float(value)
        self.points = normalize_float_points(points)
        self.interpolation = coerce_interpolation(interpolation)
        self.extend = coerce_extend(extend)

    def copy(self) -> "OmniFloatCurveValue":
        return OmniFloatCurveValue(
            [dict(point) for point in self.points],
            value=self.value,
            interpolation=self.interpolation,
            extend=self.extend,
        )

    def to_payload(self) -> dict:
        return float_curve_payload(
            [dict(point) for point in self.points],
            value=self.value,
            interpolation=self.interpolation,
            extend=self.extend,
        )

    def sample(self, position, extend=None) -> float:
        x = extend_position(position, self.extend if use_curve_extend(extend) else extend)
        points = self.points
        if x <= points[0]["x"]:
            return float(points[0]["y"])
        if x >= points[-1]["x"]:
            return float(points[-1]["y"])

        point_index = 0
        while point_index + 1 < len(points) and points[point_index + 1]["x"] < x:
            point_index += 1

        left = points[point_index]
        right = points[min(point_index + 1, len(points) - 1)]
        if self.interpolation == "CONSTANT" or right["x"] <= left["x"]:
            return float(left["y"])

        factor = (x - left["x"]) / (right["x"] - left["x"])
        return float(left["y"] * (1.0 - factor) + right["y"] * factor)

    def sample_many(self, count, extend=None) -> list[float]:
        count = max(1, int(count))
        if count == 1:
            return [self.sample(0.0, extend=extend)]
        return [self.sample(index / float(count - 1), extend=extend) for index in range(count)]


class OmniColorCurveValue:
    def __init__(self, points=None, interpolation="LINEAR", extend="CLAMP"):
        self.points = normalize_color_points(points)
        self.interpolation = coerce_interpolation(interpolation)
        self.extend = coerce_extend(extend)

    def copy(self) -> "OmniColorCurveValue":
        return OmniColorCurveValue(
            [dict(point) for point in self.points],
            interpolation=self.interpolation,
            extend=self.extend,
        )

    def to_payload(self) -> dict:
        return color_curve_payload(
            [dict(point) for point in self.points],
            interpolation=self.interpolation,
            extend=self.extend,
        )

    def sample(self, position, extend=None) -> tuple[float, float, float, float]:
        x = extend_position(position, self.extend if use_curve_extend(extend) else extend)
        points = self.points
        if x <= points[0]["x"]:
            return tuple(points[0]["color"])
        if x >= points[-1]["x"]:
            return tuple(points[-1]["color"])

        point_index = 0
        while point_index + 1 < len(points) and points[point_index + 1]["x"] < x:
            point_index += 1

        left = points[point_index]
        right = points[min(point_index + 1, len(points) - 1)]
        if self.interpolation == "CONSTANT" or right["x"] <= left["x"]:
            return tuple(left["color"])

        factor = (x - left["x"]) / (right["x"] - left["x"])
        return tuple(
            float(left["color"][channel] * (1.0 - factor) + right["color"][channel] * factor)
            for channel in range(4)
        )

    def sample_many(self, count, extend=None) -> list[tuple[float, float, float, float]]:
        count = max(1, int(count))
        if count == 1:
            return [self.sample(0.0, extend=extend)]
        return [self.sample(index / float(count - 1), extend=extend) for index in range(count)]


def resolve_float_curve(value) -> OmniFloatCurveValue:
    if isinstance(value, OmniFloatCurveValue):
        return value
    if isinstance(value, dict):
        return OmniFloatCurveValue(
            value.get("points"),
            value=value.get("value", 0.0),
            interpolation=value.get("interpolation", "LINEAR"),
            extend=value.get("extend", "CLAMP"),
        )
    if isinstance(value, (int, float)):
        return OmniFloatCurveValue(
            [{"x": 0.0, "y": float(value)}, {"x": 1.0, "y": float(value)}],
            value=float(value),
        )
    return OmniFloatCurveValue(value)


def resolve_color_curve(value) -> OmniColorCurveValue:
    if isinstance(value, OmniColorCurveValue):
        return value
    if isinstance(value, dict):
        return OmniColorCurveValue(
            value.get("points"),
            interpolation=value.get("interpolation", "LINEAR"),
            extend=value.get("extend", "CLAMP"),
        )
    return OmniColorCurveValue(value)
