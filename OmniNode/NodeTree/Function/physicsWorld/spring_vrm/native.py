"""VRM SpringBone 的 native C++ 调用包装。"""

from __future__ import annotations

import importlib
import time

import mathutils
import numpy as np

from ..utils.values import matrix16
from ..utils.writeback_pose import matrix_basis_from_pose_matrix
from .results import publish_spring_vrm_pose_result


_NATIVE_MODULE = None


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _NATIVE_MODULE = importlib.import_module("hotools_native")
    return _NATIVE_MODULE


def is_available() -> bool:
    try:
        module = native_module()
    except Exception:
        return False
    return hasattr(module, "solve_spring_bone_vrm_cpp")


def step_spring_vrm_slot(world, slot, dt: float, substeps: int, restart: bool) -> tuple[int, float, list[str]]:
    spec = slot.data.get("spec")
    if spec is None:
        return 0, 0.0, ["slot missing spec"]
    try:
        module = native_module()
    except Exception as exc:
        return 0, 0.0, [f"hotools_native 不可用: {exc}"]
    if not hasattr(module, "solve_spring_bone_vrm_cpp"):
        return 0, 0.0, ["hotools_native 缺少 solve_spring_bone_vrm_cpp"]

    frame_state = slot.data.setdefault("frame_state", {})
    if restart or frame_state.get("spec_hash") != spec.spec_hash:
        frame_state.clear()
        frame_state["spec_hash"] = spec.spec_hash
        frame_state["chains"] = {}

    armature = spec.armature
    if armature is None or getattr(armature, "pose", None) is None:
        return 0, 0.0, ["armature 无效"]

    chain_states = frame_state.setdefault("chains", {})
    published = 0
    errors: list[str] = []
    started = time.perf_counter()

    for chain in spec.chains:
        try:
            count = _step_chain(
                module,
                world,
                spec,
                chain,
                chain_states.setdefault(chain.root_bone, {}),
                dt,
                substeps,
            )
            published += count
        except Exception as exc:
            errors.append(f"{chain.root_bone}: {exc}")

    return published, (time.perf_counter() - started) * 1000.0, errors


def _step_chain(module, world, spec, chain, chain_state: dict, dt: float, substeps: int) -> int:
    records = _chain_records(spec.armature, chain)
    bone_count = len(records)
    if bone_count <= 0 or not bool(chain.enabled):
        return 0

    arrays = _build_arrays(spec.armature, chain, chain_state, records)
    if arrays is None:
        return 0

    (
        current_tails,
        prev_tails,
        target_matrices,
        target_quaternions,
        current_heads,
        current_pose_matrices,
        current_pose_quaternions,
        parent_pose_quaternions,
        current_pose_tails,
        lengths,
        init_axis_local,
        init_axis_parent,
        init_rotations,
        init_scales,
        parent_indices,
        pinned,
        use_connect,
    ) = arrays

    collider_types, collider_groups, collider_centers, collider_segment_a, collider_segment_b, collider_radii = _empty_collision_arrays()
    armature_world = np.asarray(matrix16(spec.armature.matrix_world), dtype=np.float32)
    armature_world_inv = np.asarray(matrix16(spec.armature.matrix_world.inverted()), dtype=np.float32)
    root_quaternion = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    root_tail_world = np.zeros(3, dtype=np.float32)
    gravity_dir = np.asarray(chain.gravity_dir, dtype=np.float32)
    hit_radii = np.zeros(bone_count, dtype=np.float32)
    collided_by_groups = np.zeros(bone_count, dtype=np.int32)

    module.solve_spring_bone_vrm_cpp(
        current_tails,
        prev_tails,
        target_matrices,
        target_quaternions,
        current_heads,
        current_pose_matrices,
        current_pose_quaternions,
        parent_pose_quaternions,
        current_pose_tails,
        lengths,
        init_axis_local,
        init_axis_parent,
        init_rotations,
        init_scales,
        parent_indices,
        pinned,
        use_connect,
        root_quaternion,
        root_tail_world,
        armature_world,
        armature_world_inv,
        gravity_dir,
        hit_radii,
        collided_by_groups,
        collider_types,
        collider_groups,
        collider_centers,
        collider_segment_a,
        collider_segment_b,
        collider_radii,
        float(dt),
        max(1, int(substeps)),
        float(chain.stiffness_force),
        float(chain.drag_force),
        float(chain.gravity_power),
    )

    target_pose_matrices: dict[str, mathutils.Matrix] = {}
    published = 0
    tails = chain_state.setdefault("tails", {})
    last_results = []
    frame = int(getattr(world.frame_context, "frame", 0) or 0)

    for index, record in enumerate(records):
        bone_name = record["bone_name"]
        target_matrix = _matrix_from_row(target_matrices[index])
        target_pose_matrices[bone_name] = target_matrix
        basis_matrix = matrix_basis_from_pose_matrix(record["pose_bone"], target_matrix, target_pose_matrices)
        tail = _tuple3(current_tails[index])
        tails[bone_name] = {
            "current_tail": tail,
            "prev_tail": _tuple3(prev_tails[index]),
        }
        result = publish_spring_vrm_pose_result(
            world,
            slot_id=spec.slot_id,
            armature_ptr=spec.armature_ptr,
            armature_data_ptr=spec.armature_data_ptr,
            frame=frame,
            generation=world.generation,
            bone_name=bone_name,
            pose_index=int(record["pose_index"]),
            matrix_basis=basis_matrix,
            target_pose_matrix=target_matrix,
            current_tail=tail,
            chain_root=chain.root_bone,
            backend="cpp",
        )
        if result is not None:
            last_results.append(result)
            published += 1

    chain_state["last_results"] = last_results
    return published


