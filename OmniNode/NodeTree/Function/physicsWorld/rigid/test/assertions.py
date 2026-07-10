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


def _constraint_at(frame: Mapping[str, Any], constraint_id: str) -> Mapping[str, Any]:
    for constraint in frame.get("constraints", []):
        if constraint.get("id") == constraint_id:
            return constraint
    raise SemanticAssertionError(
        f"frame {frame.get('frame')} has no constraint {constraint_id!r}"
    )


def _constraint_id(parameters: Mapping[str, Any]) -> str:
    constraint_id = parameters.get("constraint")
    if not isinstance(constraint_id, str) or not constraint_id:
        raise FixtureError("assertion constraint must be a non-empty string")
    return constraint_id


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


def _quat_conjugate(quat: Sequence[float]) -> tuple[float, float, float, float]:
    return (float(quat[0]), -float(quat[1]), -float(quat[2]), -float(quat[3]))


def _quat_multiply(
    left: Sequence[float], right: Sequence[float],
) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = (float(value) for value in left)
    rw, rx, ry, rz = (float(value) for value in right)
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def _quat_rotate(quat: Sequence[float], value: Sequence[float]) -> tuple[float, float, float]:
    vector_quat = (0.0, float(value[0]), float(value[1]), float(value[2]))
    result = _quat_multiply(_quat_multiply(quat, vector_quat), _quat_conjugate(quat))
    return (result[1], result[2], result[3])


def _quat_angle(left: Sequence[float], right: Sequence[float]) -> float:
    dot = abs(sum(float(a) * float(b) for a, b in zip(left, right)))
    return 2.0 * math.acos(max(-1.0, min(1.0, dot)))


def _sub(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float]:
    return tuple(float(left[index]) - float(right[index]) for index in range(3))


def _add(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float]:
    return tuple(float(left[index]) + float(right[index]) for index in range(3))


def _length(value: Sequence[float]) -> float:
    return math.sqrt(sum(float(component) * float(component) for component in value))


def _relative_transform(
    frame: Mapping[str, Any], body_a_id: str, body_b_id: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    if body_a_id == "WORLD":
        body_b = _body_at(frame, body_b_id)
        return tuple(body_b["position"]), tuple(body_b["rotation_wxyz"])
    if body_b_id == "WORLD":
        body_a = _body_at(frame, body_a_id)
        return tuple(body_a["position"]), tuple(body_a["rotation_wxyz"])
    body_a = _body_at(frame, body_a_id)
    body_b = _body_at(frame, body_b_id)
    inverse_a = _quat_conjugate(body_a["rotation_wxyz"])
    relative_position = _quat_rotate(
        inverse_a, _sub(body_b["position"], body_a["position"]),
    )
    relative_rotation = _quat_multiply(inverse_a, body_b["rotation_wxyz"])
    return relative_position, relative_rotation


def _live_anchor(
    initial_frame: Mapping[str, Any], current_frame: Mapping[str, Any],
    body_id: str, anchor_position: Sequence[float],
) -> tuple[float, float, float]:
    if body_id == "WORLD":
        return tuple(float(value) for value in anchor_position)
    initial_body = _body_at(initial_frame, body_id)
    current_body = _body_at(current_frame, body_id)
    local_anchor = _quat_rotate(
        _quat_conjugate(initial_body["rotation_wxyz"]),
        _sub(anchor_position, initial_body["position"]),
    )
    return _add(
        current_body["position"],
        _quat_rotate(current_body["rotation_wxyz"], local_anchor),
    )


def _live_axis(
    initial_frame: Mapping[str, Any], current_frame: Mapping[str, Any],
    body_id: str, initial_world_axis: Sequence[float],
) -> tuple[float, float, float]:
    if body_id == "WORLD":
        return tuple(float(value) for value in initial_world_axis)
    initial_body = _body_at(initial_frame, body_id)
    current_body = _body_at(current_frame, body_id)
    local_axis = _quat_rotate(
        _quat_conjugate(initial_body["rotation_wxyz"]), initial_world_axis,
    )
    return _quat_rotate(current_body["rotation_wxyz"], local_axis)


def _axis_index(value: Any) -> int:
    if isinstance(value, str):
        mapping = {"X": 0, "Y": 1, "Z": 2}
        try:
            return mapping[value.upper()]
        except KeyError as exc:
            raise FixtureError("assertion axis must be X, Y or Z") from exc
    index = int(_number(value, "axis"))
    if index not in {0, 1, 2}:
        raise FixtureError("assertion axis must be 0, 1 or 2")
    return index


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


def _assert_constraint_state_schema(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    spec = fixture.constraints_by_id.get(constraint_id)
    if spec is None:
        raise FixtureError(f"constraint-state assertion references unknown constraint: {constraint_id}")
    expected_type = str(parameters.get("type", spec.type))
    expected_kind = parameters.get("current_value_kind")
    expected_enabled = parameters.get("enabled", True)
    for frame in trace:
        state = _constraint_at(frame, constraint_id)
        if state["type"] != expected_type:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} {constraint_id}.type expected "
                f"{expected_type!r}, got {state['type']!r}"
            )
        if state["enabled"] is not expected_enabled:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} {constraint_id}.enabled expected "
                f"{expected_enabled!r}, got {state['enabled']!r}"
            )
        if expected_kind is not None and state["current_value_kind"] != expected_kind:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} {constraint_id}.current_value_kind "
                f"expected {expected_kind!r}, got {state['current_value_kind']!r}"
            )


