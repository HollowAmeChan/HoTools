"""PropertyCurve 曲线预设。"""

from __future__ import annotations

import math

from .definitions import OmniCurveCoerce, color_curve_payload, float_curve_payload


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


class OmniCurvePresetFactory:
    DERIVATIVE_EPSILON = 0.0001
    DERIVATIVE_LIMIT = 12.0

    @staticmethod
    def supported_kinds(support_color_curve=True, curve_kinds=None):
        if curve_kinds is not None:
            return set(curve_kinds)
        return {"float_curve", "color_curve"} if support_color_curve else {"float_curve"}

    @staticmethod
    def float_point(
        x,
        y,
        tangent=None,
        left_tangent=None,
        right_tangent=None,
        left_weight=1.0,
        right_weight=1.0,
        left_handle=None,
        right_handle=None,
        left_handle_x=0.0,
        left_handle_y=0.0,
        right_handle_x=0.0,
        right_handle_y=0.0,
        interpolation="BEZIER",
    ) -> dict:
        tangent = 0.0 if tangent is None else float(tangent)
        if left_tangent is None:
            left_tangent = tangent
        if right_tangent is None:
            right_tangent = tangent
        if left_handle is not None:
            left_handle_x = float(left_handle[0]) - float(x)
            left_handle_y = float(left_handle[1]) - float(y)
        if right_handle is not None:
            right_handle_x = float(right_handle[0]) - float(x)
            right_handle_y = float(right_handle[1]) - float(y)
        left_handle_x = float(left_handle_x)
        left_handle_y = float(left_handle_y)
        right_handle_x = float(right_handle_x)
        right_handle_y = float(right_handle_y)
        left_handle_type = "COORD" if left_handle is not None or left_handle_x != 0.0 or left_handle_y != 0.0 else "FREE"
        right_handle_type = "COORD" if right_handle is not None or right_handle_x != 0.0 or right_handle_y != 0.0 else "FREE"
        return {
            "x": float(x),
            "y": float(y),
            "interpolation": interpolation,
            "left_handle_type": left_handle_type,
            "right_handle_type": right_handle_type,
            "left_tangent": float(left_tangent),
            "right_tangent": float(right_tangent),
            "left_weight": float(left_weight),
            "right_weight": float(right_weight),
            "left_handle_x": left_handle_x,
            "left_handle_y": left_handle_y,
            "right_handle_x": right_handle_x,
            "right_handle_y": right_handle_y,
        }

    @staticmethod
    def bezier_points_payload(x1, y1, x2, y2, extend="CLAMP"):
        return float_curve_payload(
            points=[
                OmniCurvePresetFactory.float_point(
                    0.0,
                    0.0,
                    right_handle=(float(x1), float(y1)),
                    interpolation="BEZIER",
                ),
                OmniCurvePresetFactory.float_point(
                    1.0,
                    1.0,
                    left_handle=(float(x2), float(y2)),
                    interpolation="BEZIER",
                ),
            ],
            interpolation="BEZIER",
            extend=extend,
        )

    @staticmethod
    def make_bezier_payload(x1, y1, x2, y2):
        def payload(curve_kind="float_curve", extend="CLAMP"):
            return OmniCurvePresetFactory.bezier_points_payload(x1, y1, x2, y2, extend=extend)
        return payload

    @staticmethod
    def _function_value(func, x) -> float:
        return float(func(OmniCurveCoerce.clamp_float(x, 0.0, 1.0)))

    @staticmethod
    def _function_slope(func, x) -> float:
        epsilon = OmniCurvePresetFactory.DERIVATIVE_EPSILON
        left = max(0.0, float(x) - epsilon)
        right = min(1.0, float(x) + epsilon)
        if right <= left:
            return 0.0
        return (
            OmniCurvePresetFactory._function_value(func, right)
            - OmniCurvePresetFactory._function_value(func, left)
        ) / (right - left)

    @staticmethod
    def _limited_slope(func, x) -> float:
        return OmniCurveCoerce.clamp_float(
            OmniCurvePresetFactory._function_slope(func, x),
            -OmniCurvePresetFactory.DERIVATIVE_LIMIT,
            OmniCurvePresetFactory.DERIVATIVE_LIMIT,
        )

    @staticmethod
    def _function_positions(samples=6, positions=None) -> list[float]:
        if positions is None:
            count = max(2, min(6, int(samples)))
            return [index / float(count - 1) for index in range(count)]

        result = []
        for value in positions:
            x = OmniCurveCoerce.clamp_float(value, 0.0, 1.0)
            if not any(abs(x - existing) <= 0.000001 for existing in result):
                result.append(x)
        result.append(0.0)
        result.append(1.0)
        result = sorted(result)
        unique = []
        for x in result:
            if not unique or abs(x - unique[-1]) > 0.000001:
                unique.append(x)
        if len(unique) > 6:
            unique = unique[:5] + [unique[-1]]
        return unique

    @staticmethod
    def function_points_payload(func, samples=6, positions=None, extend="CLAMP"):
        positions = OmniCurvePresetFactory._function_positions(samples=samples, positions=positions)
        last_index = len(positions) - 1
        points = []
        for index, x in enumerate(positions):
            y = OmniCurvePresetFactory._function_value(func, x)
            slope = OmniCurvePresetFactory._limited_slope(func, x)
            point_spec = {
                "x": x,
                "y": y,
                "interpolation": "BEZIER",
            }
            if index > 0:
                previous_x = positions[index - 1]
                left_x = x - (x - previous_x) / 3.0
                point_spec["left_handle"] = (left_x, y - slope * (x - left_x))
            if index < last_index:
                next_x = positions[index + 1]
                right_x = x + (next_x - x) / 3.0
                point_spec["right_handle"] = (right_x, y + slope * (right_x - x))
            points.append(OmniCurvePresetFactory.float_point(**point_spec))
        return float_curve_payload(
            points=points,
            interpolation="BEZIER",
            extend=extend,
        )

    @staticmethod
    def make_function_payload(func, samples=6, positions=None):
        def payload(curve_kind="float_curve", extend="CLAMP"):
            return OmniCurvePresetFactory.function_points_payload(
                func,
                samples=samples,
                positions=positions,
                extend=extend,
            )
        return payload

    @staticmethod
    def float_points_payload(point_specs, extend="CLAMP"):
        points = []
        for spec in point_specs:
            if isinstance(spec, dict):
                points.append(OmniCurvePresetFactory.float_point(**spec))
            else:
                x, y, tangent = spec[:3]
                points.append(OmniCurvePresetFactory.float_point(x, y, tangent))
        return float_curve_payload(
            points=points,
            interpolation="BEZIER",
            extend=extend,
        )

    @staticmethod
    def make_float_points_payload(point_specs):
        def payload(curve_kind="float_curve", extend="CLAMP"):
            return OmniCurvePresetFactory.float_points_payload(point_specs, extend=extend)
        return payload

    @staticmethod
    def clear_payload(curve_kind="float_curve", extend="CLAMP"):
        if curve_kind == "color_curve":
            return color_curve_payload()
        return float_curve_payload()

    @staticmethod
    def linear_payload(curve_kind="float_curve", extend="CLAMP"):
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

    @staticmethod
    def reverse_linear_payload(curve_kind="float_curve", extend="CLAMP"):
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

    @staticmethod
    def ease_in_out_payload(curve_kind="float_curve", extend="CLAMP"):
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
        return OmniCurvePresetFactory.bezier_points_payload(0.42, 0.0, 0.58, 1.0, extend=extend)

    @staticmethod
    def make_fixed_preset(
        identifier,
        name,
        description,
        payload_func,
        support_color_curve=True,
        preserve_extend=True,
        curve_kinds=None,
    ):
        supported_kinds = OmniCurvePresetFactory.supported_kinds(
            support_color_curve=support_color_curve,
            curve_kinds=curve_kinds,
        )

        def payload(cls, curve_kind="float_curve", extend="CLAMP"):
            return payload_func(curve_kind=curve_kind, extend=extend)

        return type(
            f"OmniCurvePreset_{identifier}",
            (OmniCurvePreset,),
            {
                "__module__": __name__,
                "identifier": identifier,
                "name": name,
                "description": description,
                "supported_kinds": supported_kinds,
                "preserve_extend": bool(preserve_extend),
                "payload": classmethod(payload),
            },
        )

    @staticmethod
    def make_float_bezier_preset(identifier, name, description, x1, y1, x2, y2):
        return OmniCurvePresetFactory.make_fixed_preset(
            identifier,
            name,
            description,
            OmniCurvePresetFactory.make_bezier_payload(x1, y1, x2, y2),
            curve_kinds={"float_curve"},
        )

    @staticmethod
    def make_float_function_preset(identifier, name, description, func, samples=6, positions=None):
        return OmniCurvePresetFactory.make_fixed_preset(
            identifier,
            name,
            description,
            OmniCurvePresetFactory.make_function_payload(func, samples=samples, positions=positions),
            curve_kinds={"float_curve"},
        )

    @staticmethod
    def make_float_points_preset(identifier, name, description, point_specs):
        return OmniCurvePresetFactory.make_fixed_preset(
            identifier,
            name,
            description,
            OmniCurvePresetFactory.make_float_points_payload(point_specs),
            curve_kinds={"float_curve"},
        )


