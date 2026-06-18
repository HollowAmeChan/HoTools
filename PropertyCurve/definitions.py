"""HoTools 通用属性曲线数据与统一采样入口。"""

from __future__ import annotations

import bpy
from bpy.types import PropertyGroup


CURVE_INTERPOLATION_ITEMS = [
    ("LINEAR", "线性", "按直线方式插值"),
    ("CONSTANT", "常量", "保持左侧控制点数值不变"),
    ("BEZIER", "贝塞尔", "使用控制点切线进行平滑插值"),
]

CURVE_HANDLE_TYPE_ITEMS = [
    ("AUTO", "自动", "根据相邻控制点自动计算切线"),
    ("VECTOR", "向量", "使用当前曲线段方向作为切线"),
    ("FREE", "自由", "使用预设写入的切线数据"),
    ("COORD", "坐标", "使用预设写入的控制柄坐标"),
]

CURVE_EXTEND_ITEMS = [
    ("CLAMP", "钳制", "超出范围时使用边界控制点"),
    ("REPEAT", "重复", "超出范围时按 0 到 1 区间循环"),
    ("MIRROR", "镜像", "超出范围时按 0 到 1 区间来回折返"),
]

class OmniCurveCoerce:
    @staticmethod
    def clamp_float(value, minimum=None, maximum=None) -> float:
        value = float(value)
        if minimum is not None and value < minimum:
            return float(minimum)
        if maximum is not None and value > maximum:
            return float(maximum)
        return value

    @staticmethod
    def interpolation(value, fallback="LINEAR") -> str:
        fallback_key = str(fallback or "LINEAR").strip().upper()
        if fallback_key not in {"LINEAR", "CONSTANT", "BEZIER"}:
            fallback_key = "LINEAR"

        key = str(value or "").strip().upper()
        if key in {"LINEAR", "CONSTANT", "BEZIER"}:
            return key
        return fallback_key

    @staticmethod
    def handle_type(value, fallback="AUTO") -> str:
        fallback_key = str(fallback or "AUTO").strip().upper()
        if fallback_key not in {"AUTO", "VECTOR", "FREE", "COORD"}:
            fallback_key = "AUTO"

        key = str(value or "").strip().upper()
        if key in {"AUTO", "VECTOR", "FREE", "COORD"}:
            return key
        return fallback_key

    @staticmethod
    def extend(value, fallback="CLAMP") -> str:
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

    @staticmethod
    def use_curve_extend(value) -> bool:
        raw = str(value or "").strip()
        return raw == "" or raw in {"曲线", "默认"} or raw.upper() in {"CURVE", "DEFAULT"}

    @staticmethod
    def extend_position(value, extend="CLAMP") -> float:
        x = float(value)
        extend = OmniCurveCoerce.extend(extend)
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
        return OmniCurveCoerce.clamp_float(x, 0.0, 1.0)

    @staticmethod
    def color(value) -> tuple[float, float, float, float]:
        if value is None:
            return (1.0, 1.0, 1.0, 1.0)
        try:
            items = list(value)
        except Exception:
            return (1.0, 1.0, 1.0, 1.0)
        while len(items) < 4:
            items.append(1.0)
        return tuple(OmniCurveCoerce.clamp_float(items[index], 0.0, 1.0) for index in range(4))

    @staticmethod
    def color_tangent(value, fallback=0.0) -> tuple[float, float, float, float]:
        try:
            fallback_value = float(fallback)
        except Exception:
            fallback_value = 0.0
        if value is None:
            return (fallback_value, fallback_value, fallback_value, fallback_value)
        if isinstance(value, (int, float)):
            scalar = float(value)
            return (scalar, scalar, scalar, scalar)
        try:
            items = list(value)
        except Exception:
            return (fallback_value, fallback_value, fallback_value, fallback_value)
        while len(items) < 4:
            items.append(fallback_value)
        result = []
        for item in items[:4]:
            try:
                result.append(float(item))
            except Exception:
                result.append(fallback_value)
        return tuple(result)


