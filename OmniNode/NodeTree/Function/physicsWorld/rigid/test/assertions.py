"""Rigid/Jolt 语义 fixture 使用的物理 oracle。"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

try:
    from .schema import AssertionSpec, Fixture, FixtureError
except ImportError:  # 支持脚本直接执行。
    from schema import AssertionSpec, Fixture, FixtureError


class SemanticAssertionError(AssertionError):
    """fixture 已成功运行，但结果违反其声明的物理 oracle。"""


def _number(value: Any, name: str, default: float | None = None) -> float:
    if value is None and default is not None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FixtureError(f"assertion {name} must be numeric") from exc
    if not math.isfinite(result):
        raise FixtureError(f"assertion {name} must be finite")
    return result


def _vec(value: Any, size: int, name: str) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != size:
        raise FixtureError(f"assertion {name} must contain {size} numbers")
    return tuple(_number(item, f"{name}[{index}]") for index, item in enumerate(value))


def _body_id(parameters: Mapping[str, Any]) -> str:
    body_id = parameters.get("body")
    if not isinstance(body_id, str) or not body_id:
        raise FixtureError("assertion body must be a non-empty string")
    return body_id


def _frames_by_number(trace: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    return {int(frame["frame"]): frame for frame in trace}


def _body_at(frame: Mapping[str, Any], body_id: str) -> Mapping[str, Any]:
    for body in frame.get("bodies", []):
        if body.get("id") == body_id:
            return body
    raise SemanticAssertionError(f"frame {frame.get('frame')} has no body {body_id!r}")


def _near(actual: float, expected: float, abs_tol: float, rel_tol: float) -> bool:
    return abs(actual - expected) <= abs_tol + rel_tol * max(abs(actual), abs(expected))


def _assert_vector_near(
    actual: Sequence[float], expected: Sequence[float], *, abs_tol: float,
    rel_tol: float, label: str,
) -> None:
    for axis, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if not _near(float(actual_value), float(expected_value), abs_tol, rel_tol):
            raise SemanticAssertionError(
                f"{label}[{axis}] expected {expected_value:.12g}, got "
                f"{actual_value:.12g} (abs_tol={abs_tol:g}, rel_tol={rel_tol:g})"
            )


def _assert_finite_all(trace: Sequence[Mapping[str, Any]]) -> None:
    # 规范化阶段已经拒绝非有限值；这里再次递归检查，防止未来新增的
    # runner 字段绕过 canonical_body_state。
    def visit(value: Any, path: str) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise SemanticAssertionError(f"{path} is non-finite: {value!r}")
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(item, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(trace, "trace")


def _assert_free_fall(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    body_id = _body_id(parameters)
    body = fixture.bodies_by_id.get(body_id)
    if body is None:
        raise FixtureError(f"free-fall assertion references unknown body: {body_id}")
    abs_position = _number(parameters.get("position_abs"), "position_abs", 2.0e-5)
    abs_velocity = _number(parameters.get("velocity_abs"), "velocity_abs", 2.0e-5)
    rel_tol = _number(parameters.get("rel"), "rel", 1.0e-6)
    dt = fixture.world.dt
    acceleration = tuple(component * body.gravity_factor for component in fixture.world.gravity)
    for frame in trace:
        n = int(frame["frame"])
        actual = _body_at(frame, body_id)
        expected_velocity = tuple(
            body.linear_velocity[axis] + acceleration[axis] * dt * n
            for axis in range(3)
        )
        expected_position = tuple(
            body.position[axis]
            + body.linear_velocity[axis] * dt * n
            + acceleration[axis] * dt * dt * n * (n + 1) * 0.5
            for axis in range(3)
        )
        _assert_vector_near(
            actual["linear_velocity"], expected_velocity,
            abs_tol=abs_velocity, rel_tol=rel_tol,
            label=f"{fixture.id} frame {n} {body_id}.linear_velocity",
        )
        _assert_vector_near(
            actual["position"], expected_position,
            abs_tol=abs_position, rel_tol=rel_tol,
            label=f"{fixture.id} frame {n} {body_id}.position",
        )


def _assert_constant_linear_motion(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    body_id = _body_id(parameters)
    body = fixture.bodies_by_id.get(body_id)
    if body is None:
        raise FixtureError(f"constant-motion assertion references unknown body: {body_id}")
    abs_position = _number(parameters.get("position_abs"), "position_abs", 2.0e-5)
    abs_velocity = _number(parameters.get("velocity_abs"), "velocity_abs", 2.0e-5)
    rel_tol = _number(parameters.get("rel"), "rel", 1.0e-6)
    for frame in trace:
        n = int(frame["frame"])
        actual = _body_at(frame, body_id)
        expected_position = tuple(
            body.position[axis] + body.linear_velocity[axis] * fixture.world.dt * n
            for axis in range(3)
        )
        _assert_vector_near(
            actual["linear_velocity"], body.linear_velocity,
            abs_tol=abs_velocity, rel_tol=rel_tol,
            label=f"{fixture.id} frame {n} {body_id}.linear_velocity",
        )
        _assert_vector_near(
            actual["position"], expected_position,
            abs_tol=abs_position, rel_tol=rel_tol,
            label=f"{fixture.id} frame {n} {body_id}.position",
        )


def _assert_impulse_delta_velocity(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    body_id = _body_id(parameters)
    body = fixture.bodies_by_id.get(body_id)
    if body is None:
        raise FixtureError(f"impulse assertion references unknown body: {body_id}")
    frame_number = int(_number(parameters.get("frame"), "frame", 1.0))
    impulse = _vec(parameters.get("impulse"), 3, "impulse")
    abs_tol = _number(parameters.get("velocity_abs"), "velocity_abs", 2.0e-5)
    rel_tol = _number(parameters.get("rel"), "rel", 1.0e-6)
    frames = _frames_by_number(trace)
    if 0 not in frames or frame_number not in frames:
        raise FixtureError("impulse assertion requires sample frame 0 and its target frame")
    initial = _body_at(frames[0], body_id)["linear_velocity"]
    actual = _body_at(frames[frame_number], body_id)["linear_velocity"]
    expected = tuple(initial[axis] + impulse[axis] / body.mass for axis in range(3))
    _assert_vector_near(
        actual, expected, abs_tol=abs_tol, rel_tol=rel_tol,
        label=f"{fixture.id} frame {frame_number} {body_id}.linear_velocity after impulse",
    )


def _assert_body_state_near(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    body_id = _body_id(parameters)
    frame_number = int(_number(parameters.get("frame"), "frame"))
    frames = _frames_by_number(trace)
    if frame_number not in frames:
        raise FixtureError(f"body_state_near needs sampled frame {frame_number}")
    body = _body_at(frames[frame_number], body_id)
    abs_tol = _number(parameters.get("abs"), "abs", 2.0e-5)
    rel_tol = _number(parameters.get("rel"), "rel", 1.0e-6)
    for key, size in (("position", 3), ("linear_velocity", 3), ("angular_velocity", 3)):
        if key in parameters:
            expected = _vec(parameters[key], size, key)
            _assert_vector_near(
                body[key], expected, abs_tol=abs_tol, rel_tol=rel_tol,
                label=f"{fixture.id} frame {frame_number} {body_id}.{key}",
            )
    for key in ("active", "sleeping"):
        if key in parameters and body[key] is not parameters[key]:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame_number} {body_id}.{key} expected "
                f"{parameters[key]!r}, got {body[key]!r}"
            )


def evaluate_assertions(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    dispatch = {
        "finite_all": lambda spec: _assert_finite_all(trace),
        "semi_implicit_free_fall": lambda spec: _assert_free_fall(fixture, trace, spec.parameters),
        "constant_linear_motion": lambda spec: _assert_constant_linear_motion(
            fixture, trace, spec.parameters,
        ),
        "impulse_delta_velocity": lambda spec: _assert_impulse_delta_velocity(
            fixture, trace, spec.parameters,
        ),
        "body_state_near": lambda spec: _assert_body_state_near(
            fixture, trace, spec.parameters,
        ),
    }
    for index, assertion in enumerate(fixture.assertions):
        try:
            dispatch[assertion.kind](assertion)
        except Exception as exc:
            results.append({
                "index": index,
                "kind": assertion.kind,
                "passed": False,
                "message": str(exc),
            })
        else:
            results.append({
                "index": index,
                "kind": assertion.kind,
                "passed": True,
                "message": "",
            })
    return results