class OmniCurveEaseFunctions:
    @staticmethod
    def sine_in(x):
        return 1.0 - math.cos((x * math.pi) * 0.5)

    @staticmethod
    def sine_out(x):
        return math.sin((x * math.pi) * 0.5)

    @staticmethod
    def sine_in_out(x):
        return -(math.cos(math.pi * x) - 1.0) * 0.5

    @staticmethod
    def quad_in(x):
        return x * x

    @staticmethod
    def quad_out(x):
        return 1.0 - (1.0 - x) * (1.0 - x)

    @staticmethod
    def quad_in_out(x):
        if x < 0.5:
            return 2.0 * x * x
        return 1.0 - pow(-2.0 * x + 2.0, 2.0) * 0.5

    @staticmethod
    def cubic_in(x):
        return x * x * x

    @staticmethod
    def cubic_out(x):
        return 1.0 - pow(1.0 - x, 3.0)

    @staticmethod
    def cubic_in_out(x):
        if x < 0.5:
            return 4.0 * x * x * x
        return 1.0 - pow(-2.0 * x + 2.0, 3.0) * 0.5

    @staticmethod
    def quart_in(x):
        return x * x * x * x

    @staticmethod
    def quart_out(x):
        return 1.0 - pow(1.0 - x, 4.0)

    @staticmethod
    def quart_in_out(x):
        if x < 0.5:
            return 8.0 * x * x * x * x
        return 1.0 - pow(-2.0 * x + 2.0, 4.0) * 0.5

    @staticmethod
    def quint_in(x):
        return x * x * x * x * x

    @staticmethod
    def quint_out(x):
        return 1.0 - pow(1.0 - x, 5.0)

    @staticmethod
    def quint_in_out(x):
        if x < 0.5:
            return 16.0 * x * x * x * x * x
        return 1.0 - pow(-2.0 * x + 2.0, 5.0) * 0.5

    @staticmethod
    def expo_in(x):
        if x <= 0.0:
            return 0.0
        return pow(2.0, 10.0 * x - 10.0)

    @staticmethod
    def expo_out(x):
        if x >= 1.0:
            return 1.0
        return 1.0 - pow(2.0, -10.0 * x)

    @staticmethod
    def expo_in_out(x):
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        if x < 0.5:
            return pow(2.0, 20.0 * x - 10.0) * 0.5
        return (2.0 - pow(2.0, -20.0 * x + 10.0)) * 0.5

    @staticmethod
    def circ_in(x):
        return 1.0 - math.sqrt(max(0.0, 1.0 - x * x))

    @staticmethod
    def circ_out(x):
        value = x - 1.0
        return math.sqrt(max(0.0, 1.0 - value * value))

    @staticmethod
    def circ_in_out(x):
        if x < 0.5:
            return (1.0 - math.sqrt(max(0.0, 1.0 - pow(2.0 * x, 2.0)))) * 0.5
        return (math.sqrt(max(0.0, 1.0 - pow(-2.0 * x + 2.0, 2.0))) + 1.0) * 0.5

    @staticmethod
    def smoothstep(x):
        return x * x * (3.0 - 2.0 * x)

    @staticmethod
    def smootherstep(x):
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


