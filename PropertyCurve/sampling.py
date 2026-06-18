"""PropertyCurve ???????????"""

from __future__ import annotations

from .definitions import (
    OmniCurveCoerce,
    coerce_color,
    coerce_extend,
    coerce_handle_type,
    coerce_interpolation,
    color_curve_payload,
    extend_position,
    float_curve_payload,
    normalize_color_points,
    normalize_float_points,
    point_interpolation,
    use_curve_extend,
)


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
    def cubic(v0, v1, v2, v3, t) -> float:
        u = 1.0 - t
        return (
            u * u * u * v0
            + 3.0 * u * u * t * v1
            + 3.0 * u * t * t * v2
            + t * t * t * v3
        )

    @staticmethod
    def cubic_derivative(v0, v1, v2, v3, t) -> float:
        u = 1.0 - t
        return (
            3.0 * u * u * (v1 - v0)
            + 6.0 * u * t * (v2 - v1)
            + 3.0 * t * t * (v3 - v2)
        )

    @staticmethod
    def solve_cubic_x(x0, x1, x2, x3, x) -> float:
        if abs(x3 - x0) < 0.000001:
            return 0.0

        t = OmniCurveCoerce.clamp_float((x - x0) / (x3 - x0), 0.0, 1.0)
        for _index in range(8):
            value = OmniCurveSampler.cubic(x0, x1, x2, x3, t) - x
            derivative = OmniCurveSampler.cubic_derivative(x0, x1, x2, x3, t)
            if abs(derivative) < 0.000001:
                break
            next_t = t - value / derivative
            if next_t < 0.0 or next_t > 1.0:
                break
            t = next_t

        low = 0.0
        high = 1.0
        for _index in range(24):
            value = OmniCurveSampler.cubic(x0, x1, x2, x3, t)
            if abs(value - x) < 0.000001:
                return OmniCurveCoerce.clamp_float(t, 0.0, 1.0)
            if value < x:
                low = t
            else:
                high = t
            t = (low + high) * 0.5
        return OmniCurveCoerce.clamp_float(t, 0.0, 1.0)

    @staticmethod
    def has_coord_handles(left, right) -> bool:
        return (
            coerce_handle_type(left.get("right_handle_type", "AUTO")) == "COORD"
            or coerce_handle_type(right.get("left_handle_type", "AUTO")) == "COORD"
        )

    @staticmethod
    def float_coord_handles(left, right):
        return (
            {
                "x": float(left["x"]) + float(left.get("right_handle_x", 0.0)),
                "y": float(left["y"]) + float(left.get("right_handle_y", 0.0)),
            },
            {
                "x": float(right["x"]) + float(right.get("left_handle_x", 0.0)),
                "y": float(right["y"]) + float(right.get("left_handle_y", 0.0)),
            },
        )

    @staticmethod
    def color_coord_handles(left, right, channel):
        left_handle_y = left.get("right_handle_y", (0.0, 0.0, 0.0, 0.0))
        right_handle_y = right.get("left_handle_y", (0.0, 0.0, 0.0, 0.0))
        return (
            {
                "x": float(left["x"]) + float(left.get("right_handle_x", 0.0)),
                "y": float(left["color"][channel]) + float(left_handle_y[channel]),
            },
            {
                "x": float(right["x"]) + float(right.get("left_handle_x", 0.0)),
                "y": float(right["color"][channel]) + float(right_handle_y[channel]),
            },
        )

    @staticmethod
    def bezier_y_at_x(x0, y0, handle0, handle1, x1, y1, x) -> float:
        t = OmniCurveSampler.solve_cubic_x(x0, handle0["x"], handle1["x"], x1, x)
        return OmniCurveSampler.cubic(y0, handle0["y"], handle1["y"], y1, t)

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
_cubic = OmniCurveSampler.cubic
_solve_cubic_x = OmniCurveSampler.solve_cubic_x
_has_coord_handles = OmniCurveSampler.has_coord_handles
_float_coord_handles = OmniCurveSampler.float_coord_handles
_color_coord_handles = OmniCurveSampler.color_coord_handles
_bezier_y_at_x = OmniCurveSampler.bezier_y_at_x
_float_slope = OmniCurveSampler.float_slope
_float_auto_tangent = OmniCurveSampler.float_auto_tangent
_float_out_tangent = OmniCurveSampler.float_out_tangent
_float_in_tangent = OmniCurveSampler.float_in_tangent
_color_slope = OmniCurveSampler.color_slope
_color_auto_tangent = OmniCurveSampler.color_auto_tangent
_color_out_tangent = OmniCurveSampler.color_out_tangent
_color_in_tangent = OmniCurveSampler.color_in_tangent