def _assert_fixed_relative_transform(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    spec = fixture.constraints_by_id.get(constraint_id)
    if spec is None or spec.type != "FIXED":
        raise FixtureError(f"fixed assertion requires FIXED constraint: {constraint_id}")
    position_abs = _number(parameters.get("position_abs"), "position_abs", 2.0e-4)
    rotation_abs = _number(parameters.get("rotation_abs"), "rotation_abs", 2.0e-4)
    start_frame = int(_number(parameters.get("start_frame"), "start_frame", 1.0))
    reference_position, reference_rotation = _relative_transform(
        trace[0], spec.body_a, spec.body_b,
    )
    for frame in trace:
        if int(frame["frame"]) < start_frame:
            continue
        position, rotation = _relative_transform(frame, spec.body_a, spec.body_b)
        position_error = _length(_sub(position, reference_position))
        rotation_error = _quat_angle(rotation, reference_rotation)
        if position_error > position_abs:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} fixed position residual "
                f"{position_error:.12g} exceeds {position_abs:g}"
            )
        if rotation_error > rotation_abs:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} fixed rotation residual "
                f"{rotation_error:.12g} exceeds {rotation_abs:g}"
            )


def _assert_point_anchor_coincidence(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    spec = fixture.constraints_by_id.get(constraint_id)
    if spec is None or spec.type != "POINT":
        raise FixtureError(f"point assertion requires POINT constraint: {constraint_id}")
    tolerance = _number(parameters.get("distance_abs"), "distance_abs", 2.0e-4)
    start_frame = int(_number(parameters.get("start_frame"), "start_frame", 1.0))
    anchor_a = spec.anchor_position_a if spec.use_separate_anchor_frames else spec.anchor_position
    anchor_b = spec.anchor_position_b if spec.use_separate_anchor_frames else spec.anchor_position
    initial = trace[0]
    for frame in trace:
        if int(frame["frame"]) < start_frame:
            continue
        live_a = _live_anchor(initial, frame, spec.body_a, anchor_a)
        live_b = _live_anchor(initial, frame, spec.body_b, anchor_b)
        residual = _length(_sub(live_b, live_a))
        if residual > tolerance:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} point anchor residual "
                f"{residual:.12g} exceeds {tolerance:g}"
            )