class OmniCurveMotionPresetSpecs:
    POP = [
        {"x": 0.0, "y": 0.0, "right_handle": (0.16, 0.0)},
        {"x": 0.48, "y": 1.18, "left_handle": (0.34, 1.18), "right_handle": (0.58, 1.18)},
        {"x": 0.74, "y": 0.94, "left_handle": (0.66, 0.94), "right_handle": (0.82, 0.94)},
        {"x": 1.0, "y": 1.0, "left_handle": (0.92, 1.0)},
    ]

    SETTLE = [
        {"x": 0.0, "y": 0.0, "right_handle": (0.18, 0.0)},
        {"x": 0.42, "y": 1.08, "left_handle": (0.28, 1.08), "right_handle": (0.54, 1.08)},
        {"x": 0.68, "y": 0.98, "left_handle": (0.60, 0.98), "right_handle": (0.76, 0.98)},
        {"x": 1.0, "y": 1.0, "left_handle": (0.90, 1.0)},
    ]

    PUNCH = [
        {"x": 0.0, "y": 0.0, "right_handle": (0.10, 0.0)},
        {"x": 0.25, "y": 1.24, "left_handle": (0.17, 1.24), "right_handle": (0.34, 1.24)},
        {"x": 0.52, "y": 0.86, "left_handle": (0.42, 0.86), "right_handle": (0.62, 0.86)},
        {"x": 0.78, "y": 1.04, "left_handle": (0.70, 1.04), "right_handle": (0.86, 1.04)},
        {"x": 1.0, "y": 1.0, "left_handle": (0.94, 1.0)},
    ]

    BOUNCE_OUT = [
        {"x": 0.0, "y": 0.0, "right_handle": (0.12, 0.0)},
        {"x": 0.36, "y": 1.0, "left_handle": (0.26, 1.0), "right_handle": (0.43, 1.0)},
        {"x": 0.55, "y": 0.74, "left_handle": (0.49, 0.74), "right_handle": (0.62, 0.74)},
        {"x": 0.72, "y": 1.0, "left_handle": (0.66, 1.0), "right_handle": (0.78, 1.0)},
        {"x": 0.86, "y": 0.92, "left_handle": (0.81, 0.92), "right_handle": (0.92, 0.92)},
        {"x": 1.0, "y": 1.0, "left_handle": (0.96, 1.0)},
    ]

    ELASTIC_OUT = [
        {"x": 0.0, "y": 0.0, "right_handle": (0.08, 0.0)},
        {"x": 0.18, "y": 1.22, "left_handle": (0.12, 1.22), "right_handle": (0.25, 1.22)},
        {"x": 0.36, "y": 0.88, "left_handle": (0.30, 0.88), "right_handle": (0.43, 0.88)},
        {"x": 0.56, "y": 1.06, "left_handle": (0.49, 1.06), "right_handle": (0.64, 1.06)},
        {"x": 0.78, "y": 0.99, "left_handle": (0.70, 0.99), "right_handle": (0.88, 0.99)},
        {"x": 1.0, "y": 1.0, "left_handle": (0.94, 1.0)},
    ]

    ELASTIC_IN_OUT = [
        {"x": 0.0, "y": 0.0, "right_handle": (0.08, 0.0)},
        {"x": 0.20, "y": -0.08, "left_handle": (0.14, -0.08), "right_handle": (0.28, -0.08)},
        {"x": 0.40, "y": 0.58, "left_handle": (0.32, 0.58), "right_handle": (0.48, 0.58)},
        {"x": 0.60, "y": 1.12, "left_handle": (0.52, 1.12), "right_handle": (0.68, 1.12)},
        {"x": 0.82, "y": 0.98, "left_handle": (0.74, 0.98), "right_handle": (0.90, 0.98)},
        {"x": 1.0, "y": 1.0, "left_handle": (0.94, 1.0)},
    ]