class OmniCurvePointCodec:
    @staticmethod
    def interpolation(point, fallback="LINEAR") -> str:
        if isinstance(point, dict):
            return OmniCurveCoerce.interpolation(point.get("interpolation", fallback), fallback)
        return OmniCurveCoerce.interpolation(fallback)

    @staticmethod
    def handle_type(point, side, fallback="AUTO") -> str:
        if not isinstance(point, dict):
            return OmniCurveCoerce.handle_type(fallback)
        return OmniCurveCoerce.handle_type(point.get(f"{side}_handle_type", point.get("handle_type", fallback)), fallback)

    @staticmethod
    def point_float(point, key, fallback=0.0) -> float:
        if not isinstance(point, dict):
            return float(fallback)
        try:
            return float(point.get(key, fallback))
        except Exception:
            return float(fallback)

    @staticmethod
    def weight(point, key, fallback=1.0) -> float:
        return max(0.0, OmniCurvePointCodec.point_float(point, key, fallback))

    @staticmethod
    def color_tangent(point, key, fallback=0.0) -> tuple[float, float, float, float]:
        if isinstance(point, dict):
            return OmniCurveCoerce.color_tangent(point.get(key), fallback)
        return OmniCurveCoerce.color_tangent(None, fallback)

    @staticmethod
    def handle_delta(point, side, point_x, point_y) -> tuple[float, float]:
        if not isinstance(point, dict):
            return (0.0, 0.0)

        handle = point.get(f"{side}_handle")
        if handle is not None:
            try:
                handle_x = float(handle[0]) - float(point_x)
            except Exception:
                handle_x = OmniCurvePointCodec.point_float(point, f"{side}_handle_x", 0.0)
            try:
                handle_y = float(handle[1]) - float(point_y)
            except Exception:
                handle_y = OmniCurvePointCodec.point_float(point, f"{side}_handle_y", 0.0)
            return (handle_x, handle_y)

        return (
            OmniCurvePointCodec.point_float(point, f"{side}_handle_x", 0.0),
            OmniCurvePointCodec.point_float(point, f"{side}_handle_y", 0.0),
        )

    @staticmethod
    def color_handle_y(point, side, point_color) -> tuple[float, float, float, float]:
        if not isinstance(point, dict):
            return (0.0, 0.0, 0.0, 0.0)

        handle = point.get(f"{side}_handle")
        if handle is not None:
            try:
                values = list(handle[1])
                while len(values) < 4:
                    values.append(point_color[len(values)])
                return tuple(float(values[index]) - float(point_color[index]) for index in range(4))
            except Exception:
                pass

        return OmniCurveCoerce.color_tangent(point.get(f"{side}_handle_y"), 0.0)

    @staticmethod
    def base_point_data(point, default_interpolation) -> dict:
        return {
            "interpolation": OmniCurvePointCodec.interpolation(point, default_interpolation),
            "left_handle_type": OmniCurvePointCodec.handle_type(point, "left"),
            "right_handle_type": OmniCurvePointCodec.handle_type(point, "right"),
            "left_weight": OmniCurvePointCodec.weight(point, "left_weight", 1.0),
            "right_weight": OmniCurvePointCodec.weight(point, "right_weight", 1.0),
        }

    @staticmethod
    def normalize_float_points(points, interpolation="LINEAR") -> list[dict]:
        default_interpolation = OmniCurveCoerce.interpolation(interpolation)
        result = []
        try:
            iterable = points or ()
        except Exception:
            iterable = ()

        for point in iterable:
            if isinstance(point, dict):
                x = point.get("x", point.get("position", 0.0))
                y = point.get("y", point.get("value", 0.0))
                item = OmniCurvePointCodec.base_point_data(point, default_interpolation)
                item["left_tangent"] = OmniCurvePointCodec.point_float(point, "left_tangent", 0.0)
                item["right_tangent"] = OmniCurvePointCodec.point_float(point, "right_tangent", 0.0)
                item["left_handle_x"], item["left_handle_y"] = OmniCurvePointCodec.handle_delta(point, "left", x, y)
                item["right_handle_x"], item["right_handle_y"] = OmniCurvePointCodec.handle_delta(point, "right", x, y)
            else:
                try:
                    x, y = point[0], point[1]
                except Exception:
                    continue
                item = OmniCurvePointCodec.base_point_data({}, default_interpolation)
                try:
                    item["interpolation"] = OmniCurveCoerce.interpolation(point[2], default_interpolation)
                except Exception:
                    pass
                item["left_tangent"] = 0.0
                item["right_tangent"] = 0.0
                item["left_handle_x"] = 0.0
                item["left_handle_y"] = 0.0
                item["right_handle_x"] = 0.0
                item["right_handle_y"] = 0.0
            item["x"] = OmniCurveCoerce.clamp_float(x, 0.0, 1.0)
            item["y"] = float(y)
            result.append(item)

        if not result:
            result = [
                {
                    "x": 0.0,
                    "y": 0.0,
                    "interpolation": default_interpolation,
                    "left_handle_type": "AUTO",
                    "right_handle_type": "AUTO",
                    "left_tangent": 1.0,
                    "right_tangent": 1.0,
                    "left_weight": 1.0,
                    "right_weight": 1.0,
                    "left_handle_x": 0.0,
                    "left_handle_y": 0.0,
                    "right_handle_x": 0.0,
                    "right_handle_y": 0.0,
                },
                {
                    "x": 1.0,
                    "y": 1.0,
                    "interpolation": default_interpolation,
                    "left_handle_type": "AUTO",
                    "right_handle_type": "AUTO",
                    "left_tangent": 1.0,
                    "right_tangent": 1.0,
                    "left_weight": 1.0,
                    "right_weight": 1.0,
                    "left_handle_x": 0.0,
                    "left_handle_y": 0.0,
                    "right_handle_x": 0.0,
                    "right_handle_y": 0.0,
                },
            ]
        if len(result) == 1:
            only = result[0]
            result.append({
                **dict(only),
                "x": 1.0 if only["x"] <= 0.5 else 0.0,
            })
        return sorted(result, key=lambda item: item["x"])

    @staticmethod
    def normalize_color_points(points, interpolation="LINEAR") -> list[dict]:
        default_interpolation = OmniCurveCoerce.interpolation(interpolation)
        result = []
        try:
            iterable = points or ()
        except Exception:
            iterable = ()

        for point in iterable:
            if isinstance(point, dict):
                x = point.get("x", point.get("position", 0.0))
                color = point.get("color", point.get("value", (1.0, 1.0, 1.0, 1.0)))
                color = OmniCurveCoerce.color(color)
                item = OmniCurvePointCodec.base_point_data(point, default_interpolation)
                item["left_tangent"] = OmniCurvePointCodec.color_tangent(point, "left_tangent", 0.0)
                item["right_tangent"] = OmniCurvePointCodec.color_tangent(point, "right_tangent", 0.0)
                item["left_handle_x"], _left_handle_y = OmniCurvePointCodec.handle_delta(point, "left", x, 0.0)
                item["right_handle_x"], _right_handle_y = OmniCurvePointCodec.handle_delta(point, "right", x, 0.0)
                item["left_handle_y"] = OmniCurvePointCodec.color_handle_y(point, "left", color)
                item["right_handle_y"] = OmniCurvePointCodec.color_handle_y(point, "right", color)
            else:
                try:
                    x, color = point[0], point[1]
                except Exception:
                    continue
                item = OmniCurvePointCodec.base_point_data({}, default_interpolation)
                try:
                    item["interpolation"] = OmniCurveCoerce.interpolation(point[2], default_interpolation)
                except Exception:
                    pass
                item["left_tangent"] = (0.0, 0.0, 0.0, 0.0)
                item["right_tangent"] = (0.0, 0.0, 0.0, 0.0)
                item["left_handle_x"] = 0.0
                item["right_handle_x"] = 0.0
                item["left_handle_y"] = (0.0, 0.0, 0.0, 0.0)
                item["right_handle_y"] = (0.0, 0.0, 0.0, 0.0)
            item["x"] = OmniCurveCoerce.clamp_float(x, 0.0, 1.0)
            item["color"] = OmniCurveCoerce.color(color)
            result.append(item)

        if not result:
            result = [
                {
                    "x": 0.0,
                    "color": (0.0, 0.0, 0.0, 1.0),
                    "interpolation": default_interpolation,
                    "left_handle_type": "AUTO",
                    "right_handle_type": "AUTO",
                    "left_tangent": (1.0, 1.0, 1.0, 1.0),
                    "right_tangent": (1.0, 1.0, 1.0, 1.0),
                    "left_weight": 1.0,
                    "right_weight": 1.0,
                    "left_handle_x": 0.0,
                    "right_handle_x": 0.0,
                    "left_handle_y": (0.0, 0.0, 0.0, 0.0),
                    "right_handle_y": (0.0, 0.0, 0.0, 0.0),
                },
                {
                    "x": 1.0,
                    "color": (1.0, 1.0, 1.0, 1.0),
                    "interpolation": default_interpolation,
                    "left_handle_type": "AUTO",
                    "right_handle_type": "AUTO",
                    "left_tangent": (1.0, 1.0, 1.0, 1.0),
                    "right_tangent": (1.0, 1.0, 1.0, 1.0),
                    "left_weight": 1.0,
                    "right_weight": 1.0,
                    "left_handle_x": 0.0,
                    "right_handle_x": 0.0,
                    "left_handle_y": (0.0, 0.0, 0.0, 0.0),
                    "right_handle_y": (0.0, 0.0, 0.0, 0.0),
                },
            ]
        if len(result) == 1:
            only = result[0]
            result.append({
                **dict(only),
                "x": 1.0 if only["x"] <= 0.5 else 0.0,
            })
        return sorted(result, key=lambda item: item["x"])

    @staticmethod
    def float_point_dict(point):
        return {
            "x": OmniCurveCoerce.clamp_float(getattr(point, "x", 0.0), 0.0, 1.0),
            "y": float(getattr(point, "y", 0.0)),
            "interpolation": OmniCurveCoerce.interpolation(getattr(point, "interpolation", "LINEAR")),
            "left_handle_type": OmniCurveCoerce.handle_type(getattr(point, "left_handle_type", "AUTO")),
            "right_handle_type": OmniCurveCoerce.handle_type(getattr(point, "right_handle_type", "AUTO")),
            "left_tangent": float(getattr(point, "left_tangent", 0.0)),
            "right_tangent": float(getattr(point, "right_tangent", 0.0)),
            "left_weight": OmniCurvePointCodec.weight({"left_weight": getattr(point, "left_weight", 1.0)}, "left_weight"),
            "right_weight": OmniCurvePointCodec.weight({"right_weight": getattr(point, "right_weight", 1.0)}, "right_weight"),
            "left_handle_x": float(getattr(point, "left_handle_x", 0.0)),
            "left_handle_y": float(getattr(point, "left_handle_y", 0.0)),
            "right_handle_x": float(getattr(point, "right_handle_x", 0.0)),
            "right_handle_y": float(getattr(point, "right_handle_y", 0.0)),
        }

    @staticmethod
    def color_point_dict(point):
        return {
            "x": OmniCurveCoerce.clamp_float(getattr(point, "x", 0.0), 0.0, 1.0),
            "color": OmniCurveCoerce.color(getattr(point, "color", (1.0, 1.0, 1.0, 1.0))),
            "interpolation": OmniCurveCoerce.interpolation(getattr(point, "interpolation", "LINEAR")),
            "left_handle_type": OmniCurveCoerce.handle_type(getattr(point, "left_handle_type", "AUTO")),
            "right_handle_type": OmniCurveCoerce.handle_type(getattr(point, "right_handle_type", "AUTO")),
            "left_tangent": OmniCurveCoerce.color_tangent(getattr(point, "left_tangent", None)),
            "right_tangent": OmniCurveCoerce.color_tangent(getattr(point, "right_tangent", None)),
            "left_weight": OmniCurvePointCodec.weight({"left_weight": getattr(point, "left_weight", 1.0)}, "left_weight"),
            "right_weight": OmniCurvePointCodec.weight({"right_weight": getattr(point, "right_weight", 1.0)}, "right_weight"),
            "left_handle_x": float(getattr(point, "left_handle_x", 0.0)),
            "right_handle_x": float(getattr(point, "right_handle_x", 0.0)),
            "left_handle_y": OmniCurveCoerce.color_tangent(getattr(point, "left_handle_y", None)),
            "right_handle_y": OmniCurveCoerce.color_tangent(getattr(point, "right_handle_y", None)),
        }

    @staticmethod
    def apply_float_point(item, point):
        item.x = point["x"]
        item.y = point["y"]
        item.interpolation = point["interpolation"]
        item.left_handle_type = point["left_handle_type"]
        item.right_handle_type = point["right_handle_type"]
        item.left_tangent = point["left_tangent"]
        item.right_tangent = point["right_tangent"]
        item.left_weight = point["left_weight"]
        item.right_weight = point["right_weight"]
        item.left_handle_x = point["left_handle_x"]
        item.left_handle_y = point["left_handle_y"]
        item.right_handle_x = point["right_handle_x"]
        item.right_handle_y = point["right_handle_y"]

    @staticmethod
    def apply_color_point(item, point):
        item.x = point["x"]
        item.color = point["color"]
        item.interpolation = point["interpolation"]
        item.left_handle_type = point["left_handle_type"]
        item.right_handle_type = point["right_handle_type"]
        item.left_tangent = point["left_tangent"]
        item.right_tangent = point["right_tangent"]
        item.left_weight = point["left_weight"]
        item.right_weight = point["right_weight"]
        item.left_handle_x = point["left_handle_x"]
        item.right_handle_x = point["right_handle_x"]
        item.left_handle_y = point["left_handle_y"]
        item.right_handle_y = point["right_handle_y"]


