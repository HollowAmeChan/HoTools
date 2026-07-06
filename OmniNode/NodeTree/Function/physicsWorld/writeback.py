"""
physicsWorld.writeback — 物理写回算法

包含所有物理写回类型的实现，与节点声明文件（nodes.py）分离。

写回类型（对应三种偏移量语义）：
  1. rigid_body_delta  → Object.delta_location / delta_rotation_euler
  2. bone_transform    → PoseBone.matrix_basis（未来扩展占位）
  3. gn_attribute      → mesh attribute offset（未来扩展占位）

跳帧 / 复位处理：
  调用方通过检查 world.frame_context.restart_required 来决定是否触发
  归零和 frame=0 K 帧逻辑。frame_context 中的 continuous / same_frame
  标志由 Physics World Begin 统一维护，writeback 只消费，不自己判断帧连续性。
"""

from __future__ import annotations

import mathutils


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def has_keyframe_at_frame0(obj, data_path: str) -> bool:
    """检查对象在 frame=0 是否已有指定属性的 K 帧（容差 ±0.5 帧）。"""
    ad = getattr(obj, "animation_data", None)
    if ad is None or ad.action is None:
        return False
    for fc in ad.action.fcurves:
        if fc.data_path == data_path:
            if any(abs(kp.co[0]) < 0.5 for kp in fc.keyframe_points):
                return True
    return False


# ---------------------------------------------------------------------------
# 1. 刚体 delta 写回
# ---------------------------------------------------------------------------

def reset_rigid_body_deltas(world) -> None:
    """
    将所有 DYNAMIC 刚体对象的 delta_location / delta_rotation_euler 归零。

    触发时机：restart_required=True（跳帧、显式 reset、scope 变化等）。
    归零后对象返回原始 obj.location 所记录的位置。
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


def ensure_frame0_delta_keyframes(world) -> None:
    """
    对所有 DYNAMIC 刚体对象：若 frame=0 还没有 delta_location /
    delta_rotation_euler 的 K 帧，则插入一次全零K帧。

    语义：frame=0 = 物理未启动 = delta 全零 = 对象在原始 obj.location。
    之后用户拖时间轴到 frame=0，delta 自动归零即可复位。

    调用时机：restart_required=True 且写入物理结果之前。
    不覆盖已有 K 帧（幂等）。
    """
    for slot in world.solver_slots.values():
        if slot.kind != "rigid_body":
            continue
        spec = slot.data.get("spec")
        if spec is None or spec.body_type != "DYNAMIC" or spec.obj is None:
            continue
        obj = spec.obj
        try:
            if not has_keyframe_at_frame0(obj, "delta_location"):
                obj.delta_location = (0.0, 0.0, 0.0)
                obj.keyframe_insert("delta_location", frame=0)
            if not has_keyframe_at_frame0(obj, "delta_rotation_euler"):
                obj.delta_rotation_euler = (0.0, 0.0, 0.0)
                obj.keyframe_insert("delta_rotation_euler", frame=0)
        except Exception:
            pass


def writeback_rigid_body_deltas(world) -> int:
    """
    从 JoltAdapter 读取 DYNAMIC 刚体的当前变换，写入 Blender 对象的
    delta_location / delta_rotation_euler（增量变换）。

    不修改 obj.location / rotation_euler，保留原始变换供复位参考。
    复位 = 将 delta 归零，调用 reset_rigid_body_deltas()。

    返回成功写回的对象数量。
    """
    adapter = world.backend_resources.get("rigid_solver")
    if adapter is None or not getattr(adapter, "_valid", False):
        return 0

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

            # 位置 delta = Jolt世界位置 - 对象原始 obj.location
            jolt_pos = mathutils.Vector(pos_arr)
            obj.delta_location = jolt_pos - obj.location

            # 旋转 delta：从原始 rotation_euler 到 Jolt 旋转的增量
            # 使用矩阵差值保证精度，支持所有欧拉序
            q = mathutils.Quaternion((
                float(rot_arr[0]), float(rot_arr[1]),
                float(rot_arr[2]), float(rot_arr[3])
            ))
            rest_rot  = obj.rotation_euler.to_matrix().to_4x4()
            jolt_rot  = q.to_matrix().to_4x4()
            delta_mat = rest_rot.inverted() @ jolt_rot
            obj.delta_rotation_euler = delta_mat.to_euler(obj.rotation_mode)

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
    """
    消费 world.exchange["spring_bone_matrices"] 等骨骼类 solver 结果，
    批量写入 PoseBone.matrix_basis，统一 armature.update_tag()。

    当前为占位实现，SpringBone / BoneCloth 迁移到模式 B 后在此实现。
    返回写回的骨骼数量。
    """
    # TODO：Phase 7 迁移 SpringBone / BoneCloth 到 world.exchange 时实现
    return 0


# ---------------------------------------------------------------------------
# 3. GN 属性写回（未来扩展占位）
# ---------------------------------------------------------------------------

def writeback_gn_attributes(world) -> int:
    """
    消费 world.exchange["mesh_delta_attributes"] 等 GN 属性类 solver 结果，
    写入 mesh attribute（offset 语义，复位 = 全部归零）。

    当前为占位实现，MeshCloth 迁移到 world.exchange 后在此实现。
    返回写回的属性条目数量。
    """
    # TODO：Phase 7 迁移 MeshCloth 时实现
    return 0


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def apply_all_writebacks(world, restart: bool, frame0_keyframe: bool) -> int:
    """
    统一写回入口，被 physicsWriteback 节点调用。

    参数：
      world          — PhysicsWorldCache
      restart        — world.frame_context.restart_required（跳帧/复位/首帧）
      frame0_keyframe— True 时在 restart 时向 frame=0 插入一次全零K帧

    执行顺序（物理结果写入前已由 solver 完成）：
      1. restart=True → frame=0 K帧（delta=0 参考帧，幂等）
      2. restart=True → delta 归零（清除上次模拟残留）
      3. 写入刚体 delta
      4. 写入骨骼（占位）
      5. 写入 GN 属性（占位）
    """
    if restart:
        if frame0_keyframe:
            try:
                ensure_frame0_delta_keyframes(world)
            except Exception:
                pass
        reset_rigid_body_deltas(world)

    total  = writeback_rigid_body_deltas(world)
    total += writeback_bone_transforms(world)
    total += writeback_gn_attributes(world)
    return total
