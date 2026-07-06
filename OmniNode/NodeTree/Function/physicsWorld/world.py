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
    """从 Object.matrix_world 和 PhysicsTools box_size 解析有向盒半轴。"""
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


def _flatten_scope_objects(objects) -> list:
    result = []
    stack = list(objects) if isinstance(objects, (list, tuple)) else (
        [objects] if objects is not None else []
    )
    while stack:
        item = stack.pop(0)
        if isinstance(item, (list, tuple)):
            stack[0:0] = list(item)
        else:
            result.append(item)
    return result


def _clear_writeback_deltas_for_world(world: PhysicsWorldCache) -> None:
    """清除旧 world 已写过的物理 delta，避免 restart 后残留末帧姿态。"""
    try:
        from .writeback import clear_all_deltas
        clear_all_deltas(world)
    except Exception:
        pass


def _clear_scope_dynamic_rigid_deltas(scope: PhysicsObjectScope) -> None:
    """
    在 collider/spec 收集前清掉当前 scope 动态刚体 delta。

    Jolt 冷启动会从 obj.matrix_world 读取初始姿态；matrix_world 会包含
    delta_location / delta_rotation_euler，所以这一步必须早于 solver sync。
    """
    if not getattr(scope, "include_rigid_body", False):
        return

    updated = set()
    for obj in _flatten_scope_objects(getattr(scope, "objects", ())):
        rb = getattr(obj, "hotools_rigid_body", None)
        if rb is None or not bool(getattr(rb, "enabled", False)):
            continue
        if str(getattr(rb, "body_type", "DYNAMIC") or "DYNAMIC") != "DYNAMIC":
            continue
        try:
            obj.delta_location = (0.0, 0.0, 0.0)
            obj.delta_rotation_euler = (0.0, 0.0, 0.0)
            updated.add(obj)
        except Exception:
            pass

    for obj in updated:
        try:
            obj.update_tag()
        except Exception:
            pass
    if updated:
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass


def _flush_rigid_backend_handles(world: PhysicsWorldCache) -> None:
    adapter = world.backend_resources.get("rigid_solver")
    flush = getattr(adapter, "_flush_handles", None)
    if callable(flush):
        try:
            flush()
        except Exception:
            pass


def _round_float(value, digits: int = 8) -> float:
    try:
        return round(float(value), digits)
    except Exception:
        return 0.0


def _round_tuple(values, digits: int = 8) -> tuple[float, ...]:
    try:
        return tuple(_round_float(v, digits) for v in values)
    except Exception:
        return ()