class OmniCurvePayload:
    @staticmethod
    def float_curve(points=None, value=0.0, interpolation="LINEAR", extend="CLAMP") -> dict:
        interpolation = OmniCurveCoerce.interpolation(interpolation)
        points = OmniCurvePointCodec.normalize_float_points(points, interpolation=interpolation)
        return {
            "kind": "float_curve",
            "mode": "curve",
            "value": float(value),
            "interpolation": interpolation,
            "extend": OmniCurveCoerce.extend(extend),
            "points": [dict(point) for point in points],
        }

    @staticmethod
    def color_curve(points=None, interpolation="LINEAR", extend="CLAMP") -> dict:
        interpolation = OmniCurveCoerce.interpolation(interpolation)
        points = OmniCurvePointCodec.normalize_color_points(points, interpolation=interpolation)
        return {
            "kind": "color_curve",
            "mode": "color_curve",
            "interpolation": interpolation,
            "extend": OmniCurveCoerce.extend(extend),
            "points": [dict(point) for point in points],
        }


clamp_float = OmniCurveCoerce.clamp_float
coerce_interpolation = OmniCurveCoerce.interpolation
coerce_handle_type = OmniCurveCoerce.handle_type
coerce_extend = OmniCurveCoerce.extend
use_curve_extend = OmniCurveCoerce.use_curve_extend
extend_position = OmniCurveCoerce.extend_position
coerce_color = OmniCurveCoerce.color
coerce_color_tangent = OmniCurveCoerce.color_tangent
point_interpolation = OmniCurvePointCodec.interpolation
point_handle_type = OmniCurvePointCodec.handle_type
point_float = OmniCurvePointCodec.point_float
point_weight = OmniCurvePointCodec.weight
point_color_tangent = OmniCurvePointCodec.color_tangent
_base_point_data = OmniCurvePointCodec.base_point_data
normalize_float_points = OmniCurvePointCodec.normalize_float_points
normalize_color_points = OmniCurvePointCodec.normalize_color_points
_float_point_dict = OmniCurvePointCodec.float_point_dict
_color_point_dict = OmniCurvePointCodec.color_point_dict
_apply_float_point = OmniCurvePointCodec.apply_float_point
_apply_color_point = OmniCurvePointCodec.apply_color_point
float_curve_payload = OmniCurvePayload.float_curve
color_curve_payload = OmniCurvePayload.color_curve


