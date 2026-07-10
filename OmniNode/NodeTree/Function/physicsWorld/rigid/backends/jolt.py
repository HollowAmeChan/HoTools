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
import math
import time
from typing import TYPE_CHECKING

from ..names import (
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_SLOT_KIND,
)

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
    Jolt adapter 只消费 spec 快照，不回读 Blender 对象属性或包围盒。
    """
    stype = getattr(spec, "shape_type", None)
    if stype not in {"SPHERE", "CAPSULE", "CYLINDER", "TAPERED_CAPSULE", "TAPERED_CYLINDER", "PLANE", "BOX"}:
        slot_id = getattr(spec, "slot_id", "<unknown>")
        raise ValueError(f"RigidBodySpec {slot_id} has unsupported shape_type {stype!r}")
    return {
        "shape_type": stype,
        "shape_radius": max(float(getattr(spec, "shape_radius")), 0.001),
        "shape_half_height": max(float(getattr(spec, "shape_half_height")), 0.001),
        "shape_half_extents": tuple(getattr(spec, "shape_half_extents")),
        "shape_plane_half_extent": max(float(getattr(spec, "shape_plane_half_extent")), 1.0),
        "shape_top_radius": max(float(getattr(spec, "shape_top_radius")), 0.001),
        "shape_bottom_radius": max(float(getattr(spec, "shape_bottom_radius")), 0.001),
        "shape_convex_radius": max(float(getattr(spec, "shape_convex_radius")), 0.0),
        "shape_offset": tuple(getattr(spec, "shape_offset")),
        "shape_rotation_wxyz": tuple(getattr(spec, "shape_rotation_wxyz")),
    }


# ---------------------------------------------------------------------------
# 位置和旋转从 spec 快照提取
# ---------------------------------------------------------------------------

def _transform_from_body_spec(spec: "RigidBodySpec") -> tuple[tuple, tuple]:
    pos = getattr(spec, "world_position", None)
    rot = getattr(spec, "world_rotation_wxyz", None)
    try:
        return (
            (float(pos[0]), float(pos[1]), float(pos[2])),
            (float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3])),
        )
    except Exception as exc:
        slot_id = getattr(spec, "slot_id", "<unknown>")
        raise ValueError(f"RigidBodySpec {slot_id} has invalid world transform snapshot") from exc


def _constraint_frames_from_spec(spec: "ConstraintSpec") -> tuple[tuple, tuple, tuple, tuple]:
    shared_pos = getattr(spec, "anchor_position", None)
    shared_rot = getattr(spec, "anchor_rotation_wxyz", None)
    pos_a = getattr(spec, "anchor_position_a", shared_pos)
    rot_a = getattr(spec, "anchor_rotation_wxyz_a", shared_rot)
    pos_b = getattr(spec, "anchor_position_b", shared_pos)
    rot_b = getattr(spec, "anchor_rotation_wxyz_b", shared_rot)
    try:
        return (
            (float(pos_a[0]), float(pos_a[1]), float(pos_a[2])),
            (float(rot_a[0]), float(rot_a[1]), float(rot_a[2]), float(rot_a[3])),
            (float(pos_b[0]), float(pos_b[1]), float(pos_b[2])),
            (float(rot_b[0]), float(rot_b[1]), float(rot_b[2]), float(rot_b[3])),
        )
    except Exception as exc:
        slot_id = getattr(spec, "slot_id", "<unknown>")
        raise ValueError(f"ConstraintSpec {slot_id} has invalid anchor transform snapshot") from exc


def _vec3_tuple(value, fallback=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        result = (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        result = (float(fallback[0]), float(fallback[1]), float(fallback[2]))
    if not all(math.isfinite(v) for v in result):
        return (float(fallback[0]), float(fallback[1]), float(fallback[2]))
    return result


def _missed_ray_result(
    origin,
    direction,
    max_distance: float,
    end_position=None,
    reason: str = "",
) -> dict:
    ray_origin = _vec3_tuple(origin)
    ray_direction = _vec3_tuple(direction)
    distance_limit = max(float(max_distance), 0.0)
    if end_position is None:
        end_position = tuple(
            ray_origin[index] + ray_direction[index] * distance_limit
            for index in range(3)
        )
    return {
        "hit": False,
        "backend": "jolt",
        "slot_id": "",
        "origin": ray_origin,
        "direction": ray_direction,
        "max_distance": distance_limit,
        "end_position": _vec3_tuple(end_position),
        "position": _vec3_tuple(end_position),
        "normal": (0.0, 0.0, 0.0),
        "distance": distance_limit,
        "fraction": 1.0,
        "sub_shape_id": 0,
        "is_sensor": False,
        "reason": str(reason or ""),
    }


def _positive_int(value, fallback: int, low: int = 1, high: int = 1_000_000) -> int:
    try:
        number = int(value)
    except Exception:
        number = int(fallback)
    if number < low:
        number = int(fallback)
    return max(low, min(high, number))


def _capacity_tuple(
    max_bodies: int = 1024,
    max_body_pairs: int | None = None,
    max_contact_constraints: int | None = None,
) -> tuple[int, int, int]:
    bodies = _positive_int(max_bodies, 1024)
    pairs = _positive_int(max_body_pairs if max_body_pairs is not None else bodies * 4, bodies * 4)
    contacts = _positive_int(
        max_contact_constraints if max_contact_constraints is not None else bodies * 2,
        bodies * 2,
    )
    return bodies, pairs, contacts


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

    def __init__(
        self,
        max_bodies: int = 1024,
        max_body_pairs: int | None = None,
        max_contact_constraints: int | None = None,
    ):
        native = _load_native()
        if native is None:
            raise RuntimeError(
                "hotools_jolt 模块未找到。请先编译 native binding（build.bat）。"
            )
        max_bodies, max_body_pairs, max_contact_constraints = _capacity_tuple(
            max_bodies,
            max_body_pairs,
            max_contact_constraints,
        )
        self._jw = native.JoltWorld(
            max_bodies=max_bodies,
            max_body_pairs=max_body_pairs,
            max_contact_constraints=max_contact_constraints,
        )
        self.jolt_max_bodies: int = max_bodies
        self.jolt_max_body_pairs: int = max_body_pairs
        self.jolt_max_contact_constraints: int = max_contact_constraints
        self._jolt_capacity_signature: tuple[int, int, int] = (
            max_bodies,
            max_body_pairs,
            max_contact_constraints,
        )
        self._body_handles: dict[str, int] = {}
        self._body_slots_by_handle: dict[int, str] = {}
        self._constraint_handles: dict[str, int] = {}
        self.last_step_ms: float = 0.0
        self.last_contact_events: list[dict] = []
        self.last_contact_event_overflow: int = 0
        self.last_command_count: int = 0
        self.last_command_failed: int = 0
        self.last_command_errors: list[str] = []
        self.last_jolt_world_gravity: tuple[float, float, float] = (0.0, 0.0, -9.81)
        self._jolt_world_settings_signature: str = "default"
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
        self._body_slots_by_handle.clear()
        self._clear_contact_events()

    def _clear_contact_events(self) -> None:
        self.last_contact_events = []
        self.last_contact_event_overflow = 0

    # ---- Body 管理 --------------------------------------------------------

    def sync_body(self, slot_id: str, spec: "RigidBodySpec") -> int:
        """
        注册或更新刚体。generation 变化时先 remove 再 add。
        返回 body handle。
        """
        self._clear_contact_events()
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
        self._body_slots_by_handle[int(handle)] = str(slot_id)
        return handle

    def remove_body(self, slot_id: str) -> None:
        self._clear_contact_events()
        handle = self._body_handles.pop(slot_id, None)
        if handle is not None:
            self._jw.remove_body(handle)

    def _get_body_handle(self, slot_id: str) -> int | None:
        return self._body_handles.get(slot_id)

    def update_kinematic(self, slot_id: str, spec: "RigidBodySpec",
                         dt: float) -> None:
        """每帧驱动运动学刚体跟随 Blender 动画。"""
        handle = self._get_body_handle(slot_id)
        if handle is None:
            return
        if spec.body_type != "KINEMATIC":
            return
        pos, rot = _transform_from_body_spec(spec)
        self._jw.set_kinematic_transform(handle, pos, rot, dt)

    def set_body_velocity(
        self,
        slot_id: str,
        linear_velocity=(0.0, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.0),
    ) -> bool:
        handle = self._get_body_handle(slot_id)
        if handle is None or not hasattr(self._jw, "set_body_velocity"):
            return False
        return bool(self._jw.set_body_velocity(
            handle, tuple(linear_velocity), tuple(angular_velocity)))

    def add_body_force(
        self,
        slot_id: str,
        force=(0.0, 0.0, 0.0),
        torque=(0.0, 0.0, 0.0),
    ) -> bool:
        handle = self._get_body_handle(slot_id)
        if handle is None or not hasattr(self._jw, "add_body_force"):
            return False
        return bool(self._jw.add_body_force(handle, tuple(force), tuple(torque)))

    def add_body_impulse(
        self,
        slot_id: str,
        impulse=(0.0, 0.0, 0.0),
        angular_impulse=(0.0, 0.0, 0.0),
    ) -> bool:
        handle = self._get_body_handle(slot_id)
        if handle is None or not hasattr(self._jw, "add_body_impulse"):
            return False
        return bool(self._jw.add_body_impulse(
            handle, tuple(impulse), tuple(angular_impulse)))

    def set_body_gravity_factor(self, slot_id: str, gravity_factor: float) -> bool:
        handle = self._get_body_handle(slot_id)
        if handle is None or not hasattr(self._jw, "set_body_gravity_factor"):
            return False
        return bool(self._jw.set_body_gravity_factor(handle, float(gravity_factor)))

    def set_body_material_response(
        self,
        slot_id: str,
        friction: float,
        restitution: float,
    ) -> bool:
        handle = self._get_body_handle(slot_id)
        if handle is None or not hasattr(self._jw, "set_body_material_response"):
            return False
        return bool(self._jw.set_body_material_response(
            handle, float(friction), float(restitution)))

    def set_body_motion_quality(self, slot_id: str, motion_quality: str) -> bool:
        handle = self._get_body_handle(slot_id)
        if handle is None or not hasattr(self._jw, "set_body_motion_quality"):
            return False
        return bool(self._jw.set_body_motion_quality(handle, str(motion_quality)))

    def set_body_active(self, slot_id: str, active: bool = True) -> bool:
        handle = self._get_body_handle(slot_id)
        if handle is None or not hasattr(self._jw, "activate_body"):
            return False
        return bool(self._jw.activate_body(handle, bool(active)))

    def set_gravity(self, gravity=(0.0, 0.0, -9.81)) -> bool:
        if self._jw is None or not hasattr(self._jw, "set_gravity"):
            return False
        vec = _vec3_tuple(gravity, (0.0, 0.0, -9.81))
        self._jw.set_gravity(vec)
        self.last_jolt_world_gravity = vec
        return True

    def get_body_transform(self, slot_id: str):
        """返回 (position_xyz, rotation_wxyz) 或 None。"""
        handle = self._get_body_handle(slot_id)
        if handle is None:
            return None
        return self._jw.get_body_transform(handle)

    def get_body_state(self, slot_id: str) -> dict | None:
        """返回求解后的 transform、速度和激活状态，或 None。"""
        handle = self._get_body_handle(slot_id)
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

    def ray_cast(
        self,
        origin=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, -1.0),
        max_distance: float = 100.0,
        include_sensors: bool = True,
        ignore_slot_id: str | None = None,
    ) -> dict:
        """Query the closest body without exposing a native body handle."""
        ray_origin = _vec3_tuple(origin)
        ray_direction = _vec3_tuple(direction, (0.0, 0.0, -1.0))
        direction_length = math.sqrt(sum(value * value for value in ray_direction))
        distance_limit = max(float(max_distance), 0.0)
        if direction_length <= 1.0e-12 or distance_limit <= 0.0:
            return _missed_ray_result(
                ray_origin,
                ray_direction,
                distance_limit,
                reason="invalid_ray",
            )

        unit_direction = tuple(value / direction_length for value in ray_direction)
        segment = tuple(value * distance_limit for value in unit_direction)
        end_position = tuple(ray_origin[i] + segment[i] for i in range(3))
        if self._jw is None or not hasattr(self._jw, "cast_ray"):
            return _missed_ray_result(
                ray_origin,
                unit_direction,
                distance_limit,
                end_position=end_position,
                reason="native_query_unavailable",
            )

        ignore_handle = self._body_handles.get(str(ignore_slot_id), 0) if ignore_slot_id else 0
        (
            hit,
            body_handle,
            position,
            normal,
            fraction,
            sub_shape_id,
            is_sensor,
        ) = self._jw.cast_ray(
            ray_origin,
            segment,
            bool(include_sensors),
            int(ignore_handle or 0),
        )
        if not hit:
            return _missed_ray_result(
                ray_origin,
                unit_direction,
                distance_limit,
                end_position=end_position,
            )

        slot_id = self._body_slots_by_handle.get(int(body_handle), "")
        if not slot_id:
            return _missed_ray_result(
                ray_origin,
                unit_direction,
                distance_limit,
                end_position=end_position,
                reason="unmapped_body",
            )
        hit_fraction = min(max(float(fraction), 0.0), 1.0)
        return {
            "hit": True,
            "backend": self.BACKEND,
            "slot_id": str(slot_id),
            "origin": ray_origin,
            "direction": unit_direction,
            "max_distance": distance_limit,
            "end_position": end_position,
            "position": _vec3_tuple(position),
            "normal": _vec3_tuple(normal),
            "distance": hit_fraction * distance_limit,
            "fraction": hit_fraction,
            "sub_shape_id": int(sub_shape_id),
            "is_sensor": bool(is_sensor),
            "reason": "",
        }

    # ---- Constraint 管理 -------------------------------------------------

    def sync_constraint(self, slot_id: str, spec: "ConstraintSpec") -> int:
        """注册或更新约束，返回 constraint handle。"""
        self._clear_contact_events()
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

        pos_a, rot_a, pos_b, rot_b = _constraint_frames_from_spec(spec)

        kwargs = dict(
            constraint_type=spec.constraint_type,
            body_a_handle=a_handle,
            body_b_handle=b_handle,
            anchor_pos=pos_a,
            anchor_rot_wxyz=rot_a,
            use_separate_anchor_frames=True,
            anchor_pos_a=pos_a,
            anchor_rot_wxyz_a=rot_a,
            anchor_pos_b=pos_b,
            anchor_rot_wxyz_b=rot_b,
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
            swing_motor_state=str(getattr(spec, "swing_motor_state", "OFF")),
            twist_motor_state=str(getattr(spec, "twist_motor_state", "OFF")),
            swing_twist_target_angular_velocity=tuple(
                getattr(spec, "swing_twist_target_angular_velocity", (0.0, 0.0, 0.0))
            ),
            swing_twist_target_orientation_wxyz=tuple(
                getattr(spec, "swing_twist_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0))
            ),
            six_dof_axis_modes=tuple(getattr(
                spec, "six_dof_axis_modes", ("FREE",) * 6,
            )),
            six_dof_limit_min=tuple(getattr(
                spec, "six_dof_limit_min", (-1.0, -1.0, -1.0, -3.141592653589793, -3.141592653589793, -3.141592653589793),
            )),
            six_dof_limit_max=tuple(getattr(
                spec, "six_dof_limit_max", (1.0, 1.0, 1.0, 3.141592653589793, 3.141592653589793, 3.141592653589793),
            )),
            six_dof_swing_type=str(getattr(spec, "six_dof_swing_type", "PYRAMID")),
            six_dof_max_friction=tuple(getattr(
                spec, "six_dof_max_friction", (0.0,) * 6,
            )),
            six_dof_limit_spring_frequency=tuple(getattr(
                spec, "six_dof_limit_spring_frequency", (0.0,) * 3,
            )),
            six_dof_limit_spring_damping=tuple(getattr(
                spec, "six_dof_limit_spring_damping", (0.0,) * 3,
            )),
            six_dof_motor_states=tuple(getattr(
                spec, "six_dof_motor_states", ("OFF",) * 6,
            )),
            six_dof_target_velocity=tuple(getattr(
                spec, "six_dof_target_velocity", (0.0, 0.0, 0.0),
            )),
            six_dof_target_angular_velocity=tuple(getattr(
                spec, "six_dof_target_angular_velocity", (0.0, 0.0, 0.0),
            )),
            six_dof_target_position=tuple(getattr(
                spec, "six_dof_target_position", (0.0, 0.0, 0.0),
            )),
            six_dof_target_orientation_wxyz=tuple(getattr(
                spec, "six_dof_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0),
            )),
            cone_half_angle=float(getattr(spec, "cone_half_angle", 0.0)),
            swing_type=str(getattr(spec, "swing_type", "CONE")),
            swing_normal_half_angle=float(
                getattr(spec, "swing_normal_half_angle", 3.141592653589793)
            ),
            swing_plane_half_angle=float(
                getattr(spec, "swing_plane_half_angle", 3.141592653589793)
            ),
            twist_min_angle=float(getattr(spec, "twist_min_angle", -3.141592653589793)),
            twist_max_angle=float(getattr(spec, "twist_max_angle", 3.141592653589793)),
            distance_min=float(getattr(spec, "distance_min", 0.0)),
            distance_max=float(getattr(spec, "distance_max", 1.0)),
            disable_collisions=bool(getattr(spec, "disable_collisions", True)),
        )
        handle = self._jw.add_constraint(**kwargs)
        self._constraint_handles[slot_id] = handle
        return handle

    def remove_constraint(self, slot_id: str) -> None:
        self._clear_contact_events()
        handle = self._constraint_handles.pop(slot_id, None)
        if handle is not None:
            self._jw.remove_constraint(handle)

    def get_constraint_state(self, slot_id: str) -> dict | None:
        """返回约束当前值和上一物理步 lambda 的 HoTools 快照。"""
        handle = self._constraint_handles.get(slot_id)
        if handle is None or not hasattr(self._jw, "get_constraint_state"):
            return None

        raw_state = self._jw.get_constraint_state(handle)
        (
            constraint_type,
            enabled,
            current_value_kind,
            current_value,
            lambda_position,
            lambda_rotation,
            lambda_limit,
            lambda_motor,
            *extended_state,
        ) = raw_state
        current_translation = _vec3_tuple(
            extended_state[0] if len(extended_state) >= 2 else (0.0, 0.0, 0.0)
        )
        current_rotation = _vec3_tuple(
            extended_state[1] if len(extended_state) >= 2 else (0.0, 0.0, 0.0)
        )
        position = _vec3_tuple(lambda_position)
        rotation = _vec3_tuple(lambda_rotation)
        peak = max(
            math.sqrt(sum(value * value for value in position)),
            math.sqrt(sum(value * value for value in rotation)),
            abs(float(lambda_limit)),
            abs(float(lambda_motor)),
        )
        return {
            "constraint_type": str(constraint_type),
            "enabled": bool(enabled),
            "current_value_kind": str(current_value_kind or "none"),
            "current_value": float(current_value),
            "current_translation": current_translation,
            "current_rotation": current_rotation,
            "lambda_position": position,
            "lambda_rotation": rotation,
            "lambda_limit": float(lambda_limit),
            "lambda_motor": float(lambda_motor),
            "lambda_max_abs": float(peak),
        }

    def set_constraint_enabled(self, slot_id: str, enabled: bool) -> bool:
        handle = self._constraint_handles.get(slot_id)
        if handle is None or not hasattr(self._jw, "set_constraint_enabled"):
            return False
        return bool(self._jw.set_constraint_enabled(handle, bool(enabled)))

    # ---- Simulation step -------------------------------------------------

    def step(self, dt: float, substeps: int = 1) -> float:
        """执行模拟步，返回耗时（ms）。"""
        self.last_step_ms = self._jw.step(dt, substeps)
        self._refresh_contact_events()
        return self.last_step_ms

    def _refresh_contact_events(self) -> None:
        """把 native handle 事件映射成不泄露后端句柄的 slot 快照。"""
        if not hasattr(self._jw, "get_contact_events"):
            self.last_contact_events = []
            self.last_contact_event_overflow = 0
            return

        events = []
        for raw in self._jw.get_contact_events():
            if not isinstance(raw, (tuple, list)) or len(raw) != 12:
                continue
            (
                state,
                body_a_handle,
                body_b_handle,
                body_a_sensor,
                body_b_sensor,
                is_sensor,
                normal,
                penetration_depth,
                points_on_a,
                points_on_b,
                sub_shape_a,
                sub_shape_b,
            ) = raw
            slot_a = self._body_slots_by_handle.get(int(body_a_handle), "")
            slot_b = self._body_slots_by_handle.get(int(body_b_handle), "")
            if not slot_a or not slot_b:
                continue
            events.append({
                "state": str(state),
                "body_a_slot_id": slot_a,
                "body_b_slot_id": slot_b,
                "body_a_sensor": bool(body_a_sensor),
                "body_b_sensor": bool(body_b_sensor),
                "is_sensor": bool(is_sensor),
                "normal": _vec3_tuple(normal),
                "penetration_depth": float(penetration_depth),
                "points_on_a": tuple(_vec3_tuple(point) for point in points_on_a),
                "points_on_b": tuple(_vec3_tuple(point) for point in points_on_b),
                "sub_shape_a": int(sub_shape_a),
                "sub_shape_b": int(sub_shape_b),
            })
        self.last_contact_events = events
        self.last_contact_event_overflow = int(
            getattr(self._jw, "contact_event_overflow_count", 0) or 0
        )

    def get_contact_events(self) -> list[dict]:
        """返回上一真实模拟步的 HoTools 接触事件快照。"""
        return [dict(event) for event in self.last_contact_events]

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
        from ..debug import rigid_backend_debug_snapshot

        return rigid_backend_debug_snapshot(self)

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
        self._body_slots_by_handle.clear()
        self._clear_contact_events()
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
    desired_capacity = _jolt_world_capacity_from_settings(world)
    existing = world.backend_resources.get(RIGID_BACKEND_RESOURCE_KEY)
    if isinstance(existing, JoltAdapter) and existing._valid:
        if getattr(existing, "_jolt_capacity_signature", None) != desired_capacity:
            try:
                existing.dispose("rigid_jolt_world_capacity_changed")
            except Exception:
                pass
            world.backend_resources.pop(RIGID_BACKEND_RESOURCE_KEY, None)
            _mark_rigid_slots_for_resync(world)
            try:
                world.replace_required = True
            except Exception:
                pass
        else:
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
        adapter = JoltAdapter(
            max_bodies=desired_capacity[0],
            max_body_pairs=desired_capacity[1],
            max_contact_constraints=desired_capacity[2],
        )
        fc = world.frame_context if world.frame_context else None
        adapter._last_generation = fc.generation if fc else 0
        world.backend_resources[RIGID_BACKEND_RESOURCE_KEY] = adapter
        return adapter
    except Exception:
        import traceback
        traceback.print_exc()
        return None


def _jolt_world_capacity_from_settings(world) -> tuple[int, int, int]:
    try:
        from ..implicit_objects import active_rigid_jolt_world_capacities
        return active_rigid_jolt_world_capacities(world)
    except Exception:
        return _capacity_tuple()


def _mark_rigid_slots_for_resync(world) -> None:
    try:
        slots = list(world.solver_slots.values())
    except Exception:
        return
    for slot in slots:
        if getattr(slot, "kind", None) in {RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND}:
            try:
                slot.data.pop("_jolt_generation", None)
            except Exception:
                pass
