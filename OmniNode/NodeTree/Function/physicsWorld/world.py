"""
physicsWorld.world — Physics World Begin / Commit 实现

physicsWorldBegin:
  校验 scope → 创建或复用 world → 更新 FrameContext →
  计算 scope key → 构建 collider sources → 构建 collider snapshot →
  清写入锁 → 返回裸 world owner

physicsWorldCommit:
  校验 world → 按 replace_required 生成 replace / mutate intent →
  透传裸 world 供后续节点使用

外部 solver 使用示例：

    world.acquire_write(solver_id)
    try:
        slot = world.ensure_solver_slot(slot_id, kind)
        # ... solver kernel ...
    finally:
        world.release_write(solver_id)
"""

from __future__ import annotations

import mathutils
import bpy

from .types import (
    PhysicsWorldCache,
    PhysicsObjectScope,
    PhysicsColliderSource,
)
from .scope import (
    build_scope_key,
    collect_physics_sources,
    _obj_is_valid,
    _obj_is_visible,
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

_EPSILON = 1e-7


def _scene_key(scene) -> str:
    if scene is None:
        return "scene:<none>"
    try:
        return f"scene:{int(scene.as_pointer())}"
    except Exception:
        return f"scene:{id(scene)}"


def _scene_delta_time(scene) -> float:
    """从场景 render 设置读取帧间隔（秒）。"""
    try:
        render = scene.render
        fps_base = float(render.fps_base) if render.fps_base else 1.0
        fps = float(render.fps) / fps_base
        return 1.0 / fps if fps > _EPSILON else 0.0
    except Exception:
        return 1.0 / 24.0


def _matrix_scale_radius(matrix: mathutils.Matrix) -> float:
    try:
        scale = matrix.to_scale()
        return max(abs(float(scale.x)), abs(float(scale.y)), abs(float(scale.z)))
    except Exception:
        return 1.0


def _vector3(value, fallback: mathutils.Vector) -> mathutils.Vector:
    if value is None or value == "":
        return fallback.copy()
    try:
        vec = mathutils.Vector(value)
    except Exception:
        return fallback.copy()
    if len(vec) == 0:
        return fallback.copy()
    return vec.to_3d()


# ---------------------------------------------------------------------------
# 从 PhysicsColliderSource 构建碰撞条目
# ---------------------------------------------------------------------------

def _collider_from_source(source: PhysicsColliderSource) -> dict | None:
    """
    把单个 PhysicsColliderSource 转成碰撞 dict，与旧 build_collision_snapshot_from_scene 格式兼容。

    支持的 collision_type：SPHERE、CAPSULE（Object 和 Bone 级）。
    MESH 类型不产生碰撞 dict（它是 solver 内部的 mesh collision，不走此路径）。
    """
    props = source.props
    if props is None:
        return None

    owner = source.owner
    owner_type = source.owner_type

    # 计算世界矩阵
    try:
        if owner_type == "BONE":
            armature_obj = owner
            pose_bone = armature_obj.pose.bones.get(source.bone_name) if armature_obj.pose else None
            bone = armature_obj.data.bones.get(source.bone_name) if armature_obj.data else None
            local_matrix = pose_bone.matrix if pose_bone is not None else (
                bone.matrix_local if bone is not None else mathutils.Matrix.Identity(4)
            )
            matrix = armature_obj.matrix_world @ local_matrix
        else:
            matrix = owner.matrix_world
    except Exception:
        return None

    collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
    if collision_type not in {"SPHERE", "CAPSULE"}:
        return None

    radius = max(float(getattr(props, "radius", 0.0)), 0.0) * _matrix_scale_radius(matrix)
    if radius <= _EPSILON:
        return None

    offset = _vector3(getattr(props, "offset", None), mathutils.Vector((0.0, 0.0, 0.0)))
    center = matrix @ offset
    group = max(1, min(16, int(getattr(props, "primary_collision_group", 1))))

    collider: dict = {
        "type": collision_type,
        "owner": owner,
        "owner_type": owner_type,
        "bone": source.bone_name,
        "primary_group": group,
        "center": center,
        "radius": radius,
        "source_key": source.key,
    }

    if collision_type == "CAPSULE":
        half_length = max(float(getattr(props, "length", 0.0)), 0.0) * 0.5
        axis = mathutils.Vector((0.0, 1.0, 0.0))
        collider["segment_a"] = matrix @ (offset - axis * half_length)
        collider["segment_b"] = matrix @ (offset + axis * half_length)

    return collider


def build_collider_snapshot(world: PhysicsWorldCache, sources: list[PhysicsColliderSource], frame: int) -> dict:
    """
    把 ColliderSource 列表转成碰撞快照 dict。

    快照格式与旧 build_collision_snapshot_from_scene 兼容，
    MESH 类型 source 不产生碰撞条目（只作为 solver 的配置来源）。
    """
    colliders = []
    for source in sources:
        if source.owner_type == "MESH":
            continue  # Mesh collision 由 solver 内部处理
        entry = _collider_from_source(source)
        if entry is not None:
            colliders.append(entry)

    return {
        "frame": frame,
        "colliders": colliders,
        "source_count": len(sources),
    }


# ---------------------------------------------------------------------------
# Physics World Begin
# ---------------------------------------------------------------------------

def physicsWorldBegin(
    cache_state,
    scene: bpy.types.Scene,
    object_scope: PhysicsObjectScope,
    enabled: bool = True,
    reset: bool = False,
    time_scale: float = 1.0,
    substeps: int = 1,
    debug_output: bool = False,
) -> tuple:
    """
    物理世界帧开始节点。

    返回 (world, frame, collider_count, restart_required)：
      world           — 裸 PhysicsWorldCache owner（不是 cache intent）
      frame           — 当前帧帧号
      collider_count  — 本帧参与碰撞的条目数量
      restart_required — 是否需要 solver 冷启动

    注意：
    - include_hidden 由 object_scope 决定，此函数不再接收该参数。
    - replace_required 只由此函数写入；Physics World Commit 只读。
    - 返回的 world 是裸对象，不是 _OmniCache.mutate/replace intent。
    """
    # enabled=False 时直接透传，不修改 cache
    if not enabled:
        world = cache_state if isinstance(cache_state, PhysicsWorldCache) else PhysicsWorldCache()
        fc = world.frame_context
        return world, fc.frame, 0, True

    # 校验 scene
    if scene is None:
        try:
            scene = bpy.context.scene
        except Exception:
            scene = None
    if scene is None:
        world = PhysicsWorldCache()
        world.replace_required = True
        return world, 0, 0, True

    # 校验 scope
    if not isinstance(object_scope, PhysicsObjectScope):
        object_scope = PhysicsObjectScope()

    # 获取或创建 world owner
    # 注意：脏帧（帧不连续）会在后面检测，此时先拿到 committed owner
    from ...OmniNodeSocketMapping import _OmniCache
    raw = cache_state
    if hasattr(raw, "value"):  # _OmniCache 包装
        raw = raw.value

    if isinstance(raw, PhysicsWorldCache):
        world = raw
    else:
        world = PhysicsWorldCache()

    # 每帧开始清写入锁（防止上帧异常退出留下锁）
    world.clear_write_lock()

    fc = world.frame_context
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    previous_frame = fc.frame if fc.previous_frame is not None or fc.frame != 0 else None

    # 计算 dt
    raw_dt = _scene_delta_time(scene)
    effective_dt = raw_dt * max(float(time_scale), 0.0)

    # 判断帧连续性
    continuous = (previous_frame is not None) and (current_frame == previous_frame + 1)
    same_frame = (previous_frame is not None) and (current_frame == previous_frame)
    jumped = (previous_frame is not None) and not continuous and not same_frame

    # 脏帧检测：帧号不连续时标记 world.valid = False，触发重建
    if jumped and world.valid:
        world.valid = False

    # 脏帧 / 首帧：重建 world，不复用现有状态
    if not world.valid or world.generation == 0:
        if world is raw and isinstance(raw, PhysicsWorldCache):
            # 旧 world 需要被 replace，新建一个
            world = PhysicsWorldCache()
        world.generation += 1
        world.replace_required = True
        world.valid = True
        # 重建时更新 fc 引用
        fc = world.frame_context

    # 计算 scope key，检测对象范围变化
    new_scope_key = build_scope_key(object_scope)
    scope_changed = (world.object_scope_key is not None) and (new_scope_key != world.object_scope_key)
    if scope_changed:
        world.generation += 1
        world.replace_required = True
        world.invalidate_all_slots("scope_changed")

    world.object_scope_key = new_scope_key

    # 处理显式 reset
    if reset:
        world.generation += 1
        world.replace_required = True
        world.invalidate_all_slots("reset_requested")

    # 更新 FrameContext
    fc.scene_key = _scene_key(scene)
    fc.frame = current_frame
    fc.previous_frame = previous_frame
    fc.continuous = continuous
    fc.same_frame = same_frame
    fc.reset_requested = bool(reset)
    fc.restart_required = bool(reset) or scope_changed or (not continuous and not same_frame) or (previous_frame is None)
    fc.dt = effective_dt
    fc.time_scale = float(time_scale)
    fc.substeps = max(1, int(substeps))
    fc.generation = world.generation

    # 收集 collider sources 并构建快照
    # previous snapshot 先保留上帧数据（供 MC2 moving collider 使用）
    if world.collider_snapshot.get("frame") is not None:
        world.previous_collider_snapshot = world.collider_snapshot

    sources, invalid_count = collect_physics_sources(object_scope)
    new_snapshot = build_collider_snapshot(world, sources, current_frame)
    new_snapshot["invalid_count"] = invalid_count
    world.collider_snapshot = new_snapshot

    collider_count = len(new_snapshot.get("colliders") or [])

    if debug_output:
        print(
            f"[PhysicsWorldBegin] gen={world.generation} frame={current_frame} "
            f"prev={previous_frame} continuous={continuous} restart={fc.restart_required} "
            f"colliders={collider_count} invalid={invalid_count} "
            f"replace={world.replace_required}"
        )

    return world, current_frame, collider_count, fc.restart_required


# ---------------------------------------------------------------------------
# Physics World Commit
# ---------------------------------------------------------------------------

def physicsWorldCommit(
    world,
    enabled: bool = True,
) -> tuple:
    """
    物理世界帧提交节点。

    返回 (cache_value, world, solver_count)：
      cache_value  — _OmniCache.replace(world) 或 _OmniCache.mutate(world)
      world        — 裸 PhysicsWorldCache，供后续 debug/输出节点使用
      solver_count — 当前活跃的 solver slot 数量

    注意：
    - replace_required 只由 Physics World Begin 写入，此函数只读。
    - 最终仍由 Cache Write 节点提交到 OmniRuntimeState。
    """
    from ...OmniNodeSocketMapping import _OmniCache

    if not enabled or world is None:
        return _OmniCache.replace(None), world, 0

    if not isinstance(world, PhysicsWorldCache):
        return _OmniCache.replace(None), world, 0

    solver_count = len(world.solver_slots)

    if world.replace_required:
        cache_value = _OmniCache.replace(world)
    else:
        cache_value = _OmniCache.mutate(world)

    # Commit 成功后清除 replace 标志，下一帧默认走 mutate
    world.replace_required = False

    return cache_value, world, solver_count
