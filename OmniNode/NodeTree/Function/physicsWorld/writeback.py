"""
physicsWorld.writeback — 物理写回算法

包含所有物理写回类型的实现，与节点声明文件（nodes.py）分离。

写回类型（对应三种偏移量语义，归零即复位）：
  1. rigid_body_delta  → Object.delta_location / delta_rotation_euler
  2. bone_transform    → PoseBone.matrix_basis
  3. gn_attribute      → 共享 mesh 顶点最终 offset

初始状态约定：
  delta_location / delta_rotation_euler 在 Blender 中默认为 (0,0,0)，
  无需显式 K 帧记录。初始状态 = 全零 = 物理未启动。
  停止模拟或复位时调用 clear_all_deltas(world) 将 delta 归零即可。

跳帧 / 复位处理：
  world.frame_context.restart_required=True 时触发 delta 归零，
  然后再写入本帧物理结果。
"""

from __future__ import annotations

import mathutils

from .rigid.names import RIGID_BODY_SLOT_KIND
from .rigid.results import get_rigid_transform_result
from .gn_offset import clear_gn_local_offsets, normalize_local_offsets, write_gn_local_offsets
from .utils.values import matrix_from_16
from .writeback_commands import iter_bone_transform_writebacks, iter_gn_offset_writebacks


# ---------------------------------------------------------------------------
# 受影响对象注册表 key
# ---------------------------------------------------------------------------

_TOUCHED_OBJECTS_KEY     = "_writeback_touched_objects"
_TOUCHED_POSE_BONES_KEY  = "_writeback_touched_pose_bones"
_TOUCHED_GN_OBJECTS_KEY  = "_writeback_touched_gn_objects"
_CLEANUP_RESOURCE_KEY    = "_writeback_cleanup"
_GN_DIAGNOSTICS_KEY      = "_writeback_gn_diagnostics"


class WritebackCleanupResource:
    """
    挂在 world.backend_resources 里的清理对象。
    实现 omni_cache_dispose 协议：world 被 Cache Delete / addon 注销时
    自动将所有曾写过 delta 的对象归零，不残留物理偏移。
    """
    def __init__(
        self,
        touched_objects: set,
        touched_pose_bones: dict,
        touched_gn_objects: dict,
    ):
        self._touched_objects = touched_objects
        self._touched_pose_bones = touched_pose_bones
        self._touched_gn_objects = touched_gn_objects

    def omni_cache_dispose(self, reason: str) -> None:
        _reset_rigid_objects(self._touched_objects)
        _reset_pose_bones(self._touched_pose_bones)
        _reset_gn_objects(self._touched_gn_objects)


def _get_touched_set(world) -> set:
    """获取（或创建）本 world 记录的"已写过 delta"对象集合。"""
    br = world.backend_resources
    if _TOUCHED_OBJECTS_KEY not in br:
        br[_TOUCHED_OBJECTS_KEY] = set()
    return br[_TOUCHED_OBJECTS_KEY]


def _get_touched_pose_bones(world) -> dict:
    br = world.backend_resources
    if _TOUCHED_POSE_BONES_KEY not in br:
        br[_TOUCHED_POSE_BONES_KEY] = {}
    return br[_TOUCHED_POSE_BONES_KEY]


def _get_touched_gn_objects(world) -> dict:
    br = world.backend_resources
    if _TOUCHED_GN_OBJECTS_KEY not in br:
        br[_TOUCHED_GN_OBJECTS_KEY] = {}
    return br[_TOUCHED_GN_OBJECTS_KEY]


def _ensure_cleanup_resource(world) -> None:
    if _CLEANUP_RESOURCE_KEY not in world.backend_resources:
        world.backend_resources[_CLEANUP_RESOURCE_KEY] = WritebackCleanupResource(
            _get_touched_set(world),
            _get_touched_pose_bones(world),
            _get_touched_gn_objects(world),
        )


def _reset_rigid_objects(touched) -> None:
    if not touched:
        return
    for obj in list(touched):
        try:
            obj.delta_location       = (0.0, 0.0, 0.0)
            obj.delta_rotation_euler = (0.0, 0.0, 0.0)
            obj.update_tag()
        except Exception:
            pass
    try:
        touched.clear()
    except Exception:
        pass


