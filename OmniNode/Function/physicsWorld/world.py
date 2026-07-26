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

# ──────────────────────────────────────────────────────────────────────────────
# physicsWorldBegin 可以内置的内容边界（严格约束，禁止蔓延）
# ──────────────────────────────────────────────────────────────────────────────
#
# physicsWorldBegin 的职责是"从 scope 对象读取 Physics World 属性，构建公共上下文"。
# 这个职责允许内置的内容仅限于：
#
#   ✅ 允许（属于 scope 扫描 + Physics World 属性解析的范畴）：
#     - 从 Object.hotools_object_collision 构建 collider source
#     - 从 Bone.hotools_collision 构建 bone collider source
#     - 从 Object.hotools_rigid_body 构建 RigidBodySpec（slot 注册）
#     - 从 Object.hotools_rigid_constraint 构建 ConstraintSpec（slot 注册）
#     - collider snapshot 构建（汇总以上 source）
#     - scope key 计算（检测 scope 变化触发 restart）
#
#   ❌ 禁止内置（属于 solver 职责，必须由 solver 节点自己处理）：
#     - SpringBone chain 设置（hotools_collision.spring_root 或任何 VRM 链设置）
#     - MC2 mesh cloth 设置（hotools_mesh_collision 里的布料参数）
#     - MC2 bone cloth 设置（MC2 骨骼链拓扑）
#     - 任何 solver 的 spec build 逻辑（只要不是 "从 Physics World 读物理属性"）
#     - 任何 solver 的 native context / handle 创建
#     - 任何 solver 的 result stream 发布
#
# 判断标准：如果新增的内容在 ARCHITECTURE.md 里写的是
#   "节点图不应该知道这些业务参数"，就不该放进 Begin。
#
# 违反这条边界的后果：Begin 会逐渐变成"知道所有 solver"的上帝节点，
# 破坏"Begin 不应该知道 MeshCloth/SpringBone 业务参数"的架构原则。
# ──────────────────────────────────────────────────────────────────────────────
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
)
from .utils.geometry import matrix_scale_radius


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


def _vector3(value, fallback: mathutils.Vector) -> mathutils.Vector:
    if value is None or value == "":
        return fallback.copy()
    try:
        vec = mathutils.Vector(value)
    except Exception:
        return fallback.copy()
    if len(vec) == 0:
        return fallback.copy()
    if len(vec) == 1:
        return mathutils.Vector((vec[0], fallback[1], fallback[2]))
    if len(vec) == 2:
        return mathutils.Vector((vec[0], vec[1], fallback[2]))
    return vec.to_3d()


def _world_normal(matrix: mathutils.Matrix, local_axis: mathutils.Vector) -> mathutils.Vector | None:
    try:
        normal = matrix.to_3x3() @ local_axis
    except Exception:
        return None
    if normal.length <= _EPSILON:
        return None
    normal.normalize()
    return normal


def _world_axis(matrix: mathutils.Matrix, local_axis: mathutils.Vector, fallback: mathutils.Vector) -> mathutils.Vector:
    try:
        axis = matrix.to_3x3() @ local_axis
    except Exception:
        return fallback.copy()
    if axis.length <= _EPSILON:
        return fallback.copy()
    return axis


def _box_half_axes(
    matrix: mathutils.Matrix,
    size: mathutils.Vector,
) -> tuple[mathutils.Vector, mathutils.Vector, mathutils.Vector] | None:
    """从 Object.matrix_world 和 Physics World box_size 解析有向盒半轴。"""
    try:
        basis = matrix.to_3x3()
        axis_x = basis @ mathutils.Vector((max(float(size.x), 0.0) * 0.5, 0.0, 0.0))
        axis_y = basis @ mathutils.Vector((0.0, max(float(size.y), 0.0) * 0.5, 0.0))
        raw_axis_z = basis @ mathutils.Vector((0.0, 0.0, max(float(size.z), 0.0) * 0.5))
    except Exception:
        return None

    if (
        axis_x.length <= _EPSILON
        or axis_y.length <= _EPSILON
        or raw_axis_z.length <= _EPSILON
    ):
        return None

    axis_z = axis_x.cross(axis_y)
    if axis_z.length <= _EPSILON:
        return None
    axis_z.normalize()
    if raw_axis_z.dot(axis_z) < 0.0:
        axis_z.negate()
    axis_z *= raw_axis_z.length
    return axis_x, axis_y, axis_z


