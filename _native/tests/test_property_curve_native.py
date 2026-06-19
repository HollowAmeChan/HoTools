"""Native PropertyCurve sampler parity smoke test."""

from __future__ import annotations

import importlib
import math
import os
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_DIR = os.environ.get("HOTOOLS_NATIVE_TEST_DIR")
if NATIVE_DIR:
    sys.path.insert(0, NATIVE_DIR)
sys.path.insert(0, str(REPO_ROOT / "_Lib" / "py311" / "HotoolsPackage"))
sys.path.insert(0, str(REPO_ROOT.parent))

hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [str(REPO_ROOT)]
sys.modules.setdefault("HoTools", hotools_package)

property_curve_package = types.ModuleType("HoTools.PropertyCurve")
property_curve_package.__path__ = [str(REPO_ROOT / "PropertyCurve")]
sys.modules.setdefault("HoTools.PropertyCurve", property_curve_package)

bpy_module = types.ModuleType("bpy")
bpy_types_module = types.ModuleType("bpy.types")
bpy_types_module.PropertyGroup = object


class _BpyProps:
    def __getattr__(self, _name):
        def _factory(**_kwargs):
            return None

        return _factory


bpy_module.props = _BpyProps()
bpy_module.types = bpy_types_module
sys.modules.setdefault("bpy", bpy_module)
sys.modules.setdefault("bpy.types", bpy_types_module)

from HoTools.PropertyCurve.sampling import (  # noqa: E402
    OmniColorCurveValue,
    OmniFloatCurveValue,
    PropertyCurveNativeSamplerAdapter,
    use_python_curve_sampler_backend,
)


native = importlib.import_module("hotools_native")
adapter = PropertyCurveNativeSamplerAdapter(native)


def _assert_close(actual: float, expected: float, *, tolerance: float = 1.0e-6) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f"{actual!r} != {expected!r}")


def _assert_color_close(actual, expected, *, tolerance: float = 1.0e-6) -> None:
    if len(actual) != 4 or len(expected) != 4:
        raise AssertionError(f"color length mismatch: {actual!r} != {expected!r}")
    for actual_channel, expected_channel in zip(actual, expected):
        _assert_close(actual_channel, expected_channel, tolerance=tolerance)


def _float_cases() -> list[OmniFloatCurveValue]:
    return [
        OmniFloatCurveValue(
            [{"x": 0.0, "y": 0.25}, {"x": 1.0, "y": 0.75}],
            interpolation="LINEAR",
            extend="CLAMP",
        ),
        OmniFloatCurveValue(
            [
                {"x": 0.0, "y": 0.1, "interpolation": "CONSTANT"},
                {"x": 0.35, "y": 0.8, "interpolation": "LINEAR"},
                {"x": 1.0, "y": 0.2, "interpolation": "LINEAR"},
            ],
            interpolation="LINEAR",
            extend="REPEAT",
        ),
        OmniFloatCurveValue(
            [
                {
                    "x": 0.0,
                    "y": 0.0,
                    "interpolation": "BEZIER",
                    "right_handle_type": "FREE",
                    "right_tangent": 1.5,
                    "right_weight": 0.6,
                },
                {
                    "x": 1.0,
                    "y": 1.0,
                    "left_handle_type": "FREE",
                    "left_tangent": 0.25,
                    "left_weight": 0.8,
                },
            ],
            interpolation="BEZIER",
            extend="MIRROR",
        ),
        OmniFloatCurveValue(
            [
                {
                    "x": 0.0,
                    "y": 0.0,
                    "interpolation": "BEZIER",
                    "right_handle_type": "COORD",
                    "right_handle_x": 0.25,
                    "right_handle_y": 0.7,
                },
                {
                    "x": 1.0,
                    "y": 1.0,
                    "left_handle_type": "COORD",
                    "left_handle_x": -0.25,
                    "left_handle_y": -0.15,
                },
            ],
            interpolation="BEZIER",
            extend="CLAMP",
        ),
        OmniFloatCurveValue(
            [
                {
                    "x": 0.0,
                    "y": 0.5,
                    "interpolation": "BEZIER",
                    "right_handle_type": "FREE",
                    "right_tangent": 1.5,
                    "right_weight": 0.8,
                },
                {
                    "x": 1.0,
                    "y": 0.5,
                    "left_handle_type": "FREE",
                    "left_tangent": -1.5,
                    "left_weight": 0.8,
                },
            ],
            interpolation="BEZIER",
            extend="CLAMP",
        ),
        OmniFloatCurveValue(
            [{"x": 0.0, "y": 1.0}, {"x": 1.0, "y": 1.0}],
            interpolation="LINEAR",
            extend="MIRROR",
        ),
    ]