def _chain_records(armature, chain) -> list[dict]:
    pose_bones = armature.pose.bones
    pose_index = {pose_bone.name: index for index, pose_bone in enumerate(pose_bones)}
    records = []
    for bone_name in chain.simulated_bones:
        pose_bone = pose_bones.get(bone_name)
        if pose_bone is None:
            continue
        parent = getattr(pose_bone, "parent", None)
        records.append({
            "bone_name": bone_name,
            "pose_bone": pose_bone,
            "parent": parent,
            "parent_name": parent.name if parent is not None else "",
            "pose_index": int(pose_index.get(bone_name, -1)),
        })
    return records


def _build_arrays(armature, chain, chain_state: dict, records: list[dict]):
    bone_count = len(records)
    parent_lookup = {record["bone_name"]: index for index, record in enumerate(records)}
    tails = chain_state.setdefault("tails", {})

    current_tails = np.empty((bone_count, 3), dtype=np.float32)
    prev_tails = np.empty((bone_count, 3), dtype=np.float32)
    target_matrices = np.empty((bone_count, 16), dtype=np.float32)
    target_quaternions = np.empty((bone_count, 4), dtype=np.float32)
    current_heads = np.empty((bone_count, 3), dtype=np.float32)
    current_pose_matrices = np.empty((bone_count, 16), dtype=np.float32)
    current_pose_quaternions = np.empty((bone_count, 4), dtype=np.float32)
    parent_pose_quaternions = np.empty((bone_count, 4), dtype=np.float32)
    current_pose_tails = np.empty((bone_count, 3), dtype=np.float32)
    lengths = np.empty(bone_count, dtype=np.float32)
    init_axis_local = np.empty((bone_count, 3), dtype=np.float32)
    init_axis_parent = np.empty((bone_count, 3), dtype=np.float32)
    init_rotations = np.empty((bone_count, 4), dtype=np.float32)
    init_scales = np.empty((bone_count, 3), dtype=np.float32)
    parent_indices = np.full(bone_count, -1, dtype=np.int32)
    pinned = np.zeros(bone_count, dtype=np.uint8)
    use_connect = np.zeros(bone_count, dtype=np.uint8)

    armature_world = armature.matrix_world
    for index, record in enumerate(records):
        pose_bone = record["pose_bone"]
        parent = record["parent"]
        parent_indices[index] = int(parent_lookup.get(record["parent_name"], -1))
        use_connect[index] = 1 if bool(getattr(getattr(pose_bone, "bone", None), "use_connect", False)) else 0

        head = armature_world @ pose_bone.head
        tail = armature_world @ pose_bone.tail
        fallback_axis = pose_bone.tail - pose_bone.head
        if fallback_axis.length <= 1.0e-8:
            fallback_axis = mathutils.Vector((0.0, 0.0, 1.0))
        else:
            fallback_axis.normalize()

        tail_state = tails.get(record["bone_name"]) if isinstance(tails, dict) else None
        current_tail = _vector_from_state(tail_state, "current_tail", tail)
        prev_tail = _vector_from_state(tail_state, "prev_tail", current_tail)

        _write_vec3(current_tails, index, current_tail)
        _write_vec3(prev_tails, index, prev_tail)
        _write_vec3(current_heads, index, head)
        _write_vec3(current_pose_tails, index, tail)
        _write_matrix(current_pose_matrices, index, pose_bone.matrix)
        _write_matrix(target_matrices, index, pose_bone.matrix)
        _write_quat(current_pose_quaternions, index, pose_bone.matrix.to_quaternion())
        _write_quat(target_quaternions, index, pose_bone.matrix.to_quaternion())
        _write_quat(parent_pose_quaternions, index, parent.matrix.to_quaternion() if parent is not None else None)
        _write_vec3(init_axis_local, index, fallback_axis)
        _write_vec3(init_axis_parent, index, fallback_axis)
        _write_quat(init_rotations, index, pose_bone.matrix.to_quaternion())
        scale = pose_bone.matrix.to_scale()
        init_scales[index, 0] = float(scale.x)
        init_scales[index, 1] = float(scale.y)
        init_scales[index, 2] = float(scale.z)
        lengths[index] = max(float((tail - head).length), 0.0)

    return (
        current_tails,
        prev_tails,
        target_matrices,
        target_quaternions,
        current_heads,
        current_pose_matrices,
        current_pose_quaternions,
        parent_pose_quaternions,
        current_pose_tails,
        lengths,
        init_axis_local,
        init_axis_parent,
        init_rotations,
        init_scales,
        parent_indices,
        pinned,
        use_connect,
    )


