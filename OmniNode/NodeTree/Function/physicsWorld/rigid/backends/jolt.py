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


# ---------------------------------------------------------------------------
# 形状参数从 RigidBodySpec 提取
# ---------------------------------------------------------------------------

def _shape_params_from_spec(spec: "RigidBodySpec") -> dict:
    """
    从 hotools_rigid_body PropertyGroup 读取碰撞形状参数。
    如果 spec.obj 有 hotools_object_collision（简单碰撞属性），优先用那里的形状。
    否则使用 obj.dimensions 的包围球作为 fallback。
    """
    obj = spec.obj
    if obj is None:
        return {"shape_type": "SPHERE", "shape_radius": 0.1}

    # 优先读 hotools_object_collision
    col = getattr(obj, "hotools_object_collision", None)
    if col is not None and bool(getattr(col, "enabled", False)):
        ctype = str(getattr(col, "collision_type", "NONE"))
        if ctype == "SPHERE":
            r = max(float(getattr(col, "radius", 0.1)), 0.001)
            return {"shape_type": "SPHERE", "shape_radius": r}
        if ctype == "CAPSULE":
            r = max(float(getattr(col, "radius", 0.1)), 0.001)
            h = max(float(getattr(col, "length", 0.2)), 0.001) * 0.5
            return {"shape_type": "CAPSULE", "shape_radius": r,
                    "shape_half_height": h}
        if ctype == "BOX":
            bx = getattr(col, "box_size", None)
            if bx is not None:
                hx = max(float(bx[0]) * 0.5, 0.001)
                hy = max(float(bx[1]) * 0.5, 0.001)
                hz = max(float(bx[2]) * 0.5, 0.001)
                return {"shape_type": "BOX",
                        "shape_half_extents": (hx, hy, hz)}

    # fallback：对象包围盒的 AABB 半尺寸
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
        loc = obj.location
        rot = obj.rotation_euler.to_quaternion()
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
        # slot_id → jolt body handle
        self._body_handles: dict[str, int] = {}
        # slot_id → jolt constraint handle
        self._constraint_handles: dict[str, int] = {}
        # 最近一次 step 耗时（ms）
        self.last_step_ms: float = 0.0
        self._valid = True

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

        handle = self._jw.add_body(
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
        )
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

        # 找 target_a / target_b 的 body handle
        import hotools_jolt as _hj
        world_handle = _hj.WORLD_HANDLE

        def _get_handle(target_obj) -> int:
            if target_obj is None:
                return world_handle
            for sid, h in self._body_handles.items():
                try:
                    slot_obj = getattr(
                        # slot_id 格式 "rigid:{obj_ptr}:{data_ptr}"
                        None, "obj", None
                    )
                except Exception:
                    pass
            # fallback：线性搜索（通常刚体数量不多）
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

        handle = self._jw.add_constraint(
            constraint_type=spec.constraint_type,
            body_a_handle=a_handle,
            body_b_handle=b_handle,
            anchor_pos=pos,
            anchor_rot_wxyz=rot,
        )
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
        """
        import mathutils
        written = []
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
            try:
                pos_arr, rot_arr = self._jw.get_body_transform(handle)
                obj.location = mathutils.Vector(pos_arr)
                # rot_arr = (w, x, y, z)
                q = mathutils.Quaternion(
                    (rot_arr[0], rot_arr[1], rot_arr[2], rot_arr[3])
                )
                obj.rotation_euler = q.to_euler()
                written.append(slot_id)
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
        释放顺序：先约束，再刚体，最后销毁 JoltWorld。
        不能抛出异常（dispose 链约定）。
        """
        if not self._valid:
            return
        try:
            self._constraint_handles.clear()
            self._body_handles.clear()
            self._jw.clear()
        except Exception:
            pass
        self._valid = False

    def omni_cache_dispose(self, reason: str) -> None:
        """兼容 omni_cache_dispose 协议，供 backend_resources 字典调用。"""
        self.dispose(reason)


# ---------------------------------------------------------------------------
# 辅助：获取或创建 adapter
# ---------------------------------------------------------------------------

def ensure_jolt_adapter(world) -> "JoltAdapter | None":
    """
    从 world.backend_resources["rigid_solver"] 获取 JoltAdapter。
    若不存在则尝试新建。native 不可用时返回 None。
    """
    existing = world.backend_resources.get("rigid_solver")
    if isinstance(existing, JoltAdapter):
        return existing
    # 已有其他 backend 就不覆盖
    if existing is not None:
        return None
    try:
        adapter = JoltAdapter()
        world.backend_resources["rigid_solver"] = adapter
        return adapter
    except Exception as e:
        # hotools_jolt 未编译或初始化失败
        import traceback
        traceback.print_exc()
        return None
