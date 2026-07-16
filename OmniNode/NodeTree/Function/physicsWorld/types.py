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
        "include_passive_collision",
        "include_bone_collision",
        "include_mesh_collision",
        "include_rigid_body",
        "include_rigid_constraint",
        "include_hidden",
    )

    def __init__(
        self,
        objects: tuple = (),
        include_passive_collision: bool = True,
        include_bone_collision: bool = True,
        include_mesh_collision: bool = True,
        include_rigid_body: bool = True,
        include_rigid_constraint: bool = True,
        include_hidden: bool = False,
    ) -> None:
        self.objects: tuple = tuple(objects) if objects else ()
        self.include_passive_collision: bool = bool(include_passive_collision)
        self.include_bone_collision: bool = bool(include_bone_collision)
        self.include_mesh_collision: bool = bool(include_mesh_collision)
        self.include_rigid_body: bool = bool(include_rigid_body)
        self.include_rigid_constraint: bool = bool(include_rigid_constraint)
        self.include_hidden: bool = bool(include_hidden)

    def __repr__(self) -> str:
        return (
            f"PhysicsObjectScope("
            f"objects={len(self.objects)}, "
            f"passive={self.include_passive_collision}, "
            f"bone={self.include_bone_collision}, "
            f"mesh={self.include_mesh_collision}, "
            f"rigid={self.include_rigid_body}, "
            f"constraint={self.include_rigid_constraint}, "
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
        "raw_dt",
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
        self.raw_dt: float = 0.0
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
            "raw_dt": round(self.raw_dt, 6),
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
      implicit_objects       — 跨帧持久的隐式物理对象 registry
      exchange               — 当前图执行内的帧级交换 item registry
      result_streams         — 当前图执行内的 solver result registry
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
        self.implicit_objects: list[dict] = []
        self.exchange: dict[str, list[dict]] = {}
        self.result_streams: dict[str, list[dict]] = {}
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

    # ---- 隐式物理对象 --------------------------------------------------

    def append_implicit_object(
        self,
        item: dict | None = None,
        tag: str | None = None,
        producer: str = "unknown",
        stable_id: str = "",
        signature: str = "",
        enabled: bool = True,
        schema: int = 1,
        **payload,
    ) -> dict | None:
        """
        追加或更新跨帧持久的隐式物理对象。

        implicit object 不是 frame exchange：Physics World Begin 不会清空它。
        tag 是 solver 可读的类型标记；stable_id 只用于 registry 内部去重，不暴露为用户设置。
        """
        data = dict(item) if isinstance(item, dict) else {}
        if payload:
            data.update(payload)

        object_tag = str(tag or data.get("tag") or "").strip()
        if not object_tag:
            return None

        object_signature = str(signature or data.get("signature") or "").strip()
        object_stable_id = str(stable_id or data.get("stable_id") or "").strip()
        if not object_stable_id and object_signature:
            object_stable_id = f"{object_tag}:{object_signature}"
        if not object_stable_id:
            object_stable_id = f"{object_tag}:{len(self.implicit_objects)}"

        previous_index = None
        previous = None
        for index, candidate in enumerate(self.implicit_objects):
            if not isinstance(candidate, dict):
                continue
            if candidate.get("tag") == object_tag and candidate.get("stable_id") == object_stable_id:
                previous_index = index
                previous = candidate
                break

        previous_version = int(previous.get("version", 0)) if isinstance(previous, dict) else 0
        changed = (
            previous is None
            or previous.get("signature") != object_signature
            or bool(previous.get("enabled", True)) != bool(enabled)
        )
        frame = int(getattr(self.frame_context, "frame", 0) or 0)
        entry = {
            "tag": object_tag,
            "stable_id": object_stable_id,
            "schema": int(schema or data.get("schema", 1) or 1),
            "payload": dict(data.get("payload") if isinstance(data.get("payload"), dict) else data),
            "signature": object_signature,
            "version": previous_version + 1 if changed else previous_version,
            "dirty": bool(changed),
            "enabled": bool(enabled),
            "producer": str(producer or "unknown"),
            "source_id": str(data.get("source_id", "") or object_stable_id),
            "priority": int(data.get("priority", 0) or 0),
            "updated_frame": frame if changed or previous is None else previous.get("updated_frame", frame),
            "last_seen_frame": frame,
            "generation": int(self.generation),
        }
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            entry["metadata"] = dict(metadata)
        elif isinstance(previous, dict) and "metadata" in previous:
            entry["metadata"] = previous.get("metadata")

        if previous_index is None:
            self.implicit_objects.append(entry)
        else:
            self.implicit_objects[previous_index] = entry
        return entry

    def iter_implicit_objects(
        self,
        tag: str | None = None,
        producer: str | None = None,
        enabled: bool | None = True,
    ) -> list[dict]:
        """读取隐式物理对象。此操作不删除 item。"""
        items = [item for item in self.implicit_objects if isinstance(item, dict)]
        if tag is not None:
            items = [item for item in items if item.get("tag") == str(tag)]
        if producer is not None:
            items = [item for item in items if item.get("producer") == str(producer)]
        if enabled is not None:
            items = [item for item in items if bool(item.get("enabled", True)) == bool(enabled)]
        return list(items)

    def copy_implicit_objects_from(self, other) -> None:
        """
        world owner 被 replace 时保留隐式对象。

        这里故意只浅拷贝 entry：payload 里可能包含 Blender 对象引用，不能深拷贝。
        """
        if not isinstance(other, PhysicsWorldCache):
            return
        self.implicit_objects = [
            dict(item)
            for item in getattr(other, "implicit_objects", ())
            if isinstance(item, dict)
        ]

    def implicit_object_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.implicit_objects:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag") or "")
            if not tag:
                continue
            counts[tag] = counts.get(tag, 0) + 1
        return counts

    def clear_exchange(self) -> None:
        """清空当前图执行内的 frame scratch exchange。"""
        self.exchange.clear()

    def publish_exchange(
        self,
        item: dict | None = None,
        channel: str | None = None,
        producer: str = "unknown",
        scope: str = "frame",
        **payload,
    ) -> dict | None:
        """
        发布帧级 exchange item。

        返回实际存入的 dict；channel 缺失时返回 None，避免节点链路因
        临时 payload 不完整而崩溃。
        """
        data = dict(item) if isinstance(item, dict) else {}
        if payload:
            data.update(payload)
        ch = str(channel or data.get("channel") or "").strip()
        if not ch:
            return None
        data["channel"] = ch
        data.setdefault("producer", producer)
        data.setdefault("scope", scope)
        data.setdefault("frame", int(getattr(self.frame_context, "frame", 0) or 0))
        data.setdefault("generation", int(self.generation))
        self.exchange.setdefault(ch, []).append(data)
        return data

    def consume_exchange(
        self,
        channel: str | None = None,
        producer: str | None = None,
        scope: str | None = None,
    ) -> list[dict]:
        """读取 exchange item。此操作不删除 item，consumer 自行记录消费状态。"""
        if channel is None:
            items = [item for bucket in self.exchange.values() for item in bucket]
        else:
            items = list(self.exchange.get(str(channel), ()))
        if producer is not None:
            items = [item for item in items if item.get("producer") == producer]
        if scope is not None:
            items = [item for item in items if item.get("scope") == scope]
        return items

    def exchange_counts(self) -> dict[str, int]:
        return {str(channel): len(items) for channel, items in self.exchange.items()}

    def clear_results(self, channel: str | None = None, solver: str | None = None) -> None:
        """
        清空 result stream。

        channel=None 且 solver=None 时清空全部；指定 solver 时只清理该 solver
        生产的 item。result stream 是当前图执行内的本帧输出，不负责跨帧持久化。
        """
        if channel is None and solver is None:
            self.result_streams.clear()
            return

        if channel is not None:
            ch = str(channel)
            if solver is None:
                self.result_streams.pop(ch, None)
                return
            items = self.result_streams.get(ch, [])
            self.result_streams[ch] = [item for item in items if item.get("solver") != solver]
            if not self.result_streams[ch]:
                self.result_streams.pop(ch, None)
            return

        for ch in list(self.result_streams.keys()):
            items = self.result_streams.get(ch, [])
            self.result_streams[ch] = [item for item in items if item.get("solver") != solver]
            if not self.result_streams[ch]:
                self.result_streams.pop(ch, None)

    def publish_result(
        self,
        item: dict | None = None,
        channel: str | None = None,
        solver: str = "unknown",
        **payload,
    ) -> dict | None:
        """
        发布 solver result item。

        result item 是本帧纯数据快照，供 writeback、debug、export、节点读取消费。
        channel 缺失时返回 None。
        """
        data = dict(item) if isinstance(item, dict) else {}
        if payload:
            data.update(payload)
        ch = str(channel or data.get("channel") or "").strip()
        if not ch:
            return None
        data["channel"] = ch
        data.setdefault("solver", solver)
        data.setdefault("frame", int(getattr(self.frame_context, "frame", 0) or 0))
        data.setdefault("generation", int(self.generation))
        self.result_streams.setdefault(ch, []).append(data)
        return data

    def consume_results(
        self,
        channel: str | None = None,
        solver: str | None = None,
        frame: int | None = None,
        generation: int | None = None,
    ) -> list[dict]:
        """读取 result stream item。此操作不删除 item。"""
        if channel is None:
            items = [item for bucket in self.result_streams.values() for item in bucket]
        else:
            items = list(self.result_streams.get(str(channel), ()))
        if solver is not None:
            items = [item for item in items if item.get("solver") == solver]
        if frame is not None:
            items = [item for item in items if int(item.get("frame", -1)) == int(frame)]
        if generation is not None:
            items = [item for item in items if int(item.get("generation", -1)) == int(generation)]
        return items

    def result_stream_counts(self) -> dict[str, int]:
        return {str(channel): len(items) for channel, items in self.result_streams.items()}

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
        self.implicit_objects.clear()
        self.exchange.clear()
        self.result_streams.clear()

        # 重置碰撞快照（不持有 native 资源，直接清空）
        self.collider_snapshot = {"frame": None, "colliders": [], "source_count": 0}
        self.previous_collider_snapshot = None
        self.valid = False

        # 同步清除各 solver 自有可视化调试绘制条目，避免缓存销毁后残影留在视口。
        for module_name, function_name in (
            (".rigid.debug_draw", "clear_rigid_debug_draw_store"),
            (".spring_vrm.debug_draw", "clear_spring_vrm_debug_draw_store"),
            (".mc2.debug_draw", "clear_mc2_debug_draw_store"),
        ):
            try:
                from importlib import import_module
                clear_fn = getattr(import_module(module_name, __package__), function_name)
                clear_fn(world_id=str(id(self)))
            except Exception:
                pass

    # ---- omni_cache_debug_snapshot 协议 --------------------------------

    def omni_cache_debug_snapshot(self) -> dict:
        fc = self.frame_context
        slot_snapshots = {}
        for slot_id, slot in self.solver_slots.items():
            try:
                slot_snapshots[slot_id] = slot.debug_snapshot()
            except Exception as e:
                slot_snapshots[slot_id] = {"error": str(e)}

        backend_snapshots = {}
        for name, resource in self.backend_resources.items():
            try:
                snapshot_fn = getattr(resource, "debug_snapshot", None) or getattr(resource, "omni_cache_debug_snapshot", None)
                if callable(snapshot_fn):
                    backend_snapshots[name] = snapshot_fn()
                else:
                    backend_snapshots[name] = {"type": type(resource).__name__}
            except Exception as e:
                backend_snapshots[name] = {"error": str(e)}

        try:
            from .declarations import solver_declarations_debug_snapshot
            solver_declarations = solver_declarations_debug_snapshot()
        except Exception as e:
            solver_declarations = {"error": str(e)}

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
            "objects": self.collider_snapshot.get("object_count", 0),
            "collider_sources": self.collider_snapshot.get("source_count", 0),
            "colliders": len(self.collider_snapshot.get("colliders") or []),
            "implicit_objects": self.implicit_object_counts(),
            "implicit_object_count": len(self.implicit_objects),
            "exchange_channels": self.exchange_counts(),
            "exchange_item_count": sum(len(items) for items in self.exchange.values()),
            "result_channels": self.result_stream_counts(),
            "result_item_count": sum(len(items) for items in self.result_streams.values()),
            "solver_declarations": solver_declarations,
            "solver_slots": slot_snapshots,
            "backend_resources": list(self.backend_resources.keys()),
            "backend_resource_details": backend_snapshots,
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