FLOAT_CURVE_PRESET_CLASSES = [
    OmniCurvePresetFactory.make_fixed_preset(
        "CLEAR",
        "清空",
        "恢复这个曲线 socket 的默认值",
        OmniCurvePresetFactory.clear_payload,
        preserve_extend=False,
        curve_kinds={"float_curve"},
    ),
    OmniCurvePresetFactory.make_fixed_preset(
        "RAMP_0_1",
        "0 → 1",
        "从 0 线性变化到 1",
        OmniCurvePresetFactory.linear_payload,
        curve_kinds={"float_curve"},
    ),
    OmniCurvePresetFactory.make_fixed_preset(
        "RAMP_1_0",
        "1 → 0",
        "从 1 线性变化到 0",
        OmniCurvePresetFactory.reverse_linear_payload,
        curve_kinds={"float_curve"},
    ),
    OmniCurvePresetFactory.make_fixed_preset(
        "EASE_IN_OUT",
        "缓进缓出",
        "从 0 平滑变化到 1",
        OmniCurvePresetFactory.ease_in_out_payload,
        curve_kinds={"float_curve"},
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "CSS_EASE",
        "CSS Ease",
        "CSS 默认 ease 曲线",
        0.25, 0.1, 0.25, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "CSS_EASE_IN",
        "CSS Ease In",
        "CSS ease-in 曲线",
        0.42, 0.0, 1.0, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "CSS_EASE_OUT",
        "CSS Ease Out",
        "CSS ease-out 曲线",
        0.0, 0.0, 0.58, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "CSS_EASE_IN_OUT",
        "CSS Ease In Out",
        "CSS ease-in-out 曲线",
        0.42, 0.0, 0.58, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "MATERIAL_STANDARD",
        "Material 标准",
        "Material Design 标准曲线",
        0.4, 0.0, 0.2, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "MATERIAL_ACCELERATE",
        "Material 加速",
        "Material Design 加速曲线",
        0.4, 0.0, 1.0, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "MATERIAL_DECELERATE",
        "Material 减速",
        "Material Design 减速曲线",
        0.0, 0.0, 0.2, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "MATERIAL_SHARP",
        "Material 锐利",
        "Material Design 锐利曲线",
        0.4, 0.0, 0.6, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "FLOW_SNAPPY",
        "Snappy",
        "快速进入并柔和落位",
        0.22, 1.0, 0.36, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "FLOW_SOFT",
        "Soft",
        "柔和的通用缓动",
        0.25, 0.1, 0.35, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "FLOW_SMOOTH",
        "Smooth",
        "平滑稳定的动效曲线",
        0.37, 0.0, 0.63, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "OVERSHOOT",
        "Overshoot",
        "越过目标后回落",
        0.34, 1.56, 0.64, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "ANTICIPATE",
        "Anticipate",
        "先反向再进入",
        0.36, 0.0, 0.66, -0.56,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "BACK_IN",
        "Back In",
        "先回撤再加速进入",
        0.36, 0.0, 0.66, -0.56,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "BACK_OUT",
        "Back Out",
        "越过目标后回收",
        0.34, 1.56, 0.64, 1.0,
    ),
    OmniCurvePresetFactory.make_float_bezier_preset(
        "BACK_IN_OUT",
        "Back In Out",
        "两端都有回撤感",
        0.68, -0.60, 0.32, 1.60,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "SINE_IN",
        "Sine In",
        "正弦加速",
        OmniCurveEaseFunctions.sine_in,
        samples=4,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "SINE_OUT",
        "Sine Out",
        "正弦减速",
        OmniCurveEaseFunctions.sine_out,
        samples=4,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "SINE_IN_OUT",
        "Sine In Out",
        "正弦缓进缓出",
        OmniCurveEaseFunctions.sine_in_out,
        samples=5,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUAD_IN",
        "Quad In",
        "二次方加速",
        OmniCurveEaseFunctions.quad_in,
        samples=3,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUAD_OUT",
        "Quad Out",
        "二次方减速",
        OmniCurveEaseFunctions.quad_out,
        samples=3,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUAD_IN_OUT",
        "Quad In Out",
        "二次方缓进缓出",
        OmniCurveEaseFunctions.quad_in_out,
        samples=5,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "CUBIC_IN",
        "Cubic In",
        "三次方加速",
        OmniCurveEaseFunctions.cubic_in,
        samples=4,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "CUBIC_OUT",
        "Cubic Out",
        "三次方减速",
        OmniCurveEaseFunctions.cubic_out,
        samples=4,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "CUBIC_IN_OUT",
        "Cubic In Out",
        "三次方缓进缓出",
        OmniCurveEaseFunctions.cubic_in_out,
        samples=5,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUART_IN",
        "Quart In",
        "四次方加速",
        OmniCurveEaseFunctions.quart_in,
        samples=5,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUART_OUT",
        "Quart Out",
        "四次方减速",
        OmniCurveEaseFunctions.quart_out,
        samples=5,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUART_IN_OUT",
        "Quart In Out",
        "四次方缓进缓出",
        OmniCurveEaseFunctions.quart_in_out,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUINT_IN",
        "Quint In",
        "五次方加速",
        OmniCurveEaseFunctions.quint_in,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUINT_OUT",
        "Quint Out",
        "五次方减速",
        OmniCurveEaseFunctions.quint_out,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "QUINT_IN_OUT",
        "Quint In Out",
        "五次方缓进缓出",
        OmniCurveEaseFunctions.quint_in_out,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "EXPO_IN",
        "Expo In",
        "指数加速",
        OmniCurveEaseFunctions.expo_in,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "EXPO_OUT",
        "Expo Out",
        "指数减速",
        OmniCurveEaseFunctions.expo_out,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "EXPO_IN_OUT",
        "Expo In Out",
        "指数缓进缓出",
        OmniCurveEaseFunctions.expo_in_out,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "CIRC_IN",
        "Circ In",
        "圆形加速",
        OmniCurveEaseFunctions.circ_in,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "CIRC_OUT",
        "Circ Out",
        "圆形减速",
        OmniCurveEaseFunctions.circ_out,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "CIRC_IN_OUT",
        "Circ In Out",
        "圆形缓进缓出",
        OmniCurveEaseFunctions.circ_in_out,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "SMOOTHSTEP",
        "Smoothstep",
        "平滑阶跃",
        OmniCurveEaseFunctions.smoothstep,
        samples=4,
    ),
    OmniCurvePresetFactory.make_float_function_preset(
        "SMOOTHERSTEP",
        "Smootherstep",
        "更平滑的阶跃",
        OmniCurveEaseFunctions.smootherstep,
        samples=6,
    ),
    OmniCurvePresetFactory.make_float_points_preset(
        "POP",
        "Pop",
        "快速越界后回落",
        OmniCurveMotionPresetSpecs.POP,
    ),
    OmniCurvePresetFactory.make_float_points_preset(
        "SETTLE",
        "Settle",
        "轻微越界后稳定",
        OmniCurveMotionPresetSpecs.SETTLE,
    ),
    OmniCurvePresetFactory.make_float_points_preset(
        "PUNCH",
        "Punch",
        "强冲击后多次收敛",
        OmniCurveMotionPresetSpecs.PUNCH,
    ),
    OmniCurvePresetFactory.make_float_points_preset(
        "BOUNCE_OUT",
        "Bounce Out",
        "落地回弹近似",
        OmniCurveMotionPresetSpecs.BOUNCE_OUT,
    ),
    OmniCurvePresetFactory.make_float_points_preset(
        "ELASTIC_OUT",
        "Elastic Out",
        "弹性减速近似",
        OmniCurveMotionPresetSpecs.ELASTIC_OUT,
    ),
    OmniCurvePresetFactory.make_float_points_preset(
        "ELASTIC_IN_OUT",
        "Elastic In Out",
        "双端弹性近似",
        OmniCurveMotionPresetSpecs.ELASTIC_IN_OUT,
    ),
]

RGB_CURVE_PRESET_CLASSES = []

CURVE_PRESET_CLASSES = [
    *FLOAT_CURVE_PRESET_CLASSES,
    *RGB_CURVE_PRESET_CLASSES,
]


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


PropertyCurvePresetRegistry = OmniCurvePresetRegistry


for _preset_cls in (
    *CURVE_PRESET_CLASSES,
):
    PropertyCurvePresetRegistry.register(_preset_cls)


def curve_preset_items(socket=None, context=None):
    return PropertyCurvePresetRegistry.enum_items_for_socket(socket, context)


def curve_preset_payload(identifier, curve_kind="float_curve", extend="CLAMP"):
    return PropertyCurvePresetRegistry.payload(identifier, curve_kind=curve_kind, extend=extend)


def curve_preset_preview_payload(identifier, curve_kind="float_curve"):
    return PropertyCurvePresetRegistry.preview_payload(identifier, curve_kind=curve_kind)


CURVE_PRESET_ITEMS = curve_preset_items()