def _color_cases() -> list[OmniColorCurveValue]:
    return [
        OmniColorCurveValue(
            [
                {"x": 0.0, "color": (0.0, 0.2, 0.4, 1.0)},
                {"x": 1.0, "color": (1.0, 0.8, 0.6, 0.5)},
            ],
            interpolation="LINEAR",
            extend="CLAMP",
        ),
        OmniColorCurveValue(
            [
                {
                    "x": 0.0,
                    "color": (0.0, 0.0, 0.0, 1.0),
                    "interpolation": "BEZIER",
                    "right_handle_type": "FREE",
                    "right_tangent": (1.0, 0.5, 0.25, 0.0),
                    "right_weight": 0.7,
                },
                {
                    "x": 1.0,
                    "color": (1.0, 0.5, 0.25, 1.0),
                    "left_handle_type": "FREE",
                    "left_tangent": (0.0, 0.25, 0.5, 1.0),
                    "left_weight": 0.5,
                },
            ],
            interpolation="BEZIER",
            extend="MIRROR",
        ),
        OmniColorCurveValue(
            [
                {"x": 0.0, "color": (0.25, 0.5, 0.75, 1.0)},
                {"x": 1.0, "color": (0.25, 0.5, 0.75, 1.0)},
            ],
            interpolation="LINEAR",
            extend="REPEAT",
        ),
    ]


def test_float_curves() -> None:
    use_python_curve_sampler_backend()
    positions = [-0.25, 0.0, 0.1, 0.35, 0.5, 0.8, 1.0, 1.25, 2.4]
    for curve in _float_cases():
        compiled = adapter.compile_float_curve(curve)
        for position in positions:
            _assert_close(
                adapter.sample_float_curve(compiled, position),
                curve.sample(position),
            )
        for extend in ("CLAMP", "REPEAT", "MIRROR"):
            expected = curve.sample_positions(positions, extend=extend)
            actual = adapter.sample_float_positions(compiled, positions, extend=extend)
            for actual_value, expected_value in zip(actual, expected):
                _assert_close(actual_value, expected_value)

        many_expected = curve.sample_many(17)
        many_actual = adapter.sample_float_many(compiled, 17)
        for actual_value, expected_value in zip(many_actual, many_expected):
            _assert_close(actual_value, expected_value)


def test_color_curves() -> None:
    use_python_curve_sampler_backend()
    positions = [-0.25, 0.0, 0.1, 0.35, 0.5, 0.8, 1.0, 1.25, 2.4]
    for curve in _color_cases():
        compiled = adapter.compile_color_curve(curve)
        for position in positions:
            _assert_color_close(
                adapter.sample_color_curve(compiled, position),
                curve.sample(position),
            )
        for extend in ("CLAMP", "REPEAT", "MIRROR"):
            expected = curve.sample_positions(positions, extend=extend)
            actual = adapter.sample_color_positions(compiled, positions, extend=extend)
            for actual_value, expected_value in zip(actual, expected):
                _assert_color_close(actual_value, expected_value)

        many_expected = curve.sample_many(17)
        many_actual = adapter.sample_color_many(compiled, 17)
        for actual_value, expected_value in zip(many_actual, many_expected):
            _assert_color_close(actual_value, expected_value)


if __name__ == "__main__":
    test_float_curves()
    test_color_curves()
    print("property curve native parity ok")
