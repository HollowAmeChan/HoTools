"""
physicsWorld.writeback — 物理写回算法

包含所有物理写回类型的实现，与节点声明文件（nodes.py）分离。

写回类型（对应三种偏移量语义，归零即复位）：
  1. rigid_body_delta  → Object.delta_location / delta_rotation_euler|quaternion
  2. bone_transform    → PoseBone.matrix_basis
  3. gn_attribute      → Simple Cloth 顶点最终 offset

初始状态约定：
  delta_location / delta_rotation_euler 在 Blender 中默认为 (0,0,0)，
  无需显式 K 帧记录。初始状态 = 全零 = 物理未启动。
  停止模拟或复位时调用 clear_all_deltas(world) 将 delta 归零即可。

跳帧 / 复位处理：
  world.frame_context.restart_required=True 时触发 delta 归零，
  然后再写入本帧物理结果。
"""

from __future__ import annotations

import math
import mathutils
import numpy as np

from .rigid.names import RIGID_BODY_SLOT_KIND
from .rigid.results import index_rigid_transform_results_by_slot
from .scope import (
    PHYSICS_SCOPE_COLLECTION_BATCH_CHANNEL,
    PHYSICS_SCOPE_COLLECTION_BATCH_SCHEMA,
)
from .simple_cloth.output import (
    clear_gn_local_offsets,
    ensure_gn_offset_output,
    normalize_local_offsets,
    write_gn_local_offsets,
)
from .simple_cloth.results import iter_gn_offset_writebacks
from .names import GN_OFFSET_ATTRIBUTE_NAME, GN_OFFSET_MODIFIER_NAME
from .utils.values import matrix_from_16
from .utils.blender_scene import update_view_layer_if_allowed
from .writeback_commands import iter_bone_transform_writebacks


# ---------------------------------------------------------------------------
# 受影响对象注册表 key
# ---------------------------------------------------------------------------

_TOUCHED_OBJECTS_KEY     = "_writeback_touched_objects"
_TOUCHED_POSE_BONES_KEY  = "_writeback_touched_pose_bones"
_TOUCHED_GN_OBJECTS_KEY  = "_writeback_touched_gn_objects"
_CLEANUP_RESOURCE_KEY    = "_writeback_cleanup"
_BONE_DIAGNOSTICS_KEY    = "_writeback_bone_diagnostics"
_BONE_RECEIPTS_KEY       = "_writeback_bone_receipts"
_BONE_RECEIPT_SERIAL_KEY = "_writeback_bone_receipt_serial"
_GN_DIAGNOSTICS_KEY      = "_writeback_gn_diagnostics"
_RIGID_DIAGNOSTICS_KEY   = "_writeback_rigid_diagnostics"
_GN_RECEIPT_SERIAL_KEY   = "_writeback_gn_receipt_serial"
_EULER_ORDERS = {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}


def _foreach_float(collection, property_name: str, width: int) -> np.ndarray:
    values = np.empty(len(collection) * int(width), dtype=np.float32)
    if values.size:
        collection.foreach_get(property_name, values)
    return values