def _assert_distance_range(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    spec = fixture.constraints_by_id.get(constraint_id)
    if spec is None or spec.type != "DISTANCE":
        raise FixtureError(f"distance assertion requires DISTANCE constraint: {constraint_id}")
    minimum = _number(parameters.get("minimum"), "minimum", min(spec.distance_min, spec.distance_max))
    maximum = _number(parameters.get("maximum"), "maximum", max(spec.distance_min, spec.distance_max))
    tolerance = _number(parameters.get("distance_abs"), "distance_abs", 2.0e-4)
    start_frame = int(_number(parameters.get("start_frame"), "start_frame", 1.0))
    for frame in trace:
        if int(frame["frame"]) < start_frame:
            continue
        state = _constraint_at(frame, constraint_id)
        if state["current_value_kind"] != "distance":
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} {constraint_id} did not publish distance"
            )
        value = float(state["current_value"])
        if value < minimum - tolerance or value > maximum + tolerance:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} distance {value:.12g} outside "
                f"[{minimum:g}, {maximum:g}] with tolerance {tolerance:g}"
            )


def _assert_distance_converges_to_range(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    spec = fixture.constraints_by_id.get(constraint_id)
    if spec is None or spec.type != "DISTANCE":
        raise FixtureError(f"distance convergence requires DISTANCE constraint: {constraint_id}")
    minimum = _number(parameters.get("minimum"), "minimum", min(spec.distance_min, spec.distance_max))
    maximum = _number(parameters.get("maximum"), "maximum", max(spec.distance_min, spec.distance_max))
    final_abs = _number(parameters.get("final_abs"), "final_abs", 2.0e-4)
    monotonic_abs = _number(parameters.get("monotonic_abs"), "monotonic_abs", 2.0e-6)
    errors: list[tuple[int, float]] = []
    for frame in trace:
        state = _constraint_at(frame, constraint_id)
        value = float(state["current_value"])
        error = max(minimum - value, 0.0, value - maximum)
        errors.append((int(frame["frame"]), error))
    for (previous_frame, previous), (current_frame, current) in zip(errors, errors[1:]):
        if current > previous + monotonic_abs:
            raise SemanticAssertionError(
                f"{fixture.id} {constraint_id} distance residual increased from "
                f"{previous:.12g} at frame {previous_frame} to {current:.12g} "
                f"at frame {current_frame}"
            )
    if errors[-1][1] > final_abs:
        raise SemanticAssertionError(
            f"{fixture.id} {constraint_id} final distance residual {errors[-1][1]:.12g} "
            f"exceeds {final_abs:g}"
        )


def _assert_rotation_changed_min(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    body_id = _body_id(parameters)
    frame_number = int(_number(parameters.get("frame"), "frame"))
    angle_min = _number(parameters.get("angle_min"), "angle_min")
    frames = _frames_by_number(trace)
    if 0 not in frames or frame_number not in frames:
        raise FixtureError("rotation_changed_min requires sample frame 0 and target frame")
    initial = _body_at(frames[0], body_id)["rotation_wxyz"]
    current = _body_at(frames[frame_number], body_id)["rotation_wxyz"]
    angle = _quat_angle(initial, current)
    if angle < angle_min:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {body_id} rotation changed "
            f"{angle:.12g}, expected at least {angle_min:g}"
        )


def _assert_constraint_anchor_coincidence(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    spec = fixture.constraints_by_id.get(constraint_id)
    if spec is None or spec.type not in {"FIXED", "POINT", "HINGE", "CONE"}:
        raise FixtureError(
            f"anchor coincidence requires fixed-point constraint: {constraint_id}"
        )
    tolerance = _number(parameters.get("distance_abs"), "distance_abs", 2.0e-4)
    start_frame = int(_number(parameters.get("start_frame"), "start_frame", 1.0))
    anchor_a = spec.anchor_position_a if spec.use_separate_anchor_frames else spec.anchor_position
    anchor_b = spec.anchor_position_b if spec.use_separate_anchor_frames else spec.anchor_position
    initial = trace[0]
    for frame in trace:
        if int(frame["frame"]) < start_frame:
            continue
        live_a = _live_anchor(initial, frame, spec.body_a, anchor_a)
        live_b = _live_anchor(initial, frame, spec.body_b, anchor_b)
        residual = _length(_sub(live_b, live_a))
        if residual > tolerance:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} anchor residual "
                f"{residual:.12g} exceeds {tolerance:g}"
            )