class OmniFloatCurvePoint(PropertyGroup):
    x: bpy.props.FloatProperty(name="位置", default=0.0, min=0.0, max=1.0)  # type: ignore
    y: bpy.props.FloatProperty(name="数值", default=0.0)  # type: ignore
    interpolation: bpy.props.EnumProperty(name="插值", items=CURVE_INTERPOLATION_ITEMS, default="LINEAR")  # type: ignore
    left_handle_type: bpy.props.EnumProperty(name="左柄", items=CURVE_HANDLE_TYPE_ITEMS, default="AUTO")  # type: ignore
    right_handle_type: bpy.props.EnumProperty(name="右柄", items=CURVE_HANDLE_TYPE_ITEMS, default="AUTO")  # type: ignore
    left_tangent: bpy.props.FloatProperty(name="左切线", default=0.0)  # type: ignore
    right_tangent: bpy.props.FloatProperty(name="右切线", default=0.0)  # type: ignore
    left_weight: bpy.props.FloatProperty(name="左权重", default=1.0, min=0.0)  # type: ignore
    right_weight: bpy.props.FloatProperty(name="右权重", default=1.0, min=0.0)  # type: ignore
    left_handle_x: bpy.props.FloatProperty(name="左柄X", default=0.0)  # type: ignore
    left_handle_y: bpy.props.FloatProperty(name="左柄Y", default=0.0)  # type: ignore
    right_handle_x: bpy.props.FloatProperty(name="右柄X", default=0.0)  # type: ignore
    right_handle_y: bpy.props.FloatProperty(name="右柄Y", default=0.0)  # type: ignore


