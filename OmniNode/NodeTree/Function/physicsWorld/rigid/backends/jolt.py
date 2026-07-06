"""
physicsWorld.rigid.backends.jolt — Jolt Physics Python 适配器

职责：
- 包装 hotools_jolt.JoltWorld（nanobind 绑定）。
- 从 RigidBodySpec / ConstraintSpec 构造 Jolt 所需的参数。
- 管理 body_handle / constraint_handle 到 slot_id 的映射。
- 提供 dispose 协议，确保 Jolt native 资源先于 Python 对象释放。

设计约定（对应 HoTools Phase 5 文档）：
- JoltAdapter 实例存放在 world.backend_resources["rigid_solver"]。
- body_handle / constraint_handle 只存在于 rigid solver slot，不写回 Blender 对象。
- 公开类型名使用 HoTools 语义，Jolt 内部 API 完全在此文件内消化。
"""

from __future__ import annotations

import importlib
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..specs import RigidBodySpec, ConstraintSpec


# ---------------------------------------------------------------------------
# 懒加载 native 模块（编译产物不存在时静默失败）
# ---------------------------------------------------------------------------

def _load_native():
    try:
        return importlib.import_module("hotools_jolt")
    except ImportError:
        return None


def _get_native_const(attr: str, default):
    """安全读取 hotools_jolt 模块常量，模块不可用时返回 default。"""
    mod = _load_native()
    return getattr(mod, attr, default) if mod is not None else default


# ---------------------------------------------------------------------------
# 形状参数从 RigidBodySpec 提取
# ---------------------------------------------------------------------------

def _shape_params_from_spec(spec: "RigidBodySpec") -> dict:
    """
    从 RigidBodySpec 提取碰撞形状参数。
    新版 spec 已经持有持久化 shape 字段；旧 spec 才回退到对象属性/包围盒。
    """
    stype = getattr(spec, "shape_type", None)
    if stype in {"SPHERE", "CAPSULE", "CYLINDER", "TAPERED_CAPSULE", "TAPERED_CYLINDER", "PLANE", "BOX"}:
        return {
            "shape_type": stype,
            "shape_radius": max(float(getattr(spec, "shape_radius", 0.5)), 0.001),
            "shape_half_height": max(float(getattr(spec, "shape_half_height", 0.5)), 0.001),
            "shape_half_extents": tuple(getattr(spec, "shape_half_extents", (0.5, 0.5, 0.5))),
            "shape_plane_half_extent": max(float(getattr(spec, "shape_plane_half_extent", 10.0)), 1.0),
            "shape_top_radius": max(float(getattr(spec, "shape_top_radius", 0.5)), 0.001),
            "shape_bottom_radius": max(float(getattr(spec, "shape_bottom_radius", 0.3)), 0.001),
            "shape_convex_radius": max(float(getattr(spec, "shape_convex_radius", 0.05)), 0.0),
            "shape_offset": tuple(getattr(spec, "shape_offset", (0.0, 0.0, 0.0))),
            "shape_rotation_wxyz": tuple(getattr(spec, "shape_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
        }

    obj = spec.obj
    if obj is None:
        return {"shape_type": "SPHERE", "shape_radius": 0.1}

    rb = getattr(obj, "hotools_rigid_body", None)
    if rb is not None:
        stype = str(getattr(rb, "shape_type", "SPHERE"))
        if stype == "SPHERE":
            return {"shape_type": "SPHERE",
                    "shape_radius": max(float(getattr(rb, "shape_radius", 0.5)), 0.001)}
        if stype == "CAPSULE":
            return {"shape_type": "CAPSULE",
                    "shape_radius":      max(float(getattr(rb, "shape_radius",      0.3)), 0.001),
                    "shape_half_height": max(float(getattr(rb, "shape_half_height", 0.5)), 0.001)}
        if stype == "CYLINDER":
            return {
                "shape_type": "CYLINDER",
                "shape_radius": max(float(getattr(rb, "shape_radius", 0.5)), 0.001),
                "shape_half_height": max(float(getattr(rb, "shape_half_height", 0.5)), 0.001),
                "shape_convex_radius": max(float(getattr(rb, "shape_convex_radius", 0.05)), 0.0),
            }
        if stype in {"TAPERED_CAPSULE", "TAPERED_CYLINDER"}:
            return {
                "shape_type": stype,
                "shape_top_radius": max(float(getattr(rb, "shape_top_radius", 0.5)), 0.001),
                "shape_bottom_radius": max(float(getattr(rb, "shape_bottom_radius", 0.3)), 0.001),
                "shape_half_height": max(float(getattr(rb, "shape_half_height", 0.5)), 0.001),
                "shape_convex_radius": max(float(getattr(rb, "shape_convex_radius", 0.05)), 0.0),
            }
        if stype == "BOX":
            he = getattr(rb, "shape_half_extents", None)
            if he is not None:
                hx = max(float(he[0]), 0.001)
                hy = max(float(he[1]), 0.001)
                hz = max(float(he[2]), 0.001)
            else:
                hx = hy = hz = 0.5
            return {"shape_type": "BOX", "shape_half_extents": (hx, hy, hz)}
        if stype == "PLANE":
            he = getattr(rb, "shape_half_extents", None)
            if he is not None:
                hx = max(float(he[0]), 0.001)
                hy = max(float(he[1]), 0.001)
                hz = max(float(he[2]), 0.001)
            else:
                hx = hy = 5.0
                hz = 0.001
            return {
                "shape_type": "PLANE",
                "shape_half_extents": (hx, hy, hz),
                "shape_plane_half_extent": max(float(getattr(rb, "shape_plane_half_extent", max(hx, hy))), 1.0),
            }

    # Fallback：对象包围盒
    try:
        dims = obj.dimensions
        hx = max(float(dims.x) * 0.5, 0.01)
        hy = max(float(dims.y) * 0.5, 0.01)
        hz = max(float(dims.z) * 0.5, 0.01)
        return {"shape_type": "BOX", "shape_half_extents": (hx, hy, hz)}
    except Exception:
        return {"shape_type": "SPHERE", "shape_radius": 0.1}


# ---------------------------------------------------------------------------
# 位置和旋转从 spec 快照提取
# ---------------------------------------------------------------------------

def _transform_from_obj(obj) -> tuple[tuple, tuple]:
    """返回 (position, rotation_wxyz)。仅用于旧数据或 KINEMATIC 兜底。"""
    try:
        loc, rot, _scale = obj.matrix_world.decompose()
        return ((float(loc.x), float(loc.y), float(loc.z)),
                (float(rot.w), float(rot.x), float(rot.y), float(rot.z)))
    except Exception:
        return ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))