def _rigid_body_sync_signature(spec) -> tuple:
    """
    返回会影响 Jolt body 创建参数的轻量签名。

    动态/运动学 body 的 world transform 不放进签名：动态 transform 来自
    物理写回 delta，运动学 transform 由 update_kinematic 每帧驱动。静态
    body 没有写回路径，位置变化需要重新同步。
    """
    body_type = str(getattr(spec, "body_type", "DYNAMIC") or "DYNAMIC")
    static_pose = ()
    if body_type == "STATIC":
        static_pose = (
            _round_tuple(getattr(spec, "world_position", (0.0, 0.0, 0.0))),
            _round_tuple(getattr(spec, "world_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        )

    return (
        body_type,
        _round_float(getattr(spec, "mass", 1.0)),
        _round_float(getattr(spec, "friction", 0.5)),
        _round_float(getattr(spec, "restitution", 0.0)),
        int(getattr(spec, "rigid_collision_group", 1) or 1),
        int(getattr(spec, "rigid_collides_with_groups", 0xFFFF) or 0),
        str(getattr(spec, "shape_type", "SPHERE") or "SPHERE"),
        _round_float(getattr(spec, "shape_radius", 0.5)),
        _round_float(getattr(spec, "shape_half_height", 0.5)),
        _round_tuple(getattr(spec, "shape_half_extents", (0.5, 0.5, 0.5))),
        _round_float(getattr(spec, "shape_plane_half_extent", 10.0)),
        _round_float(getattr(spec, "shape_top_radius", 0.5)),
        _round_float(getattr(spec, "shape_bottom_radius", 0.3)),
        _round_float(getattr(spec, "shape_convex_radius", 0.05)),
        _round_tuple(getattr(spec, "shape_offset", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "shape_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "linear_velocity", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "angular_velocity", (0.0, 0.0, 0.0))),
        _round_float(getattr(spec, "linear_damping", 0.05)),
        _round_float(getattr(spec, "angular_damping", 0.05)),
        _round_float(getattr(spec, "gravity_factor", 1.0)),
        bool(getattr(spec, "allow_sleeping", True)),
        str(getattr(spec, "motion_quality", "DISCRETE") or "DISCRETE"),
        _round_float(getattr(spec, "max_linear_velocity", 500.0)),
        _round_float(getattr(spec, "max_angular_velocity", 47.1239)),
        bool(getattr(spec, "is_sensor", False)),
        bool(getattr(spec, "collide_kinematic_vs_non_dynamic", False)),
        int(getattr(spec, "allowed_dofs", 0x3F) or 0),
        static_pose,
    )


def _kinematic_pose_signature(spec) -> tuple:
    if str(getattr(spec, "body_type", "DYNAMIC") or "DYNAMIC") != "KINEMATIC":
        return ()
    return (
        _round_tuple(getattr(spec, "world_position", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "world_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
    )


def _constraint_sync_signature(spec) -> tuple:
    return (
        str(getattr(spec, "constraint_type", "FIXED") or "FIXED"),
        int(getattr(spec, "target_a_ptr", 0) or 0),
        int(getattr(spec, "target_b_ptr", 0) or 0),
        bool(getattr(spec, "disable_collisions", True)),
        _round_tuple(getattr(spec, "anchor_position", (0.0, 0.0, 0.0))),
        _round_tuple(getattr(spec, "anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        int(getattr(spec, "constraint_priority", 0) or 0),
        int(getattr(spec, "solver_velocity_steps", 0) or 0),
        int(getattr(spec, "solver_position_steps", 0) or 0),
        _round_float(getattr(spec, "draw_constraint_size", 1.0)),
        bool(getattr(spec, "limit_enabled", False)),
        _round_float(getattr(spec, "angular_limit_min", -3.141592653589793)),
        _round_float(getattr(spec, "angular_limit_max", 3.141592653589793)),
        _round_float(getattr(spec, "linear_limit_min", -1.0)),
        _round_float(getattr(spec, "linear_limit_max", 1.0)),
        _round_float(getattr(spec, "limit_spring_frequency", 0.0)),
        _round_float(getattr(spec, "limit_spring_damping", 0.0)),
        _round_float(getattr(spec, "max_friction_torque", 0.0)),
        _round_float(getattr(spec, "max_friction_force", 0.0)),
        str(getattr(spec, "motor_state", "OFF") or "OFF"),
        _round_float(getattr(spec, "motor_frequency", 2.0)),
        _round_float(getattr(spec, "motor_damping", 1.0)),
        _round_float(getattr(spec, "motor_force_limit", 0.0)),
        _round_float(getattr(spec, "motor_torque_limit", 0.0)),
        _round_float(getattr(spec, "motor_target_angular_velocity", 0.0)),
        _round_float(getattr(spec, "motor_target_angle", 0.0)),
        _round_float(getattr(spec, "motor_target_velocity", 0.0)),
        _round_float(getattr(spec, "motor_target_position", 0.0)),
        _round_float(getattr(spec, "cone_half_angle", 0.0)),
    )


def _mark_all_rigid_slots_for_resync(world: PhysicsWorldCache) -> None:
    _flush_rigid_backend_handles(world)
    for slot in world.solver_slots.values():
        if slot.kind in {"rigid_body", "rigid_constraint"}:
            slot.data.pop("_jolt_generation", None)


def _prune_stale_rigid_slots(
    world: PhysicsWorldCache,
    active_body_ids: set[str],
    active_constraint_ids: set[str],
) -> int:
    """
    删除本帧 scope 中已经不存在的刚体/约束 slot。

    旧 slot 如果继续留在 world 里，rigid solver 会在 restart 后把它们重新
    sync 到 Jolt，看起来就像首帧没有重新收集世界信息。
    """
    stale_ids = []
    for slot_id, slot in list(world.solver_slots.items()):
        if slot.kind == "rigid_body" and slot_id not in active_body_ids:
            stale_ids.append(slot_id)
        elif slot.kind == "rigid_constraint" and slot_id not in active_constraint_ids:
            stale_ids.append(slot_id)

    if not stale_ids:
        return 0

    for slot_id in stale_ids:
        slot = world.solver_slots.pop(slot_id, None)
        if slot is not None:
            try:
                slot.dispose("rigid_scope_prune")
            except Exception:
                pass

    # 约束/body 拓扑变化后，直接 flush Jolt handles 并强制剩余 slot 重 sync。
    _mark_all_rigid_slots_for_resync(world)
    return len(stale_ids)


# ---------------------------------------------------------------------------
# 从 PhysicsColliderSource 构建碰撞条目
# ---------------------------------------------------------------------------

def _collider_from_source(source: PhysicsColliderSource) -> dict | None:
    """
    把单个 PhysicsColliderSource 转成碰撞 dict，与旧 build_collision_snapshot_from_scene 格式兼容。

    支持的 collision_type：
      - Object 级：SPHERE、CAPSULE、PLANE、BOX
      - Bone 级：SPHERE、CAPSULE
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
        radius = max(float(getattr(props, "radius", 0.0)), 0.0) * _matrix_scale_radius(matrix)
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
    MESH 类型 source 不产生碰撞条目（只作为 solver 的配置来源）。
    """
    colliders = []
    for source in sources:
        if source.owner_type == "MESH":
            continue  # Mesh collision 由 solver 内部处理
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
        _clear_scope_dynamic_rigid_deltas(object_scope)

    # 更新 FrameContext
    fc.scene_key = _scene_key(scene)
    fc.frame = current_frame
    fc.previous_frame = previous_frame
    fc.continuous = continuous
    fc.same_frame = same_frame
    fc.reset_requested = bool(reset)
    fc.restart_required = restart_required
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

    # 自动从 scope 收集刚体和约束 spec，写入 world slot
    # 与碰撞 snapshot 同级：都是"从 scope 对象读取 PhysicsTools 属性"，
    # 不是 solver 职责，不应要求用户额外接节点。
    _collect_rigid_specs(world, object_scope)

    if debug_output:
        print(
            f"[PhysicsWorldBegin] gen={world.generation} frame={current_frame} "
            f"prev={previous_frame} continuous={continuous} restart={fc.restart_required} "
            f"colliders={collider_count} invalid={invalid_count} "
            f"replace={world.replace_required}"
        )

    return world, current_frame, collider_count, fc.restart_required


# ---------------------------------------------------------------------------
# 内部：从 scope 自动收集刚体和约束 spec
# ---------------------------------------------------------------------------

def _collect_rigid_specs(world: PhysicsWorldCache, scope: PhysicsObjectScope) -> None:
    """
    遍历 scope.objects，把启用了 hotools_rigid_body / hotools_rigid_constraint
    的对象自动注册到 world solver slot。

    这和碰撞 snapshot 同级——都是"从 scope 读取 PhysicsTools 属性"，
    不需要用户额外接节点。
    """
    try:
        from .rigid.specs import build_rigid_body_spec, build_constraint_spec
        from .rigid.solver import _flatten
    except Exception:
        return  # rigid domain 未加载时静默跳过

    solver_id = "_world_begin_rigid_auto"
    world.acquire_write(solver_id)
    try:
        active_body_ids: set[str] = set()
        active_constraint_ids: set[str] = set()
        spec_sync_dirty = False

        for obj in _flatten(scope.objects):
            # 刚体
            if scope.include_rigid_body:
                spec = build_rigid_body_spec(obj)
                if spec is not None:
                    active_body_ids.add(spec.slot_id)
                    slot = world.ensure_solver_slot(spec.slot_id, "rigid_body")
                    if slot.world_generation != world.generation:
                        slot.data.clear()
                        slot.world_generation = world.generation

                    signature = _rigid_body_sync_signature(spec)
                    previous_signature = slot.data.get("_sync_signature")
                    if previous_signature is not None and previous_signature != signature:
                        spec_sync_dirty = True
                    slot.data["_sync_signature"] = signature

                    pose_signature = _kinematic_pose_signature(spec)
                    previous_pose_signature = slot.data.get("_kinematic_pose_signature")
                    if pose_signature:
                        if (
                            previous_pose_signature is not None
                            and previous_pose_signature != pose_signature
                        ):
                            slot.data["_jolt_kinematic_pose_dirty"] = True
                        slot.data["_kinematic_pose_signature"] = pose_signature
                    else:
                        slot.data.pop("_kinematic_pose_signature", None)
                        slot.data.pop("_jolt_kinematic_pose_dirty", None)

                    slot.data["spec"] = spec
                    slot.data["_debug_snapshot"] = lambda s=spec: s.debug_dict()

            # 约束（只对 EMPTY 对象，受 include_rigid_constraint 控制）
            if scope.include_rigid_constraint:
                try:
                    if obj.type == "EMPTY":
                        cspec = build_constraint_spec(obj)
                        if cspec is not None:
                            active_constraint_ids.add(cspec.slot_id)
                            cslot = world.ensure_solver_slot(cspec.slot_id, "rigid_constraint")
                            if cslot.world_generation != world.generation:
                                cslot.data.clear()
                                cslot.world_generation = world.generation

                            signature = _constraint_sync_signature(cspec)
                            previous_signature = cslot.data.get("_sync_signature")
                            if previous_signature is not None and previous_signature != signature:
                                spec_sync_dirty = True
                            cslot.data["_sync_signature"] = signature

                            cslot.data["spec"] = cspec
                            cslot.data["_debug_snapshot"] = lambda s=cspec: s.debug_dict()
                except Exception:
                    pass

        pruned = _prune_stale_rigid_slots(world, active_body_ids, active_constraint_ids)
        if spec_sync_dirty:
            _mark_all_rigid_slots_for_resync(world)
        if pruned:
            world.replace_required = True
        elif spec_sync_dirty:
            world.replace_required = True
    finally:
        world.release_write(solver_id)


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