class OmniColorCurvePoint(PropertyGroup):
    x: bpy.props.FloatProperty(name="位置", default=0.0, min=0.0, max=1.0)  # type: ignore
    interpolation: bpy.props.EnumProperty(name="插值", items=CURVE_INTERPOLATION_ITEMS, default="LINEAR")  # type: ignore
    left_handle_type: bpy.props.EnumProperty(name="左柄", items=CURVE_HANDLE_TYPE_ITEMS, default="AUTO")  # type: ignore
    right_handle_type: bpy.props.EnumProperty(name="右柄", items=CURVE_HANDLE_TYPE_ITEMS, default="AUTO")  # type: ignore
    left_tangent: bpy.props.FloatVectorProperty(name="左切线", default=(0.0, 0.0, 0.0, 0.0), size=4)  # type: ignore
    right_tangent: bpy.props.FloatVectorProperty(name="右切线", default=(0.0, 0.0, 0.0, 0.0), size=4)  # type: ignore
    left_weight: bpy.props.FloatProperty(name="左权重", default=1.0, min=0.0)  # type: ignore
    right_weight: bpy.props.FloatProperty(name="右权重", default=1.0, min=0.0)  # type: ignore
    left_handle_x: bpy.props.FloatProperty(name="左柄X", default=0.0)  # type: ignore
    right_handle_x: bpy.props.FloatProperty(name="右柄X", default=0.0)  # type: ignore
    left_handle_y: bpy.props.FloatVectorProperty(name="左柄Y", default=(0.0, 0.0, 0.0, 0.0), size=4)  # type: ignore
    right_handle_y: bpy.props.FloatVectorProperty(name="右柄Y", default=(0.0, 0.0, 0.0, 0.0), size=4)  # type: ignore
    color: bpy.props.FloatVectorProperty(  # type: ignore
        name="颜色",
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        size=4,
        subtype="COLOR",
    )