class PropertyCurvePythonSamplerBackend:
    """默认 Python 采样后端。"""

    name = "python"
    version = 1

    @staticmethod
    def compile_float_curve(curve):
        return curve

    @staticmethod
    def compile_color_curve(curve):
        return curve

    @staticmethod
    def sample_float_curve(curve, position, extend=None) -> float:
        x = extend_position(position, curve.extend if use_curve_extend(extend) else extend)
        points = curve.points
        if x <= points[0]["x"]:
            return float(points[0]["y"])
        if x >= points[-1]["x"]:
            return float(points[-1]["y"])

        point_index, left, right = _find_segment(points, x)
        dx = right["x"] - left["x"]
        segment_interpolation = point_interpolation(left, curve.interpolation)
        if segment_interpolation == "CONSTANT" or dx <= 0.0:
            return float(left["y"])

        factor = (x - left["x"]) / dx
        if segment_interpolation == "BEZIER":
            if _has_coord_handles(left, right):
                left_handle, right_handle = _float_coord_handles(left, right)
                return float(_bezier_y_at_x(
                    left["x"],
                    left["y"],
                    left_handle,
                    right_handle,
                    right["x"],
                    right["y"],
                    x,
                ))

            out_tangent = _float_out_tangent(points, point_index, left, right)
            in_tangent = _float_in_tangent(points, point_index + 1, left, right)
            m0 = out_tangent * dx * float(left.get("right_weight", 1.0))
            m1 = in_tangent * dx * float(right.get("left_weight", 1.0))
            return float(_hermite(left["y"], right["y"], m0, m1, factor))

        return float(left["y"] * (1.0 - factor) + right["y"] * factor)

    @staticmethod
    def sample_float_many(curve, count, extend=None) -> list[float]:
        count = max(1, int(count))
        if count == 1:
            return [PropertyCurvePythonSamplerBackend.sample_float_curve(curve, 0.0, extend=extend)]
        return [
            PropertyCurvePythonSamplerBackend.sample_float_curve(curve, index / float(count - 1), extend=extend)
            for index in range(count)
        ]

    @staticmethod
    def sample_float_positions(curve, positions, extend=None) -> list[float]:
        return [
            PropertyCurvePythonSamplerBackend.sample_float_curve(curve, position, extend=extend)
            for position in positions
        ]

    @staticmethod
    def sample_color_curve(curve, position, extend=None) -> tuple[float, float, float, float]:
        x = extend_position(position, curve.extend if use_curve_extend(extend) else extend)
        points = curve.points
        if x <= points[0]["x"]:
            return tuple(points[0]["color"])
        if x >= points[-1]["x"]:
            return tuple(points[-1]["color"])

        point_index, left, right = _find_segment(points, x)
        dx = right["x"] - left["x"]
        segment_interpolation = point_interpolation(left, curve.interpolation)
        if segment_interpolation == "CONSTANT" or dx <= 0.0:
            return tuple(left["color"])

        factor = (x - left["x"]) / dx
        if segment_interpolation == "BEZIER":
            if _has_coord_handles(left, right):
                values = []
                for channel in range(4):
                    left_handle, right_handle = _color_coord_handles(left, right, channel)
                    values.append(_bezier_y_at_x(
                        left["x"],
                        left["color"][channel],
                        left_handle,
                        right_handle,
                        right["x"],
                        right["color"][channel],
                        x,
                    ))
                return tuple(float(value) for value in values)

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

    @staticmethod
    def sample_color_many(curve, count, extend=None) -> list[tuple[float, float, float, float]]:
        count = max(1, int(count))
        if count == 1:
            return [PropertyCurvePythonSamplerBackend.sample_color_curve(curve, 0.0, extend=extend)]
        return [
            PropertyCurvePythonSamplerBackend.sample_color_curve(curve, index / float(count - 1), extend=extend)
            for index in range(count)
        ]

    @staticmethod
    def sample_color_positions(curve, positions, extend=None) -> list[tuple[float, float, float, float]]:
        return [
            PropertyCurvePythonSamplerBackend.sample_color_curve(curve, position, extend=extend)
            for position in positions
        ]


