"""
physicsWorld.writeback — 物理写回算法

包含所有物理写回类型的实现，与节点声明文件（nodes.py）分离。

写回类型（对应三种偏移量语义，归零即复位）：
  1. rigid_body_delta  → Object.delta_location / delta_rotation_euler
  2. bone_transform    → PoseBone.matrix_basis（未来扩展占位）
  3. gn_attribute      → mesh attribute offset（未来扩展占位）

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


# ---------------------------------------------------------------------------
# 受影响对象注册表 key
# ---------------------------------------------------------------------------

_TOUCHED_OBJECTS_KEY    = "_writeback_touched_objects"
_CLEANUP_RESOURCE_KEY   = "_writeback_cleanup"


class WritebackCleanupResource:
    """
    挂在 world.backend_resources 里的清理对象。
    实现 omni_cache_dispose 协议：world 被 Cache Delete / addon 注销时
    自动将所有曾写过 delta 的对象归零，不残留物理偏移。
    """
    def __init__(self, touched: set):
        self._touched = touched

    def omni_cache_dispose(self, reason: str) -> None:
        for obj in list(self._touched):
            try:
                obj.delta_location       = (0.0, 0.0, 0.0)
                obj.delta_rotation_euler = (0.0, 0.0, 0.0)
                obj.update_tag()
            except Exception:
                pass
        self._touched.clear()


def _get_touched_set(world) -> set:
    """获取（或创建）本 world 记录的"已写过 delta"对象集合。"""
    br = world.backend_resources
    if _TOUCHED_OBJECTS_KEY not in br:
        br[_TOUCHED_OBJECTS_KEY] = set()
    return br[_TOUCHED_OBJECTS_KEY]


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
        if slot.kind != "rigid_body":
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
    清除本 world 期间所有曾被写过 delta 的对象（无论是否在 solver_slots 里）。
    在 omni_cache_dispose / Cache Delete / 停止模拟时调用，确保对象归位。
    """
    touched = _get_touched_set(world)
    for obj in list(touched):
        try:
            obj.delta_location       = (0.0, 0.0, 0.0)
            obj.delta_rotation_euler = (0.0, 0.0, 0.0)
            obj.update_tag()
        except Exception:
            pass
    touched.clear()


def writeback_rigid_body_deltas(world) -> int:
    """
    从 JoltAdapter 读取 DYNAMIC 刚体的当前变换，写入 Blender 对象的
    delta_location / delta_rotation_euler（增量变换）。

    不修改 obj.location / rotation_euler，保留原始变换。
    复位 = delta 归零（调用 reset_rigid_body_deltas 或 clear_all_deltas）。

    返回成功写回的对象数量。
    """
    adapter = world.backend_resources.get("rigid_solver")
    if adapter is None or not getattr(adapter, "_valid", False):
        return 0

    touched = _get_touched_set(world)
    # 首次写回时注册清理资源，确保 world dispose 时自动归零 delta
    if _CLEANUP_RESOURCE_KEY not in world.backend_resources:
        world.backend_resources[_CLEANUP_RESOURCE_KEY] = WritebackCleanupResource(touched)

    updated = set()
    written = 0

    for slot_id, handle in list(adapter._body_handles.items()):
        slot = world.solver_slots.get(slot_id)
        spec = slot.data.get("spec") if slot else None
        if spec is None or spec.body_type != "DYNAMIC" or spec.obj is None:
            continue

        result = adapter._jw.get_body_transform(handle)
        if result is None:
            continue

        try:
            pos_arr, rot_arr = result
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
            if slot:
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
    # TODO：Phase 7 迁移 SpringBone / BoneCloth 到 world.exchange 时实现
    return 0


# ---------------------------------------------------------------------------
# 3. GN 属性写回（未来扩展占位）
# ---------------------------------------------------------------------------

def writeback_gn_attributes(world) -> int:
    # TODO：Phase 7 迁移 MeshCloth 时实现
    return 0


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

    total  = writeback_rigid_body_deltas(world)
    total += writeback_bone_transforms(world)
    total += writeback_gn_attributes(world)
    return total