class OmniFloatCurveData(PropertyGroup):
    interpolation: bpy.props.EnumProperty(name="默认插值", items=CURVE_INTERPOLATION_ITEMS, default="LINEAR")  # type: ignore
    extend: bpy.props.EnumProperty(name="延伸", items=CURVE_EXTEND_ITEMS, default="CLAMP")  # type: ignore
    value: bpy.props.FloatProperty(name="默认值", default=0.0)  # type: ignore
    points: bpy.props.CollectionProperty(type=OmniFloatCurvePoint)  # type: ignore

    def ensure_defaults(self):
        if len(self.points) > 0:
            return
        self.from_payload(float_curve_payload(interpolation=self.interpolation, extend=self.extend))

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

        normalized = normalize_float_points(points, interpolation=self.interpolation)
        self.points.clear()
        for point in normalized:
            _apply_float_point(self.points.add(), point)


class OmniColorCurveData(PropertyGroup):
    interpolation: bpy.props.EnumProperty(name="默认插值", items=CURVE_INTERPOLATION_ITEMS, default="LINEAR")  # type: ignore
    extend: bpy.props.EnumProperty(name="延伸", items=CURVE_EXTEND_ITEMS, default="CLAMP")  # type: ignore
    points: bpy.props.CollectionProperty(type=OmniColorCurvePoint)  # type: ignore

    def ensure_defaults(self):
        if len(self.points) > 0:
            return
        self.from_payload(color_curve_payload(interpolation=self.interpolation, extend=self.extend))

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

        normalized = normalize_color_points(points, interpolation=self.interpolation)
        self.points.clear()
        for point in normalized:
            _apply_color_point(self.points.add(), point)


curve_property_cls = [
    OmniFloatCurvePoint,
    OmniColorCurvePoint,
    OmniFloatCurveData,
    OmniColorCurveData,
]


class OmniCurveRegister:
    @staticmethod
    def register():
        try:
            for item in curve_property_cls:
                bpy.utils.register_class(item)
        except Exception:
            print(__file__ + " register failed!!!")

    @staticmethod
    def unregister():
        try:
            for item in reversed(curve_property_cls):
                bpy.utils.unregister_class(item)
        except Exception:
            print(__file__ + " unregister failed!!!")


register = OmniCurveRegister.register
unregister = OmniCurveRegister.unregister


