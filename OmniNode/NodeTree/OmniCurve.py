"""OmniNode 曲线数据与统一采样入口。"""

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
        if fallback_key not in {"AUTO", "VECTOR", "FREE"}:
            fallback_key = "AUTO"

        key = str(value or "").strip().upper()
        if key in {"AUTO", "VECTOR", "FREE"}:
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
                item = OmniCurvePointCodec.base_point_data(point, default_interpolation)
                item["left_tangent"] = OmniCurvePointCodec.color_tangent(point, "left_tangent", 0.0)
                item["right_tangent"] = OmniCurvePointCodec.color_tangent(point, "right_tangent", 0.0)
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


class OmniCurvePreset:
    identifier = ""
    name = ""
    description = ""
    supported_kinds = {"float_curve", "color_curve"}
    preserve_extend = True

    @classmethod
    def enum_item(cls):
        return (cls.identifier, cls.name, cls.description)

    @classmethod
    def payload(cls, curve_kind="float_curve", extend="CLAMP"):
        raise NotImplementedError

    @classmethod
    def preview_payload(cls, curve_kind="float_curve"):
        return cls.payload(curve_kind=curve_kind, extend="CLAMP")


class OmniCurveClearPreset(OmniCurvePreset):
    identifier = "CLEAR"
    name = "清空"
    description = "恢复这个曲线 socket 的默认值"
    preserve_extend = False

    @classmethod
    def payload(cls, curve_kind="float_curve", extend="CLAMP"):
        if curve_kind == "color_curve":
            return color_curve_payload()
        return float_curve_payload()


class OmniCurveRampUpPreset(OmniCurvePreset):
    identifier = "RAMP_0_1"
    name = "0 → 1"
    description = "从 0 线性变化到 1"

    @classmethod
    def payload(cls, curve_kind="float_curve", extend="CLAMP"):
        if curve_kind == "color_curve":
            return color_curve_payload(
                points=[
                    {"x": 0.0, "color": (0.0, 0.0, 0.0, 1.0), "interpolation": "LINEAR"},
                    {"x": 1.0, "color": (1.0, 1.0, 1.0, 1.0), "interpolation": "LINEAR"},
                ],
                interpolation="LINEAR",
                extend=extend,
            )
        return float_curve_payload(
            points=[
                {"x": 0.0, "y": 0.0, "interpolation": "LINEAR"},
                {"x": 1.0, "y": 1.0, "interpolation": "LINEAR"},
            ],
            value=0.0,
            interpolation="LINEAR",
            extend=extend,
        )


class OmniCurveRampDownPreset(OmniCurvePreset):
    identifier = "RAMP_1_0"
    name = "1 → 0"
    description = "从 1 线性变化到 0"

    @classmethod
    def payload(cls, curve_kind="float_curve", extend="CLAMP"):
        if curve_kind == "color_curve":
            return color_curve_payload(
                points=[
                    {"x": 0.0, "color": (1.0, 1.0, 1.0, 1.0), "interpolation": "LINEAR"},
                    {"x": 1.0, "color": (0.0, 0.0, 0.0, 1.0), "interpolation": "LINEAR"},
                ],
                interpolation="LINEAR",
                extend=extend,
            )
        return float_curve_payload(
            points=[
                {"x": 0.0, "y": 1.0, "interpolation": "LINEAR"},
                {"x": 1.0, "y": 0.0, "interpolation": "LINEAR"},
            ],
            value=0.0,
            interpolation="LINEAR",
            extend=extend,
        )


