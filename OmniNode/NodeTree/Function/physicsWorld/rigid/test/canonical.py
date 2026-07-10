"""所有 Rigid/Jolt runner 共用的规范化 trace 工具。"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from typing import Any, Iterable, Mapping, Sequence


class NonFiniteTraceError(ValueError):
    """模拟输出 NaN 或无穷值时立即抛出。"""


def finite_float(value: Any, path: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NonFiniteTraceError(f"{path} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise NonFiniteTraceError(f"{path} is non-finite: {number!r}")
    return 0.0 if number == 0.0 else number


def vector(value: Sequence[Any], size: int, path: str) -> list[float]:
    if len(value) != size:
        raise NonFiniteTraceError(f"{path} expected {size} values, got {len(value)}")
    return [finite_float(item, f"{path}[{index}]") for index, item in enumerate(value)]


def quaternion_wxyz(value: Sequence[Any], path: str) -> list[float]:
    quat = vector(value, 4, path)
    length_sq = sum(component * component for component in quat)
    if length_sq <= 1.0e-30:
        raise NonFiniteTraceError(f"{path} is a zero quaternion")
    inv_length = 1.0 / math.sqrt(length_sq)
    quat = [component * inv_length for component in quat]
    if quat[0] < 0.0 or (quat[0] == 0.0 and next(
        (component for component in quat[1:] if component != 0.0), 0.0
    ) < 0.0):
        quat = [-component for component in quat]
    return [0.0 if component == 0.0 else component for component in quat]


def f32_hex(values: Iterable[float]) -> list[str]:
    return [struct.pack("<f", float(value)).hex() for value in values]


def canonical_body_state(body_id: str, state: Sequence[Any]) -> dict[str, Any]:
    if len(state) != 6:
        raise NonFiniteTraceError(f"body {body_id} state expected 6 fields, got {len(state)}")
    position = vector(state[0], 3, f"bodies.{body_id}.position")
    raw_rotation = vector(state[1], 4, f"bodies.{body_id}.rotation_wxyz")
    rotation = quaternion_wxyz(state[1], f"bodies.{body_id}.rotation_wxyz")
    linear_velocity = vector(state[2], 3, f"bodies.{body_id}.linear_velocity")
    angular_velocity = vector(state[3], 3, f"bodies.{body_id}.angular_velocity")
    if not isinstance(state[4], bool) or not isinstance(state[5], bool):
        raise NonFiniteTraceError(f"body {body_id} active/sleeping fields must be boolean")
    raw_values = position + raw_rotation + linear_velocity + angular_velocity
    return {
        "id": body_id,
        "position": position,
        "rotation_wxyz": rotation,
        "linear_velocity": linear_velocity,
        "angular_velocity": angular_velocity,
        "active": state[4],
        "sleeping": state[5],
        "raw_f32_hex": f32_hex(raw_values),
    }


def canonical_constraint_state(
    constraint_id: str,
    state: Sequence[Any],
    *,
    breakable: bool = False,
    breaking_threshold: float = 1000.0,
    broken: bool = False,
    breaking_impulse: float = 0.0,
) -> dict[str, Any]:
    """将 native 约束状态转换为稳定 trace，兼容旧的八字段 ABI。"""
    if len(state) not in {8, 10}:
        raise NonFiniteTraceError(
            f"constraint {constraint_id} state expected 8 or 10 fields, got {len(state)}"
        )
    constraint_type = str(state[0])
    if not isinstance(state[1], bool):
        raise NonFiniteTraceError(f"constraint {constraint_id} enabled field must be boolean")
    value_kind = str(state[2])
    current_value = finite_float(state[3], f"constraints.{constraint_id}.current_value")
    lambda_position = vector(
        state[4], 3, f"constraints.{constraint_id}.lambda_position",
    )
    lambda_rotation = vector(
        state[5], 3, f"constraints.{constraint_id}.lambda_rotation",
    )
    lambda_limit = finite_float(state[6], f"constraints.{constraint_id}.lambda_limit")
    lambda_motor = finite_float(state[7], f"constraints.{constraint_id}.lambda_motor")
    current_translation = vector(
        state[8] if len(state) >= 10 else (0.0, 0.0, 0.0),
        3, f"constraints.{constraint_id}.current_translation",
    )
    current_rotation = vector(
        state[9] if len(state) >= 10 else (0.0, 0.0, 0.0),
        3, f"constraints.{constraint_id}.current_rotation",
    )
    numeric = (
        [current_value] + lambda_position + lambda_rotation
        + [lambda_limit, lambda_motor] + current_translation + current_rotation
    )
    threshold = finite_float(
        breaking_threshold, f"constraints.{constraint_id}.breaking_threshold"
    )
    impulse = finite_float(
        breaking_impulse, f"constraints.{constraint_id}.breaking_impulse"
    )
    return {
        "id": constraint_id,
        "type": constraint_type,
        "enabled": state[1],
        "breakable": bool(breakable),
        "breaking_threshold": threshold,
        "broken": bool(broken),
        "breaking_impulse": impulse,
        "current_value_kind": value_kind,
        "current_value": current_value,
        "current_translation": current_translation,
        "current_rotation": current_rotation,
        "lambda_position": lambda_position,
        "lambda_rotation": lambda_rotation,
        "lambda_limit": lambda_limit,
        "lambda_motor": lambda_motor,
        "lambda_max_abs": max(abs(value) for value in numeric[1:]),
        "raw_f32_hex": f32_hex(numeric),
    }


def canonical_contact_event(
    event: Sequence[Any], handle_to_id: Mapping[int, str],
) -> dict[str, Any]:
    """将 native contact tuple 转为按稳定刚体 id 排序的事件。"""
    if len(event) != 12:
        raise NonFiniteTraceError(f"contact event expected 12 fields, got {len(event)}")
    try:
        body_a = handle_to_id[int(event[1])]
        body_b = handle_to_id[int(event[2])]
    except KeyError as exc:
        raise NonFiniteTraceError(f"contact references unknown body handle: {exc}") from exc
    sensor_a = bool(event[3])
    sensor_b = bool(event[4])
    normal = vector(event[6], 3, "contact.normal")
    points_a = [vector(point, 3, "contact.points_a") for point in event[8]]
    points_b = [vector(point, 3, "contact.points_b") for point in event[9]]
    sub_shape_a = int(event[10])
    sub_shape_b = int(event[11])
    if body_b < body_a:
        body_a, body_b = body_b, body_a
        sensor_a, sensor_b = sensor_b, sensor_a
        points_a, points_b = points_b, points_a
        sub_shape_a, sub_shape_b = sub_shape_b, sub_shape_a
        normal = [-value for value in normal]
    numeric = normal + [
        finite_float(event[7], "contact.penetration_depth"),
        *[value for point in points_a for value in point],
        *[value for point in points_b for value in point],
    ]
    return {
        "state": str(event[0]),
        "body_a": body_a,
        "body_b": body_b,
        "body_a_sensor": sensor_a,
        "body_b_sensor": sensor_b,
        "is_sensor": bool(event[5]),
        "normal": normal,
        "penetration_depth": numeric[3],
        "points_on_a": points_a,
        "points_on_b": points_b,
        "sub_shape_a": sub_shape_a,
        "sub_shape_b": sub_shape_b,
        "raw_f32_hex": f32_hex(numeric),
    }


def canonical_ray_result(
    query_id: str, result: Sequence[Any], handle_to_id: Mapping[int, str],
) -> dict[str, Any]:
    """将 native RayCast 七字段结果转换为稳定 query trace。"""
    if len(result) != 7:
        raise NonFiniteTraceError(f"ray result expected 7 fields, got {len(result)}")
    hit = bool(result[0])
    handle = int(result[1])
    body_id = ""
    if hit:
        try:
            body_id = handle_to_id[handle]
        except KeyError as exc:
            raise NonFiniteTraceError(f"ray hit unknown body handle: {handle}") from exc
    position = vector(result[2], 3, f"queries.{query_id}.position")
    normal = vector(result[3], 3, f"queries.{query_id}.normal")
    fraction = finite_float(result[4], f"queries.{query_id}.fraction")
    numeric = position + normal + [fraction]
    return {
        "id": query_id,
        "type": "RAY_CAST",
        "hit": hit,
        "body_id": body_id,
        "position": position,
        "normal": normal,
        "fraction": fraction,
        "sub_shape": int(result[5]),
        "is_sensor": bool(result[6]),
        "raw_f32_hex": f32_hex(numeric),
    }


def canonical_value(value: Any, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return finite_float(value, path)
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(value[key], f"{path}.{key}")
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonical_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise NonFiniteTraceError(
        f"{path} has unsupported trace value type: {type(value).__name__}"
    )


def physical_frame(frame: Mapping[str, Any]) -> dict[str, Any]:
    """移除 trace 帧中的 runner 与计时元数据，只保留物理状态。"""
    return {
        "frame": int(frame["frame"]),
        "dt": finite_float(frame["dt"], "frame.dt"),
        "substeps": int(frame["substeps"]),
        "bodies": [
            {
                key: body[key]
                for key in (
                    "id", "position", "rotation_wxyz", "linear_velocity",
                    "angular_velocity", "active", "sleeping", "raw_f32_hex",
                )
            }
            for body in frame.get("bodies", [])
        ],
        "constraints": frame.get("constraints", []),
        "contacts": frame.get("contacts", []),
        "queries": frame.get("queries", []),
        "stats": {
            key: value
            for key, value in frame.get("stats", {}).items()
            if key != "step_ms"
        },
    }


def physical_trace_hash(trace: Sequence[Mapping[str, Any]]) -> str:
    payload = [physical_frame(frame) for frame in trace]
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def traces_bitwise_equal(
    left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]],
) -> bool:
    return [physical_frame(item) for item in left] == [physical_frame(item) for item in right]
