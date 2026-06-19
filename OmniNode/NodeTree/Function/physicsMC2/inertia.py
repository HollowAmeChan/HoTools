"""MC2 风格的世界/局部惯性补偿。

这里先复刻 InertiaConstraint 中对 MeshCloth 最关键的部分：对象整体位移/旋转造成的
inertia shift、teleport 判定、depth inertia、粒子速度上限和离心力近似。完整的 anchor、
sync team、负缩放和稳定化时间后续仍可在同一接口上继续扩展。
"""

import math

import bpy
import numpy as np

from . import baseline, math_utils
from .constants import MC2SystemConstants

TELEPORT_NONE = 0
TELEPORT_RESET = 1
TELEPORT_KEEP = 2


def _identity_quat() -> np.ndarray:
    return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)


def _matrix_translation(matrix: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(matrix[:3, 3], dtype=np.float32)


def _matrix_rotation_quat(matrix: np.ndarray) -> np.ndarray:
    basis = np.asarray(matrix[:3, :3], dtype=np.float32)
    x = math_utils.safe_normal_np(basis[:, 0], np.asarray((1.0, 0.0, 0.0), dtype=np.float32))
    y = basis[:, 1] - x * float(np.dot(basis[:, 1], x))
    y = math_utils.safe_normal_np(y, np.asarray((0.0, 1.0, 0.0), dtype=np.float32))
    z = math_utils.safe_normal_np(np.cross(x, y), np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    y = math_utils.safe_normal_np(np.cross(z, x), y)
    rot = np.asarray(
        (
            (x[0], y[0], z[0]),
            (x[1], y[1], z[1]),
            (x[2], y[2], z[2]),
        ),
        dtype=np.float32,
    )
    return _quat_from_matrix(rot)


def _quat_from_matrix(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float32)
    trace = float(m[0, 0] + m[1, 1] + m[2, 2])
    if trace > 0.0:
        s = float(math.sqrt(trace + 1.0) * 2.0)
        return _quat_normalize(
            np.asarray(
                (
                    (m[2, 1] - m[1, 2]) / s,
                    (m[0, 2] - m[2, 0]) / s,
                    (m[1, 0] - m[0, 1]) / s,
                    0.25 * s,
                ),
                dtype=np.float32,
            )
        )
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = float(math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0)
        return _quat_normalize(
            np.asarray(
                (
                    0.25 * s,
                    (m[0, 1] + m[1, 0]) / s,
                    (m[0, 2] + m[2, 0]) / s,
                    (m[2, 1] - m[1, 2]) / s,
                ),
                dtype=np.float32,
            )
        )
    if m[1, 1] > m[2, 2]:
        s = float(math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0)
        return _quat_normalize(
            np.asarray(
                (
                    (m[0, 1] + m[1, 0]) / s,
                    0.25 * s,
                    (m[1, 2] + m[2, 1]) / s,
                    (m[0, 2] - m[2, 0]) / s,
                ),
                dtype=np.float32,
            )
        )
    s = float(math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0)
    return _quat_normalize(
        np.asarray(
            (
                (m[0, 2] + m[2, 0]) / s,
                (m[1, 2] + m[2, 1]) / s,
                0.25 * s,
                (m[1, 0] - m[0, 1]) / s,
            ),
            dtype=np.float32,
        )
    )


def _quat_normalize(quat: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(quat))
    if length <= MC2SystemConstants.EPSILON:
        return _identity_quat()
    return np.asarray(quat / length, dtype=np.float32)


def _quat_dot_abs(a: np.ndarray, b: np.ndarray) -> float:
    return abs(float(np.dot(_quat_normalize(a), _quat_normalize(b))))


def quat_angle(a: np.ndarray, b: np.ndarray) -> float:
    dot = max(-1.0, min(1.0, _quat_dot_abs(a, b)))
    return float(2.0 * math.acos(dot))


def quat_slerp(a: np.ndarray, b: np.ndarray, ratio: float) -> np.ndarray:
    t = max(0.0, min(1.0, float(ratio)))
    qa = _quat_normalize(a)
    qb = _quat_normalize(b)
    dot = float(np.dot(qa, qb))
    if dot < 0.0:
        qb = -qb
        dot = -dot
    if dot > 0.9995:
        return _quat_normalize(qa + (qb - qa) * t)
    theta0 = float(math.acos(max(-1.0, min(1.0, dot))))
    theta = theta0 * t
    sin_theta = float(math.sin(theta))
    sin_theta0 = float(math.sin(theta0))
    s0 = float(math.cos(theta) - dot * sin_theta / sin_theta0)
    s1 = float(sin_theta / sin_theta0)
    return _quat_normalize((s0 * qa) + (s1 * qb))


def quat_from_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return baseline.quat_mul(_quat_normalize(b), baseline.quat_inverse(_quat_normalize(a)))


def quat_to_axis_angle(quat: np.ndarray) -> tuple[np.ndarray, float]:
    q = _quat_normalize(quat)
    w = max(-1.0, min(1.0, float(q[3])))
    angle = float(2.0 * math.acos(w))
    s = float(math.sqrt(max(1.0 - w * w, 0.0)))
    if s <= MC2SystemConstants.EPSILON:
        return np.asarray((0.0, 0.0, 0.0), dtype=np.float32), 0.0
    return np.asarray(q[:3] / s, dtype=np.float32), angle


def shift_position(position: np.ndarray, pivot: np.ndarray, shift_vector: np.ndarray, shift_rotation: np.ndarray) -> np.ndarray:
    local = np.asarray(position, dtype=np.float32) - pivot
    return np.ascontiguousarray(pivot + baseline.quat_rotate(shift_rotation, local) + shift_vector, dtype=np.float32)


def capture_object_pose(obj: bpy.types.Object) -> dict:
    matrix = math_utils.matrix_to_numpy(obj.matrix_world)
    scale_radius = math_utils.matrix_scale_radius(obj.matrix_world)
    return {
        "matrix": matrix,
        "position": _matrix_translation(matrix),
        "rotation": _matrix_rotation_quat(matrix),
        "scale_radius": scale_radius,
        "negative_scale_sign": math_utils.object_negative_scale_sign(obj),
        "negative_scale_direction": math_utils.object_negative_scale_direction(obj),
    }


def make_runtime_state(obj: bpy.types.Object) -> dict:
    pose = capture_object_pose(obj)
    return {
        "old_component_position": pose["position"],
        "old_component_rotation": pose["rotation"],
        "shift_pivot_position": pose["position"],
        "smoothing_velocity": np.zeros(3, dtype=np.float32),
        "frame_component_shift_vector": np.zeros(3, dtype=np.float32),
        "frame_component_shift_rotation": _identity_quat(),
        "old_world_position": pose["position"],
        "old_world_rotation": pose["rotation"],
        "old_component_matrix": pose["matrix"],
        "now_component_matrix": pose["matrix"],
        "old_scale_radius": pose["scale_radius"],
        "init_scale_radius": pose["scale_radius"],
        "scale_ratio": 1.0,
        "negative_scale_sign": pose["negative_scale_sign"],
        "negative_scale_direction": pose["negative_scale_direction"],
        "old_negative_scale_sign": pose["negative_scale_sign"],
        "old_negative_scale_direction": pose["negative_scale_direction"],
        "negative_scale_changed": False,
        "now_world_position": pose["position"],
        "now_world_rotation": pose["rotation"],
        "step_vector": np.zeros(3, dtype=np.float32),
        "step_rotation": _identity_quat(),
        "inertia_vector": np.zeros(3, dtype=np.float32),
        "inertia_rotation": _identity_quat(),
        "rotation_axis": np.zeros(3, dtype=np.float32),
        "angular_velocity": 0.0,
        "teleport_state": 0,
    }


def sanitize_runtime_state(runtime_state: dict | None, obj: bpy.types.Object) -> dict:
    if not isinstance(runtime_state, dict):
        return make_runtime_state(obj)
    state = dict(runtime_state)
    defaults = make_runtime_state(obj)
    for key, value in defaults.items():
        if key not in state:
            state[key] = value
    return state


def prepare_frame(
    runtime_state: dict,
    obj: bpy.types.Object,
    frame_dt: float,
    world_inertia: float,
    movement_inertia_smoothing: float,
    movement_speed_limit: float,
    rotation_speed_limit: float,
    teleport_mode: int,
    teleport_distance: float,
    teleport_rotation_degrees: float,
) -> dict:
    next_state = sanitize_runtime_state(runtime_state, obj)
    pose = capture_object_pose(obj)
    old_component_pos = np.asarray(next_state["old_component_position"], dtype=np.float32)
    work_old_pos = old_component_pos.copy()
    old_rot = np.asarray(next_state["old_component_rotation"], dtype=np.float32)
    now_pos = pose["position"]
    now_rot = pose["rotation"]
    now_scale_radius = float(pose["scale_radius"])
    init_scale_radius = max(
        float(next_state.get("init_scale_radius", now_scale_radius) or now_scale_radius),
        MC2SystemConstants.EPSILON,
    )
    old_negative_scale_sign = int(next_state.get("old_negative_scale_sign", pose["negative_scale_sign"]) or 1)
    now_negative_scale_sign = int(pose["negative_scale_sign"])
    old_negative_scale_direction = np.asarray(
        next_state.get("old_negative_scale_direction", pose["negative_scale_direction"]),
        dtype=np.float32,
    ).reshape(3)
    now_negative_scale_direction = np.asarray(pose["negative_scale_direction"], dtype=np.float32).reshape(3)
    negative_scale_changed = bool(np.any(old_negative_scale_direction != now_negative_scale_direction))
    if negative_scale_changed:
        # 负缩放翻转帧只做历史坐标系矫正，不再叠加普通对象位移惯性。
        old_component_pos = now_pos.copy()
        work_old_pos = old_component_pos.copy()
        old_rot = now_rot.copy()
    delta = now_pos - work_old_pos
    delta_angle = quat_angle(old_rot, now_rot)

    teleport_state = TELEPORT_NONE
    if int(teleport_mode) != TELEPORT_NONE:
        distance_hit = float(np.linalg.norm(delta)) >= max(float(teleport_distance), 0.0)
        rotation_hit = math.degrees(delta_angle) >= max(float(teleport_rotation_degrees), 0.0)
        if distance_hit or rotation_hit:
            teleport_state = TELEPORT_RESET if int(teleport_mode) == TELEPORT_RESET else TELEPORT_KEEP

    if teleport_state == TELEPORT_RESET:
        next_state = make_runtime_state(obj)
        next_state["teleport_state"] = TELEPORT_RESET
        next_state["negative_scale_changed"] = negative_scale_changed
        return next_state

    smooth_delta = np.zeros(3, dtype=np.float32)
    smoothing = max(0.0, min(1.0, float(movement_inertia_smoothing)))
    if smoothing > MC2SystemConstants.EPSILON and teleport_state != TELEPORT_KEEP and frame_dt > MC2SystemConstants.EPSILON:
        frame_velocity = delta / frame_dt
        if movement_speed_limit >= 0.0:
            frame_velocity = math_utils.clamp_vector(frame_velocity, movement_speed_limit)
        average_ratio = max(0.0, min(1.0, ((1.0 - smoothing) ** 3.0) * 0.99 + 0.01))
        old_smoothing_velocity = np.asarray(next_state.get("smoothing_velocity"), dtype=np.float32)
        smoothing_velocity = old_smoothing_velocity * (1.0 - average_ratio) + frame_velocity * average_ratio
        smooth_pos = now_pos - smoothing_velocity * frame_dt
        smooth_delta = smooth_pos - work_old_pos
        work_old_pos = smooth_pos
        next_state["smoothing_velocity"] = np.ascontiguousarray(smoothing_velocity, dtype=np.float32)
        delta = now_pos - work_old_pos
    else:
        next_state["smoothing_velocity"] = (
            np.zeros(3, dtype=np.float32)
            if teleport_state == TELEPORT_KEEP
            else np.asarray(next_state.get("smoothing_velocity"), dtype=np.float32)
        )

    move_shift_ratio = 1.0 - max(0.0, min(1.0, float(world_inertia)))
    rotation_shift_ratio = move_shift_ratio
    if teleport_state == TELEPORT_KEEP:
        move_shift_ratio = 1.0
        rotation_shift_ratio = 1.0

    work_limited_pos = work_old_pos * (1.0 - move_shift_ratio) + now_pos * move_shift_ratio
    work_old_rot = quat_slerp(old_rot, now_rot, rotation_shift_ratio)
    if frame_dt > MC2SystemConstants.EPSILON and movement_speed_limit >= 0.0:
        remaining_delta = now_pos - work_limited_pos
        speed = float(np.linalg.norm(remaining_delta)) / frame_dt
        if speed > movement_speed_limit and speed > MC2SystemConstants.EPSILON:
            limit_ratio = max(0.0, min(1.0, max(speed - movement_speed_limit, 0.0) / speed))
            move_shift_ratio = move_shift_ratio * (1.0 - limit_ratio) + limit_ratio

    if frame_dt > MC2SystemConstants.EPSILON and rotation_speed_limit >= 0.0:
        remaining_angle = quat_angle(work_old_rot, now_rot)
        rotation_speed = math.degrees(remaining_angle) / frame_dt
        if rotation_speed > rotation_speed_limit and rotation_speed > MC2SystemConstants.EPSILON:
            limit_ratio = max(0.0, min(1.0, max(rotation_speed - rotation_speed_limit, 0.0) / rotation_speed))
            rotation_shift_ratio = rotation_shift_ratio * (1.0 - limit_ratio) + limit_ratio

    shift_vector = delta * move_shift_ratio + smooth_delta
    shift_rotation = quat_slerp(_identity_quat(), quat_from_to(old_rot, now_rot), rotation_shift_ratio)

    shifted_old_center = shift_position(old_component_pos, old_component_pos, shift_vector, shift_rotation)
    shifted_old_rotation = baseline.quat_mul(shift_rotation, old_rot)

    next_state["shift_pivot_position"] = np.ascontiguousarray(old_component_pos, dtype=np.float32)
    next_state["frame_component_shift_vector"] = np.ascontiguousarray(shift_vector, dtype=np.float32)
    next_state["frame_component_shift_rotation"] = np.ascontiguousarray(shift_rotation, dtype=np.float32)
    next_state["old_component_position"] = np.ascontiguousarray(old_component_pos, dtype=np.float32)
    next_state["old_component_rotation"] = np.ascontiguousarray(old_rot, dtype=np.float32)
    next_state["old_component_matrix"] = np.ascontiguousarray(next_state.get("old_component_matrix", pose["matrix"]), dtype=np.float32)
    next_state["now_component_matrix"] = np.ascontiguousarray(pose["matrix"], dtype=np.float32)
    next_state["old_scale_radius"] = float(next_state.get("old_scale_radius", now_scale_radius) or now_scale_radius)
    next_state["init_scale_radius"] = float(init_scale_radius)
    next_state["scale_ratio"] = float(max(now_scale_radius / init_scale_radius, MC2SystemConstants.EPSILON))
    next_state["negative_scale_sign"] = now_negative_scale_sign
    next_state["negative_scale_direction"] = np.ascontiguousarray(now_negative_scale_direction, dtype=np.float32)
    next_state["negative_scale_changed"] = bool(negative_scale_changed)
    next_state["old_world_position"] = np.ascontiguousarray(shifted_old_center, dtype=np.float32)
    next_state["old_world_rotation"] = np.ascontiguousarray(shifted_old_rotation, dtype=np.float32)
    next_state["now_world_position"] = np.ascontiguousarray(now_pos, dtype=np.float32)
    next_state["now_world_rotation"] = np.ascontiguousarray(now_rot, dtype=np.float32)
    next_state["teleport_state"] = teleport_state
    return next_state


def commit_frame(runtime_state: dict, obj: bpy.types.Object) -> dict:
    next_state = sanitize_runtime_state(runtime_state, obj)
    pose = capture_object_pose(obj)
    next_state["old_component_position"] = np.ascontiguousarray(pose["position"], dtype=np.float32)
    next_state["old_component_rotation"] = np.ascontiguousarray(pose["rotation"], dtype=np.float32)
    next_state["old_component_matrix"] = np.ascontiguousarray(pose["matrix"], dtype=np.float32)
    next_state["old_scale_radius"] = float(pose["scale_radius"])
    next_state["init_scale_radius"] = float(
        max(
            float(next_state.get("init_scale_radius", pose["scale_radius"]) or pose["scale_radius"]),
            MC2SystemConstants.EPSILON,
        )
    )
    next_state["scale_ratio"] = float(
        max(float(pose["scale_radius"]) / float(next_state["init_scale_radius"]), MC2SystemConstants.EPSILON)
    )
    next_state["negative_scale_sign"] = int(pose["negative_scale_sign"])
    next_state["negative_scale_direction"] = np.ascontiguousarray(pose["negative_scale_direction"], dtype=np.float32)
    next_state["old_negative_scale_sign"] = int(pose["negative_scale_sign"])
    next_state["old_negative_scale_direction"] = np.ascontiguousarray(pose["negative_scale_direction"], dtype=np.float32)
    next_state["negative_scale_changed"] = False
    next_state["shift_pivot_position"] = np.ascontiguousarray(pose["position"], dtype=np.float32)
    next_state["smoothing_velocity"] = np.asarray(next_state.get("smoothing_velocity"), dtype=np.float32)
    next_state["frame_component_shift_vector"] = np.zeros(3, dtype=np.float32)
    next_state["frame_component_shift_rotation"] = _identity_quat()
    next_state["old_world_position"] = np.ascontiguousarray(pose["position"], dtype=np.float32)
    next_state["old_world_rotation"] = np.ascontiguousarray(pose["rotation"], dtype=np.float32)
    next_state["now_world_position"] = np.ascontiguousarray(pose["position"], dtype=np.float32)
    next_state["now_world_rotation"] = np.ascontiguousarray(pose["rotation"], dtype=np.float32)
    next_state["teleport_state"] = TELEPORT_NONE
    return next_state


def apply_negative_scale_teleport(
    old_positions: np.ndarray,
    velocity_positions: np.ndarray,
    display_positions: np.ndarray,
    velocities: np.ndarray,
    real_velocities: np.ndarray,
    runtime_state: dict,
) -> None:
    if not bool(runtime_state.get("negative_scale_changed", False)):
        return
    old_matrix = np.ascontiguousarray(runtime_state.get("old_component_matrix"), dtype=np.float32)
    now_matrix = np.ascontiguousarray(runtime_state.get("now_component_matrix"), dtype=np.float32)
    if old_matrix.shape != (4, 4) or now_matrix.shape != (4, 4):
        return
    try:
        negative_matrix = np.ascontiguousarray(now_matrix @ np.linalg.inv(old_matrix), dtype=np.float32)
    except Exception:
        return
    old_positions[...] = math_utils.transform_positions(negative_matrix, old_positions)
    velocity_positions[...] = math_utils.transform_positions(negative_matrix, velocity_positions)
    display_positions[...] = math_utils.transform_positions(negative_matrix, display_positions)
    velocities[...] = math_utils.transform_vectors(negative_matrix, velocities)
    real_velocities[...] = math_utils.transform_vectors(negative_matrix, real_velocities)


def apply_frame_shift(
    old_positions: np.ndarray,
    velocity_positions: np.ndarray,
    display_positions: np.ndarray,
    velocities: np.ndarray,
    real_velocities: np.ndarray,
    runtime_state: dict,
) -> None:
    shift_vector = np.asarray(runtime_state.get("frame_component_shift_vector"), dtype=np.float32)
    shift_rotation = np.asarray(runtime_state.get("frame_component_shift_rotation"), dtype=np.float32)
    if (
        float(np.linalg.norm(shift_vector)) <= MC2SystemConstants.EPSILON
        and quat_angle(_identity_quat(), shift_rotation) <= MC2SystemConstants.EPSILON
    ):
        return
    pivot = np.asarray(runtime_state.get("shift_pivot_position"), dtype=np.float32)
    for vertex_index in range(len(old_positions)):
        old_positions[vertex_index] = shift_position(old_positions[vertex_index], pivot, shift_vector, shift_rotation)
        velocity_positions[vertex_index] = shift_position(
            velocity_positions[vertex_index],
            pivot,
            shift_vector,
            shift_rotation,
        )
        display_positions[vertex_index] = shift_position(display_positions[vertex_index], pivot, shift_vector, shift_rotation)
        velocities[vertex_index] = baseline.quat_rotate(shift_rotation, velocities[vertex_index])
        real_velocities[vertex_index] = baseline.quat_rotate(shift_rotation, real_velocities[vertex_index])


def prepare_substep(
    runtime_state: dict,
    substep_index: int,
    substep_count: int,
    step_dt: float,
    local_inertia: float,
    local_movement_speed_limit: float,
    local_rotation_speed_limit: float,
) -> dict:
    count = max(1, int(substep_count))
    start_ratio = float(substep_index) / float(count)
    end_ratio = float(substep_index + 1) / float(count)
    frame_start = np.asarray(runtime_state["old_world_position"], dtype=np.float32)
    frame_end = np.asarray(runtime_state["now_world_position"], dtype=np.float32)
    rot_start = np.asarray(runtime_state["old_world_rotation"], dtype=np.float32)
    rot_end = np.asarray(runtime_state["now_world_rotation"], dtype=np.float32)
    old_pos = frame_start * (1.0 - start_ratio) + frame_end * start_ratio
    now_pos = frame_start * (1.0 - end_ratio) + frame_end * end_ratio
    old_rot = quat_slerp(rot_start, rot_end, start_ratio)
    now_rot = quat_slerp(rot_start, rot_end, end_ratio)
    step_vector = now_pos - old_pos
    step_rotation = quat_from_to(old_rot, now_rot)
    axis, angle = quat_to_axis_angle(step_rotation)
    local_move_ratio = 1.0 - max(0.0, min(1.0, float(local_inertia)))
    local_rotation_ratio = local_move_ratio
    if step_dt > MC2SystemConstants.EPSILON and local_movement_speed_limit >= 0.0:
        local_vector = step_vector * (1.0 - local_move_ratio)
        local_speed = float(np.linalg.norm(local_vector)) / step_dt
        if local_speed > local_movement_speed_limit and local_speed > MC2SystemConstants.EPSILON:
            t = max(0.0, min(1.0, local_movement_speed_limit / local_speed))
            local_move_ratio = 1.0 * (1.0 - t) + local_move_ratio * t
    if step_dt > MC2SystemConstants.EPSILON and local_rotation_speed_limit >= 0.0:
        local_angle = angle * (1.0 - local_rotation_ratio)
        local_speed = math.degrees(local_angle / step_dt)
        if local_speed > local_rotation_speed_limit and local_speed > MC2SystemConstants.EPSILON:
            t = max(0.0, min(1.0, local_rotation_speed_limit / local_speed))
            local_rotation_ratio = 1.0 * (1.0 - t) + local_rotation_ratio * t
    inertia_vector = step_vector * local_move_ratio
    inertia_rotation = quat_slerp(_identity_quat(), step_rotation, local_rotation_ratio)
    return {
        "old_world_position": old_pos,
        "now_world_position": now_pos,
        "step_vector": step_vector,
        "step_rotation": step_rotation,
        "inertia_vector": inertia_vector,
        "inertia_rotation": inertia_rotation,
        "step_move_inertia_ratio": local_move_ratio,
        "step_rotation_inertia_ratio": local_rotation_ratio,
        "rotation_axis": axis,
        "angular_velocity": angle / step_dt if step_dt > MC2SystemConstants.EPSILON else 0.0,
    }


def apply_substep_inertia(
    old_positions: np.ndarray,
    velocities: np.ndarray,
    depths: np.ndarray,
    movable: np.ndarray,
    runtime_step: dict,
    depth_inertia: float,
) -> None:
    depth_inertia = max(0.0, min(1.0, float(depth_inertia)))
    if not bool(np.any(movable)):
        return
    old_world = np.asarray(runtime_step["old_world_position"], dtype=np.float32)
    step_vector = np.asarray(runtime_step["step_vector"], dtype=np.float32)
    step_rotation = np.asarray(runtime_step["step_rotation"], dtype=np.float32)
    base_vector = np.asarray(runtime_step["inertia_vector"], dtype=np.float32)
    base_rotation = np.asarray(runtime_step["inertia_rotation"], dtype=np.float32)
    for vertex_index in np.nonzero(movable)[0]:
        depth = max(0.0, min(1.0, float(depths[vertex_index])))
        ratio = depth_inertia * (1.0 - depth * depth)
        inertia_vector = base_vector * (1.0 - ratio) + step_vector * ratio
        inertia_rotation = quat_slerp(base_rotation, step_rotation, ratio)
        local = old_positions[vertex_index] - old_world
        old_positions[vertex_index] = old_world + baseline.quat_rotate(inertia_rotation, local) + inertia_vector
        velocities[vertex_index] = baseline.quat_rotate(inertia_rotation, velocities[vertex_index])


def apply_centrifugal_velocity(
    positions: np.ndarray,
    velocities: np.ndarray,
    depths: np.ndarray,
    movable: np.ndarray,
    runtime_step: dict,
    centrifugal: float,
) -> None:
    centrifugal = max(0.0, min(1.0, float(centrifugal)))
    if centrifugal <= MC2SystemConstants.EPSILON or not bool(np.any(movable)):
        return
    angular_velocity = float(runtime_step.get("angular_velocity", 0.0))
    axis = np.asarray(runtime_step.get("rotation_axis"), dtype=np.float32)
    if angular_velocity <= MC2SystemConstants.EPSILON or float(np.linalg.norm(axis)) <= MC2SystemConstants.EPSILON:
        return
    center = np.asarray(runtime_step["now_world_position"], dtype=np.float32)
    axis = math_utils.safe_normal_np(axis, np.asarray((0.0, 1.0, 0.0), dtype=np.float32))
    for vertex_index in np.nonzero(movable)[0]:
        velocity = velocities[vertex_index]
        speed = float(np.linalg.norm(velocity))
        if speed <= MC2SystemConstants.EPSILON:
            continue
        local = positions[vertex_index] - center
        radial = math_utils.project_on_plane(local, axis)
        radius = float(np.linalg.norm(radial))
        if radius <= MC2SystemConstants.EPSILON:
            continue
        n = radial / radius
        tangent = math_utils.safe_normal_np(np.cross(axis, n), np.zeros(3, dtype=np.float32))
        forward = velocity / speed
        strength = max(0.0, float(np.dot(forward, tangent)))
        mass = 1.0 + (1.0 - max(0.0, min(1.0, float(depths[vertex_index]))))
        force = mass * angular_velocity * angular_velocity * radius
        velocities[vertex_index] = velocity + n * (force * centrifugal * 0.02 * strength)
