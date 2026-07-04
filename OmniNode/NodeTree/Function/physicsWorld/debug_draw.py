"""
physicsWorld.debug_draw — OmniNode 物理世界可视化调试绘制

draw handler 读取 _DRAW_STORE，在 3D 视口中绘制本帧参与模拟的所有对象：
  - 简单碰撞体（球/胶囊）
  - 骨骼碰撞体
  - 刚体轮廓（按类型着色）
  - 刚体约束锚点

由 physicsWorldDebugDraw 节点写入 _DRAW_STORE，不进 OmniNode cache。
draw handler 在首次写入时自动注册，插件注销时清理。
"""

from __future__ import annotations

import math
import bpy
import gpu
import mathutils
from gpu_extras.batch import batch_for_shader

# ---------------------------------------------------------------------------
# 颜色常量
# ---------------------------------------------------------------------------
_COLOR_COLLIDER      = (0.20, 0.80, 1.00, 0.80)   # 简单碰撞：蓝白
_COLOR_BONE          = (0.60, 0.90, 0.30, 0.80)   # 骨骼碰撞：黄绿
_COLOR_RIGID_DYNAMIC = (0.20, 0.90, 0.20, 0.85)   # 动态刚体：绿
_COLOR_RIGID_STATIC  = (0.60, 0.60, 0.65, 0.70)   # 静态刚体：灰
_COLOR_RIGID_KINEMA  = (0.40, 0.60, 1.00, 0.85)   # 运动学刚体：蓝
_COLOR_CONSTRAINT    = (1.00, 0.75, 0.10, 0.90)   # 约束锚点：橙黄

_SEGMENTS = 24   # 调试绘制用较少段数，比配置预览更轻量

# 预计算单位圆（与 collisionPreview 同策略）
_UNIT_CIRCLE = [
    (math.cos(math.tau * i / _SEGMENTS), math.sin(math.tau * i / _SEGMENTS))
    for i in range(_SEGMENTS + 1)
]

# ---------------------------------------------------------------------------
# 全局绘制数据存储
# ---------------------------------------------------------------------------
# key: node_uid (str)
# value: {
#   "frame": int,
#   "colliders": list[dict],      ← 来自 world.collider_snapshot["colliders"]
#   "rigid_slots": list[dict],    ← 来自 rigid_body solver slots
#   "constraint_slots": list[dict],
#   "show_colliders": bool,
#   "show_rigid": bool,
#   "show_constraints": bool,
# }
_DRAW_STORE: dict[str, dict] = {}
_DRAW_HANDLE = None


# ---------------------------------------------------------------------------
# 几何生成辅助
# ---------------------------------------------------------------------------

def _line(lines, a, b):
    lines.append(tuple(a))
    lines.append(tuple(b))


def _circle(lines, center, axis_a, axis_b, radius):
    if radius <= 1e-7:
        return
    sa = axis_a * radius
    sb = axis_b * radius
    pts = [center + c * sa + s * sb for c, s in _UNIT_CIRCLE]
    for i in range(len(pts) - 1):
        _line(lines, pts[i], pts[i + 1])


def _sphere_lines(lines, center, radius):
    x = mathutils.Vector((1, 0, 0))
    y = mathutils.Vector((0, 1, 0))
    z = mathutils.Vector((0, 0, 1))
    _circle(lines, center, x, y, radius)
    _circle(lines, center, x, z, radius)
    _circle(lines, center, y, z, radius)


def _capsule_lines(lines, seg_a, seg_b, radius):
    if radius <= 1e-7:
        return
    axis = seg_b - seg_a
    length = axis.length
    if length < 1e-7:
        _sphere_lines(lines, seg_a, radius)
        return
    axis.normalize()
    # 找两个垂直轴
    ref = mathutils.Vector((1, 0, 0)) if abs(axis.dot(mathutils.Vector((0, 0, 1)))) > 0.9 else mathutils.Vector((0, 0, 1))
    perp_a = axis.cross(ref).normalized()
    perp_b = axis.cross(perp_a).normalized()
    _circle(lines, seg_a, perp_a, perp_b, radius)
    _circle(lines, seg_b, perp_a, perp_b, radius)
    for sign in (perp_a, -perp_a, perp_b, -perp_b):
        _line(lines, seg_a + sign * radius, seg_b + sign * radius)


def _axis_cross(lines, center, matrix_world, size=0.08):
    """在约束锚点处画一个小轴框。"""
    origin = matrix_world.translation.copy()
    for i, col in enumerate(((1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1))):
        ax = mathutils.Vector(matrix_world.col[i][:3]).normalized() * size
        _line(lines, origin, origin + ax)


# ---------------------------------------------------------------------------
# 构建 draw call 列表
# ---------------------------------------------------------------------------

