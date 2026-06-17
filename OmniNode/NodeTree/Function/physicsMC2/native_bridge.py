"""MC2 native 后端的 Python ABI 打包层。

当前只做数组视图打包和 native 可用性探测，不调用 C++ 求解。正式 C++ 后端
应从这里接入，避免把 buffer contract 散落到节点入口或 solver 调度里。
"""

import importlib

import bpy
import numpy as np

from . import collision, params
from .constants import MC2_SOLVER_VERSION

_NATIVE_MODULE = None
_NATIVE_IMPORT_ERROR = None


def native_module():
    global _NATIVE_MODULE
    global _NATIVE_IMPORT_ERROR
    if _NATIVE_MODULE is not None:
        return _NATIVE_MODULE
    try:
        _NATIVE_MODULE = importlib.import_module("hotools_native")
        _NATIVE_IMPORT_ERROR = None
    except Exception as exc:
        _NATIVE_MODULE = False
        _NATIVE_IMPORT_ERROR = repr(exc)
        return None
    return _NATIVE_MODULE


def native_status(function_name: str = "solve_meshcloth_mc2") -> dict:
    module = native_module()
    available = bool(module is not None and hasattr(module, function_name))
    return {
        "module": "hotools_native",
        "function": function_name,
        "available": available,
        "import_error": None if module is not None else _NATIVE_IMPORT_ERROR,
    }


def has_function(function_name: str) -> bool:
    module = native_module()
    return bool(module is not None and hasattr(module, function_name))


def _array(state: dict, key: str, dtype, shape_tail: tuple[int, ...] = ()) -> np.ndarray:
    value = np.ascontiguousarray(state[key], dtype=dtype)
    if shape_tail and value.shape[-len(shape_tail):] != shape_tail:
        raise ValueError(f"MC2 native ABI field {key} shape mismatch: {value.shape}")
    return value


def project_neighbor_constraints(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    starts: np.ndarray,
    counts: np.ndarray,
    neighbors: np.ndarray,
    rest_lengths: np.ndarray,
    stiffness_values: np.ndarray,
    velocity_positions: np.ndarray,
    velocity_attenuation: float,
) -> bool:
    module = native_module()
    function = getattr(module, "project_neighbor_constraints_mc2", None) if module is not None else None
    if function is None:
        return False

    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    velocity_positions_view = np.ascontiguousarray(velocity_positions, dtype=np.float32)
    function(
        positions_view,
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        np.ascontiguousarray(starts, dtype=np.int32),
        np.ascontiguousarray(counts, dtype=np.int32),
        np.ascontiguousarray(neighbors, dtype=np.int32),
        np.ascontiguousarray(rest_lengths, dtype=np.float32),
        np.ascontiguousarray(stiffness_values, dtype=np.float32),
        velocity_positions_view,
        float(velocity_attenuation),
    )
    if positions_view is not positions:
        positions[...] = positions_view
    if velocity_positions_view is not velocity_positions:
        velocity_positions[...] = velocity_positions_view
    return True


def project_tether(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    root_indices: np.ndarray,
    root_rest_lengths: np.ndarray,
    velocity_positions: np.ndarray,
    stiffness: float,
    compression: float,
    stretch: float,
) -> bool:
    module = native_module()
    function = getattr(module, "project_tether_mc2", None) if module is not None else None
    if function is None:
        return False

    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    velocity_positions_view = np.ascontiguousarray(velocity_positions, dtype=np.float32)
    function(
        positions_view,
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        np.ascontiguousarray(root_indices, dtype=np.int32),
        np.ascontiguousarray(root_rest_lengths, dtype=np.float32),
        velocity_positions_view,
        float(stiffness),
        float(compression),
        float(stretch),
    )
    if positions_view is not positions:
        positions[...] = positions_view
    if velocity_positions_view is not velocity_positions:
        velocity_positions[...] = velocity_positions_view
    return True


