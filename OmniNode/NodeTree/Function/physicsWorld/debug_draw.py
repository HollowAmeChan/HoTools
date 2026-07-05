"""
physicsWorld.debug_draw — OmniNode 物理世界可视化调试绘制

draw handler 读取 _DRAW_STORE，在 3D 视口中绘制本帧参与模拟的所有对象：
  - 简单碰撞体（球/胶囊/平面/盒子）
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
_COLOR_BUG           = (1.00, 0.10, 0.10, 0.95)   # bug 状态：红

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
_DRAW_HANDLE_2D = None


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


def _plane_lines(lines, center, axis_x, axis_y, normal):
    corners = [
        center - axis_x - axis_y,
        center + axis_x - axis_y,
        center + axis_x + axis_y,
        center - axis_x + axis_y,
    ]
    for index, corner in enumerate(corners):
        _line(lines, corner, corners[(index + 1) % len(corners)])
    ray = normal.normalized() * max(axis_x.length, axis_y.length, 0.5)
    for corner in corners:
        _line(lines, corner, corner - ray)


def _box_lines(lines, center, axis_x, axis_y, axis_z):
    corners = [
        center + sx * axis_x + sy * axis_y + sz * axis_z
        for sx, sy, sz in (
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        )
    ]
    for start, end in (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ):
        _line(lines, corners[start], corners[end])




# ---------------------------------------------------------------------------
# 2D 屏幕空间约束绘制辅助
# ---------------------------------------------------------------------------

def _l2(lines, a, b):
    """往 2D lines 列表加一条线段。"""
    lines.append(tuple(a))
    lines.append(tuple(b))


def _constraint_indicator_2d(lines, sx, sy, constraint_type: str, r: int = 14, direction=None):
    """
    在屏幕坐标 (sx, sy) 处画固定像素大小的约束类型标识。
    direction=(dx,dy): 单位向量，HINGE 沿此方向展开两臂；
                       None 时默认朝上 (0, 1)。
    """
    if constraint_type == "FIXED":
        corners = [(sx - r, sy - r), (sx + r, sy - r),
                   (sx + r, sy + r), (sx - r, sy + r)]
        for i in range(4):
            _l2(lines, corners[i], corners[(i + 1) % 4])

    elif constraint_type == "HINGE":
        dx, dy = direction if direction is not None else (0.0, 1.0)
        px, py = -dy, dx           # 垂直于轴的方向

        # 中轴线（铰链旋转轴）
        _l2(lines, (sx - dx * r, sy - dy * r), (sx + dx * r, sy + dy * r))

        # 半圆弧：从轴一端绕到另一端，朝 +perpendicular 方向凸出
        steps = 12
        prev = None
        for i in range(steps + 1):
            a = math.pi * i / steps   # 0 → π
            pt = (sx + r * (dx * math.cos(a) + px * math.sin(a)),
                  sy + r * (dy * math.cos(a) + py * math.sin(a)))
            if prev:
                _l2(lines, prev, pt)
            prev = pt

    elif constraint_type == "SLIDER":
        head = r * 0.4
        _l2(lines, (sx, sy - r), (sx, sy + r))
        # 箭头朝内（从两端指向中心）
        for tip_y, inward in ((sy - r, head), (sy + r, -head)):
            _l2(lines, (sx, tip_y), (sx - head * 0.5, tip_y + inward))
            _l2(lines, (sx, tip_y), (sx + head * 0.5, tip_y + inward))

    elif constraint_type == "CONE":
        apex = (sx, sy - r)
        bl = (sx - r * 0.65, sy + r * 0.6)
        br = (sx + r * 0.65, sy + r * 0.6)
        _l2(lines, apex, bl)
        _l2(lines, apex, br)
        _l2(lines, bl, br)

    elif constraint_type == "POINT":
        steps = 12
        pts = [(sx + r * 0.65 * math.cos(math.tau * i / steps),
                sy + r * 0.65 * math.sin(math.tau * i / steps))
               for i in range(steps + 1)]
        for i in range(len(pts) - 1):
            _l2(lines, pts[i], pts[i + 1])

    else:
        _l2(lines, (sx - r, sy), (sx + r, sy))
        _l2(lines, (sx, sy - r), (sx, sy + r))


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
            elif c.get("type") == "PLANE":
                center = c.get("center")
                normal = c.get("normal")
                if center is not None and normal is not None:
                    n = mathutils.Vector(normal)
                    axis_x_value = c.get("plane_axis_x")
                    axis_y_value = c.get("plane_axis_y")
                    axis_x = mathutils.Vector(axis_x_value if axis_x_value is not None else (0.5, 0.0, 0.0))
                    axis_y = mathutils.Vector(axis_y_value if axis_y_value is not None else (0.0, 0.5, 0.0))
                    if n.length > 1e-7 and axis_x.length > 1e-7 and axis_y.length > 1e-7:
                        _plane_lines(target, mathutils.Vector(center), axis_x, axis_y, n)
            elif c.get("type") == "BOX":
                center = c.get("center")
                ax, ay, az = c.get("box_axis_x"), c.get("box_axis_y"), c.get("box_axis_z")
                if center is not None and ax is not None and ay is not None and az is not None:
                    _box_lines(
                        target,
                        mathutils.Vector(center),
                        mathutils.Vector(ax),
                        mathutils.Vector(ay),
                        mathutils.Vector(az),
                    )
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

    # 约束类型标识和连线已移入 POST_PIXEL handler（屏幕空间，大小固定不随距离缩小）

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


def _draw_physics_debug_2d():
    """
    POST_PIXEL handler：在屏幕空间绘制所有约束相关内容（大小固定）：
      - 约束类型标识（正方形/两臂弧/箭头/三角形/圆）
      - 锚点到目标对象的连线
      - bug 红叉（缺目标或连到自身）
    """
    if not _DRAW_STORE:
        return

    context = bpy.context
    if context is None or context.area is None or context.area.type != "VIEW_3D":
        return
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return

    from bpy_extras.view3d_utils import location_3d_to_region_2d

    con_lines = []    # 约束标识 + 连线（橙黄）
    bug_lines = []    # bug 叉（红）

    for data in _DRAW_STORE.values():
        if not data.get("enabled"):
            continue
        show_constraints = data.get("show_constraints", True)
        show_bugs = data.get("show_bugs", True)

        # --- 约束类型标识 + 连线 ---
        if show_constraints:
            for slot in (data.get("constraint_slots") or []):
                spec = slot.get("spec")
                empty_obj = getattr(spec, "empty_obj", None) if spec is not None else None
                if empty_obj is None:
                    continue
                try:
                    sc = location_3d_to_region_2d(region, rv3d, empty_obj.location)
                    if sc is None:
                        continue
                    sx, sy = sc
                    ctype = str(getattr(spec, "constraint_type", "FIXED"))

                    # HINGE：投影 Empty 本地 Z 轴到屏幕，作为铰链方向
                    hinge_dir = None
                    if ctype == "HINGE":
                        try:
                            z_w = mathutils.Vector(
                                empty_obj.matrix_world.col[2][:3]
                            ).normalized()
                            tip_sc = location_3d_to_region_2d(
                                region, rv3d, empty_obj.location + z_w * 0.2
                            )
                            if tip_sc:
                                ddx = tip_sc[0] - sx
                                ddy = tip_sc[1] - sy
                                norm = (ddx * ddx + ddy * ddy) ** 0.5
                                if norm > 0.5:   # 至少半像素，避免除零
                                    hinge_dir = (ddx / norm, ddy / norm)
                        except Exception:
                            pass

                    _constraint_indicator_2d(con_lines, sx, sy, ctype,
                                             direction=hinge_dir)

                    # 连线到 target_a / target_b
                    for target in (getattr(spec, "target_a", None),
                                   getattr(spec, "target_b", None)):
                        if target is None:
                            continue
                        try:
                            is_self = target.as_pointer() == empty_obj.as_pointer()
                        except Exception:
                            is_self = False
                        if is_self:
                            continue
                        try:
                            t_sc = location_3d_to_region_2d(region, rv3d, target.location)
                            if t_sc:
                                _l2(con_lines, (sx, sy), tuple(t_sc))
                        except Exception:
                            pass
                except Exception:
                    pass

        # --- bug 叉 ---
        if show_bugs and show_constraints:
            cross = 10
            for pos in (data.get("bug_positions") or []):
                sc = location_3d_to_region_2d(region, rv3d, mathutils.Vector(pos))
                if sc is None:
                    continue
                x, y = sc
                bug_lines += [
                    (x - cross, y - cross), (x + cross, y + cross),
                    (x + cross, y - cross), (x - cross, y + cross),
                ]

    if not con_lines and not bug_lines:
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    try:
        if con_lines:
            batch = batch_for_shader(shader, "LINES", {"pos": con_lines})
            shader.bind()
            shader.uniform_float("color", _COLOR_CONSTRAINT)
            gpu.state.line_width_set(2.5)
            batch.draw(shader)
        if bug_lines:
            batch = batch_for_shader(shader, "LINES", {"pos": bug_lines})
            shader.bind()
            shader.uniform_float("color", _COLOR_BUG)
            gpu.state.line_width_set(3.0)
            batch.draw(shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")


def _ensure_draw_handler():
    global _DRAW_HANDLE, _DRAW_HANDLE_2D
    if _DRAW_HANDLE is None:
        _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_physics_debug, (), "WINDOW", "POST_VIEW"
        )
    if _DRAW_HANDLE_2D is None:
        _DRAW_HANDLE_2D = bpy.types.SpaceView3D.draw_handler_add(
            _draw_physics_debug_2d, (), "WINDOW", "POST_PIXEL"
        )


def _remove_draw_handler():
    global _DRAW_HANDLE, _DRAW_HANDLE_2D
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None
    if _DRAW_HANDLE_2D is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE_2D, "WINDOW")
        _DRAW_HANDLE_2D = None


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
    show_bugs: bool = True,
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

    # 预计算 bug 锚点位置（供 POST_PIXEL 2D handler 投影画叉）
    bug_positions = []
    if show_bugs and show_constraints:
        for slot in constraint_slots:
            spec = slot.get("spec")
            empty_obj = getattr(spec, "empty_obj", None) if spec is not None else None
            if empty_obj is None:
                continue
            try:
                target_a = getattr(spec, "target_a", None)
                target_b = getattr(spec, "target_b", None)
                is_bug = False
                for t in (target_a, target_b):
                    if t is None:
                        is_bug = True
                    else:
                        try:
                            if t.as_pointer() == empty_obj.as_pointer():
                                is_bug = True
                        except Exception:
                            is_bug = True
                if is_bug:
                    bug_positions.append(tuple(empty_obj.location))
            except Exception:
                pass

    _DRAW_STORE[node_uid] = {
        "frame": fc.frame,
        "enabled": True,
        "show_colliders": show_colliders,
        "show_rigid": show_rigid,
        "show_constraints": show_constraints,
        "show_bugs": show_bugs,
        "bug_positions": bug_positions,
        "colliders": list(world.collider_snapshot.get("colliders") or []),
        "rigid_slots": rigid_slots,
        "constraint_slots": constraint_slots,
    }


def clear_draw_store(node_uid: str) -> None:
    """节点删除或禁用时清理。"""
    _DRAW_STORE.pop(node_uid, None)