class PropertyCurveNativeSamplerAdapter:
    """预留 C++ 采样后端适配层。

    推荐 native ABI：
    - compile_property_float_curve(payload: dict) -> handle
    - compile_property_color_curve(payload: dict) -> handle
    - sample_property_float_curve(handle, position: float, extend: str | None) -> float
    - sample_property_color_curve(handle, position: float, extend: str | None) -> tuple[float, float, float, float]

    真正高频场景应优先实现 compile + 批量采样，避免每次采样都跨 Python/C++ 传 dict。
    """

    name = "cpp"
    version = 1

    def __init__(self, native_module):
        self.native_module = native_module

    def compile_float_curve(self, curve):
        compile_func = getattr(self.native_module, "compile_property_float_curve", None)
        if compile_func is None:
            return curve.to_payload()
        return compile_func(curve.to_payload())

    def compile_color_curve(self, curve):
        compile_func = getattr(self.native_module, "compile_property_color_curve", None)
        if compile_func is None:
            return curve.to_payload()
        return compile_func(curve.to_payload())

    def sample_float_curve(self, compiled_curve, position, extend=None) -> float:
        sample_func = getattr(self.native_module, "sample_property_float_curve", None)
        if sample_func is None:
            raise NotImplementedError("native backend missing sample_property_float_curve")
        return float(sample_func(compiled_curve, float(position), extend))

    def sample_color_curve(self, compiled_curve, position, extend=None) -> tuple[float, float, float, float]:
        sample_func = getattr(self.native_module, "sample_property_color_curve", None)
        if sample_func is None:
            raise NotImplementedError("native backend missing sample_property_color_curve")
        value = sample_func(compiled_curve, float(position), extend)
        return coerce_color(value)

    def sample_float_many(self, compiled_curve, count, extend=None) -> list[float]:
        sample_func = getattr(self.native_module, "sample_property_float_curve_many", None)
        if sample_func is not None:
            return [float(value) for value in sample_func(compiled_curve, int(count), extend)]
        count = max(1, int(count))
        if count == 1:
            return [self.sample_float_curve(compiled_curve, 0.0, extend=extend)]
        return [
            self.sample_float_curve(compiled_curve, index / float(count - 1), extend=extend)
            for index in range(count)
        ]

    def sample_color_many(self, compiled_curve, count, extend=None) -> list[tuple[float, float, float, float]]:
        sample_func = getattr(self.native_module, "sample_property_color_curve_many", None)
        if sample_func is not None:
            return [coerce_color(value) for value in sample_func(compiled_curve, int(count), extend)]
        divisor = float(max(1, int(count)) - 1)
        if divisor <= 0.0:
            return [self.sample_color_curve(compiled_curve, 0.0, extend=extend)]
        return [self.sample_color_curve(compiled_curve, index / divisor, extend=extend) for index in range(max(1, int(count)))]

    def sample_float_positions(self, compiled_curve, positions, extend=None) -> list[float]:
        sample_func = getattr(self.native_module, "sample_property_float_curve_positions", None)
        if sample_func is not None:
            return [float(value) for value in sample_func(compiled_curve, positions, extend)]
        return [self.sample_float_curve(compiled_curve, position, extend=extend) for position in positions]

    def sample_color_positions(self, compiled_curve, positions, extend=None) -> list[tuple[float, float, float, float]]:
        sample_func = getattr(self.native_module, "sample_property_color_curve_positions", None)
        if sample_func is not None:
            return [coerce_color(value) for value in sample_func(compiled_curve, positions, extend)]
        return [self.sample_color_curve(compiled_curve, position, extend=extend) for position in positions]