def project_motion_constraint(
    positions: np.ndarray,
    base_positions: np.ndarray,
    base_normals: np.ndarray,
    inv_masses: np.ndarray,
    depths: np.ndarray,
    max_distance_param: dict,
    motion_stiffness_param: dict,
    backstop_radius_param: dict,
    backstop_distance_param: dict,
    world_scale: float,
    velocity_positions: np.ndarray,
) -> bool:
    module = native_module()
    function = getattr(module, "project_motion_constraints_mc2", None) if module is not None else None
    if function is None:
        return False

    motion_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32) ** 2, 0.0, 1.0)
    scale = max(float(world_scale), 0.0)
    max_distances = np.ascontiguousarray(params.sample_param(max_distance_param, motion_depths) * scale, dtype=np.float32)
    stiffness_values = np.ascontiguousarray(
        np.clip(params.sample_param(motion_stiffness_param, motion_depths), 0.0, 1.0),
        dtype=np.float32,
    )
    backstop_radii = np.ascontiguousarray(params.sample_param(backstop_radius_param, motion_depths) * scale, dtype=np.float32)
    backstop_distances = np.ascontiguousarray(
        params.sample_param(backstop_distance_param, motion_depths) * scale,
        dtype=np.float32,
    )

    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    velocity_positions_view = np.ascontiguousarray(velocity_positions, dtype=np.float32)
    function(
        positions_view,
        np.ascontiguousarray(base_positions, dtype=np.float32),
        np.ascontiguousarray(base_normals, dtype=np.float32),
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        max_distances,
        stiffness_values,
        backstop_radii,
        backstop_distances,
        velocity_positions_view,
    )
    if positions_view is not positions:
        positions[...] = positions_view
    if velocity_positions_view is not velocity_positions:
        velocity_positions[...] = velocity_positions_view
    return True


def apply_post_step(
    positions: np.ndarray,
    old_positions: np.ndarray,
    velocity_positions: np.ndarray,
    velocity: np.ndarray,
    real_velocity: np.ndarray,
    friction: np.ndarray,
    static_friction: np.ndarray,
    collision_normals: np.ndarray,
    inv_masses: np.ndarray,
    step_dt: float,
    dynamic_friction: float,
    static_friction_speed: float,
    particle_speed_limit: float,
) -> bool:
    module = native_module()
    function = getattr(module, "apply_post_step_mc2", None) if module is not None else None
    if function is None:
        return False

    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    old_positions_view = np.ascontiguousarray(old_positions, dtype=np.float32)
    velocity_positions_view = np.ascontiguousarray(velocity_positions, dtype=np.float32)
    velocity_view = np.ascontiguousarray(velocity, dtype=np.float32)
    real_velocity_view = np.ascontiguousarray(real_velocity, dtype=np.float32)
    friction_view = np.ascontiguousarray(friction, dtype=np.float32)
    static_friction_view = np.ascontiguousarray(static_friction, dtype=np.float32)
    function(
        positions_view,
        old_positions_view,
        velocity_positions_view,
        velocity_view,
        real_velocity_view,
        friction_view,
        static_friction_view,
        np.ascontiguousarray(collision_normals, dtype=np.float32),
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        float(step_dt),
        float(dynamic_friction),
        float(static_friction_speed),
        float(particle_speed_limit),
    )
    if positions_view is not positions:
        positions[...] = positions_view
    if old_positions_view is not old_positions:
        old_positions[...] = old_positions_view
    if velocity_positions_view is not velocity_positions:
        velocity_positions[...] = velocity_positions_view
    if velocity_view is not velocity:
        velocity[...] = velocity_view
    if real_velocity_view is not real_velocity:
        real_velocity[...] = real_velocity_view
    if friction_view is not friction:
        friction[...] = friction_view
    if static_friction_view is not static_friction:
        static_friction[...] = static_friction_view
    return True


def project_collisions(
    positions: np.ndarray,
    base_positions: np.ndarray,
    inv_masses: np.ndarray,
    collision_radii: np.ndarray,
    collided_by_groups: int,
    collider_arrays: dict,
    collision_normals: np.ndarray,
    friction: np.ndarray,
) -> bool:
    module = native_module()
    function = getattr(module, "project_collisions_mc2", None) if module is not None else None
    if function is None:
        return False

    collider_types = np.ascontiguousarray(collider_arrays.get("collider_types", ()), dtype=np.int32)
    if len(collider_types) == 0 or int(collided_by_groups) == 0:
        return True

    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    collision_normals_view = np.ascontiguousarray(collision_normals, dtype=np.float32)
    friction_view = np.ascontiguousarray(friction, dtype=np.float32)
    function(
        positions_view,
        np.ascontiguousarray(base_positions, dtype=np.float32),
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        np.ascontiguousarray(collision_radii, dtype=np.float32),
        collision_normals_view,
        friction_view,
        int(collided_by_groups),
        collider_types,
        np.ascontiguousarray(collider_arrays.get("collider_group_bits", ()), dtype=np.int32),
        np.ascontiguousarray(collider_arrays.get("collider_centers", ()), dtype=np.float32),
        np.ascontiguousarray(collider_arrays.get("collider_segment_a", ()), dtype=np.float32),
        np.ascontiguousarray(collider_arrays.get("collider_segment_b", ()), dtype=np.float32),
        np.ascontiguousarray(collider_arrays.get("collider_radii", ()), dtype=np.float32),
    )
    if positions_view is not positions:
        positions[...] = positions_view
    if collision_normals_view is not collision_normals:
        collision_normals[...] = collision_normals_view
    if friction_view is not friction:
        friction[...] = friction_view
    return True