class OmniCurveEaseInOutPreset(OmniCurvePreset):
    identifier = "EASE_IN_OUT"
    name = "缓进缓出"
    description = "从 0 平滑变化到 1"

    @classmethod
    def payload(cls, curve_kind="float_curve", extend="CLAMP"):
        if curve_kind == "color_curve":
            return color_curve_payload(
                points=[
                    {
                        "x": 0.0,
                        "color": (0.0, 0.0, 0.0, 1.0),
                        "interpolation": "BEZIER",
                        "right_handle_type": "FREE",
                        "right_tangent": (0.0, 0.0, 0.0, 0.0),
                        "right_weight": 1.0,
                    },
                    {
                        "x": 1.0,
                        "color": (1.0, 1.0, 1.0, 1.0),
                        "interpolation": "BEZIER",
                        "left_handle_type": "FREE",
                        "left_tangent": (0.0, 0.0, 0.0, 0.0),
                        "left_weight": 1.0,
                    },
                ],
                interpolation="BEZIER",
                extend=extend,
            )
        return float_curve_payload(
            points=[
                {
                    "x": 0.0,
                    "y": 0.0,
                    "interpolation": "BEZIER",
                    "right_handle_type": "FREE",
                    "right_tangent": 0.0,
                    "right_weight": 1.0,
                },
                {
                    "x": 1.0,
                    "y": 1.0,
                    "interpolation": "BEZIER",
                    "left_handle_type": "FREE",
                    "left_tangent": 0.0,
                    "left_weight": 1.0,
                },
            ],
            value=0.0,
            interpolation="BEZIER",
            extend=extend,
        )


class OmniCurvePresetRegistry:
    _classes = []

    @classmethod
    def register(cls, preset_cls):
        if preset_cls.identifier and preset_cls not in cls._classes:
            cls._classes.append(preset_cls)

    @classmethod
    def get(cls, identifier):
        for preset_cls in cls._classes:
            if preset_cls.identifier == identifier:
                return preset_cls
        return None

    @classmethod
    def classes(cls, curve_kind=None):
        return [
            preset_cls
            for preset_cls in cls._classes
            if curve_kind is None or curve_kind in preset_cls.supported_kinds
        ]

    @classmethod
    def enum_items(cls, curve_kind=None):
        return [preset_cls.enum_item() for preset_cls in cls.classes(curve_kind)]

    @classmethod
    def enum_items_for_socket(cls, socket=None, context=None):
        curve_kind = None
        bl_idname = getattr(socket, "bl_idname", "")
        if bl_idname == "OmniNodeSocketFloatCurve":
            curve_kind = "float_curve"
        elif bl_idname == "OmniNodeSocketColorCurve":
            curve_kind = "color_curve"
        return cls.enum_items(curve_kind)

    @classmethod
    def payload(cls, identifier, curve_kind="float_curve", extend="CLAMP"):
        preset_cls = cls.get(identifier)
        if preset_cls is None:
            return None
        if curve_kind not in preset_cls.supported_kinds:
            return None
        actual_extend = extend if preset_cls.preserve_extend else "CLAMP"
        return preset_cls.payload(curve_kind=curve_kind, extend=actual_extend)

    @classmethod
    def preview_payload(cls, identifier, curve_kind="float_curve"):
        preset_cls = cls.get(identifier)
        if preset_cls is None:
            return None
        if curve_kind not in preset_cls.supported_kinds:
            return None
        return preset_cls.preview_payload(curve_kind=curve_kind)


for _preset_cls in (
    OmniCurveClearPreset,
    OmniCurveRampUpPreset,
    OmniCurveRampDownPreset,
    OmniCurveEaseInOutPreset,
):
    OmniCurvePresetRegistry.register(_preset_cls)


def curve_preset_items(socket=None, context=None):
    return OmniCurvePresetRegistry.enum_items_for_socket(socket, context)


def curve_preset_payload(identifier, curve_kind="float_curve", extend="CLAMP"):
    return OmniCurvePresetRegistry.payload(identifier, curve_kind=curve_kind, extend=extend)


def curve_preset_preview_payload(identifier, curve_kind="float_curve"):
    return OmniCurvePresetRegistry.preview_payload(identifier, curve_kind=curve_kind)


CURVE_PRESET_ITEMS = curve_preset_items()


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