class WritebackCleanupResource:
    """
    挂在 world.backend_resources 里的清理对象。
    实现 omni_cache_dispose 协议：world 被 Cache Delete / addon 注销时
    自动将所有曾写过 delta 的对象归零，不残留物理偏移。
    """
    def __init__(
        self,
        touched_objects: dict,
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


def _get_touched_set(world) -> dict:
    """获取（或创建）本 world 记录的刚体写回稳定身份表。"""
    br = world.backend_resources
    if _TOUCHED_OBJECTS_KEY not in br:
        br[_TOUCHED_OBJECTS_KEY] = {}
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


def _build_object_pointer_index() -> dict[int, tuple[int, object]]:
    """单次枚举 Blender Object，供一轮写回按稳定指针 O(1) 解析。"""
    try:
        import bpy
    except Exception:
        return {}

    indexed = {}
    for obj in tuple(getattr(bpy.data, "objects", ())):
        try:
            object_ptr = int(obj.as_pointer())
            data = getattr(obj, "data", None)
            data_ptr = int(data.as_pointer()) if data is not None else 0
            indexed[object_ptr] = (data_ptr, obj)
        except Exception:
            continue
    return indexed


def _reset_rigid_objects(touched) -> None:
    if not touched:
        return
    object_index = _build_object_pointer_index()
    values = list(touched.values()) if isinstance(touched, dict) else list(touched)
    for item in values:
        try:
            if isinstance(item, tuple) and len(item) == 2:
                obj = _find_object_by_pointer(
                    item[0],
                    item[1],
                    object_index=object_index,
                )
            else:
                # 兼容迁移前直接保存 bpy Object 的旧 cache。
                obj = item
            if obj is None:
                continue
            obj.delta_location       = (0.0, 0.0, 0.0)
            obj.delta_rotation_euler = (0.0, 0.0, 0.0)
            obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            obj.delta_scale = (1.0, 1.0, 1.0)
            obj.update_tag()
        except Exception:
            pass
    try:
        touched.clear()
    except Exception:
        pass


def _find_object_by_pointer(
    object_ptr,
    object_data_ptr=0,
    *,
    object_index: dict[int, tuple[int, object]] | None = None,
):
    object_ptr = int(object_ptr or 0)
    object_data_ptr = int(object_data_ptr or 0)
    if object_index is not None:
        record = object_index.get(object_ptr)
        if record is None:
            return None
        live_data_ptr, obj = record
        if object_data_ptr > 0 and live_data_ptr != object_data_ptr:
            return None
        return obj
    try:
        from ..OmniReferenceGuard import resolve_bpy_object_reference

        return resolve_bpy_object_reference(
            object_ptr,
            object_data_ptr,
        )
    except Exception:
        return None


def _reset_pose_bones(touched) -> None:
    if not touched:
        return
    identity = mathutils.Matrix.Identity(4)
    updated_armatures = set()
    values = list(touched.values()) if isinstance(touched, dict) else list(touched)
    for item in values:
        try:
            if len(item) == 3:
                armature_ptr, armature_data_ptr, bone_name = item
                armature = _find_armature_by_pointer(
                    armature_ptr,
                    armature_data_ptr,
                )
            else:
                # 兼容刷新前已经存在的旧 cache；新写回不再生成活引用记录。
                legacy_armature, bone_name = item
                armature = _find_armature_by_pointer(
                    legacy_armature.as_pointer(),
                    legacy_armature.data.as_pointer(),
                )
            if armature is None:
                continue
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
        update_view_layer_if_allowed()
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
    object_index = _build_object_pointer_index()
    for slot in getattr(world, "solver_slots", {}).values():
        if slot.kind != RIGID_BODY_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None or spec.body_type != "DYNAMIC" or spec.obj is None:
            continue
        obj = _find_object_by_pointer(
            getattr(spec, "obj_ptr", 0),
            getattr(spec, "data_ptr", 0),
            object_index=object_index,
        ) or spec.obj
        try:
            obj.delta_location       = (0.0, 0.0, 0.0)
            obj.delta_rotation_euler = (0.0, 0.0, 0.0)
            obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            obj.delta_scale = (1.0, 1.0, 1.0)
            updated.add(obj)
        except Exception as exc:
            slot.data["_writeback_error"] = f"reset delta: {exc}"

    for obj in updated:
        try:
            obj.update_tag()
        except Exception:
            pass


def reset_all_writebacks(world) -> None:
    """
    统一清除本 world 的三类公共写回状态。

    刚体同时覆盖当前 slot 与历史 touched 对象；骨骼和 GN 使用公共写回登记表
    恢复。跳帧、显式 reset、scope 改变和 cache dispose 都必须走这个入口。
    """
    reset_rigid_body_deltas(world)
    br = getattr(world, "backend_resources", {})
    _reset_rigid_objects(br.get(_TOUCHED_OBJECTS_KEY))
    _reset_pose_bones(br.get(_TOUCHED_POSE_BONES_KEY))
    _reset_gn_objects(br.get(_TOUCHED_GN_OBJECTS_KEY))


def clear_all_deltas(world) -> None:
    """兼容旧调用名；实际执行统一写回状态清理。"""
    reset_all_writebacks(world)


def _batch_rotation_matrix(batch: dict, index: int, rotation_mode: str) -> mathutils.Matrix:
    """从 Scope 冻结的基础旋转构造矩阵，不能读取本帧已写入的 delta 结果。"""
    if rotation_mode == "QUATERNION":
        values = batch["rotation_quaternions_f32"][index * 4:(index + 1) * 4]
        quaternion = mathutils.Quaternion(tuple(float(value) for value in values))
        return quaternion.to_matrix().to_4x4()
    if rotation_mode == "AXIS_ANGLE":
        values = batch["rotation_axis_angles_f32"][index * 4:(index + 1) * 4]
        angle, axis_x, axis_y, axis_z = (float(value) for value in values)
        axis = mathutils.Vector((axis_x, axis_y, axis_z))
        if axis.length_squared <= 1.0e-20:
            axis = mathutils.Vector((0.0, 0.0, 1.0))
        return mathutils.Quaternion(axis, angle).to_matrix().to_4x4()
    values = batch["rotation_eulers_f32"][index * 3:(index + 1) * 3]
    order = rotation_mode if rotation_mode in _EULER_ORDERS else "XYZ"
    euler = mathutils.Euler(tuple(float(value) for value in values), order)
    return euler.to_matrix().to_4x4()


def _rigid_delta_components(batch: dict, index: int, obj, result: dict):
    pos_arr = result.get("position")
    rot_arr = result.get("rotation_wxyz")
    if pos_arr is None or rot_arr is None:
        raise ValueError("刚体结果缺少 position 或 rotation_wxyz")
    base_location = batch["locations_f32"][index * 3:(index + 1) * 3]
    delta_location = tuple(
        float(value)
        for value in mathutils.Vector(pos_arr) - mathutils.Vector(base_location)
    )

    rotation_mode = str(getattr(obj, "rotation_mode", "XYZ") or "XYZ")
    rest_rot = _batch_rotation_matrix(batch, index, rotation_mode)
    q = mathutils.Quaternion(tuple(float(value) for value in rot_arr))
    delta_mat = rest_rot.inverted() @ q.to_matrix().to_4x4()
    if rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
        return (
            delta_location,
            (0.0, 0.0, 0.0),
            tuple(float(value) for value in delta_mat.to_quaternion()),
        )
    order = rotation_mode if rotation_mode in _EULER_ORDERS else "XYZ"
    return (
        delta_location,
        tuple(float(value) for value in delta_mat.to_euler(order)),
        (1.0, 0.0, 0.0, 0.0),
    )


def _collection_batch_writeback(world, results_by_slot: dict, touched: dict) -> int | None:
    """
    按 Collection 批次选择刚体 delta 的稠密或稀疏写入 API。

    返回 None 表示批次已失效，调用方必须退回逐 Object 路径。批次只保存本帧
    的稳定顺序；删除、重挂集合等编辑会使预检失败，而不是对错误目标批量写入。
    """
    batches = world.consume_exchange(
        PHYSICS_SCOPE_COLLECTION_BATCH_CHANNEL,
        producer="physics_object_scope",
    )
    if not batches:
        return None

    diagnostics = {
        "schema": "rigid_writeback_api_diagnostics_v1",
        "dense_collection_count": 0,
        "dense_object_count": 0,
        "sparse_collection_count": 0,
        "sparse_object_count": 0,
        "fallback_reason": "",
    }
    world.backend_resources[_RIGID_DIAGNOSTICS_KEY] = diagnostics

    updates = {}
    slots_by_object = {}
    for slot in list(world.solver_slots.values()):
        if slot.kind != RIGID_BODY_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None or spec.body_type != "DYNAMIC" or spec.obj is None:
            continue
        result = results_by_slot.get(slot.slot_id)
        if result is None:
            continue
        object_ptr = int(getattr(spec, "obj_ptr", 0) or 0)
        if object_ptr <= 0 or object_ptr in updates:
            diagnostics["fallback_reason"] = "invalid_or_duplicate_target"
            return None
        updates[object_ptr] = (spec, result)
        slots_by_object[object_ptr] = slot

    if not updates:
        return 0

    batch_locations = {}
    for batch in batches:
        if (
            not isinstance(batch, dict)
            or batch.get("schema") != PHYSICS_SCOPE_COLLECTION_BATCH_SCHEMA
        ):
            diagnostics["fallback_reason"] = "invalid_batch_schema"
            return None
        collection = batch.get("collection")
        object_ptrs = tuple(batch.get("object_ptrs") or ())
        objects = tuple(batch.get("objects") or ())
        object_count = int(batch.get("object_count", -1))
        try:
            live_objects = collection.all_objects
            if (
                int(collection.as_pointer()) != int(batch.get("collection_ptr", 0))
                or len(live_objects) != object_count
                or len(objects) != object_count
                or len(object_ptrs) != object_count
                or tuple(int(obj.as_pointer()) for obj in live_objects) != object_ptrs
            ):
                diagnostics["fallback_reason"] = "collection_membership_changed"
                return None
        except Exception:
            diagnostics["fallback_reason"] = "collection_reference_invalid"
            return None
        for index, object_ptr in enumerate(object_ptrs):
            if object_ptr in batch_locations:
                diagnostics["fallback_reason"] = "overlapping_collection_target"
                return None
            batch_locations[object_ptr] = (batch, index, live_objects)

    if any(object_ptr not in batch_locations for object_ptr in updates):
        diagnostics["fallback_reason"] = "target_outside_collection_batches"
        return None

    written = 0
    for batch in batches:
        collection = batch["collection"]
        live_objects = collection.all_objects
        object_ptrs = tuple(batch["object_ptrs"])
        objects = tuple(batch["objects"])
        active_indices = [
            index for index, object_ptr in enumerate(object_ptrs)
            if object_ptr in updates
        ]
        if not active_indices:
            continue
        dense_batch = len(active_indices) == len(object_ptrs)
        if not dense_batch:
            diagnostics["sparse_collection_count"] += 1
            for index in active_indices:
                object_ptr = object_ptrs[index]
                spec, result = updates[object_ptr]
                slot = slots_by_object[object_ptr]
                obj = objects[index]
                previous = (
                    tuple(obj.delta_location),
                    tuple(obj.delta_rotation_euler),
                    tuple(obj.delta_rotation_quaternion),
                )
                try:
                    location, euler, quaternion = _rigid_delta_components(
                        batch,
                        index,
                        obj,
                        result,
                    )
                    obj.delta_location = location
                    obj.delta_rotation_euler = euler
                    obj.delta_rotation_quaternion = quaternion
                    data_ptr = int(getattr(spec, "data_ptr", 0) or 0)
                    touched[(object_ptr, data_ptr)] = (object_ptr, data_ptr)
                    slot.data.pop("_writeback_error", None)
                    diagnostics["sparse_object_count"] += 1
                    written += 1
                except Exception as exc:
                    try:
                        obj.delta_location = previous[0]
                        obj.delta_rotation_euler = previous[1]
                        obj.delta_rotation_quaternion = previous[2]
                    except Exception:
                        pass
                    slot.data["_writeback_error"] = str(exc)
                    continue
                try:
                    obj.update_tag()
                except Exception:
                    pass
            continue

        try:
            delta_location = _foreach_float(live_objects, "delta_location", 3)
            delta_euler = _foreach_float(live_objects, "delta_rotation_euler", 3)
            delta_quaternion = _foreach_float(live_objects, "delta_rotation_quaternion", 4)
            original_location = delta_location.copy()
            original_euler = delta_euler.copy()
            original_quaternion = delta_quaternion.copy()

            for index in active_indices:
                object_ptr = object_ptrs[index]
                _spec, result = updates[object_ptr]
                obj = objects[index]
                location, euler, quaternion = _rigid_delta_components(
                    batch,
                    index,
                    obj,
                    result,
                )
                delta_location[index * 3:(index + 1) * 3] = location
                delta_euler[index * 3:(index + 1) * 3] = euler
                delta_quaternion[index * 4:(index + 1) * 4] = quaternion

            live_objects.foreach_set("delta_location", delta_location)
            live_objects.foreach_set("delta_rotation_euler", delta_euler)
            live_objects.foreach_set("delta_rotation_quaternion", delta_quaternion)
        except Exception:
            try:
                live_objects.foreach_set("delta_location", original_location)
                live_objects.foreach_set("delta_rotation_euler", original_euler)
                live_objects.foreach_set("delta_rotation_quaternion", original_quaternion)
            except Exception:
                pass
            diagnostics["fallback_reason"] = "dense_collection_write_failed"
            return None

        diagnostics["dense_collection_count"] += 1
        diagnostics["dense_object_count"] += len(active_indices)

        for index in active_indices:
            object_ptr = object_ptrs[index]
            spec, _result = updates[object_ptr]
            slot = slots_by_object[object_ptr]
            obj = objects[index]
            try:
                obj.update_tag()
            except Exception:
                pass
            data_ptr = int(getattr(spec, "data_ptr", 0) or 0)
            touched[(object_ptr, data_ptr)] = (object_ptr, data_ptr)
            slot.data.pop("_writeback_error", None)
            written += 1
    return written


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
    results_by_slot = index_rigid_transform_results_by_slot(
        world,
        frame=frame,
        generation=generation,
    )

    batch_written = _collection_batch_writeback(world, results_by_slot, touched)
    if batch_written is not None:
        return batch_written

    object_index = _build_object_pointer_index()

    for slot in list(world.solver_slots.values()):
        if slot.kind != RIGID_BODY_SLOT_KIND:
            continue
        spec = slot.data.get("spec")
        if spec is None or spec.body_type != "DYNAMIC" or spec.obj is None:
            continue

        result = results_by_slot.get(slot.slot_id)
        if result is None:
            continue

        try:
            pos_arr = result.get("position")
            rot_arr = result.get("rotation_wxyz")
            obj = _find_object_by_pointer(
                getattr(spec, "obj_ptr", 0),
                getattr(spec, "data_ptr", 0),
                object_index=object_index,
            ) or spec.obj

            # 位置 delta = Jolt 世界位置 - 对象原始 location
            jolt_pos = mathutils.Vector(pos_arr)
            obj.delta_location = jolt_pos - obj.location

            # 旋转 delta：基础旋转可由 Euler / Quaternion / Axis-Angle 表达。
            q = mathutils.Quaternion((
                float(rot_arr[0]), float(rot_arr[1]),
                float(rot_arr[2]), float(rot_arr[3])
            ))
            rotation_mode = str(getattr(obj, "rotation_mode", "XYZ") or "XYZ")
            if rotation_mode == "QUATERNION":
                rest_rot = obj.rotation_quaternion.to_matrix().to_4x4()
            elif rotation_mode == "AXIS_ANGLE":
                angle, axis_x, axis_y, axis_z = obj.rotation_axis_angle
                axis = mathutils.Vector((axis_x, axis_y, axis_z))
                if axis.length_squared <= 1.0e-20:
                    axis = mathutils.Vector((0.0, 0.0, 1.0))
                rest_rot = mathutils.Quaternion(axis, angle).to_matrix().to_4x4()
            else:
                rest_rot = obj.rotation_euler.to_matrix().to_4x4()
            jolt_rot  = q.to_matrix().to_4x4()
            delta_mat = rest_rot.inverted() @ jolt_rot
            if rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
                obj.delta_rotation_euler = (0.0, 0.0, 0.0)
                obj.delta_rotation_quaternion = delta_mat.to_quaternion()
            else:
                obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                obj.delta_rotation_euler = delta_mat.to_euler(rotation_mode)

            object_ptr = int(getattr(spec, "obj_ptr", 0) or obj.as_pointer())
            data_ptr = int(getattr(spec, "data_ptr", 0) or 0)
            touched[(object_ptr, data_ptr)] = (object_ptr, data_ptr)
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
    diagnostics = {
        "schema": "bone_writeback_diagnostics_v1",
        "frame": frame,
        "generation": generation,
        "transaction_count": 0,
        "committed_transaction_count": 0,
        "failed_transaction_count": 0,
        "written_count": 0,
        "errors": [],
        "receipt_errors": [],
        "receipts": [],
    }
    world.backend_resources[_BONE_DIAGNOSTICS_KEY] = diagnostics

    results = iter_bone_transform_writebacks(
        world,
        frame=frame,
        generation=generation,
        expand_batches=False,
    )
    groups = []
    grouped = {}
    for sequence, result in enumerate(results):
        transaction_id = str(result.get("transaction_id") or "")
        key = (
            ("transaction", str(result.get("solver") or ""), transaction_id)
            if transaction_id
            else ("single", sequence)
        )
        group = grouped.get(key)
        if group is None:
            group = []
            grouped[key] = group
            groups.append(group)
        group.append(result)
    diagnostics["transaction_count"] = len(groups)

    for group in groups:
        slots = [_slot_for_writeback_result(world, result) for result in group]
        try:
            _validate_bone_transaction(group)
            if all(
                result.get("writeback_type") == "bone_transform_batch"
                for result in group
            ):
                armature, batch_written = _writeback_bone_transform_transaction(
                    group,
                    slots,
                    touched_pose_bones,
                )
            elif len(group) == 1:
                armature, batch_written = _writeback_single_bone_transform(
                    group[0],
                    slots[0],
                    touched_pose_bones,
                )
            else:
                raise ValueError("公共 Bone 事务只能包含 batch 写回")
            if armature is not None and batch_written:
                updated_armatures.add(armature)
                written += batch_written
            for result in group:
                _append_bone_writeback_receipt(world, diagnostics, result)
            diagnostics["committed_transaction_count"] += 1
            for slot in slots:
                if slot is not None:
                    slot.data.pop("_writeback_error", None)
        except Exception as exc:
            diagnostics["failed_transaction_count"] += 1
            for result in group:
                diagnostics["errors"].append({
                    "solver": str(result.get("solver") or ""),
                    "slot_id": str(result.get("slot_id") or ""),
                    "transaction_id": str(result.get("transaction_id") or ""),
                    "message": str(exc),
                })
            for slot in slots:
                if slot is not None:
                    slot.data["_writeback_error"] = str(exc)

    for armature in updated_armatures:
        try:
            armature.update_tag()
        except Exception:
            pass

    diagnostics["written_count"] = written
    return written


def get_bone_writeback_diagnostics(world) -> dict:
    source = getattr(world, "backend_resources", {}).get(
        _BONE_DIAGNOSTICS_KEY,
        {},
    )
    if not isinstance(source, dict):
        return {}
    snapshot = dict(source)
    snapshot["errors"] = [dict(item) for item in source.get("errors", ())]
    snapshot["receipt_errors"] = [
        dict(item) for item in source.get("receipt_errors", ())
    ]
    snapshot["receipts"] = [dict(item) for item in source.get("receipts", ())]
    return snapshot


def get_bone_writeback_receipts(world) -> tuple[dict, ...]:
    """返回本 world 最近一次成功写入各 Bone result 的纯值 receipt。"""

    store = getattr(world, "runtime_caches", {}).get(_BONE_RECEIPTS_KEY, {})
    if not isinstance(store, dict):
        return ()
    values = [dict(item) for item in store.values() if isinstance(item, dict)]
    values.sort(key=lambda item: int(item.get("serial", 0)))
    return tuple(values)


def _append_bone_writeback_receipt(world, diagnostics: dict, result) -> None:
    try:
        serial = int(world.runtime_caches.get(_BONE_RECEIPT_SERIAL_KEY, 0) or 0) + 1
        world.runtime_caches[_BONE_RECEIPT_SERIAL_KEY] = serial
        receipt = {
            "schema": "bone_writeback_receipt_v1",
            "serial": serial,
            "frame": int(result.get("frame", diagnostics["frame"])),
            "generation": int(result.get("generation", diagnostics["generation"])),
            "solver": str(result.get("solver") or ""),
            "slot_id": str(result.get("slot_id") or ""),
            "transaction_id": str(result.get("transaction_id") or ""),
            "transaction_index": int(result.get("transaction_index", -1)),
            "transaction_size": int(result.get("transaction_size", 0)),
            "publication_id": int(result.get("publication_id", 0)),
            "armature_ptr": int(result.get("armature_ptr", 0) or 0),
            "armature_data_ptr": int(result.get("armature_data_ptr", 0) or 0),
            "bone_count": int(result.get("bone_count", 0) or 0),
        }
        diagnostics["receipts"].append(dict(receipt))
        store = world.runtime_caches.setdefault(_BONE_RECEIPTS_KEY, {})
        store[(receipt["solver"], receipt["slot_id"])] = receipt
    except Exception as exc:
        # Blender 已完成原子提交后不能再因诊断记录失败伪装成写回失败。
        diagnostics.setdefault("receipt_errors", []).append({
            "solver": str(result.get("solver") or ""),
            "slot_id": str(result.get("slot_id") or ""),
            "message": str(exc),
        })


def _validate_bone_transaction(results) -> None:
    transaction_id = str(results[0].get("transaction_id") or "") if results else ""
    if not transaction_id:
        if len(results) != 1:
            raise ValueError("无 transaction_id 的公共 Bone 写回不能跨 result 聚合")
        return
    sizes = {int(result.get("transaction_size", -1)) for result in results}
    indices = [int(result.get("transaction_index", -1)) for result in results]
    solvers = {str(result.get("solver") or "") for result in results}
    identities = {
        (
            int(result.get("armature_ptr", 0) or 0),
            int(result.get("armature_data_ptr", 0) or 0),
        )
        for result in results
    }
    if (
        len(sizes) != 1
        or next(iter(sizes), -1) != len(results)
        or sorted(indices) != list(range(len(results)))
        or len(solvers) != 1
        or len(identities) != 1
        or any(result.get("writeback_type") != "bone_transform_batch" for result in results)
    ):
        raise ValueError("公共 Bone 多 result 事务不完整或元数据不一致")


def _writeback_single_bone_transform(result, slot, touched_pose_bones):
    armature = _armature_for_bone_writeback(None, result, slot)
    if armature is None:
        raise ReferenceError("公共 Bone 写回目标 Armature 不存在或 data identity 已变化")
    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    if pose_bones is None:
        raise ReferenceError("公共 Bone 写回目标缺少 PoseBone 集合")
    bone_name = str(result.get("bone_name") or "")
    pose_bone = pose_bones.get(bone_name)
    if pose_bone is None:
        raise ReferenceError(f"公共 Bone 写回目标已失效: {bone_name!r}")
    matrix_basis = _validated_basis_matrix(result.get("matrix_basis"), bone_name)
    previous = pose_bone.matrix_basis.copy()
    try:
        pose_bone.matrix_basis = matrix_basis
    except Exception:
        try:
            pose_bone.matrix_basis = previous
        except Exception:
            pass
        raise
    _remember_touched_pose_bone(touched_pose_bones, result, bone_name)
    return armature, 1


def _writeback_bone_transform_batch(result, slot, touched_pose_bones):
    """兼容旧调用者；单 result 也走完整预检与原子提交。"""

    return _writeback_bone_transform_transaction(
        [result],
        [slot],
        touched_pose_bones,
    )


def _writeback_bone_transform_transaction(
    results,
    slots,
    touched_pose_bones,
) -> tuple[object, int]:
    first = results[0]
    armature = _armature_for_bone_writeback(None, first, slots[0])
    if armature is None:
        raise ReferenceError("公共 Bone 写回目标 Armature 不存在或 data identity 已变化")
    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    if pose_bones is None:
        raise ReferenceError("公共 Bone 写回目标缺少 PoseBone 集合")

    updates = []
    seen_bones = set()
    for result, slot in zip(results, slots):
        updates.extend(_preflight_bone_batch_result(
            result,
            slot,
            armature,
            pose_bones,
            seen_bones,
        ))

    basis_values = _bone_basis_buffer(pose_bones, slots)
    _apply_bone_basis_updates(pose_bones, updates, basis_values)
    for _pose_bone, _pose_index, _basis_matrix, bone_name in updates:
        _remember_touched_pose_bone(touched_pose_bones, first, bone_name)
    return armature, len(updates)


def _preflight_bone_batch_result(result, slot, armature, pose_bones, seen_bones):
    if slot is None:
        raise ReferenceError(
            f"公共 Bone 写回 slot 已失效: {str(result.get('slot_id') or '')!r}"
        )
    if not _armature_matches_writeback(armature, result):
        raise ReferenceError("公共 Bone 写回事务混入了其它 Armature identity")
    plan = slot.data.get("writeback_plan")
    if not isinstance(plan, dict):
        raise ValueError("公共 Bone batch 缺少 writeback_plan")
    plan_schema = str(result.get("plan_schema") or "")
    stored_schema = str(plan.get("schema") or "")
    if plan_schema and stored_schema and stored_schema != plan_schema:
        raise ValueError("公共 Bone result 与 writeback_plan schema 不一致")
    for name in ("armature_ptr", "armature_data_ptr"):
        plan_pointer = int(plan.get(name, 0) or 0)
        result_pointer = int(result.get(name, 0) or 0)
        if plan_pointer and plan_pointer != result_pointer:
            raise ReferenceError(f"公共 Bone writeback_plan 的 {name} 已失配")

    updates = []
    for batch in plan.get("batches") or ():
        if not isinstance(batch, dict):
            raise TypeError("公共 Bone writeback batch 必须是 dict")
        records = tuple(batch.get("records") or ())
        matrix_bases = tuple(batch.get("matrix_bases") or ())
        if len(records) != len(matrix_bases):
            raise ValueError("公共 Bone record 与 matrix_basis 数量不一致")
        for record, basis_value in zip(records, matrix_bases):
            if not isinstance(record, dict):
                raise TypeError("公共 Bone writeback record 必须是 dict")
            bone_name = str(record.get("bone_name") or "")
            if not bone_name or bone_name in seen_bones:
                raise ValueError(f"公共 Bone 写回目标为空或重复: {bone_name!r}")
            pose_bone = pose_bones.get(bone_name)
            if pose_bone is None:
                raise ReferenceError(f"公共 Bone 写回目标已失效: {bone_name!r}")
            pose_index = int(pose_bones.find(bone_name))
            if pose_index < 0:
                raise ReferenceError(f"公共 Bone 写回无法解析当前 pose index: {bone_name!r}")
            matrix_basis = _validated_basis_matrix(basis_value, bone_name)
            seen_bones.add(bone_name)
            updates.append((pose_bone, pose_index, matrix_basis, bone_name))

    result_count = int(result.get("bone_count", -1))
    plan_count = int(plan.get("bone_count", len(updates)))
    if result_count != len(updates) or plan_count != len(updates):
        raise ValueError(
            f"公共 Bone batch 数量不一致: result={result_count}, "
            f"plan={plan_count}, records={len(updates)}"
        )
    return updates


def _bone_basis_buffer(pose_bones, slots) -> list[float]:
    """复用纯数值 foreach 缓冲；不得把 Armature/PoseBone 放回持久计划。"""

    buffer_size = len(pose_bones) * 16
    plans = []
    basis_values = None
    for slot in slots:
        plan = slot.data.get("writeback_plan") if slot is not None else None
        if not isinstance(plan, dict):
            continue
        plans.append(plan)
        candidate = plan.get("basis_values")
        if isinstance(candidate, list) and len(candidate) == buffer_size:
            basis_values = candidate
    if basis_values is None:
        basis_values = [0.0] * buffer_size
    for plan in plans:
        plan["basis_values"] = basis_values
    return basis_values


def _validated_basis_matrix(value, bone_name: str):
    try:
        matrix = matrix_from_16(value)
        if not all(
            math.isfinite(float(matrix[row][column]))
            for row in range(4)
            for column in range(4)
        ):
            raise ValueError
    except Exception:
        raise ValueError(f"公共 Bone matrix_basis 非法: {bone_name!r}") from None
    return matrix


def _remember_touched_pose_bone(touched_pose_bones, result, bone_name: str) -> None:
    identity = (
        int(result.get("armature_ptr", 0) or 0),
        int(result.get("armature_data_ptr", 0) or 0),
        str(bone_name or ""),
    )
    if identity[0] > 0 and identity[1] > 0 and identity[2]:
        touched_pose_bones[identity] = identity


def _apply_bone_basis_updates(pose_bones, updates, basis_values=None) -> None:
    if not updates:
        return
    previous = tuple(
        (pose_bone, pose_bone.matrix_basis.copy())
        for pose_bone, _pose_index, _basis_matrix, _bone_name in updates
    )

    pose_indices = {pose_index for _bone, pose_index, _matrix, _name in updates}
    dense_owner = (
        len(updates) == len(pose_bones)
        and pose_indices == set(range(len(pose_bones)))
    )

    if dense_owner and isinstance(basis_values, list):
        candidate_values = basis_values
    elif dense_owner:
        try:
            buffer_size = len(pose_bones) * 16
        except Exception:
            buffer_size = (
                max(pose_index for _bone, pose_index, _matrix, _name in updates)
                + 1
            ) * 16
        candidate_values = [0.0] * buffer_size
    else:
        candidate_values = None
    if candidate_values is not None:
        try:
            pose_bones.foreach_get("matrix_basis", candidate_values)
            for _pose_bone, pose_index, basis_matrix, _bone_name in updates:
                _write_matrix_to_foreach_buffer(
                    candidate_values,
                    pose_index * 16,
                    basis_matrix,
                )
        except Exception:
            candidate_values = None

    if candidate_values is not None:
        try:
            pose_bones.foreach_set("matrix_basis", candidate_values)
            return
        except Exception as foreach_error:
            rollback_errors = _restore_bone_basis_updates(previous)
            if rollback_errors:
                raise RuntimeError(
                    f"bone batch foreach_set failed ({foreach_error}); rollback failed: "
                    + "; ".join(rollback_errors)
                ) from foreach_error

    try:
        for pose_bone, _pose_index, basis_matrix, _bone_name in updates:
            pose_bone.matrix_basis = basis_matrix
    except Exception as write_error:
        rollback_errors = _restore_bone_basis_updates(previous)
        if rollback_errors:
            raise RuntimeError(
                f"bone writeback failed ({write_error}); rollback failed: "
                + "; ".join(rollback_errors)
            ) from write_error
        raise


def _restore_bone_basis_updates(previous) -> list[str]:
    errors = []
    for pose_bone, old_basis in previous:
        try:
            pose_bone.matrix_basis = old_basis
        except Exception as rollback_error:
            errors.append(str(rollback_error))
    return errors


def _write_matrix_to_foreach_buffer(values: list[float], offset: int, matrix) -> None:
    """Blender 的 matrix foreach 布局为 column-major。"""
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


def _armature_for_bone_writeback(_world, result, _slot):
    return _find_armature_by_pointer(
        result.get("armature_ptr"),
        result.get("armature_data_ptr"),
    )


def _armature_matches_writeback(armature, result) -> bool:
    if armature is None:
        return False
    try:
        armature_ptr = int(result.get("armature_ptr", 0) or 0)
        data_ptr = int(result.get("armature_data_ptr", 0) or 0)
        data = getattr(armature, "data", None)
        return (
            armature_ptr > 0
            and data_ptr > 0
            and int(armature.as_pointer()) == armature_ptr
            and data is not None
            and int(data.as_pointer()) == data_ptr
        )
    except Exception:
        return False


def _find_armature_by_pointer(armature_ptr, armature_data_ptr=0):
    try:
        from ..OmniReferenceGuard import resolve_bpy_object_reference

        return resolve_bpy_object_reference(
            int(armature_ptr or 0),
            int(armature_data_ptr or 0),
            object_type="ARMATURE",
        )
    except Exception:
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
    snapshot["receipts"] = [dict(item) for item in snapshot.get("receipts", ())]
    return snapshot


def get_gn_writeback_receipts(world) -> tuple[dict, ...]:
    """Return immutable-by-copy receipts for successful GN target mutations."""

    source = getattr(world, "runtime_caches", {}).get(_GN_DIAGNOSTICS_KEY, {})
    receipts = source.get("receipts", ()) if isinstance(source, dict) else ()
    return tuple(dict(item) for item in receipts if isinstance(item, dict))


def _append_gn_writeback_receipt(world, diagnostics: dict, result) -> None:
    serial = int(world.runtime_caches.get(_GN_RECEIPT_SERIAL_KEY, 0) or 0) + 1
    world.runtime_caches[_GN_RECEIPT_SERIAL_KEY] = serial
    diagnostics["receipts"].append({
        "schema": "gn_writeback_receipt_v1",
        "serial": serial,
        "frame": int(diagnostics["frame"]),
        "generation": int(diagnostics["generation"]),
        "solver": str(result.get("solver") or ""),
        "slot_id": str(result.get("slot_id") or ""),
        "writer_id": str(result.get("writer_id") or ""),
        "target_key": str(result.get("target_key") or ""),
        "object_ptr": int(result.get("object_ptr", 0) or 0),
        "object_data_ptr": int(result.get("object_data_ptr", 0) or 0),
        "transaction_id": str(result.get("transaction_id") or ""),
        "transaction_index": int(result.get("transaction_index", -1)),
        "transaction_size": int(result.get("transaction_size", 0)),
    })


def _preflight_gn_target(result) -> dict:
    obj = _find_mesh_by_pointer(
        result.get("object_ptr"),
        result.get("object_data_ptr"),
    )
    if obj is None:
        raise ValueError("GN offset 目标 Mesh 不存在或 data pointer 已变化")
    if int(getattr(obj.data, "users", 1) or 1) != 1:
        raise ValueError("GN 物理 offset 要求目标 Mesh 数据单用户，避免共享数据串写")
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
    attribute = obj.data.attributes.get(GN_OFFSET_ATTRIBUTE_NAME)
    if attribute is not None and (
        attribute.domain != "POINT" or attribute.data_type != "FLOAT_VECTOR"
    ):
        raise ValueError("GN offset 保留属性类型或 domain 已被外部改写")
    modifier = obj.modifiers.get(GN_OFFSET_MODIFIER_NAME)
    if modifier is not None and modifier.type != "NODES":
        raise ValueError("GN offset 保留修改器已被外部改成非 Nodes 类型")
    previous = np.zeros((vertex_count, 3), dtype=np.float32)
    if attribute is not None:
        attribute.data.foreach_get("vector", previous.reshape(-1))
    return {
        "result": result,
        "obj": obj,
        "values": values,
        "previous": previous,
        "had_attribute": attribute is not None,
        "had_modifier": modifier is not None,
    }


def _restore_gn_target(target: dict) -> None:
    obj = target["obj"]
    if target["had_attribute"]:
        attribute = obj.data.attributes.get(GN_OFFSET_ATTRIBUTE_NAME)
        if attribute is None:
            attribute, _modifier = ensure_gn_offset_output(obj)
        attribute.data.foreach_set("vector", target["previous"].reshape(-1))
    else:
        attribute = obj.data.attributes.get(GN_OFFSET_ATTRIBUTE_NAME)
        if attribute is not None:
            obj.data.attributes.remove(attribute)
    if not target["had_modifier"]:
        modifier = obj.modifiers.get(GN_OFFSET_MODIFIER_NAME)
        if modifier is not None:
            obj.modifiers.remove(modifier)
    obj.data.update()
    obj.update_tag()


def _apply_gn_transaction(world, diagnostics: dict, results) -> tuple[set[str], bool]:
    targets = []
    try:
        targets = [_preflight_gn_target(result) for result in results]
        for target in targets:
            ensure_gn_offset_output(target["obj"])
        for target in targets:
            write_gn_local_offsets(target["obj"], target["values"])
    except Exception as write_error:
        rollback_errors = []
        for target in reversed(targets):
            try:
                _restore_gn_target(target)
                diagnostics["rollback_count"] += 1
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        message = f"GN 多目标事务失败：{write_error}"
        if rollback_errors:
            message += "；回滚失败：" + "; ".join(rollback_errors)
        for result in results:
            _gn_writeback_error(diagnostics, result, message)
            _set_gn_slot_error(world, result, message)
        diagnostics["failed_transaction_count"] += 1
        return set(), False

    written_targets = set()
    touched = _get_touched_gn_objects(world)
    for target in targets:
        result = target["result"]
        target_key = str(result["target_key"])
        touched[target_key] = target["obj"]
        written_targets.add(target_key)
        diagnostics["written_count"] += 1
        _append_gn_writeback_receipt(world, diagnostics, result)
        _set_gn_slot_error(world, result, None)
    diagnostics["committed_transaction_count"] += 1
    return written_targets, True


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
        "transaction_count": 0,
        "committed_transaction_count": 0,
        "failed_transaction_count": 0,
        "rollback_count": 0,
        "errors": [],
        "receipts": [],
    }
    world.runtime_caches[_GN_DIAGNOSTICS_KEY] = diagnostics
    touched = _get_touched_gn_objects(world)
    _ensure_cleanup_resource(world)

    by_target: dict[str, dict[str, dict]] = {}
    rejected_transactions = set()
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
            transaction_id = str(result.get("transaction_id") or "")
            if transaction_id:
                rejected_transactions.add(transaction_id)

    diagnostics["candidate_count"] = len(by_target)
    selected_results = []
    for target_key, writers in by_target.items():
        if len(writers) != 1:
            diagnostics["conflict_count"] += 1
            message = "同一 Mesh 目标存在多个最终 GN offset writer；请先在 world.exchange 归并"
            for result in writers.values():
                _gn_writeback_error(diagnostics, result, message)
                _set_gn_slot_error(world, result, message)
                transaction_id = str(result.get("transaction_id") or "")
                if transaction_id:
                    rejected_transactions.add(transaction_id)
            old_obj = touched.pop(target_key, None)
            if old_obj is not None and clear_gn_local_offsets(old_obj):
                diagnostics["cleared_count"] += 1
            continue
        selected_results.append(next(iter(writers.values())))

    transactions: dict[str, list[dict]] = {}
    for sequence, result in enumerate(selected_results):
        transaction_id = str(result.get("transaction_id") or "")
        key = (
            f"transaction:{transaction_id}"
            if transaction_id
            else f"single:{sequence}:{result.get('target_key', '')}"
        )
        transactions.setdefault(key, []).append(result)
    diagnostics["transaction_count"] = len(transactions)

    written_targets = set()
    for key, transaction_results in transactions.items():
        transaction_id = (
            str(transaction_results[0].get("transaction_id") or "")
            if transaction_results else ""
        )
        error = None
        if transaction_id and transaction_id in rejected_transactions:
            error = "GN 多目标事务包含冲突或非法 target"
        elif transaction_id:
            sizes = {int(result.get("transaction_size", -1)) for result in transaction_results}
            indices = [int(result.get("transaction_index", -1)) for result in transaction_results]
            solvers = {str(result.get("solver") or "") for result in transaction_results}
            if (
                len(sizes) != 1
                or next(iter(sizes), -1) != len(transaction_results)
                or sorted(indices) != list(range(len(transaction_results)))
                or len(solvers) != 1
            ):
                error = "GN 多目标事务不完整或批次元数据不一致"
            else:
                transaction_results.sort(key=lambda item: int(item["transaction_index"]))
        if error:
            diagnostics["failed_transaction_count"] += 1
            for result in transaction_results:
                _gn_writeback_error(diagnostics, result, error)
                _set_gn_slot_error(world, result, error)
            continue
        committed, _success = _apply_gn_transaction(
            world,
            diagnostics,
            transaction_results,
        )
        written_targets.update(committed)

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

    restart=True 时先统一清除刚体、骨骼和 GN 三种写回状态，再写入本帧结果。
    """
    if restart:
        reset_all_writebacks(world)

    total  = writeback_rigid_body_deltas(world)
    total += writeback_bone_transforms(world)
    total += writeback_gn_attributes(world)
    return total