class PropertyCurveSamplerBackend:
    """曲线采样后端管理器。

    Python 负责存储、预设和 RNA 数据；采样从这里统一分发，后续可切到 C++ 后端。
    """

    _python_backend = PropertyCurvePythonSamplerBackend()
    _backend = _python_backend

    @classmethod
    def active_backend(cls):
        return cls._backend

    @classmethod
    def active_backend_name(cls) -> str:
        return str(getattr(cls._backend, "name", "unknown"))

    @classmethod
    def set_backend(cls, backend=None):
        backend = backend or cls._python_backend
        for method_name in ("compile_float_curve", "compile_color_curve", "sample_float_curve", "sample_color_curve"):
            if not callable(getattr(backend, method_name, None)):
                raise TypeError(f"PropertyCurve sampler backend missing {method_name}")
        cls._backend = backend
        return cls._backend

    @classmethod
    def use_python_backend(cls):
        return cls.set_backend(cls._python_backend)

    @classmethod
    def use_native_backend(cls, native_module):
        return cls.set_backend(PropertyCurveNativeSamplerAdapter(native_module))

    @classmethod
    def try_use_native_backend(cls, module_name="hotools_native") -> bool:
        try:
            import importlib
            native_module = importlib.import_module(module_name)
        except Exception:
            return False
        cls.use_native_backend(native_module)
        return True

    @classmethod
    def invalidate_cache(cls, curve):
        cache = getattr(curve, "_sample_backend_cache", None)
        if isinstance(cache, dict):
            cache.clear()

    @classmethod
    def _compiled_curve(cls, curve, curve_kind):
        backend = cls.active_backend()
        version = getattr(backend, "version", 0)
        key = (curve_kind, id(backend), version)
        cache = getattr(curve, "_sample_backend_cache", None)
        if cache is None:
            cache = {}
            curve._sample_backend_cache = cache
        if key not in cache:
            if curve_kind == "float":
                cache[key] = backend.compile_float_curve(curve)
            else:
                cache[key] = backend.compile_color_curve(curve)
        return cache[key]

    @classmethod
    def sample_float(cls, curve, position, extend=None) -> float:
        backend = cls.active_backend()
        compiled_curve = cls._compiled_curve(curve, "float")
        return float(backend.sample_float_curve(compiled_curve, position, extend=extend))

    @classmethod
    def sample_color(cls, curve, position, extend=None) -> tuple[float, float, float, float]:
        backend = cls.active_backend()
        compiled_curve = cls._compiled_curve(curve, "color")
        return coerce_color(backend.sample_color_curve(compiled_curve, position, extend=extend))

    @classmethod
    def sample_float_many(cls, curve, count, extend=None) -> list[float]:
        backend = cls.active_backend()
        compiled_curve = cls._compiled_curve(curve, "float")
        sample_many = getattr(backend, "sample_float_many", None)
        if callable(sample_many):
            return [float(value) for value in sample_many(compiled_curve, count, extend=extend)]
        count = max(1, int(count))
        if count == 1:
            return [float(backend.sample_float_curve(compiled_curve, 0.0, extend=extend))]
        return [
            float(backend.sample_float_curve(compiled_curve, index / float(count - 1), extend=extend))
            for index in range(count)
        ]

    @classmethod
    def sample_color_many(cls, curve, count, extend=None) -> list[tuple[float, float, float, float]]:
        backend = cls.active_backend()
        compiled_curve = cls._compiled_curve(curve, "color")
        sample_many = getattr(backend, "sample_color_many", None)
        if callable(sample_many):
            return [coerce_color(value) for value in sample_many(compiled_curve, count, extend=extend)]
        count = max(1, int(count))
        if count == 1:
            return [coerce_color(backend.sample_color_curve(compiled_curve, 0.0, extend=extend))]
        return [
            coerce_color(backend.sample_color_curve(compiled_curve, index / float(count - 1), extend=extend))
            for index in range(count)
        ]

    @classmethod
    def sample_float_positions(cls, curve, positions, extend=None) -> list[float]:
        backend = cls.active_backend()
        compiled_curve = cls._compiled_curve(curve, "float")
        sample_positions = getattr(backend, "sample_float_positions", None)
        if callable(sample_positions):
            return [float(value) for value in sample_positions(compiled_curve, positions, extend=extend)]
        return [float(backend.sample_float_curve(compiled_curve, position, extend=extend)) for position in positions]

    @classmethod
    def sample_color_positions(cls, curve, positions, extend=None) -> list[tuple[float, float, float, float]]:
        backend = cls.active_backend()
        compiled_curve = cls._compiled_curve(curve, "color")
        sample_positions = getattr(backend, "sample_color_positions", None)
        if callable(sample_positions):
            return [coerce_color(value) for value in sample_positions(compiled_curve, positions, extend=extend)]
        return [coerce_color(backend.sample_color_curve(compiled_curve, position, extend=extend)) for position in positions]