def _compact_collider_snapshot(colliders: list[dict] | None) -> dict:
    """
    构造按 collider key 索引的 previous snapshot。

    完整当前帧仍存放在 world.collider_snapshot["colliders"] list 中；
    这个紧凑版本用于 moving collider 查询。
    """
    snapshots = {}
    for collider in colliders or []:
        if not isinstance(collider, dict):
            continue
        key = collider.get("key") or collider.get("source_key")
        center = collider.get("center")
        if not key or center is None:
            continue
        collider_type = str(collider.get("type", "SPHERE") or "SPHERE")
        if collider_type == "CAPSULE":
            segment_a = collider.get("segment_a", center)
            segment_b = collider.get("segment_b", center)
        elif collider_type == "PLANE":
            segment_a = collider.get("normal")
            segment_b = center
            if segment_a is None:
                continue
        elif collider_type == "BOX":
            segment_a = collider.get("box_axis_x")
            segment_b = collider.get("box_axis_y")
            axis_z = collider.get("box_axis_z")
            if segment_a is None or segment_b is None or axis_z is None:
                continue
        else:
            segment_a = center
            segment_b = center

        snapshot = {
            "type": collider_type,
            "center": center,
            "segment_a": segment_a,
            "segment_b": segment_b,
        }
        if collider_type == "PLANE":
            snapshot["normal"] = segment_a
        elif collider_type == "BOX":
            snapshot["box_axis_x"] = segment_a
            snapshot["box_axis_y"] = segment_b
            snapshot["box_axis_z"] = collider.get("box_axis_z")
        snapshots[str(key)] = snapshot
    return {"colliders": snapshots}


def _clear_writeback_deltas_for_world(world: PhysicsWorldCache) -> None:
    """清除旧 world 已写过的物理 delta，避免 restart 后残留末帧姿态。"""
    try:
        from .writeback import clear_all_deltas
        clear_all_deltas(world)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 从 PhysicsColliderSource 构建碰撞条目
# ---------------------------------------------------------------------------

