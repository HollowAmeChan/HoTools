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
    if stype in {"SPHERE", "CAPSULE", "BOX"}:
        return {
            "shape_type": stype,
            "shape_radius": max(float(getattr(spec, "shape_radius", 0.5)), 0.001),
            "shape_half_height": max(float(getattr(spec, "shape_half_height", 0.5)), 0.001),
            "shape_half_extents": tuple(getattr(spec, "shape_half_extents", (0.5, 0.5, 0.5))),
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
        if stype == "BOX":
            he = getattr(rb, "shape_half_extents", None)
            if he is not None:
                hx = max(float(he[0]), 0.001)
                hy = max(float(he[1]), 0.001)
                hz = max(float(he[2]), 0.001)
            else:
                hx = hy = hz = 0.5
            return {"shape_type": "BOX", "shape_half_extents": (hx, hy, hz)}

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
# 位置和旋转从 Blender 对象提取
# ---------------------------------------------------------------------------

def _transform_from_obj(obj) -> tuple[tuple, tuple]:
    """返回 (position, rotation_wxyz)。"""
    try:
        loc, rot, _scale = obj.matrix_world.decompose()
        return ((float(loc.x), float(loc.y), float(loc.z)),
                (float(rot.w), float(rot.x), float(rot.y), float(rot.z)))
    except Exception:
        return ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))


def _transform_from_empty(empty_obj) -> tuple[tuple, tuple]:
    """约束锚点 Empty 的 anchor frame。"""
    return _transform_from_obj(empty_obj)


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

        pos, rot = _transform_from_obj(spec.obj)
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
            collision_group=int(getattr(spec, "collision_group", 1)),
            collided_by_groups=int(getattr(spec, "collided_by_groups", 0xFFFF)),
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
        pos, rot = _transform_from_obj(spec.obj)
        self._jw.set_kinematic_transform(handle, pos, rot, dt)

    def get_body_transform(self, slot_id: str):
        """返回 (position_xyz, rotation_wxyz) 或 None。"""
        handle = self._body_handles.get(slot_id)
        if handle is None:
            return None
        return self._jw.get_body_transform(handle)

    # ---- Constraint 管理 -------------------------------------------------

    def sync_constraint(self, slot_id: str, spec: "ConstraintSpec") -> int:
        """注册或更新约束，返回 constraint handle。"""
        if slot_id in self._constraint_handles:
            self._jw.remove_constraint(self._constraint_handles.pop(slot_id))

        # WORLD_HANDLE：固定到世界（native 侧 0xFFFFFFFF）
        world_handle: int = _get_native_const("WORLD_HANDLE", 0xFFFFFFFF)

        def _get_handle(target_obj) -> int:
            """通过 slot_id 前缀 "rigid:{obj_ptr}:" 查找已注册的 body handle。"""
            if target_obj is None:
                return world_handle
            target_ptr = int(target_obj.as_pointer())
            for sid, h in self._body_handles.items():
                try:
                    if sid.startswith(f"rigid:{target_ptr}:"):
                        return h
                except Exception:
                    pass
            return world_handle

        a_handle = _get_handle(spec.target_a)
        b_handle = _get_handle(spec.target_b)

        pos, rot = _transform_from_empty(spec.empty_obj)

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
        把 Jolt 结果写回 Blender 对象变换。
        只处理 DYNAMIC body；KINEMATIC/STATIC 由动画驱动，不写回。
        返回成功写回的 slot_id 列表。

        注意：这是 Phase 5 的 legacy inline writeback 路径。
        未来统一写入节点（Physics Writeback）落地后，此方法将被替换。
        """
        import mathutils
        written = []
        # 收集本次写回了哪些 armature/object，最后统一 update_tag
        updated_objects = set()

        for slot_id, handle in self._body_handles.items():
            slot = solver_slots.get(slot_id)
            if slot is None:
                continue
            spec = slot.data.get("spec")
            if spec is None or spec.body_type != "DYNAMIC":
                continue
            obj = spec.obj
            if obj is None:
                continue

            result = self._jw.get_body_transform(handle)
            if result is None:
                slot.data["_writeback_error"] = "get_body_transform 返回 None"
                continue

            try:
                pos_arr, rot_arr = result
                obj.location = mathutils.Vector(pos_arr)

                q = mathutils.Quaternion(
                    (float(rot_arr[0]), float(rot_arr[1]),
                     float(rot_arr[2]), float(rot_arr[3]))
                )
                # 兼容不同旋转模式
                if obj.rotation_mode == "QUATERNION":
                    obj.rotation_quaternion = q
                elif obj.rotation_mode == "AXIS_ANGLE":
                    aa = q.to_axis_angle()
                    obj.rotation_axis_angle = (aa[1], aa[0].x, aa[0].y, aa[0].z)
                else:
                    obj.rotation_euler = q.to_euler(obj.rotation_mode)

                updated_objects.add(obj)
                written.append(slot_id)
                slot.data.pop("_writeback_error", None)

            except Exception as exc:
                slot.data["_writeback_error"] = str(exc)

        # 统一 update_tag，通知 depsgraph 刷新
        for obj in updated_objects:
            try:
                obj.update_tag()
            except Exception:
                pass

        return written

    # ---- Info ------------------------------------------------------------

    def debug_snapshot(self) -> dict:
        return {
            "backend": self.BACKEND,
            "body_count": self._jw.body_count,
            "constraint_count": self._jw.constraint_count,
            "last_step_ms": round(self.last_step_ms, 3),
        }

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