def _reset_pose_bones(touched) -> None:
    if not touched:
        return
    identity = mathutils.Matrix.Identity(4)
    updated_armatures = set()
    values = list(touched.values()) if isinstance(touched, dict) else list(touched)
    for item in values:
        try:
            armature, bone_name = item
            pose = getattr(armature, "pose", None)
            pose_bone = pose.bones.get(str(bone_name or "")) if pose is not None else None
            if pose_bone is None:
                continue
            pose_bone.matrix_basis = identity.copy()
            updated_armatures.add(armature)
        except Exception:
            pass
    for armature in updated_armatures:
        try:
            armature.update_tag()
        except Exception:
            pass
    if updated_armatures:
        try:
            import bpy
            bpy.context.view_layer.update()
        except Exception:
            pass
    try:
        touched.clear()
    except Exception:
        pass


def _reset_gn_objects(touched) -> None:
    if not touched:
        return
    values = list(touched.values()) if isinstance(touched, dict) else list(touched)
    for obj in values:
        try:
            clear_gn_local_offsets(obj)
        except Exception:
            pass
    try:
        touched.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. 刚体 delta 写回
# ---------------------------------------------------------------------------

def reset_rigid_body_deltas(world) -> None:
    """
    将所有 DYNAMIC 刚体对象的 delta_location / delta_rotation_euler 归零。

    触发时机：restart_required=True（跳帧、显式 reset、scope 变化等）。
    归零后对象返回 obj.location 所记录的原始位置。
    """
    updated = set()
    for slot in world.solver_slots.values():
        if slot.kind != RIGID_BODY_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None or spec.body_type != "DYNAMIC" or spec.obj is None:
            continue
        obj = spec.obj
        try:
            obj.delta_location       = (0.0, 0.0, 0.0)
            obj.delta_rotation_euler = (0.0, 0.0, 0.0)
            updated.add(obj)
        except Exception as exc:
            slot.data["_writeback_error"] = f"reset delta: {exc}"

    for obj in updated:
        try:
            obj.update_tag()
        except Exception:
            pass


def clear_all_deltas(world) -> None:
    """
    清除本 world 期间所有曾被写过的对象、骨骼和 GN offset。
    在 omni_cache_dispose / Cache Delete / 停止模拟时调用，确保目标归位。
    """
    br = getattr(world, "backend_resources", {})
    _reset_rigid_objects(br.get(_TOUCHED_OBJECTS_KEY))
    _reset_pose_bones(br.get(_TOUCHED_POSE_BONES_KEY))
    _reset_gn_objects(br.get(_TOUCHED_GN_OBJECTS_KEY))


