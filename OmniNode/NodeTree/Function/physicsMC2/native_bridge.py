"""MC2 native 后端的 Python ABI 打包层。

当前只做数组视图打包和 native 可用性探测，不调用 C++ 求解。正式 C++ 后端
应从这里接入，避免把 buffer contract 散落到节点入口或 solver 调度里。
"""

import importlib

import bpy
import numpy as np

from . import collision
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


def _array(state: dict, key: str, dtype, shape_tail: tuple[int, ...] = ()) -> np.ndarray:
    value = np.ascontiguousarray(state[key], dtype=dtype)
    if shape_tail and value.shape[-len(shape_tail):] != shape_tail:
        raise ValueError(f"MC2 native ABI field {key} shape mismatch: {value.shape}")
    return value


def state_arrays_for_native(state: dict) -> dict:
    return {
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