def _assert_rotation_axis_only(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    body_id = _body_id(parameters)
    frame_number = int(_number(parameters.get("frame"), "frame"))
    axis = _axis_index(parameters.get("axis"))
    off_axis_abs = _number(parameters.get("off_axis_abs"), "off_axis_abs", 2.0e-4)
    angle_min = _number(parameters.get("angle_min"), "angle_min", 0.1)
    frames = _frames_by_number(trace)
    if 0 not in frames or frame_number not in frames:
        raise FixtureError("rotation_axis_only requires sample frame 0 and target frame")
    initial = _body_at(frames[0], body_id)["rotation_wxyz"]
    current = _body_at(frames[frame_number], body_id)["rotation_wxyz"]
    relative = _quat_multiply(_quat_conjugate(initial), current)
    off_axis = [abs(relative[index + 1]) for index in range(3) if index != axis]
    if max(off_axis, default=0.0) > off_axis_abs:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {body_id} off-axis quaternion "
            f"{off_axis} exceeds {off_axis_abs:g}"
        )
    angle = _quat_angle(initial, current)
    if angle < angle_min:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {body_id} rotation {angle:.12g} "
            f"is below {angle_min:g}"
        )


def _assert_linear_axis_only(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    body_id = _body_id(parameters)
    frame_number = int(_number(parameters.get("frame"), "frame"))
    axis = _axis_index(parameters.get("axis"))
    off_axis_abs = _number(parameters.get("off_axis_abs"), "off_axis_abs", 2.0e-4)
    displacement_min = _number(parameters.get("displacement_min"), "displacement_min", 0.1)
    rotation_abs = _number(parameters.get("rotation_abs"), "rotation_abs", 2.0e-4)
    frames = _frames_by_number(trace)
    if 0 not in frames or frame_number not in frames:
        raise FixtureError("linear_axis_only requires sample frame 0 and target frame")
    initial = _body_at(frames[0], body_id)
    current = _body_at(frames[frame_number], body_id)
    displacement = _sub(current["position"], initial["position"])
    off_axis = [abs(displacement[index]) for index in range(3) if index != axis]
    if max(off_axis, default=0.0) > off_axis_abs:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {body_id} off-axis displacement "
            f"{off_axis} exceeds {off_axis_abs:g}"
        )
    if abs(displacement[axis]) < displacement_min:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {body_id} axis displacement "
            f"{displacement[axis]:.12g} is below {displacement_min:g}"
        )
    rotation_error = _quat_angle(initial["rotation_wxyz"], current["rotation_wxyz"])
    if rotation_error > rotation_abs:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {body_id} rotation residual "
            f"{rotation_error:.12g} exceeds {rotation_abs:g}"
        )


def _assert_cone_swing_limit(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    spec = fixture.constraints_by_id.get(constraint_id)
    if spec is None or spec.type != "CONE":
        raise FixtureError(f"cone swing assertion requires CONE constraint: {constraint_id}")
    tolerance = _number(parameters.get("angle_abs"), "angle_abs", 2.0e-3)
    swing_min = _number(parameters.get("swing_min"), "swing_min", 0.0)
    start_frame = int(_number(parameters.get("start_frame"), "start_frame", 1.0))
    rotation_a = (
        spec.anchor_rotation_wxyz_a
        if spec.use_separate_anchor_frames else spec.anchor_rotation_wxyz
    )
    rotation_b = (
        spec.anchor_rotation_wxyz_b
        if spec.use_separate_anchor_frames else spec.anchor_rotation_wxyz
    )
    axis_a_initial = _quat_rotate(rotation_a, (0.0, 0.0, 1.0))
    axis_b_initial = _quat_rotate(rotation_b, (0.0, 0.0, 1.0))
    initial = trace[0]
    max_swing = 0.0
    for frame in trace:
        if int(frame["frame"]) < start_frame:
            continue
        axis_a = _live_axis(initial, frame, spec.body_a, axis_a_initial)
        axis_b = _live_axis(initial, frame, spec.body_b, axis_b_initial)
        denominator = _length(axis_a) * _length(axis_b)
        cosine = sum(a * b for a, b in zip(axis_a, axis_b)) / denominator
        swing = math.acos(max(-1.0, min(1.0, cosine)))
        max_swing = max(max_swing, swing)
        if swing > spec.cone_half_angle + tolerance:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} cone swing {swing:.12g} exceeds "
                f"{spec.cone_half_angle:g} + {tolerance:g}"
            )
    if max_swing < swing_min:
        raise SemanticAssertionError(
            f"{fixture.id} maximum cone swing {max_swing:.12g} is below {swing_min:g}"
        )