def project_triangle_bending(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    dihedral_pairs: np.ndarray,
    dihedral_rest_angles: np.ndarray,
    dihedral_signs: np.ndarray,
    volume_pairs: np.ndarray,
    volume_rest: np.ndarray,
    stiffness_values: np.ndarray,
) -> bool:
    module = native_module()
    function = getattr(module, "project_triangle_bending_mc2", None) if module is not None else None
    if function is None:
        return False

    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    function(
        positions_view,
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        np.ascontiguousarray(dihedral_pairs, dtype=np.int32).reshape((-1, 4)),
        np.ascontiguousarray(dihedral_rest_angles, dtype=np.float32),
        np.ascontiguousarray(dihedral_signs, dtype=np.int32),
        np.ascontiguousarray(volume_pairs, dtype=np.int32).reshape((-1, 4)),
        np.ascontiguousarray(volume_rest, dtype=np.float32),
        np.ascontiguousarray(stiffness_values, dtype=np.float32),
    )
    if positions_view is not positions:
        positions[...] = positions_view
    return True


def project_angle_constraints(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    parent_indices: np.ndarray,
    baseline_start: np.ndarray,
    baseline_count: np.ndarray,
    baseline_data: np.ndarray,
    step_basic_positions: np.ndarray,
    step_basic_rotations: np.ndarray,
    restoration_values: np.ndarray,
    limit_values: np.ndarray,
    velocity_positions: np.ndarray,
    restoration_velocity_attenuation: float,
    restoration_gravity_falloff: float,
    limit_stiffness: float,
) -> bool:
    module = native_module()
    function = getattr(module, "project_angle_constraints_mc2", None) if module is not None else None
    if function is None:
        return False

    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    velocity_positions_view = np.ascontiguousarray(velocity_positions, dtype=np.float32)
    function(
        positions_view,
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        np.ascontiguousarray(parent_indices, dtype=np.int32),
        np.ascontiguousarray(baseline_start, dtype=np.int32),
        np.ascontiguousarray(baseline_count, dtype=np.int32),
        np.ascontiguousarray(baseline_data, dtype=np.int32),
        np.ascontiguousarray(step_basic_positions, dtype=np.float32),
        np.ascontiguousarray(step_basic_rotations, dtype=np.float32),
        np.ascontiguousarray(restoration_values, dtype=np.float32),
        np.ascontiguousarray(limit_values, dtype=np.float32),
        velocity_positions_view,
        float(restoration_velocity_attenuation),
        float(restoration_gravity_falloff),
        float(limit_stiffness),
    )
    if positions_view is not positions:
        positions[...] = positions_view
    if velocity_positions_view is not velocity_positions:
        velocity_positions[...] = velocity_positions_view
    return True


def apply_substep_inertia(
    old_positions: np.ndarray,
    velocity: np.ndarray,
    depths: np.ndarray,
    inv_masses: np.ndarray,
    runtime_step: dict,
    depth_inertia: float,
) -> bool:
    module = native_module()
    function = getattr(module, "apply_substep_inertia_mc2", None) if module is not None else None
    if function is None:
        return False

    zero3 = np.zeros(3, dtype=np.float32)
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    old_positions_view = np.ascontiguousarray(old_positions, dtype=np.float32)
    velocity_view = np.ascontiguousarray(velocity, dtype=np.float32)
    function(
        old_positions_view,
        velocity_view,
        np.ascontiguousarray(depths, dtype=np.float32),
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        _state_vector(runtime_step, "old_world_position", zero3),
        _state_vector(runtime_step, "step_vector", zero3),
        _state_vector(runtime_step, "step_rotation", identity),
        _state_vector(runtime_step, "inertia_vector", zero3),
        _state_vector(runtime_step, "inertia_rotation", identity),
        float(depth_inertia),
    )
    if old_positions_view is not old_positions:
        old_positions[...] = old_positions_view
    if velocity_view is not velocity:
        velocity[...] = velocity_view
    return True


