"""
physicsWorld.types — 统一物理世界的基础数据类型

包含：
  PhysicsObjectScope    — 本帧物理世界的对象范围（纯运行值，无跨帧生命周期）
  PhysicsFrameContext   — 统一帧状态（连续性、重置、dt、generation）
  PhysicsColliderSource — 从 scope 解析出的单个碰撞源（轻量中间值）
  PhysicsWorldCache     — 跨帧共享的物理世界 owner（实现 omni_cache_dispose 协议）
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import bpy


# ---------------------------------------------------------------------------
# PhysicsObjectScope
# ---------------------------------------------------------------------------

class PhysicsObjectScope:
    """
    本帧物理世界关心的对象范围。

    它是纯运行值，不实现 omni_cache_dispose，不跨帧持有资源。
    include_hidden 由此处统一决定；Physics World Begin 不再接收同名参数。
    """

    __slots__ = (
        "objects",
        "include_object_colliders",
        "include_bone_colliders",
        "include_mesh_collision",
        "include_hidden",
    )

    def __init__(
        self,
        objects: tuple = (),
        include_object_colliders: bool = True,
        include_bone_colliders: bool = True,
        include_mesh_collision: bool = True,
        include_hidden: bool = False,
    ) -> None:
        self.objects: tuple = tuple(objects) if objects else ()
        self.include_object_colliders: bool = bool(include_object_colliders)
        self.include_bone_colliders: bool = bool(include_bone_colliders)
        self.include_mesh_collision: bool = bool(include_mesh_collision)
        self.include_hidden: bool = bool(include_hidden)

    def __repr__(self) -> str:
        return (
            f"PhysicsObjectScope("
            f"objects={len(self.objects)}, "
            f"obj_col={self.include_object_colliders}, "
            f"bone_col={self.include_bone_colliders}, "
            f"mesh_col={self.include_mesh_collision}, "
            f"hidden={self.include_hidden})"
        )


# ---------------------------------------------------------------------------
# PhysicsFrameContext
# ---------------------------------------------------------------------------

class PhysicsFrameContext:
    """
    统一的当前帧状态，由 Physics World Begin 写入，solver 只读。

    continuous   — current_frame == previous_frame + 1
    same_frame   — current_frame == previous_frame（同帧重复求值）
    restart_required — reset / 跳帧 / 倒放 / scope 变化 / world invalid
    generation   — world 每次重建或全局 restart 时递增；
                   solver slot 用它判断是否需要冷启动
    """

    __slots__ = (
        "scene_key",
        "frame",
        "previous_frame",
        "continuous",
        "same_frame",
        "reset_requested",
        "restart_required",
        "dt",
        "time_scale",
        "substeps",
        "generation",
    )

    def __init__(self) -> None:
        self.scene_key: str = ""
        self.frame: int = 0
        self.previous_frame: int | None = None
        self.continuous: bool = False
        self.same_frame: bool = False
        self.reset_requested: bool = False
        self.restart_required: bool = True
        self.dt: float = 0.0
        self.time_scale: float = 1.0
        self.substeps: int = 1
        self.generation: int = 0

    def to_debug_dict(self) -> dict:
        return {
            "scene_key": self.scene_key,
            "frame": self.frame,
            "previous_frame": self.previous_frame,
            "continuous": self.continuous,
            "same_frame": self.same_frame,
            "reset_requested": self.reset_requested,
            "restart_required": self.restart_required,
            "dt": round(self.dt, 6),
            "time_scale": self.time_scale,
            "substeps": self.substeps,
            "generation": self.generation,
        }


# ---------------------------------------------------------------------------
# PhysicsColliderSource
# ---------------------------------------------------------------------------

class PhysicsColliderSource:
    """
    从 object scope 解析出的单个碰撞源。

    它是 Physics World Begin 内部的轻量中间值，不持有 native 资源，
    不跨帧缓存（由 collider_snapshot 负责帧间传递）。

    owner_type: "OBJECT" | "BONE" | "MESH"
    """

    __slots__ = (
        "owner",
        "owner_type",
        "bone_name",
        "props",
        "key",
        "visible",
    )

    def __init__(
        self,
        owner,
        owner_type: str,
        bone_name: str = "",
        props=None,
        key: str = "",
        visible: bool = True,
    ) -> None:
        self.owner = owner
        self.owner_type: str = str(owner_type)
        self.bone_name: str = str(bone_name)
        self.props = props
        self.key: str = str(key)
        self.visible: bool = bool(visible)


# ---------------------------------------------------------------------------
# PhysicsSolverSlot
# ---------------------------------------------------------------------------

class PhysicsSolverSlot:
    """
    solver 在 world 内的私有状态槽。

    solver 自己负责往 .data 里写状态；world 只管 slot 的生命周期：
      - scope/world restart 时可标记所有 slot 的 world_generation。
      - solver topology/config 变化时，solver 自己重建 slot.data。
      - world dispose 时调用所有 slot 的 dispose()。
    """

    __slots__ = ("slot_id", "kind", "world_generation", "data")

    def __init__(self, slot_id: str, kind: str, world_generation: int = 0) -> None:
        self.slot_id: str = slot_id
        self.kind: str = kind
        self.world_generation: int = world_generation
        self.data: dict = {}

    def dispose(self, reason: str) -> None:
        """释放 slot 内持有的 native 资源（由 solver 在 data 中注册 dispose 回调）。"""
        dispose_fn = self.data.get("_dispose")
        if callable(dispose_fn):
            try:
                dispose_fn(reason)
            except Exception:
                pass
        self.data.clear()

    def debug_snapshot(self) -> dict:
        snapshot_fn = self.data.get("_debug_snapshot")
        if callable(snapshot_fn):
            try:
                return snapshot_fn()
            except Exception:
                pass
        keys = [k for k in self.data if not k.startswith("_")]
        return {"slot_id": self.slot_id, "kind": self.kind, "keys": keys}


# ---------------------------------------------------------------------------
# PhysicsWorldCache
# ---------------------------------------------------------------------------

class PhysicsWorldCache:
    """
    跨帧共享的物理世界 owner。

    实现 omni_cache_dispose 协议，走零拷贝 cache 路径。
    持有：
      frame_context          — 统一帧状态
      object_scope_key       — 上帧 scope key（用于检测 scope 变化）
      collider_snapshot      — 当帧碰撞快照（dict list）
      previous_collider_snapshot — 上帧快照（供 MC2 moving collider 使用）
      solver_slots           — 各 solver 的私有状态槽
      backend_resources      — native backend 资源（如 Jolt world context）
      generation             — 每次 world 重建时递增
      replace_required       — 当帧 Commit 是否走 replace（由 Begin 写入，Commit 只读）
      valid                  — 上帧是否正常完成；Begin 检测到脏帧时重置为 False
      _current_writer        — 分叉写入防护锁（持锁的 solver_id）
    """

    kind = "hotools.physics_world"
    schema = 1

    def __init__(self) -> None:
        self.frame_context: PhysicsFrameContext = PhysicsFrameContext()
        self.object_scope_key = None
        self.collider_snapshot: dict = {"frame": None, "colliders": [], "source_count": 0}
        self.previous_collider_snapshot: dict | None = None
        self.solver_slots: dict[str, PhysicsSolverSlot] = {}
        self.runtime_caches: dict = {}
        self.backend_resources: dict = {}
        self.generation: int = 0
        self.replace_required: bool = True
        self.valid: bool = True
        self._current_writer: str | None = None
        self._created_at: float = time.perf_counter()

    # ---- 写入锁 --------------------------------------------------------

    def acquire_write(self, solver_id: str) -> None:
        """
        solver 开始写入 world 前调用。
        若 world 已被另一个 solver 持有则立即抛错，防止分叉 mutation 产生静默错误。
        """
        if self._current_writer is not None and self._current_writer != solver_id:
            raise RuntimeError(
                f"PhysicsWorldCache 分叉写入冲突：{self._current_writer!r} 尚未释放，"
                f"{solver_id!r} 不能同时写入同一个 world。"
                f"请检查节点连线是否把 world 分叉给了多个 solver。"
            )
        self._current_writer = solver_id

    def release_write(self, solver_id: str) -> None:
        """solver 写入结束后调用。"""
        if self._current_writer == solver_id:
            self._current_writer = None

    def clear_write_lock(self) -> None:
        """Physics World Begin 每帧开始时调用，防止上帧异常退出留下锁。"""
        self._current_writer = None

    # ---- Solver Slot ---------------------------------------------------

    def ensure_solver_slot(self, slot_id: str, kind: str) -> PhysicsSolverSlot:
        """
        获取或创建 solver slot。

        slot_id 必须包含 obj_ptr + data_ptr 双指针，不能只用单 obj_ptr，
        避免 Blender 删除对象后指针复用导致错误的 slot 命中。
        """
        slot = self.solver_slots.get(slot_id)
        if slot is None:
            slot = PhysicsSolverSlot(slot_id, kind, self.generation)
            self.solver_slots[slot_id] = slot
        return slot

    def invalidate_all_slots(self, reason: str = "world_restart") -> None:
        """scope/world restart 时标记所有 slot 的 world_generation，
        使 solver 在下次检测到 generation 不匹配时冷启动。"""
        for slot in self.solver_slots.values():
            slot.world_generation = self.generation - 1  # 故意不匹配

    def runtime_cache(self, name: str):
        """按名称获取 world 内部的轻量 runtime cache（如 collider arrays）。"""
        return self.runtime_caches.get(name)

    def set_runtime_cache(self, name: str, value) -> None:
        self.runtime_caches[name] = value

    # ---- omni_cache_dispose 协议 ---------------------------------------

    def omni_cache_dispose(self, reason: str) -> None:
        """
        释放所有持有资源。由 OmniRuntimeState 在 cache 被替换或 clear_all 时调用。
        dispose 内不能抛出异常，否则会中断上层 dispose 链。
        """
        # 释放所有 solver slot
        for slot in list(self.solver_slots.values()):
            try:
                slot.dispose(reason)
            except Exception:
                pass
        self.solver_slots.clear()

        # 释放 backend resources（如 Jolt world context）
        # backend 资源须先释放 bodies/constraints，再释放 world，顺序不能颠倒
        for name, resource in list(self.backend_resources.items()):
            dispose_fn = getattr(resource, "dispose", None) or getattr(resource, "omni_cache_dispose", None)
            if callable(dispose_fn):
                try:
                    dispose_fn(reason)
                except Exception:
                    pass
        self.backend_resources.clear()

        # 清理 runtime caches（Python 容器，GC 即可，但显式 clear 更安全）
        self.runtime_caches.clear()

        # 重置碰撞快照（不持有 native 资源，直接清空）
        self.collider_snapshot = {"frame": None, "colliders": [], "source_count": 0}
        self.previous_collider_snapshot = None
        self.valid = False

    # ---- omni_cache_debug_snapshot 协议 --------------------------------

    def omni_cache_debug_snapshot(self) -> dict:
        fc = self.frame_context
        slot_snapshots = {}
        for slot_id, slot in self.solver_slots.items():
            try:
                slot_snapshots[slot_id] = slot.debug_snapshot()
            except Exception as e:
                slot_snapshots[slot_id] = {"error": str(e)}

        return {
            "kind": self.kind,
            "schema": self.schema,
            "generation": self.generation,
            "replace_required": self.replace_required,
            "valid": self.valid,
            "frame": fc.frame,
            "previous_frame": fc.previous_frame,
            "continuous": fc.continuous,
            "same_frame": fc.same_frame,
            "restart_required": fc.restart_required,
            "dt": round(fc.dt, 6),
            "time_scale": fc.time_scale,
            "substeps": fc.substeps,
            "objects": len(self.collider_snapshot.get("colliders") or []),
            "collider_sources": self.collider_snapshot.get("source_count", 0),
            "colliders": len(self.collider_snapshot.get("colliders") or []),
            "solver_slots": slot_snapshots,
            "backend_resources": list(self.backend_resources.keys()),
        }

    def __repr__(self) -> str:
        fc = self.frame_context
        return (
            f"PhysicsWorldCache("
            f"gen={self.generation}, "
            f"frame={fc.frame}, "
            f"slots={len(self.solver_slots)}, "
            f"valid={self.valid})"
        )