def writeback_rigid_body_deltas(world) -> int:
    """
    从 world result stream 读取 DYNAMIC 刚体的当前变换，写入 Blender 对象的
    delta_location / delta_rotation_euler（增量变换）。

    不修改 obj.location / rotation_euler，保留原始变换。
    复位 = delta 归零（调用 reset_rigid_body_deltas 或 clear_all_deltas）。

    返回成功写回的对象数量。
    """
    fc = getattr(world, "frame_context", None)
    frame = int(getattr(fc, "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)

    # Register cleanup once so cache dispose can restore written transforms.
    _ensure_cleanup_resource(world)

    touched = _get_touched_set(world)
    updated = set()
    written = 0

    for slot in list(world.solver_slots.values()):
        if slot.kind != RIGID_BODY_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None or spec.body_type != "DYNAMIC" or spec.obj is None:
            continue

        result = get_rigid_transform_result(
            world,
            slot_id=slot.slot_id,
            frame=frame,
            generation=generation,
        )
        if result is None:
            continue

        try:
            pos_arr = result.get("position")
            rot_arr = result.get("rotation_wxyz")
            obj = spec.obj

            # 位置 delta = Jolt 世界位置 - 对象原始 location
            jolt_pos = mathutils.Vector(pos_arr)
            obj.delta_location = jolt_pos - obj.location

            # 旋转 delta：矩阵差值，精确支持所有欧拉序
            q = mathutils.Quaternion((
                float(rot_arr[0]), float(rot_arr[1]),
                float(rot_arr[2]), float(rot_arr[3])
            ))
            rest_rot  = obj.rotation_euler.to_matrix().to_4x4()
            jolt_rot  = q.to_matrix().to_4x4()
            delta_mat = rest_rot.inverted() @ jolt_rot
            obj.delta_rotation_euler = delta_mat.to_euler(obj.rotation_mode)

            touched.add(obj)    # 记录已写过 delta 的对象
            updated.add(obj)
            written += 1
            slot.data.pop("_writeback_error", None)

        except Exception as exc:
            slot.data["_writeback_error"] = str(exc)

    for obj in updated:
        try:
            obj.update_tag()
        except Exception:
            pass

    return written


# ---------------------------------------------------------------------------
# 2. 骨骼变换写回（未来扩展占位）
# ---------------------------------------------------------------------------

def writeback_bone_transforms(world) -> int:
    fc = getattr(world, "frame_context", None)
    frame = int(getattr(fc, "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)

    updated_armatures = set()
    written = 0
    touched_pose_bones = _get_touched_pose_bones(world)
    _ensure_cleanup_resource(world)

    results = iter_bone_transform_writebacks(
        world,
        frame=frame,
        generation=generation,
        expand_batches=False,
    )
    for result in results:
        slot = _slot_for_writeback_result(world, result)
        try:
            if result.get("writeback_type") == "bone_transform_batch":
                armature, batch_written = _writeback_bone_transform_batch(
                    result,
                    slot,
                    touched_pose_bones,
                )
                if armature is not None and batch_written:
                    updated_armatures.add(armature)
                    written += batch_written
                if slot is not None:
                    slot.data.pop("_writeback_error", None)
                continue

            armature = _armature_for_bone_writeback(world, result, slot)
            pose = getattr(armature, "pose", None)
            if pose is None:
                continue

            bone_name = str(result.get("bone_name") or "")
            pose_bone = pose.bones.get(bone_name)
            if pose_bone is None:
                continue
            pose_bone.matrix_basis = matrix_from_16(result.get("matrix_basis"))
            try:
                touched_pose_bones[(int(armature.as_pointer()), bone_name)] = (armature, bone_name)
            except Exception:
                pass
            updated_armatures.add(armature)
            written += 1
            if slot is not None:
                slot.data.pop("_writeback_error", None)
        except Exception as exc:
            if slot is not None:
                slot.data["_writeback_error"] = str(exc)

    for armature in updated_armatures:
        try:
            armature.update_tag()
        except Exception:
            pass

    return written


def _writeback_bone_transform_batch(result, slot, touched_pose_bones) -> tuple[object | None, int]:
    plan = slot.data.get("writeback_plan") if slot is not None else None
    armature = plan.get("armature") if isinstance(plan, dict) else None
    if not _armature_matches_writeback(armature, result):
        armature = _armature_for_bone_writeback(None, result, slot)
    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    if pose_bones is None:
        return armature, 0

    buffer_size = len(pose_bones) * 16
    basis_values = plan.get("basis_values") if isinstance(plan, dict) else None
    if not isinstance(basis_values, list) or len(basis_values) != buffer_size:
        basis_values = [0.0] * buffer_size
        if isinstance(plan, dict):
            plan["basis_values"] = basis_values

    updates = []
    for batch in (plan.get("batches") or ()) if isinstance(plan, dict) else ():
        if not isinstance(batch, dict):
            continue
        records = batch.get("records") or ()
        matrix_bases = batch.get("matrix_bases") or ()
        for index, record in enumerate(records):
            if not isinstance(record, dict) or index >= len(matrix_bases):
                continue
            basis_matrix = matrix_bases[index]
            pose_bone = record.get("pose_bone")
            pose_index = int(record.get("pose_index", -1))
            if basis_matrix is None or pose_bone is None or pose_index < 0:
                continue
            updates.append((pose_bone, pose_index, basis_matrix, str(record.get("bone_name") or "")))

    can_foreach_set = False
    if updates:
        try:
            pose_bones.foreach_get("matrix_basis", basis_values)
            for _pose_bone, pose_index, basis_matrix, _bone_name in updates:
                _write_matrix_to_foreach_buffer(basis_values, pose_index * 16, basis_matrix)
            pose_bones.foreach_set("matrix_basis", basis_values)
            can_foreach_set = True
        except Exception:
            can_foreach_set = False

    if not can_foreach_set:
        for pose_bone, _pose_index, basis_matrix, _bone_name in updates:
            pose_bone.matrix_basis = basis_matrix

    try:
        armature_ptr = int(armature.as_pointer())
    except Exception:
        armature_ptr = 0
    for _pose_bone, _pose_index, _basis_matrix, bone_name in updates:
        if armature_ptr and bone_name:
            touched_pose_bones[(armature_ptr, bone_name)] = (armature, bone_name)
    return armature, len(updates)


def _write_matrix_to_foreach_buffer(values: list[float], offset: int, matrix) -> None:
    """Blender's matrix foreach layout is column-major."""
    values[offset + 0] = float(matrix[0][0])
    values[offset + 1] = float(matrix[1][0])
    values[offset + 2] = float(matrix[2][0])
    values[offset + 3] = float(matrix[3][0])
    values[offset + 4] = float(matrix[0][1])
    values[offset + 5] = float(matrix[1][1])
    values[offset + 6] = float(matrix[2][1])
    values[offset + 7] = float(matrix[3][1])
    values[offset + 8] = float(matrix[0][2])
    values[offset + 9] = float(matrix[1][2])
    values[offset + 10] = float(matrix[2][2])
    values[offset + 11] = float(matrix[3][2])
    values[offset + 12] = float(matrix[0][3])
    values[offset + 13] = float(matrix[1][3])
    values[offset + 14] = float(matrix[2][3])
    values[offset + 15] = float(matrix[3][3])


def _slot_for_writeback_result(world, result):
    slot_id = str(result.get("slot_id") or "")
    if not slot_id:
        return None
    return getattr(world, "solver_slots", {}).get(slot_id)


def _armature_for_bone_writeback(world, result, slot):
    spec = slot.data.get("spec") if slot is not None else None
    armature = getattr(spec, "armature", None)
    if _armature_matches_writeback(armature, result):
        return armature

    armature = _find_armature_by_pointer(result.get("armature_ptr"))
    if armature is not None:
        return armature
    return None


def _armature_matches_writeback(armature, result) -> bool:
    if armature is None:
        return False
    try:
        armature_ptr = int(result.get("armature_ptr", 0) or 0)
        if armature_ptr and int(armature.as_pointer()) != armature_ptr:
            return False
        data_ptr = int(result.get("armature_data_ptr", 0) or 0)
        data = getattr(armature, "data", None)
        if data_ptr and (data is None or int(data.as_pointer()) != data_ptr):
            return False
    except Exception:
        return False
    return True


def _find_armature_by_pointer(armature_ptr):
    try:
        target = int(armature_ptr or 0)
    except Exception:
        return None
    if not target:
        return None
    try:
        import bpy
    except Exception:
        return None
    for obj in getattr(bpy.data, "objects", ()):
        try:
            if int(obj.as_pointer()) == target:
                return obj
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# 3. GN 顶点最终 offset 写回
# ---------------------------------------------------------------------------

def reset_gn_offsets(world) -> None:
    br = getattr(world, "backend_resources", {})
    _reset_gn_objects(br.get(_TOUCHED_GN_OBJECTS_KEY))


def _find_mesh_by_pointer(object_ptr, object_data_ptr):
    try:
        obj_target = int(object_ptr or 0)
        data_target = int(object_data_ptr or 0)
    except Exception:
        return None
    if obj_target <= 0 or data_target <= 0:
        return None
    try:
        import bpy
    except Exception:
        return None
    for obj in getattr(bpy.data, "objects", ()):
        try:
            if (
                getattr(obj, "type", None) == "MESH"
                and getattr(obj, "data", None) is not None
                and int(obj.as_pointer()) == obj_target
                and int(obj.data.as_pointer()) == data_target
            ):
                return obj
        except Exception:
            continue
    return None


def _gn_writeback_error(diagnostics: dict, result, message: object) -> None:
    errors = diagnostics.setdefault("errors", [])
    if len(errors) < 32:
        errors.append({
            "target_key": str(result.get("target_key") or "") if isinstance(result, dict) else "",
            "writer_id": str(result.get("writer_id") or "") if isinstance(result, dict) else "",
            "message": str(message),
        })


def _set_gn_slot_error(world, result, message: str | None) -> None:
    slot_id = str(result.get("slot_id") or "") if isinstance(result, dict) else ""
    slot = getattr(world, "solver_slots", {}).get(slot_id)
    if slot is None:
        return
    if message:
        slot.data["_writeback_error"] = str(message)
    else:
        slot.data.pop("_writeback_error", None)


def get_gn_writeback_diagnostics(world) -> dict:
    source = getattr(world, "runtime_caches", {}).get(_GN_DIAGNOSTICS_KEY, {})
    snapshot = dict(source) if isinstance(source, dict) else {}
    snapshot["errors"] = [dict(item) for item in snapshot.get("errors", ())]
    return snapshot


def writeback_gn_attributes(world) -> int:
    """写入每个 Mesh 目标唯一的对象局部最终 offset。

    同一 writer 在同一帧重复发布时取最后一个快照；同一目标若出现多个
    writer，说明中间分量没有先在 exchange 归并，目标会清零并记录冲突。
    """
    fc = getattr(world, "frame_context", None)
    frame = int(getattr(fc, "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)
    results = iter_gn_offset_writebacks(world, frame=frame, generation=generation)
    diagnostics = {
        "frame": frame,
        "generation": generation,
        "result_count": len(results),
        "candidate_count": 0,
        "superseded_count": 0,
        "conflict_count": 0,
        "written_count": 0,
        "cleared_count": 0,
        "errors": [],
    }
    world.runtime_caches[_GN_DIAGNOSTICS_KEY] = diagnostics
    touched = _get_touched_gn_objects(world)
    _ensure_cleanup_resource(world)

    by_target: dict[str, dict[str, dict]] = {}
    for result in results:
        try:
            obj_ptr = int(result.get("object_ptr", 0) or 0)
            data_ptr = int(result.get("object_data_ptr", 0) or 0)
            target_key = f"{obj_ptr}:{data_ptr}"
            solver = str(result.get("solver") or "").strip()
            slot_id = str(result.get("slot_id") or "").strip()
            writer_id = f"{solver}:{slot_id}"
            if obj_ptr <= 0 or data_ptr <= 0 or result.get("target_key") != target_key:
                raise ValueError("target pointer/key 不一致")
            if not solver or not slot_id or result.get("writer_id") != writer_id:
                raise ValueError("writer_id 必须由 solver + stable slot_id 构成")
            writers = by_target.setdefault(target_key, {})
            if writer_id in writers:
                diagnostics["superseded_count"] += 1
            writers[writer_id] = result
        except Exception as exc:
            _gn_writeback_error(diagnostics, result, exc)
            _set_gn_slot_error(world, result, str(exc))

    diagnostics["candidate_count"] = len(by_target)
    written_targets = set()
    for target_key, writers in by_target.items():
        if len(writers) != 1:
            diagnostics["conflict_count"] += 1
            message = "同一 Mesh 目标存在多个最终 GN offset writer；请先在 world.exchange 归并"
            for result in writers.values():
                _gn_writeback_error(diagnostics, result, message)
                _set_gn_slot_error(world, result, message)
            old_obj = touched.pop(target_key, None)
            if old_obj is not None and clear_gn_local_offsets(old_obj):
                diagnostics["cleared_count"] += 1
            continue

        result = next(iter(writers.values()))
        try:
            obj = _find_mesh_by_pointer(
                result.get("object_ptr"),
                result.get("object_data_ptr"),
            )
            if obj is None:
                raise ValueError("GN offset 目标 Mesh 不存在或 data pointer 已变化")
            vertex_count = int(result.get("vertex_count", -1))
            values = normalize_local_offsets(
                result.get("local_offsets"),
                vertex_count,
                copy=False,
            )
            if vertex_count != len(obj.data.vertices):
                raise ValueError(
                    f"GN offset 拓扑已变化：result={vertex_count} target={len(obj.data.vertices)}"
                )
            write_gn_local_offsets(obj, values)
            touched[target_key] = obj
            written_targets.add(target_key)
            diagnostics["written_count"] += 1
            _set_gn_slot_error(world, result, None)
        except Exception as exc:
            _gn_writeback_error(diagnostics, result, exc)
            _set_gn_slot_error(world, result, str(exc))

    for target_key, obj in list(touched.items()):
        if target_key in written_targets:
            continue
        if clear_gn_local_offsets(obj):
            diagnostics["cleared_count"] += 1
        touched.pop(target_key, None)
    return int(diagnostics["written_count"])


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def apply_all_writebacks(world, restart: bool) -> int:
    """
    统一写回入口，被 physicsWriteback 节点调用。

    restart=True 时（跳帧/复位/首帧）：先将所有刚体 delta 归零，再写入结果。
    初始状态 = delta 全零，Blender 默认值，无需显式 K 帧记录。
    """
    if restart:
        reset_rigid_body_deltas(world)
        reset_gn_offsets(world)

    total  = writeback_rigid_body_deltas(world)
    total += writeback_bone_transforms(world)
    total += writeback_gn_attributes(world)
    return total