def apply_centrifugal_velocity(
    positions: np.ndarray,
    velocity: np.ndarray,
    depths: np.ndarray,
    inv_masses: np.ndarray,
    runtime_step: dict,
    centrifugal: float,
) -> bool:
    module = native_module()
    function = getattr(module, "apply_centrifugal_velocity_mc2", None) if module is not None else None
    if function is None:
        return False

    zero3 = np.zeros(3, dtype=np.float32)
    positions_view = np.ascontiguousarray(positions, dtype=np.float32)
    velocity_view = np.ascontiguousarray(velocity, dtype=np.float32)
    function(
        positions_view,
        velocity_view,
        np.ascontiguousarray(depths, dtype=np.float32),
        np.ascontiguousarray(inv_masses, dtype=np.float32),
        _state_vector(runtime_step, "now_world_position", zero3),
        _state_vector(runtime_step, "rotation_axis", zero3),
        float(runtime_step.get("angular_velocity", 0.0) or 0.0),
        float(centrifugal),
    )
    if velocity_view is not velocity:
        velocity[...] = velocity_view
    return True


def _state_vector(state: dict, key: str, default) -> np.ndarray:
    value = np.ascontiguousarray(state.get(key, default), dtype=np.float32).reshape(-1)
    if value.shape != (len(default),):
        value = np.ascontiguousarray(default, dtype=np.float32)
    return value


def _inertia_state_arrays(state: dict) -> dict:
    inertia_state = state.get("inertia_state") if isinstance(state.get("inertia_state"), dict) else {}
    zero3 = np.zeros(3, dtype=np.float32)
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    return {
        "inertia_old_component_position": _state_vector(inertia_state, "old_component_position", zero3),
        "inertia_old_component_rotation": _state_vector(inertia_state, "old_component_rotation", identity),
        "inertia_shift_pivot_position": _state_vector(inertia_state, "shift_pivot_position", zero3),
        "inertia_smoothing_velocity": _state_vector(inertia_state, "smoothing_velocity", zero3),
        "inertia_frame_component_shift_vector": _state_vector(inertia_state, "frame_component_shift_vector", zero3),
        "inertia_frame_component_shift_rotation": _state_vector(inertia_state, "frame_component_shift_rotation", identity),
        "inertia_old_world_position": _state_vector(inertia_state, "old_world_position", zero3),
        "inertia_old_world_rotation": _state_vector(inertia_state, "old_world_rotation", identity),
        "inertia_now_world_position": _state_vector(inertia_state, "now_world_position", zero3),
        "inertia_now_world_rotation": _state_vector(inertia_state, "now_world_rotation", identity),
        "inertia_step_vector": _state_vector(inertia_state, "step_vector", zero3),
        "inertia_step_rotation": _state_vector(inertia_state, "step_rotation", identity),
        "inertia_vector": _state_vector(inertia_state, "inertia_vector", zero3),
        "inertia_rotation": _state_vector(inertia_state, "inertia_rotation", identity),
        "inertia_rotation_axis": _state_vector(inertia_state, "rotation_axis", zero3),
        "inertia_angular_velocity": float(inertia_state.get("angular_velocity", 0.0) or 0.0),
        "inertia_teleport_state": int(inertia_state.get("teleport_state", 0) or 0),
    }