def _transform_from_empty(empty_obj) -> tuple[tuple, tuple]:
    """约束锚点 Empty 的 anchor frame。"""
    return _transform_from_obj(empty_obj)


def _transform_from_body_spec(spec: "RigidBodySpec") -> tuple[tuple, tuple]:
    pos = getattr(spec, "world_position", None)
    rot = getattr(spec, "world_rotation_wxyz", None)
    if pos is not None and rot is not None:
        try:
            return (
                (float(pos[0]), float(pos[1]), float(pos[2])),
                (float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3])),
            )
        except Exception:
            pass
    return _transform_from_obj(getattr(spec, "obj", None))


def _transform_from_constraint_spec(spec: "ConstraintSpec") -> tuple[tuple, tuple]:
    pos = getattr(spec, "anchor_position", None)
    rot = getattr(spec, "anchor_rotation_wxyz", None)
    if pos is not None and rot is not None:
        try:
            return (
                (float(pos[0]), float(pos[1]), float(pos[2])),
                (float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3])),
            )
        except Exception:
            pass
    return _transform_from_empty(getattr(spec, "empty_obj", None))


# ---------------------------------------------------------------------------
# JoltAdapter
# ---------------------------------------------------------------------------

class JoltAdapter:
    """
    封装 hotools_jolt.JoltWorld，提供 HoTools 语义的 Python 接口。

    生命周期：
    - 由 ensure_jolt_adapter(world) 创建，挂在 world.backend_resources。
    - dispose() 在 world.omni_cache_dispose() 链中被调用。
    """

    BACKEND = "jolt"

    def __init__(self, max_bodies: int = 1024):
        native = _load_native()
        if native is None:
            raise RuntimeError(
                "hotools_jolt 模块未找到。请先编译 native binding（build.bat）。"
            )
        self._jw = native.JoltWorld(
            max_bodies=max_bodies,
            max_body_pairs=max_bodies * 4,
            max_contact_constraints=max_bodies * 2,
        )
        self._body_handles: dict[str, int] = {}
        self._constraint_handles: dict[str, int] = {}
        self.last_step_ms: float = 0.0
        self._valid = True
        self._last_generation: int = -1   # generation 变化时 flush handles

    def _flush_handles(self) -> None:
        """
        world generation 变化（restart/scope 改变）时清空所有 handles。
        直接调用 JoltWorld.clear()，它内部已保证顺序：先约束再 body。
        下一帧 sync 时会重新注册。
        """
        try:
            self._jw.clear()
        except Exception:
            pass
        self._constraint_handles.clear()
        self._body_handles.clear()

    # ---- Body 管理 --------------------------------------------------------

    def sync_body(self, slot_id: str, spec: "RigidBodySpec") -> int:
        """
        注册或更新刚体。generation 变化时先 remove 再 add。
        返回 body handle。
        """
        # 移除旧 handle（如果存在）
        if slot_id in self._body_handles:
            self._jw.remove_body(self._body_handles.pop(slot_id))

        pos, rot = _transform_from_body_spec(spec)
        shape = _shape_params_from_spec(spec)

        kwargs = dict(
            body_type=spec.body_type,
            mass=float(spec.mass),
            friction=float(spec.friction),
            restitution=float(spec.restitution),
            position=pos,
            rotation_wxyz=rot,
            shape_type=shape["shape_type"],
            shape_radius=float(shape.get("shape_radius", 0.5)),
            shape_half_height=float(shape.get("shape_half_height", 0.5)),
            shape_half_extents=tuple(shape.get("shape_half_extents",
                                               (0.5, 0.5, 0.5))),
            shape_plane_half_extent=float(shape.get("shape_plane_half_extent", 10.0)),
            shape_top_radius=float(shape.get("shape_top_radius", 0.5)),
            shape_bottom_radius=float(shape.get("shape_bottom_radius", 0.3)),
            shape_convex_radius=float(shape.get("shape_convex_radius", 0.05)),
            collision_group=int(getattr(spec, "rigid_collision_group", 1)),
            collided_by_groups=int(getattr(spec, "rigid_collides_with_groups", 0xFFFF)),
            shape_offset=tuple(shape.get("shape_offset", (0.0, 0.0, 0.0))),
            shape_rotation_wxyz=tuple(shape.get("shape_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))),
            linear_velocity=tuple(getattr(spec, "linear_velocity", (0.0, 0.0, 0.0))),
            angular_velocity=tuple(getattr(spec, "angular_velocity", (0.0, 0.0, 0.0))),
            linear_damping=float(getattr(spec, "linear_damping", 0.05)),
            angular_damping=float(getattr(spec, "angular_damping", 0.05)),
            gravity_factor=float(getattr(spec, "gravity_factor", 1.0)),
            allow_sleeping=bool(getattr(spec, "allow_sleeping", True)),
            motion_quality=str(getattr(spec, "motion_quality", "DISCRETE")),
            max_linear_velocity=float(getattr(spec, "max_linear_velocity", 500.0)),
            max_angular_velocity=float(getattr(spec, "max_angular_velocity", 47.1239)),
            is_sensor=bool(getattr(spec, "is_sensor", False)),
            allowed_dofs=int(getattr(spec, "allowed_dofs", 0x3F)),
            collide_kinematic_vs_non_dynamic=bool(getattr(spec, "collide_kinematic_vs_non_dynamic", False)),
        )
        handle = self._jw.add_body(**kwargs)
        self._body_handles[slot_id] = handle
        return handle

    def remove_body(self, slot_id: str) -> None:
        handle = self._body_handles.pop(slot_id, None)
        if handle is not None:
            self._jw.remove_body(handle)

    def update_kinematic(self, slot_id: str, spec: "RigidBodySpec",
                         dt: float) -> None:
        """每帧驱动运动学刚体跟随 Blender 动画。"""
        handle = self._body_handles.get(slot_id)
        if handle is None:
            return
        if spec.body_type != "KINEMATIC":
            return
        pos, rot = _transform_from_body_spec(spec)
        self._jw.set_kinematic_transform(handle, pos, rot, dt)

    def get_body_transform(self, slot_id: str):
        """返回 (position_xyz, rotation_wxyz) 或 None。"""
        handle = self._body_handles.get(slot_id)
        if handle is None:
            return None
        return self._jw.get_body_transform(handle)

    def get_body_state(self, slot_id: str) -> dict | None:
        """返回求解后的 transform、速度和激活状态，或 None。"""
        handle = self._body_handles.get(slot_id)
        if handle is None:
            return None

        if hasattr(self._jw, "get_body_state"):
            pos, rot, lin, ang, active, sleeping = self._jw.get_body_state(handle)
        else:
            pos, rot = self._jw.get_body_transform(handle)
            lin = (0.0, 0.0, 0.0)
            ang = (0.0, 0.0, 0.0)
            active = False
            sleeping = False

        return {
            "position": tuple(pos),
            "rotation_wxyz": tuple(rot),
            "linear_velocity": tuple(lin),
            "angular_velocity": tuple(ang),
            "active": bool(active),
            "sleeping": bool(sleeping),
        }

    # ---- Constraint 管理 -------------------------------------------------

    def sync_constraint(self, slot_id: str, spec: "ConstraintSpec") -> int:
        """注册或更新约束，返回 constraint handle。"""
        if slot_id in self._constraint_handles:
            self._jw.remove_constraint(self._constraint_handles.pop(slot_id))

        # WORLD_HANDLE：固定到世界（native 侧 0xFFFFFFFF）
        world_handle: int = _get_native_const("WORLD_HANDLE", 0xFFFFFFFF)

        def _get_handle(target_ptr: int) -> int:
            """通过 slot_id 前缀 "rigid:{obj_ptr}:" 查找已注册的 body handle。"""
            if not target_ptr:
                return world_handle
            for sid, h in self._body_handles.items():
                try:
                    if sid.startswith(f"rigid:{target_ptr}:"):
                        return h
                except Exception:
                    pass
            return world_handle

        a_handle = _get_handle(int(getattr(spec, "target_a_ptr", 0) or 0))
        b_handle = _get_handle(int(getattr(spec, "target_b_ptr", 0) or 0))

        pos, rot = _transform_from_constraint_spec(spec)

        kwargs = dict(
            constraint_type=spec.constraint_type,
            body_a_handle=a_handle,
            body_b_handle=b_handle,
            anchor_pos=pos,
            anchor_rot_wxyz=rot,
            constraint_priority=int(getattr(spec, "constraint_priority", 0)),
            solver_velocity_steps=int(getattr(spec, "solver_velocity_steps", 0)),
            solver_position_steps=int(getattr(spec, "solver_position_steps", 0)),
            draw_constraint_size=float(getattr(spec, "draw_constraint_size", 1.0)),
            limit_enabled=bool(getattr(spec, "limit_enabled", False)),
            angular_limit_min=float(getattr(spec, "angular_limit_min", -3.141592653589793)),
            angular_limit_max=float(getattr(spec, "angular_limit_max", 3.141592653589793)),
            linear_limit_min=float(getattr(spec, "linear_limit_min", -1.0)),
            linear_limit_max=float(getattr(spec, "linear_limit_max", 1.0)),
            limit_spring_frequency=float(getattr(spec, "limit_spring_frequency", 0.0)),
            limit_spring_damping=float(getattr(spec, "limit_spring_damping", 0.0)),
            max_friction_torque=float(getattr(spec, "max_friction_torque", 0.0)),
            max_friction_force=float(getattr(spec, "max_friction_force", 0.0)),
            motor_state=str(getattr(spec, "motor_state", "OFF")),
            motor_frequency=float(getattr(spec, "motor_frequency", 2.0)),
            motor_damping=float(getattr(spec, "motor_damping", 1.0)),
            motor_force_limit=float(getattr(spec, "motor_force_limit", 0.0)),
            motor_torque_limit=float(getattr(spec, "motor_torque_limit", 0.0)),
            motor_target_angular_velocity=float(getattr(spec, "motor_target_angular_velocity", 0.0)),
            motor_target_angle=float(getattr(spec, "motor_target_angle", 0.0)),
            motor_target_velocity=float(getattr(spec, "motor_target_velocity", 0.0)),
            motor_target_position=float(getattr(spec, "motor_target_position", 0.0)),
            cone_half_angle=float(getattr(spec, "cone_half_angle", 0.0)),
            disable_collisions=bool(getattr(spec, "disable_collisions", True)),
        )
        handle = self._jw.add_constraint(**kwargs)
        self._constraint_handles[slot_id] = handle
        return handle

    def remove_constraint(self, slot_id: str) -> None:
        handle = self._constraint_handles.pop(slot_id, None)
        if handle is not None:
            self._jw.remove_constraint(handle)

    # ---- Simulation step -------------------------------------------------

    def step(self, dt: float, substeps: int = 1) -> float:
        """执行模拟步，返回耗时（ms）。"""
        self.last_step_ms = self._jw.step(dt, substeps)
        return self.last_step_ms

    # ---- Writeback -------------------------------------------------------

    def writeback_transforms(self, solver_slots: dict) -> list[str]:
        """
        Deprecated no-op.

        写回统一由 physicsWorld.writeback 执行，基于 Object.delta_*。
        保留方法名只为旧调用兼容，避免任何路径重新直接写 Object.location。
        """
        return []

    # ---- Info ------------------------------------------------------------

    def debug_snapshot(self) -> dict:
        return {
            "backend": self.BACKEND,
            "body_count": self._jw.body_count,
            "constraint_count": self._jw.constraint_count,
            "last_step_ms": round(self.last_step_ms, 3),
        }

    @property
    def body_count(self) -> int:
        try:
            return int(self._jw.body_count)
        except Exception:
            return 0

    @property
    def constraint_count(self) -> int:
        try:
            return int(self._jw.constraint_count)
        except Exception:
            return 0

    # ---- Dispose ---------------------------------------------------------

    def dispose(self, reason: str = "dispose") -> None:
        """
        释放所有 Jolt 资源。
        JoltWorld.clear() 内部已保证顺序：先删约束，再删 body，与 C++ 析构顺序一致。
        不能抛出异常（dispose 链约定）。幂等（多次调用安全）。
        """
        if not self._valid:
            return
        self._valid = False   # 先标记，防止 dispose 途中异常后重入
        try:
            self._jw.clear()  # 对应 C++ clear()：先约束后 body，顺序正确
        except Exception:
            pass
        self._constraint_handles.clear()
        self._body_handles.clear()
        self._jw = None       # 允许 GC 回收 JoltWorld Python 对象

    def omni_cache_dispose(self, reason: str) -> None:
        """兼容 omni_cache_dispose 协议，供 backend_resources 字典调用。"""
        self.dispose(reason)


# ---------------------------------------------------------------------------
# 辅助：获取或创建 adapter
# ---------------------------------------------------------------------------

def ensure_jolt_adapter(world) -> "JoltAdapter | None":
    """
    从 world.backend_resources["rigid_solver"] 获取 JoltAdapter。
    若不存在则尝试新建。
    若存在但 world generation 变化，清空 adapter 内所有 handles（不重建 JoltWorld）。
    native 不可用时返回 None。
    """
    existing = world.backend_resources.get("rigid_solver")
    if isinstance(existing, JoltAdapter) and existing._valid:
        # generation 变化：清空 handles，下一帧的 sync 会重新注册
        fc = world.frame_context if world.frame_context else None
        if fc is not None and existing._last_generation != fc.generation:
            existing._flush_handles()
            existing._last_generation = fc.generation
        return existing

    # 已有其他 backend 就不覆盖
    if existing is not None and not isinstance(existing, JoltAdapter):
        return None

    try:
        adapter = JoltAdapter()
        fc = world.frame_context if world.frame_context else None
        adapter._last_generation = fc.generation if fc else 0
        world.backend_resources["rigid_solver"] = adapter
        return adapter
    except Exception:
        import traceback
        traceback.print_exc()
        return None