class OmniFloatCurveValue:
    def __init__(self, points=None, value=0.0, interpolation="LINEAR", extend="CLAMP"):
        self.value = float(value)
        self.interpolation = coerce_interpolation(interpolation)
        self.points = normalize_float_points(points, interpolation=self.interpolation)
        self.extend = coerce_extend(extend)
        self._sample_backend_cache = {}

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

        if _has_coord_handles(left, right):
            return _float_coord_handles(left, right)

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
        return PropertyCurveSamplerBackend.sample_float(self, position, extend=extend)

    def sample_many(self, count, extend=None) -> list[float]:
        return PropertyCurveSamplerBackend.sample_float_many(self, count, extend=extend)

    def sample_positions(self, positions, extend=None) -> list[float]:
        return PropertyCurveSamplerBackend.sample_float_positions(self, positions, extend=extend)


class OmniColorCurveValue:
    def __init__(self, points=None, interpolation="LINEAR", extend="CLAMP"):
        self.interpolation = coerce_interpolation(interpolation)
        self.points = normalize_color_points(points, interpolation=self.interpolation)
        self.extend = coerce_extend(extend)
        self._sample_backend_cache = {}

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

        if _has_coord_handles(left, right):
            return _color_coord_handles(left, right, channel)

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
        return PropertyCurveSamplerBackend.sample_color(self, position, extend=extend)

    def sample_many(self, count, extend=None) -> list[tuple[float, float, float, float]]:
        return PropertyCurveSamplerBackend.sample_color_many(self, count, extend=extend)

    def sample_positions(self, positions, extend=None) -> list[tuple[float, float, float, float]]:
        return PropertyCurveSamplerBackend.sample_color_positions(self, positions, extend=extend)


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


def set_curve_sampler_backend(backend=None):
    return PropertyCurveSamplerBackend.set_backend(backend)


def use_python_curve_sampler_backend():
    return PropertyCurveSamplerBackend.use_python_backend()


def use_native_curve_sampler_backend(native_module):
    return PropertyCurveSamplerBackend.use_native_backend(native_module)


def try_use_native_curve_sampler_backend(module_name="hotools_native") -> bool:
    return PropertyCurveSamplerBackend.try_use_native_backend(module_name)