class OmniColorCurvePoint(PropertyGroup):
    x: bpy.props.FloatProperty(name="位置", default=0.0, min=0.0, max=1.0)  # type: ignore
    interpolation: bpy.props.EnumProperty(name="插值", items=CURVE_INTERPOLATION_ITEMS, default="LINEAR")  # type: ignore
    left_handle_type: bpy.props.EnumProperty(name="左柄", items=CURVE_HANDLE_TYPE_ITEMS, default="AUTO")  # type: ignore
    right_handle_type: bpy.props.EnumProperty(name="右柄", items=CURVE_HANDLE_TYPE_ITEMS, default="AUTO")  # type: ignore
    left_tangent: bpy.props.FloatVectorProperty(name="左切线", default=(0.0, 0.0, 0.0, 0.0), size=4)  # type: ignore
    right_tangent: bpy.props.FloatVectorProperty(name="右切线", default=(0.0, 0.0, 0.0, 0.0), size=4)  # type: ignore
    left_weight: bpy.props.FloatProperty(name="左权重", default=1.0, min=0.0)  # type: ignore
    right_weight: bpy.props.FloatProperty(name="右权重", default=1.0, min=0.0)  # type: ignore
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


class OmniCurveSampler:
    @staticmethod
    def find_segment(points, x):
        point_index = 0
        while point_index + 1 < len(points) and points[point_index + 1]["x"] <= x:
            point_index += 1
        left = points[point_index]
        right = points[min(point_index + 1, len(points) - 1)]
        return point_index, left, right

    @staticmethod
    def safe_slope(delta, dx) -> float:
        if dx == 0.0:
            return 0.0
        return float(delta) / float(dx)

    @staticmethod
    def hermite(v0, v1, m0, m1, t) -> float:
        t2 = t * t
        t3 = t2 * t
        return (
            (2.0 * t3 - 3.0 * t2 + 1.0) * v0
            + (t3 - 2.0 * t2 + t) * m0
            + (-2.0 * t3 + 3.0 * t2) * v1
            + (t3 - t2) * m1
        )

    @staticmethod
    def float_slope(points, left_index, right_index) -> float:
        left = points[left_index]
        right = points[right_index]
        return OmniCurveSampler.safe_slope(right["y"] - left["y"], right["x"] - left["x"])

    @staticmethod
    def float_auto_tangent(points, index) -> float:
        left_index = max(0, index - 1)
        right_index = min(len(points) - 1, index + 1)
        if left_index == right_index:
            return 0.0
        return OmniCurveSampler.float_slope(points, left_index, right_index)

    @staticmethod
    def float_out_tangent(points, index, left, right) -> float:
        handle_type = coerce_handle_type(left.get("right_handle_type", "AUTO"))
        if handle_type == "FREE":
            return float(left.get("right_tangent", 0.0))
        if handle_type == "AUTO":
            return OmniCurveSampler.float_auto_tangent(points, index)
        return OmniCurveSampler.safe_slope(right["y"] - left["y"], right["x"] - left["x"])

    @staticmethod
    def float_in_tangent(points, index, left, right) -> float:
        handle_type = coerce_handle_type(right.get("left_handle_type", "AUTO"))
        if handle_type == "FREE":
            return float(right.get("left_tangent", 0.0))
        if handle_type == "AUTO":
            return OmniCurveSampler.float_auto_tangent(points, index)
        return OmniCurveSampler.safe_slope(right["y"] - left["y"], right["x"] - left["x"])

    @staticmethod
    def color_slope(points, left_index, right_index, channel) -> float:
        left = points[left_index]
        right = points[right_index]
        return OmniCurveSampler.safe_slope(right["color"][channel] - left["color"][channel], right["x"] - left["x"])

    @staticmethod
    def color_auto_tangent(points, index, channel) -> float:
        left_index = max(0, index - 1)
        right_index = min(len(points) - 1, index + 1)
        if left_index == right_index:
            return 0.0
        return OmniCurveSampler.color_slope(points, left_index, right_index, channel)

    @staticmethod
    def color_out_tangent(points, index, left, right, channel) -> float:
        handle_type = coerce_handle_type(left.get("right_handle_type", "AUTO"))
        if handle_type == "FREE":
            return float(left.get("right_tangent", (0.0, 0.0, 0.0, 0.0))[channel])
        if handle_type == "AUTO":
            return OmniCurveSampler.color_auto_tangent(points, index, channel)
        return OmniCurveSampler.safe_slope(right["color"][channel] - left["color"][channel], right["x"] - left["x"])

    @staticmethod
    def color_in_tangent(points, index, left, right, channel) -> float:
        handle_type = coerce_handle_type(right.get("left_handle_type", "AUTO"))
        if handle_type == "FREE":
            return float(right.get("left_tangent", (0.0, 0.0, 0.0, 0.0))[channel])
        if handle_type == "AUTO":
            return OmniCurveSampler.color_auto_tangent(points, index, channel)
        return OmniCurveSampler.safe_slope(right["color"][channel] - left["color"][channel], right["x"] - left["x"])