def state_arrays_for_native(state: dict) -> dict:
    arrays = {
        "schema_version": int(MC2_SOLVER_VERSION),
        "vertex_count": int(state["vertex_count"]),
        "positions": _array(state, "next_positions", np.float32, (3,)),
        "old_positions": _array(state, "old_positions", np.float32, (3,)),
        "base_positions": _array(state, "base_positions", np.float32, (3,)),
        "rest_world_positions": _array(state, "rest_world_positions", np.float32, (3,)),
        "base_normals": _array(state, "base_normals", np.float32, (3,)),
        "rest_world_normals": _array(state, "rest_world_normals", np.float32, (3,)),
        "velocity_positions": _array(state, "velocity_positions", np.float32, (3,)),
        "velocity": _array(state, "velocity", np.float32, (3,)),
        "real_velocity": _array(state, "real_velocity", np.float32, (3,)),
        "collision_normals": _array(state, "collision_normals", np.float32, (3,)),
        "attributes": _array(state, "attributes", np.uint8),
        "depths": _array(state, "depths", np.float32),
        "inv_masses": _array(state, "inv_masses", np.float32),
        "friction": _array(state, "friction", np.float32),
        "static_friction": _array(state, "static_friction", np.float32),
        "root_indices": _array(state, "root_indices", np.int32),
        "parent_indices": _array(state, "parent_indices", np.int32),
        "root_rest_lengths": _array(state, "root_rest_lengths", np.float32),
        "baseline_start": _array(state, "baseline_start", np.int32),
        "baseline_count": _array(state, "baseline_count", np.int32),
        "baseline_data": _array(state, "baseline_data", np.int32),
        "baseline_flags": _array(state, "baseline_flags", np.uint8),
        "base_rotations": _array(state, "base_rotations", np.float32, (4,)),
        "step_basic_positions": _array(state, "step_basic_positions", np.float32, (3,)),
        "step_basic_rotations": _array(state, "step_basic_rotations", np.float32, (4,)),
        "vertex_local_positions": _array(state, "vertex_local_positions", np.float32, (3,)),
        "vertex_local_rotations": _array(state, "vertex_local_rotations", np.float32, (4,)),
        "tether_rest_lengths": _array(state, "tether_rest_lengths", np.float32),
        "edge_i": _array(state, "edge_i", np.int32),
        "edge_j": _array(state, "edge_j", np.int32),
        "edge_rest": _array(state, "edge_rest", np.float32),
        "edge_type": _array(state, "edge_type", np.int32),
        "distance_start": _array(state, "distance_start", np.int32),
        "distance_count": _array(state, "distance_count", np.int32),
        "distance_data": _array(state, "distance_data", np.int32),
        "distance_rest": _array(state, "distance_rest", np.float32),
        "bend_kind": str(state.get("bend_kind", "")),
        "bend_distance_i": _array(state, "bend_distance_i", np.int32),
        "bend_distance_j": _array(state, "bend_distance_j", np.int32),
        "bend_distance_rest": _array(state, "bend_distance_rest", np.float32),
        "bend_distance_type": _array(state, "bend_distance_type", np.int32),
        "bend_distance_start": _array(state, "bend_distance_start", np.int32),
        "bend_distance_count": _array(state, "bend_distance_count", np.int32),
        "bend_distance_data": _array(state, "bend_distance_data", np.int32),
        "bend_distance_neighbor_rest": _array(state, "bend_distance_neighbor_rest", np.float32),
        "triangle_pairs": _array(state, "triangle_pairs", np.int32, (4,)),
        "dihedral_pairs": _array(state, "dihedral_pairs", np.int32, (4,)),
        "dihedral_rest_angles": _array(state, "dihedral_rest_angles", np.float32),
        "dihedral_signs": _array(state, "dihedral_signs", np.int8),
        "volume_pairs": _array(state, "volume_pairs", np.int32, (4,)),
        "volume_rest": _array(state, "volume_rest", np.float32),
        "collision_radii": _array(state, "collision_radii", np.float32),
        "collided_by_groups": int(state.get("collided_by_groups", 0)),
    }
    arrays.update(_inertia_state_arrays(state))
    return arrays


def param_slots_for_native(state: dict) -> dict:
    slots = dict(state.get("param_slots") or {})
    result = {}
    for name, slot in slots.items():
        if not isinstance(slot, dict):
            result[name] = {"mode": "none", "value": 0.0, "samples": np.empty(0, dtype=np.float32)}
            continue
        mode = str(slot.get("mode", "scalar") or "scalar")
        value = float(slot.get("value", 0.0) or 0.0)
        samples = slot.get("samples")
        sample_array = (
            np.empty(0, dtype=np.float32)
            if samples is None
            else np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
        )
        result[name] = {
            "mode": mode,
            "value": value,
            "samples": sample_array,
        }
    return result


def build_abi_view(
    state: dict,
    obj: bpy.types.Object,
    colliders: list[dict] | None,
    function_name: str = "solve_meshcloth_mc2",
) -> dict:
    return {
        "status": native_status(function_name),
        "state": state_arrays_for_native(state),
        "params": param_slots_for_native(state),
        "colliders": collision.collider_arrays_for_native(state, obj, colliders),
    }