def _empty_collision_arrays() -> tuple:
    return (
        np.empty(0, dtype=np.int32),
        np.empty(0, dtype=np.int32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty(0, dtype=np.float32),
    )


def _vector_from_state(state, key: str, fallback: mathutils.Vector) -> mathutils.Vector:
    if isinstance(state, dict):
        value = state.get(key)
        if value is not None:
            try:
                return mathutils.Vector((float(value[0]), float(value[1]), float(value[2])))
            except Exception:
                pass
    return fallback.copy()


def _write_vec3(array: np.ndarray, index: int, value) -> None:
    array[index, 0] = float(value[0])
    array[index, 1] = float(value[1])
    array[index, 2] = float(value[2])


def _write_quat(array: np.ndarray, index: int, value) -> None:
    if value is None:
        array[index] = (0.0, 0.0, 0.0, 1.0)
        return
    array[index, 0] = float(value.x)
    array[index, 1] = float(value.y)
    array[index, 2] = float(value.z)
    array[index, 3] = float(value.w)


def _write_matrix(array: np.ndarray, index: int, value) -> None:
    array[index] = np.asarray(matrix16(value), dtype=np.float32)


def _matrix_from_row(row) -> mathutils.Matrix:
    values = [float(item) for item in row]
    return mathutils.Matrix((
        (values[0], values[1], values[2], values[3]),
        (values[4], values[5], values[6], values[7]),
        (values[8], values[9], values[10], values[11]),
        (values[12], values[13], values[14], values[15]),
    ))


def _tuple3(value) -> tuple[float, float, float]:
    return (float(value[0]), float(value[1]), float(value[2]))