_find_segment = OmniCurveSampler.find_segment
_safe_slope = OmniCurveSampler.safe_slope
_hermite = OmniCurveSampler.hermite
_float_slope = OmniCurveSampler.float_slope
_float_auto_tangent = OmniCurveSampler.float_auto_tangent
_float_out_tangent = OmniCurveSampler.float_out_tangent
_float_in_tangent = OmniCurveSampler.float_in_tangent
_color_slope = OmniCurveSampler.color_slope
_color_auto_tangent = OmniCurveSampler.color_auto_tangent
_color_out_tangent = OmniCurveSampler.color_out_tangent
_color_in_tangent = OmniCurveSampler.color_in_tangent


class OmniFloatCurveValue:
    def __init__(self, points=None, value=0.0, interpolation="LINEAR", extend="CLAMP"):
        self.value = float(value)
        self.interpolation = coerce_interpolation(interpolation)
        self.points = normalize_float_points(points, interpolation=self.interpolation)
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

    def segment_interpolation(self, index) -> str:
        if index < 0 or index >= len(self.points) - 1:
            return self.interpolation
        return point_interpolation(self.points[index], self.interpolation)

    def segment_handles(self, index):
        if index < 0 or index >= len(self.points) - 1:
            return None
        left = self.points[index]
        right = self.points[index + 1]
        dx = right["x"] - left["x"]
        if self.segment_interpolation(index) != "BEZIER" or dx <= 0.0:
            return None

        out_tangent = _float_out_tangent(self.points, index, left, right)
        in_tangent = _float_in_tangent(self.points, index + 1, left, right)
        right_weight = float(left.get("right_weight", 1.0))
        left_weight = float(right.get("left_weight", 1.0))
        return (
            {
                "x": left["x"] + dx * right_weight / 3.0,
                "y": left["y"] + out_tangent * dx * right_weight / 3.0,
            },
            {
                "x": right["x"] - dx * left_weight / 3.0,
                "y": right["y"] - in_tangent * dx * left_weight / 3.0,
            },
        )

    def sample(self, position, extend=None) -> float:
        x = extend_position(position, self.extend if use_curve_extend(extend) else extend)
        points = self.points
        if x <= points[0]["x"]:
            return float(points[0]["y"])
        if x >= points[-1]["x"]:
            return float(points[-1]["y"])

        point_index, left, right = _find_segment(points, x)
        dx = right["x"] - left["x"]
        segment_interpolation = point_interpolation(left, self.interpolation)
        if segment_interpolation == "CONSTANT" or dx <= 0.0:
            return float(left["y"])

        factor = (x - left["x"]) / dx
        if segment_interpolation == "BEZIER":
            out_tangent = _float_out_tangent(points, point_index, left, right)
            in_tangent = _float_in_tangent(points, point_index + 1, left, right)
            m0 = out_tangent * dx * float(left.get("right_weight", 1.0))
            m1 = in_tangent * dx * float(right.get("left_weight", 1.0))
            return float(_hermite(left["y"], right["y"], m0, m1, factor))

        return float(left["y"] * (1.0 - factor) + right["y"] * factor)

    def sample_many(self, count, extend=None) -> list[float]:
        count = max(1, int(count))
        if count == 1:
            return [self.sample(0.0, extend=extend)]
        return [self.sample(index / float(count - 1), extend=extend) for index in range(count)]