def _assert_constraint_value_in_range(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    minimum = _number(parameters.get("minimum"), "minimum")
    maximum = _number(parameters.get("maximum"), "maximum")
    tolerance = _number(parameters.get("value_abs"), "value_abs", 2.0e-3)
    start_frame = int(_number(parameters.get("start_frame"), "start_frame", 0.0))
    for frame in trace:
        if int(frame["frame"]) < start_frame:
            continue
        state = _constraint_at(frame, constraint_id)
        value = float(state["current_value"])
        if value < minimum - tolerance or value > maximum + tolerance:
            raise SemanticAssertionError(
                f"{fixture.id} frame {frame['frame']} {constraint_id} value "
                f"{value:.12g} outside [{minimum:g}, {maximum:g}] with "
                f"tolerance {tolerance:g}"
            )


def _assert_constraint_value_near(
    fixture: Fixture, trace: Sequence[Mapping[str, Any]], parameters: Mapping[str, Any],
) -> None:
    constraint_id = _constraint_id(parameters)
    frame_number = int(_number(parameters.get("frame"), "frame"))
    expected = _number(parameters.get("expected"), "expected")
    tolerance = _number(parameters.get("value_abs"), "value_abs", 2.0e-3)
    expected_kind = parameters.get("current_value_kind")
    frames = _frames_by_number(trace)
    if frame_number not in frames:
        raise FixtureError(f"constraint_value_near needs sampled frame {frame_number}")
    state = _constraint_at(frames[frame_number], constraint_id)
    if expected_kind is not None and state["current_value_kind"] != expected_kind:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {constraint_id} value kind expected "
            f"{expected_kind!r}, got {state['current_value_kind']!r}"
        )
    value = float(state["current_value"])
    if abs(value - expected) > tolerance:
        raise SemanticAssertionError(
            f"{fixture.id} frame {frame_number} {constraint_id} value {value:.12g} "
            f"differs from {expected:.12g} by more than {tolerance:g}"
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
        "constraint_state_schema": lambda spec: _assert_constraint_state_schema(
            fixture, trace, spec.parameters,
        ),
        "fixed_relative_transform": lambda spec: _assert_fixed_relative_transform(
            fixture, trace, spec.parameters,
        ),
        "point_anchor_coincidence": lambda spec: _assert_point_anchor_coincidence(
            fixture, trace, spec.parameters,
        ),
        "distance_range": lambda spec: _assert_distance_range(
            fixture, trace, spec.parameters,
        ),
        "distance_converges_to_range": lambda spec: _assert_distance_converges_to_range(
            fixture, trace, spec.parameters,
        ),
        "rotation_changed_min": lambda spec: _assert_rotation_changed_min(
            fixture, trace, spec.parameters,
        ),
        "constraint_anchor_coincidence": lambda spec: _assert_constraint_anchor_coincidence(
            fixture, trace, spec.parameters,
        ),
        "rotation_axis_only": lambda spec: _assert_rotation_axis_only(
            fixture, trace, spec.parameters,
        ),
        "linear_axis_only": lambda spec: _assert_linear_axis_only(
            fixture, trace, spec.parameters,
        ),
        "cone_swing_limit": lambda spec: _assert_cone_swing_limit(
            fixture, trace, spec.parameters,
        ),
        "constraint_value_in_range": lambda spec: _assert_constraint_value_in_range(
            fixture, trace, spec.parameters,
        ),
        "constraint_value_near": lambda spec: _assert_constraint_value_near(
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