def active_curve_sampler_backend_name() -> str:
    return PropertyCurveSamplerBackend.active_backend_name()


def compile_float_curve(curve):
    return PropertyCurveSamplerBackend._compiled_curve(resolve_float_curve(curve), "float")


def compile_color_curve(curve):
    return PropertyCurveSamplerBackend._compiled_curve(resolve_color_curve(curve), "color")


def sample_compiled_float_curve(compiled_curve, position, extend=None) -> float:
    backend = PropertyCurveSamplerBackend.active_backend()
    return float(backend.sample_float_curve(compiled_curve, position, extend=extend))


def sample_compiled_color_curve(compiled_curve, position, extend=None) -> tuple[float, float, float, float]:
    backend = PropertyCurveSamplerBackend.active_backend()
    return coerce_color(backend.sample_color_curve(compiled_curve, position, extend=extend))


def sample_compiled_float_curve_many(compiled_curve, count, extend=None) -> list[float]:
    backend = PropertyCurveSamplerBackend.active_backend()
    sample_many = getattr(backend, "sample_float_many", None)
    if callable(sample_many):
        return [float(value) for value in sample_many(compiled_curve, count, extend=extend)]
    count = max(1, int(count))
    if count == 1:
        return [float(backend.sample_float_curve(compiled_curve, 0.0, extend=extend))]
    return [
        float(backend.sample_float_curve(compiled_curve, index / float(count - 1), extend=extend))
        for index in range(count)
    ]


def sample_compiled_color_curve_many(compiled_curve, count, extend=None) -> list[tuple[float, float, float, float]]:
    backend = PropertyCurveSamplerBackend.active_backend()
    sample_many = getattr(backend, "sample_color_many", None)
    if callable(sample_many):
        return [coerce_color(value) for value in sample_many(compiled_curve, count, extend=extend)]
    count = max(1, int(count))
    if count == 1:
        return [coerce_color(backend.sample_color_curve(compiled_curve, 0.0, extend=extend))]
    return [
        coerce_color(backend.sample_color_curve(compiled_curve, index / float(count - 1), extend=extend))
        for index in range(count)
    ]


def sample_compiled_float_curve_positions(compiled_curve, positions, extend=None) -> list[float]:
    backend = PropertyCurveSamplerBackend.active_backend()
    sample_positions = getattr(backend, "sample_float_positions", None)
    if callable(sample_positions):
        return [float(value) for value in sample_positions(compiled_curve, positions, extend=extend)]
    return [float(backend.sample_float_curve(compiled_curve, position, extend=extend)) for position in positions]


def sample_compiled_color_curve_positions(compiled_curve, positions, extend=None) -> list[tuple[float, float, float, float]]:
    backend = PropertyCurveSamplerBackend.active_backend()
    sample_positions = getattr(backend, "sample_color_positions", None)
    if callable(sample_positions):
        return [coerce_color(value) for value in sample_positions(compiled_curve, positions, extend=extend)]
    return [coerce_color(backend.sample_color_curve(compiled_curve, position, extend=extend)) for position in positions]


def sample_float_curve(curve, position, extend=None) -> float:
    return resolve_float_curve(curve).sample(position, extend=extend)


def sample_color_curve(curve, position, extend=None) -> tuple[float, float, float, float]:
    return resolve_color_curve(curve).sample(position, extend=extend)


def sample_float_curve_many(curve, count, extend=None) -> list[float]:
    return resolve_float_curve(curve).sample_many(count, extend=extend)


def sample_color_curve_many(curve, count, extend=None) -> list[tuple[float, float, float, float]]:
    return resolve_color_curve(curve).sample_many(count, extend=extend)


def sample_float_curve_positions(curve, positions, extend=None) -> list[float]:
    return resolve_float_curve(curve).sample_positions(positions, extend=extend)


def sample_color_curve_positions(curve, positions, extend=None) -> list[tuple[float, float, float, float]]:
    return resolve_color_curve(curve).sample_positions(positions, extend=extend)