class OmniColorCurveValue:
    def __init__(self, points=None, interpolation="LINEAR", extend="CLAMP"):
        self.interpolation = coerce_interpolation(interpolation)
        self.points = normalize_color_points(points, interpolation=self.interpolation)
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

    def segment_interpolation(self, index) -> str:
        if index < 0 or index >= len(self.points) - 1:
            return self.interpolation
        return point_interpolation(self.points[index], self.interpolation)

    def segment_handles(self, index, channel):
        if index < 0 or index >= len(self.points) - 1:
            return None
        left = self.points[index]
        right = self.points[index + 1]
        dx = right["x"] - left["x"]
        if self.segment_interpolation(index) != "BEZIER" or dx <= 0.0:
            return None

        out_tangent = _color_out_tangent(self.points, index, left, right, channel)
        in_tangent = _color_in_tangent(self.points, index + 1, left, right, channel)
        right_weight = float(left.get("right_weight", 1.0))
        left_weight = float(right.get("left_weight", 1.0))
        return (
            {
                "x": left["x"] + dx * right_weight / 3.0,
                "y": left["color"][channel] + out_tangent * dx * right_weight / 3.0,
            },
            {
                "x": right["x"] - dx * left_weight / 3.0,
                "y": right["color"][channel] - in_tangent * dx * left_weight / 3.0,
            },
        )

    def sample(self, position, extend=None) -> tuple[float, float, float, float]:
        x = extend_position(position, self.extend if use_curve_extend(extend) else extend)
        points = self.points
        if x <= points[0]["x"]:
            return tuple(points[0]["color"])
        if x >= points[-1]["x"]:
            return tuple(points[-1]["color"])

        point_index, left, right = _find_segment(points, x)
        dx = right["x"] - left["x"]
        segment_interpolation = point_interpolation(left, self.interpolation)
        if segment_interpolation == "CONSTANT" or dx <= 0.0:
            return tuple(left["color"])

        factor = (x - left["x"]) / dx
        if segment_interpolation == "BEZIER":
            values = []
            for channel in range(4):
                out_tangent = _color_out_tangent(points, point_index, left, right, channel)
                in_tangent = _color_in_tangent(points, point_index + 1, left, right, channel)
                m0 = out_tangent * dx * float(left.get("right_weight", 1.0))
                m1 = in_tangent * dx * float(right.get("left_weight", 1.0))
                values.append(_hermite(left["color"][channel], right["color"][channel], m0, m1, factor))
            return tuple(float(value) for value in values)

        return tuple(
            float(left["color"][channel] * (1.0 - factor) + right["color"][channel] * factor)
            for channel in range(4)
        )

    def sample_many(self, count, extend=None) -> list[tuple[float, float, float, float]]:
        count = max(1, int(count))
        if count == 1:
            return [self.sample(0.0, extend=extend)]
        return [self.sample(index / float(count - 1), extend=extend) for index in range(count)]


class OmniCurveResolver:
    @staticmethod
    def float_curve(value) -> OmniFloatCurveValue:
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

    @staticmethod
    def color_curve(value) -> OmniColorCurveValue:
        if isinstance(value, OmniColorCurveValue):
            return value
        if isinstance(value, dict):
            return OmniColorCurveValue(
                value.get("points"),
                interpolation=value.get("interpolation", "LINEAR"),
                extend=value.get("extend", "CLAMP"),
            )
        return OmniColorCurveValue(value)


resolve_float_curve = OmniCurveResolver.float_curve
resolve_color_curve = OmniCurveResolver.color_curve