def _collider_from_source(source: PhysicsColliderSource) -> dict | None:
    """
    把单个 PhysicsColliderSource 转成碰撞 dict，与旧 build_collision_snapshot_from_scene 格式兼容。

    支持的 collision_type：
      - Object 级：SPHERE、CAPSULE、PLANE、BOX
      - Bone 级：SPHERE、CAPSULE
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
    allowed_types = {"SPHERE", "CAPSULE"} if owner_type == "BONE" else {"SPHERE", "CAPSULE", "PLANE", "BOX"}
    if collision_type not in allowed_types:
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
        "key": source.key,
        "source_key": source.key,
    }

    if collision_type in {"SPHERE", "CAPSULE"}:
        radius = max(float(getattr(props, "radius", 0.0)), 0.0) * matrix_scale_radius(matrix)
        if radius <= _EPSILON:
            return None
        collider["radius"] = radius

    if collision_type == "CAPSULE":
        half_length = max(float(getattr(props, "length", 0.0)), 0.0) * 0.5
        axis = mathutils.Vector((0.0, 1.0, 0.0))
        collider["segment_a"] = matrix @ (offset - axis * half_length)
        collider["segment_b"] = matrix @ (offset + axis * half_length)
    elif collision_type == "PLANE":
        normal = _world_normal(matrix, mathutils.Vector((0.0, 0.0, 1.0)))
        if normal is None:
            return None
        half_size = max(float(getattr(props, "length", 1.0)), 1.0) * 0.5
        collider["radius"] = 0.0
        collider["normal"] = normal
        collider["plane_axis_x"] = _world_axis(
            matrix,
            mathutils.Vector((half_size, 0.0, 0.0)),
            mathutils.Vector((half_size, 0.0, 0.0)),
        )
        collider["plane_axis_y"] = _world_axis(
            matrix,
            mathutils.Vector((0.0, half_size, 0.0)),
            mathutils.Vector((0.0, half_size, 0.0)),
        )
    elif collision_type == "BOX":
        size = _vector3(getattr(props, "box_size", None), mathutils.Vector((1.0, 1.0, 1.0)))
        axes = _box_half_axes(matrix, size)
        if axes is None:
            return None
        collider["radius"] = 0.0
        collider["box_axis_x"] = axes[0]
        collider["box_axis_y"] = axes[1]
        collider["box_axis_z"] = axes[2]

    return collider


def build_collider_snapshot(world: PhysicsWorldCache, sources: list[PhysicsColliderSource], frame: int) -> dict:
    """
    把 ColliderSource 列表转成碰撞快照 dict。

    快照格式与旧 build_collision_snapshot_from_scene 兼容，
    """
    colliders = []
    for source in sources:
        entry = _collider_from_source(source)
        if entry is not None:
            colliders.append(entry)

    object_keys = set()
    for source in sources:
        try:
            object_keys.add(int(source.owner.as_pointer()))
        except Exception:
            pass

    return {
        "frame": frame,
        "colliders": colliders,
        "source_count": len(sources),
        "object_count": len(object_keys),
    }


# ---------------------------------------------------------------------------
# 物理世界 Begin
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
    world.clear_exchange()
    world.clear_results()

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
    restart_before_scope = bool(reset) or jumped or (previous_frame is None)

    if restart_before_scope:
        _clear_writeback_deltas_for_world(world)

    # 脏帧检测：帧号不连续时标记 world.valid = False，触发重建
    if jumped and world.valid:
        world.valid = False

    # 脏帧 / 首帧：重建 world，不复用现有状态
    if not world.valid or world.generation == 0:
        if world is raw and isinstance(raw, PhysicsWorldCache):
            # 旧 world 需要被 replace，新建一个
            previous_world = world
            world = PhysicsWorldCache()
            world.copy_implicit_objects_from(previous_world)
        world.generation += 1
        world.replace_required = True
        world.valid = True
        # 重建时更新 fc 引用
        fc = world.frame_context

    # 计算 scope key，检测对象范围变化
    new_scope_key = build_scope_key(object_scope)
    scope_changed = (world.object_scope_key is not None) and (new_scope_key != world.object_scope_key)
    if scope_changed:
        _clear_writeback_deltas_for_world(world)
        world.generation += 1
        world.replace_required = True
        world.invalidate_all_slots("scope_changed")

    world.object_scope_key = new_scope_key

    # 处理显式 reset
    if reset:
        _clear_writeback_deltas_for_world(world)
        world.generation += 1
        world.replace_required = True
        world.invalidate_all_slots("reset_requested")

    restart_required = bool(reset) or scope_changed or (not continuous and not same_frame) or (previous_frame is None)
    if restart_required:
        _run_scope_restart_handlers(world, object_scope)

    # 更新 FrameContext
    fc.scene_key = _scene_key(scene)
    fc.frame = current_frame
    fc.previous_frame = previous_frame
    fc.continuous = continuous
    fc.same_frame = same_frame
    fc.reset_requested = bool(reset)
    fc.restart_required = restart_required
    fc.raw_dt = raw_dt
    fc.dt = effective_dt
    fc.time_scale = float(time_scale)
    fc.substeps = max(1, int(substeps))
    fc.generation = world.generation

    # 收集 collider sources 并构建快照。
    # 连续帧才保留上帧紧凑快照；restart 帧不沿用旧 pose。
    if (not fc.restart_required) and world.collider_snapshot.get("frame") is not None:
        world.previous_collider_snapshot = _compact_collider_snapshot(
            world.collider_snapshot.get("colliders") or []
        )
    else:
        world.previous_collider_snapshot = None

    sources, invalid_count = collect_physics_sources(object_scope)
    new_snapshot = build_collider_snapshot(world, sources, current_frame)
    new_snapshot["invalid_count"] = invalid_count
    world.collider_snapshot = new_snapshot

    collider_count = len(new_snapshot.get("colliders") or [])

    # 允许已装载解算器从对象作用域正式收集自己的规格和槽输入。
    # 物理世界 Begin 不直接知道刚体、弹簧、布料等解算器的私有脏标记策略。
    _collect_scope_solver_specs(world, object_scope)

    if debug_output:
        print(
            f"[PhysicsWorldBegin] gen={world.generation} frame={current_frame} "
            f"prev={previous_frame} continuous={continuous} restart={fc.restart_required} "
            f"colliders={collider_count} invalid={invalid_count} "
            f"replace={world.replace_required}"
        )

    return world, current_frame, collider_count, fc.restart_required


# ---------------------------------------------------------------------------
# 内部：运行解算器模块的对象作用域回调
# ---------------------------------------------------------------------------

def _run_scope_restart_handlers(world: PhysicsWorldCache, scope: PhysicsObjectScope) -> None:
    """运行解算器模块声明的重启阶段对象作用域回调。"""
    try:
        from .registry import run_scope_restart_handlers
    except Exception:
        return

    run_scope_restart_handlers(world, scope)


def _collect_scope_solver_specs(world: PhysicsWorldCache, scope: PhysicsObjectScope) -> None:
    """运行解算器模块声明的对象作用域收集器。"""
    try:
        from .registry import collect_scope_solver_specs
    except Exception:
        return

    collect_scope_solver_specs(world, scope)


# ---------------------------------------------------------------------------
# 物理世界 Commit
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
