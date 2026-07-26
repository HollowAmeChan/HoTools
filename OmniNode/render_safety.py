"""渲染安全工具：渲染期间刷新/验证 bpy 对象引用，防止跨帧悬空指针崩溃。

Blender 渲染动画时，每帧渲染完毕后会释放/重建渲染评估资源（evaluated depsgraph）。
如果 Python 侧的物理缓存（PhysicsWorldCache → solver_slots → spec.armature）
持有指向已释放对象的 bpy 引用，下一帧 frame_change_post 访问时就会崩溃。

解决思路：
  - 渲染开始前（render_pre）以及每帧渲染前（frame_change_post 内检测到 _IS_RENDERING）
    调用 on_render_frame_start()，遍历所有物理世界缓存，
    把 spec.armature 这类直接 bpy 引用替换成当前帧的活体对象。
  - 替换依据：spec.armature_ptr + spec.armature_data_ptr 双指针。

此模块位于 NodeTree 级别，不依赖 physicsWorld 内部结构，
通过反射/协议接口访问缓存，避免循环依赖。
"""

from __future__ import annotations

import bpy


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------

def on_render_frame_start() -> None:
    """渲染每帧开始前刷新所有物理缓存中的 bpy 引用。

    在 OmniNodeTree 的 render_pre handler 和每帧 frame_change_post（渲染期间）
    调用此函数，可保证物理 spec 里的 armature 引用始终有效。
    """
    _refresh_all_physics_armature_refs()


# ---------------------------------------------------------------------------
# bpy 引用验证
# ---------------------------------------------------------------------------

def is_bpy_object_valid(obj) -> bool:
    """检查 bpy Object 引用是否仍然有效（未被 Blender 释放）。"""
    if obj is None:
        return False
    try:
        _ = obj.name
        return True
    except ReferenceError:
        return False
    except Exception:
        return True


def resolve_armature_by_ptr(armature_ptr: int, armature_data_ptr: int):
    """通过双指针在 bpy.data.objects 中重新查找 armature 活体引用。

    Args:
        armature_ptr: obj.as_pointer() 整数值
        armature_data_ptr: obj.data.as_pointer() 整数值

    Returns:
        匹配的 bpy.types.Object，或 None。
    """
    if armature_ptr <= 0 or armature_data_ptr <= 0:
        return None
    try:
        for obj in bpy.data.objects:
            try:
                if obj.type != "ARMATURE":
                    continue
                if obj.as_pointer() != armature_ptr:
                    continue
                data = getattr(obj, "data", None)
                if data is not None and data.as_pointer() == armature_data_ptr:
                    return obj
            except Exception:
                continue
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 刷新所有物理缓存中的 spec.armature 引用
# ---------------------------------------------------------------------------

def _refresh_all_physics_armature_refs() -> None:
    """遍历所有 OmniNodeTree 的 runtime cache，刷新物理 spec 里的 armature 引用。

    只有在引用已失效、或指针校验不匹配时才重新查找，有效引用直接跳过，
    性能损耗极低。
    """
    try:
        for ng in list(bpy.data.node_groups):
            try:
                _refresh_tree_physics_armature_refs(ng)
            except Exception:
                pass
    except Exception:
        pass


def _refresh_tree_physics_armature_refs(tree) -> None:
    """刷新单棵 OmniNodeTree runtime cache 内所有物理 spec 的 armature 引用。"""
    physics_worlds = _get_physics_world_caches_from_tree(tree)
    _walk_cache_and_refresh(physics_worlds)


def _get_physics_world_caches_from_tree(tree) -> list:
    """从 tree 的 runtime cache 中找出所有 PhysicsWorldCache 实例。"""
    try:
        from .Function.physicsWorld.types import PhysicsWorldCache
    except Exception:
        return []

    results = []
    try:
        # 通过 OmniRuntimeState 访问 committed 缓存（同 NodeTree 级别）
        from .OmniRuntimeState import OmniRuntimeState
        state = OmniRuntimeState.get_state(tree)
        if state is None:
            return results
        committed = getattr(state, "_committed", None)
        if not isinstance(committed, dict):
            return results
        for ns_dict in committed.values():
            if not isinstance(ns_dict, dict):
                continue
            for value in ns_dict.values():
                if isinstance(value, PhysicsWorldCache):
                    results.append(value)
    except Exception:
        pass
    return results


def _walk_cache_and_refresh(physics_worlds: list) -> None:
    for world in physics_worlds:
        try:
            _refresh_physics_world(world)
        except Exception:
            pass


def _refresh_physics_world(world) -> None:
    """刷新单个 PhysicsWorldCache 内所有 solver slot spec 的 armature 引用。"""
    solver_slots = getattr(world, "solver_slots", None)
    if isinstance(solver_slots, dict):
        for slot in list(solver_slots.values()):
            try:
                _refresh_slot_spec(slot)
            except Exception:
                pass

    _refresh_implicit_objects(world)


def _refresh_slot_spec(slot) -> None:
    """刷新 solver slot 内 spec 的 armature 引用。"""
    data = getattr(slot, "data", None)
    spec = data.get("spec") if isinstance(data, dict) else None
    if spec is None:
        return

    _refresh_spec_armature(spec, "armature", "armature_ptr", "armature_data_ptr")

    for chain in getattr(spec, "chains", ()) or ():
        try:
            _refresh_spec_armature(chain, "armature", "armature_ptr", "armature_data_ptr")
        except Exception:
            pass


def _refresh_spec_armature(spec, attr: str, ptr_attr: str, data_ptr_attr: str) -> None:
    """检查 spec 上的直接 bpy 引用，若失效则按双指针重新解析。"""
    current = getattr(spec, attr, None)
    ptr = int(getattr(spec, ptr_attr, 0) or 0)
    data_ptr = int(getattr(spec, data_ptr_attr, 0) or 0)

    if is_bpy_object_valid(current):
        try:
            if current.as_pointer() == ptr:
                cur_data = getattr(current, "data", None)
                if cur_data is not None and cur_data.as_pointer() == data_ptr:
                    return  # 有效且匹配，无需刷新
        except Exception:
            pass

    fresh = resolve_armature_by_ptr(ptr, data_ptr)
    try:
        setattr(spec, attr, fresh)
    except Exception:
        pass


def _refresh_implicit_objects(world) -> None:
    """刷新 PhysicsWorldCache.implicit_objects 列表中 armature 字段的 bpy 引用。"""
    implicit_objects = getattr(world, "implicit_objects", None)
    if not isinstance(implicit_objects, list):
        return

    for item in implicit_objects:
        if not isinstance(item, dict):
            continue
        armature = item.get("armature")
        ptr = int(item.get("armature_ptr", 0) or 0)
        data_ptr = int(item.get("armature_data_ptr", 0) or 0)
        if ptr <= 0 or data_ptr <= 0:
            continue

        if is_bpy_object_valid(armature):
            try:
                if armature.as_pointer() == ptr:
                    data = getattr(armature, "data", None)
                    if data is not None and data.as_pointer() == data_ptr:
                        continue
            except Exception:
                pass

        item["armature"] = resolve_armature_by_ptr(ptr, data_ptr)