def _build_draw_calls(data: dict) -> list[tuple]:
    """把 _DRAW_STORE 里的一条记录转成 [(batch, color, line_width), ...] 列表。"""
    draw_calls = []
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    # 简单碰撞 + 骨骼碰撞
    if data.get("show_colliders", True):
        collider_lines = []
        bone_lines = []
        for c in (data.get("colliders") or []):
            target = bone_lines if c.get("owner_type") == "BONE" else collider_lines
            if c.get("type") == "SPHERE":
                center = c.get("center")
                if center is not None:
                    _sphere_lines(target, mathutils.Vector(center), float(c.get("radius", 0.0)))
            elif c.get("type") == "CAPSULE":
                sa, sb = c.get("segment_a"), c.get("segment_b")
                if sa is not None and sb is not None:
                    _capsule_lines(target, mathutils.Vector(sa), mathutils.Vector(sb), float(c.get("radius", 0.0)))
        if collider_lines:
            draw_calls.append((batch_for_shader(shader, "LINES", {"pos": collider_lines}), _COLOR_COLLIDER, 1.5))
        if bone_lines:
            draw_calls.append((batch_for_shader(shader, "LINES", {"pos": bone_lines}), _COLOR_BONE, 1.5))

    # 刚体轮廓
    if data.get("show_rigid", True):
        dyn_lines, sta_lines, kin_lines = [], [], []
        for slot in (data.get("rigid_slots") or []):
            spec = slot.get("spec")
            if spec is None:
                continue
            obj = getattr(spec, "obj", None)
            if obj is None:
                continue
            body_type = str(getattr(spec, "body_type", "DYNAMIC"))
            target = dyn_lines if body_type == "DYNAMIC" else (sta_lines if body_type == "STATIC" else kin_lines)
            try:
                r = max(obj.dimensions) * 0.5
                _sphere_lines(target, obj.location.copy(), r * 0.6)
            except Exception:
                pass
        if dyn_lines:
            draw_calls.append((batch_for_shader(shader, "LINES", {"pos": dyn_lines}), _COLOR_RIGID_DYNAMIC, 1.5))
        if sta_lines:
            draw_calls.append((batch_for_shader(shader, "LINES", {"pos": sta_lines}), _COLOR_RIGID_STATIC, 1.0))
        if kin_lines:
            draw_calls.append((batch_for_shader(shader, "LINES", {"pos": kin_lines}), _COLOR_RIGID_KINEMA, 1.5))

    # 约束锚点
    if data.get("show_constraints", True):
        con_lines = []
        for slot in (data.get("constraint_slots") or []):
            spec = slot.get("spec")
            obj = getattr(spec, "empty_obj", None) if spec is not None else None
            if obj is None:
                continue
            try:
                _axis_cross(con_lines, obj.location, obj.matrix_world)
            except Exception:
                pass
        if con_lines:
            draw_calls.append((batch_for_shader(shader, "LINES", {"pos": con_lines}), _COLOR_CONSTRAINT, 2.0))

    return draw_calls


# ---------------------------------------------------------------------------
# Draw handler
# ---------------------------------------------------------------------------

def _draw_physics_debug():
    if not _DRAW_STORE:
        return

    context = bpy.context
    if context is None or context.area is None:
        return

    all_draw_calls = []
    for data in _DRAW_STORE.values():
        if data.get("enabled", True):
            all_draw_calls.extend(_build_draw_calls(data))

    if not all_draw_calls:
        return

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        for batch, color, line_width in all_draw_calls:
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            shader.bind()
            shader.uniform_float("color", color)
            gpu.state.line_width_set(line_width)
            batch.draw(shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


def _ensure_draw_handler():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is None:
        _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_physics_debug, (), "WINDOW", "POST_VIEW"
        )


def _remove_draw_handler():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None


# ---------------------------------------------------------------------------
# 节点写入接口
# ---------------------------------------------------------------------------

def update_draw_store(
    node_uid: str,
    world,
    enabled: bool,
    show_colliders: bool,
    show_rigid: bool,
    show_constraints: bool,
) -> None:
    """
    由 physicsWorldDebugDraw 节点每帧调用。
    把 world 里的数据写进 _DRAW_STORE，draw handler 下次视口重绘时读取。
    enabled=False 时清掉该节点的条目。
    """
    if not enabled:
        _DRAW_STORE.pop(node_uid, None)
        return

    _ensure_draw_handler()

    from .types import PhysicsWorldCache
    if not isinstance(world, PhysicsWorldCache):
        _DRAW_STORE.pop(node_uid, None)
        return

    fc = world.frame_context

    # 收集 rigid / constraint slot 数据（只传轻量引用，不深拷贝）
    rigid_slots = []
    constraint_slots = []
    for slot_id, slot in world.solver_slots.items():
        spec = slot.data.get("spec")
        if spec is None:
            continue
        if slot.kind == "rigid_body":
            rigid_slots.append({"spec": spec})
        elif slot.kind == "rigid_constraint":
            constraint_slots.append({"spec": spec})

    _DRAW_STORE[node_uid] = {
        "frame": fc.frame,
        "enabled": True,
        "show_colliders": show_colliders,
        "show_rigid": show_rigid,
        "show_constraints": show_constraints,
        "colliders": list(world.collider_snapshot.get("colliders") or []),
        "rigid_slots": rigid_slots,
        "constraint_slots": constraint_slots,
    }


def clear_draw_store(node_uid: str) -> None:
    """节点删除或禁用时清理。"""
    _DRAW_STORE.pop(node_uid, None)
