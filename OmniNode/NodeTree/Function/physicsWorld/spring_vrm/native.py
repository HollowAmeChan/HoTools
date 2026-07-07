"""VRM SpringBone 的 native C++ 调用包装。"""

from __future__ import annotations

import importlib
import time

import mathutils
import numpy as np

from ..names import (
    COLLIDER_TYPE_BOX,
    COLLIDER_TYPE_CAPSULE,
    COLLIDER_TYPE_PLANE,
    COLLIDER_TYPE_SPHERE,
)
from ..utils.geometry import (
    clamp_int,
    matrix_scale_radius,
    numpy_vec3,
    signed_third_axis_length,
    vec3_length,
)
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

    (
        collider_types,
        collider_groups,
        collider_centers,
        collider_segment_a,
        collider_segment_b,
        collider_radii,
    ) = _collision_arrays_from_world(world, spec.armature, chain)
    armature_world = np.asarray(matrix16(spec.armature.matrix_world), dtype=np.float32)
    armature_world_inv = np.asarray(matrix16(spec.armature.matrix_world.inverted()), dtype=np.float32)
    root_quaternion = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    root_tail_world = np.zeros(3, dtype=np.float32)
    gravity_dir = np.asarray(chain.gravity_dir, dtype=np.float32)
    hit_radii, collided_by_groups = _bone_collision_profiles(spec.armature, records)

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


def _collision_arrays_from_world(world, armature, chain) -> tuple:
    snapshot = getattr(world, "collider_snapshot", None)
    colliders = snapshot.get("colliders") if isinstance(snapshot, dict) else None
    if not colliders:
        return _empty_collision_arrays()

    chain_bones = set(str(name or "") for name in getattr(chain, "bones", ()) or ())
    collider_types = []
    collider_groups = []
    collider_centers = []
    collider_segment_a = []
    collider_segment_b = []
    collider_radii = []
    zero = np.zeros(3, dtype=np.float32)

    for collider in colliders:
        if not isinstance(collider, dict):
            continue
        if _is_self_chain_collider(collider, armature, chain_bones):
            continue

        collider_type = str(collider.get("type", "SPHERE") or "SPHERE")
        center = numpy_vec3(collider.get("center"))
        if collider_type == "SPHERE":
            if center is None:
                continue
            segment_a = center
            segment_b = center
            radius = max(float(collider.get("radius", 0.0) or 0.0), 0.0)
            if radius <= 1.0e-8:
                continue
            type_code = COLLIDER_TYPE_SPHERE
        elif collider_type == "CAPSULE":
            segment_a = numpy_vec3(collider.get("segment_a"))
            segment_b = numpy_vec3(collider.get("segment_b"))
            if segment_a is None or segment_b is None:
                continue
            if center is None:
                center = (segment_a + segment_b) * 0.5
            radius = max(float(collider.get("radius", 0.0) or 0.0), 0.0)
            if radius <= 1.0e-8:
                continue
            type_code = COLLIDER_TYPE_CAPSULE
        elif collider_type == "PLANE":
            if center is None:
                continue
            normal = numpy_vec3(collider.get("normal"))
            if normal is None or vec3_length(normal) <= 1.0e-8:
                continue
            segment_a = normal
            segment_b = zero
            radius = 0.0
            type_code = COLLIDER_TYPE_PLANE
        elif collider_type == "BOX":
            if center is None:
                continue
            axis_x = numpy_vec3(collider.get("box_axis_x"))
            axis_y = numpy_vec3(collider.get("box_axis_y"))
            axis_z = numpy_vec3(collider.get("box_axis_z"))
            signed_half_z = signed_third_axis_length(axis_x, axis_y, axis_z)
            if axis_x is None or axis_y is None or signed_half_z is None:
                continue
            segment_a = axis_x
            segment_b = axis_y
            radius = signed_half_z
            type_code = COLLIDER_TYPE_BOX
        else:
            continue

        collider_types.append(type_code)
        collider_groups.append(max(1, min(16, int(collider.get("primary_group", 1) or 1))))
        collider_centers.append(center)
        collider_segment_a.append(segment_a)
        collider_segment_b.append(segment_b)
        collider_radii.append(radius)

    if not collider_types:
        return _empty_collision_arrays()

    return (
        np.ascontiguousarray(collider_types, dtype=np.int32),
        np.ascontiguousarray(collider_groups, dtype=np.int32),
        np.ascontiguousarray(collider_centers, dtype=np.float32).reshape((-1, 3)),
        np.ascontiguousarray(collider_segment_a, dtype=np.float32).reshape((-1, 3)),
        np.ascontiguousarray(collider_segment_b, dtype=np.float32).reshape((-1, 3)),
        np.ascontiguousarray(collider_radii, dtype=np.float32),
    )


def _bone_collision_profiles(armature, records: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    hit_radii = np.zeros(len(records), dtype=np.float32)
    collided_by_groups = np.zeros(len(records), dtype=np.int32)
    for index, record in enumerate(records):
        radius, mask = _bone_collision_profile(armature, str(record.get("bone_name") or ""))
        hit_radii[index] = float(radius)
        collided_by_groups[index] = int(mask)
    return hit_radii, collided_by_groups


def _bone_collision_profile(armature, bone_name: str) -> tuple[float, int]:
    bone = getattr(getattr(armature, "data", None), "bones", {}).get(bone_name)
    props = getattr(bone, "hotools_collision", None) if bone is not None else None
    if props is None:
        return 0.0, 0

    collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
    if collision_type not in {"SPHERE", "CAPSULE"}:
        return 0.0, 0

    pose_bone = getattr(getattr(armature, "pose", None), "bones", {}).get(bone_name)
    local_matrix = pose_bone.matrix if pose_bone is not None else bone.matrix_local
    radius = max(float(getattr(props, "radius", 0.0) or 0.0), 0.0)
    radius *= matrix_scale_radius(armature.matrix_world @ local_matrix)
    if radius <= 1.0e-8:
        return 0.0, 0
    return radius, clamp_int(getattr(props, "collided_by_groups", 0), 0, 0xFFFF, 0)


def _is_self_chain_collider(collider: dict, armature, chain_bones: set[str]) -> bool:
    if collider.get("owner_type") != "BONE":
        return False
    if collider.get("owner") is not armature:
        return False
    return str(collider.get("bone") or "") in chain_bones


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
