"""
physicsWorld.scope — object scope 工具函数

职责：
  - object 列表去重、过滤
  - scope key 计算（Collection 边界、对象数量和类型开关）
  - 从 scope 解析 PhysicsColliderSource 列表
"""

from __future__ import annotations

import bpy
import numpy as np
from .types import PhysicsObjectScope, PhysicsColliderSource


PHYSICS_SCOPE_COLLECTION_BATCH_CHANNEL = "physics_scope_collection_batch_v1"
PHYSICS_SCOPE_COLLECTION_BATCH_SCHEMA = "physics_scope_collection_batch_v1"


# ---------------------------------------------------------------------------
# 对象有效性检查
# ---------------------------------------------------------------------------

def _obj_is_valid(obj) -> bool:
    """判断 bpy.types.Object 引用是否仍然有效。"""
    if obj is None:
        return False
    try:
        # 访问 .as_pointer() 对已失效的 bpy 引用会抛 ReferenceError
        _ = obj.as_pointer()
        _ = obj.type
        return True
    except (ReferenceError, AttributeError, RuntimeError):
        return False


def _obj_is_visible(obj) -> bool:
    """判断对象在当前视口是否可见。"""
    try:
        return bool(obj.visible_get())
    except Exception:
        return True  # 无法判断时默认视为可见，不跳过


def _collection_is_valid(collection) -> bool:
    if collection is None or not isinstance(collection, bpy.types.Collection):
        return False
    try:
        collection.as_pointer()
        return True
    except (ReferenceError, AttributeError, RuntimeError):
        return False


# ---------------------------------------------------------------------------
# Scope Key
# ---------------------------------------------------------------------------

def build_scope_key(scope: PhysicsObjectScope) -> frozenset:
    """
    计算低频 scope key，只观察节点边界、对象数量和类型开关。

    对象内部属性、data 替换以及“同数量对象替换”不在运行时逐层核对；
    这类编辑由用户重新编译 Omni 树后刷新注册。
    """
    entries: list[tuple] = []
    for collection in getattr(scope, "collections", ()):
        try:
            entries.append(("collection", int(collection.as_pointer())))
        except Exception:
            entries.append(("collection_invalid", id(collection)))
    entries.append(("object_count", len(getattr(scope, "objects", ()))))

    include_flags = (
        bool(scope.include_passive_collision),
        bool(scope.include_bone_collision),
        bool(scope.include_rigid_body),
        bool(scope.include_rigid_constraint),
        bool(scope.include_hidden),
        bool(scope.include_field),
    )
    return frozenset(entries) | {("flags", include_flags)}


# ---------------------------------------------------------------------------
# 对象去重
# ---------------------------------------------------------------------------

def _flatten_objects(objects) -> list:
    """
    递归展平可能嵌套的 list / tuple（多重输入 socket 传来的值是嵌套结构）。
    非容器的叶节点直接收集，不做类型校验（无效对象在 dedupe_objects 里过滤）。
    """
    result = []
    stack = list(objects) if isinstance(objects, (list, tuple)) else ([objects] if objects is not None else [])
    while stack:
        item = stack.pop(0)
        if isinstance(item, (list, tuple)):
            stack[0:0] = list(item)
        else:
            result.append(item)
    return result


def dedupe_objects(objects) -> list:
    """
    去重并保持顺序。

    - 自动展平嵌套 list（多重输入 socket 值）。
    - 同一个 obj_ptr 只保留第一次出现的引用。
    - 无效引用跳过（不计入结果）。
    """
    seen: set[int] = set()
    result = []
    for obj in _flatten_objects(objects):
        if not _obj_is_valid(obj):
            continue
        try:
            ptr = int(obj.as_pointer())
        except Exception:
            continue
        if ptr in seen:
            continue
        seen.add(ptr)
        result.append(obj)
    return result


def _flatten_collections(collections) -> list:
    result = []
    stack = list(reversed(collections)) if isinstance(collections, (list, tuple)) else (
        [collections] if collections is not None else []
    )
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(reversed(item))
        else:
            result.append(item)
    return result


def dedupe_collections(collections) -> list:
    """展平 Collection 多重输入并按 datablock pointer 保序去重。"""
    result = []
    seen = set()
    for collection in _flatten_collections(collections):
        if not _collection_is_valid(collection):
            continue
        pointer = int(collection.as_pointer())
        if pointer in seen:
            continue
        seen.add(pointer)
        result.append(collection)
    return result


def _foreach_float(collection_objects, property_name: str, width: int) -> np.ndarray:
    values = np.empty(len(collection_objects) * int(width), dtype=np.float32)
    if values.size:
        collection_objects.foreach_get(property_name, values)
    return values


def build_collection_batches(
    collections,
) -> tuple[tuple[dict, ...], dict[int, tuple[int, int]]]:
    """冻结 Collection.all_objects 顺序及 Object 直接 transform 批量输入。"""
    batches = []
    locations = {}
    seen_objects = {}
    for batch_index, collection in enumerate(dedupe_collections(collections)):
        collection_objects = collection.all_objects
        objects = tuple(collection_objects)
        object_ptrs = []
        data_ptrs = []
        for object_index, obj in enumerate(objects):
            object_ptr = int(obj.as_pointer())
            previous = seen_objects.get(object_ptr)
            if previous is not None:
                raise ValueError(
                    "物理对象范围的多个 Collection 包含同一对象："
                    f"{obj.name_full} 同时属于 {previous} 与 {collection.name_full}"
                )
            seen_objects[object_ptr] = collection.name_full
            data = getattr(obj, "data", None)
            data_ptr = int(data.as_pointer()) if data is not None else 0
            object_ptrs.append(object_ptr)
            data_ptrs.append(data_ptr)
            locations[object_ptr] = (batch_index, object_index)

        batches.append({
            "schema": PHYSICS_SCOPE_COLLECTION_BATCH_SCHEMA,
            "collection": collection,
            "collection_ptr": int(collection.as_pointer()),
            "objects": objects,
            "object_ptrs": tuple(object_ptrs),
            "data_ptrs": tuple(data_ptrs),
            "object_count": len(objects),
            "locations_f32": _foreach_float(collection_objects, "location", 3),
            "rotation_eulers_f32": _foreach_float(
                collection_objects, "rotation_euler", 3
            ),
            "rotation_quaternions_f32": _foreach_float(
                collection_objects, "rotation_quaternion", 4
            ),
            "rotation_axis_angles_f32": _foreach_float(
                collection_objects, "rotation_axis_angle", 4
            ),
            "matrix_world_f32": _foreach_float(collection_objects, "matrix_world", 16),
        })
    return tuple(batches), locations


def publish_scope_collection_batches(world, scope: PhysicsObjectScope) -> int:
    """把当前 Scope 的 Collection 批次发布为帧级 exchange。"""
    count = 0
    for batch in getattr(scope, "collection_batches", ()):
        if not isinstance(batch, dict):
            continue
        world.publish_exchange(
            batch,
            channel=PHYSICS_SCOPE_COLLECTION_BATCH_CHANNEL,
            producer="physics_object_scope",
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# 合并多个 object 列表
# ---------------------------------------------------------------------------

def merge_object_lists(*lists) -> list:
    """合并多个 object 列表并去重。"""
    combined = []
    for lst in lists:
        if lst is None:
            continue
        if isinstance(lst, (list, tuple)):
            combined.extend(lst)
        else:
            combined.append(lst)
    return dedupe_objects(combined)


# ---------------------------------------------------------------------------
# 从 collection 收集对象
# ---------------------------------------------------------------------------

def objects_from_collection(collection, recursive: bool = True, include_hidden: bool = False) -> list:
    """
    从 bpy.types.Collection 收集对象。

    recursive=True 时递归子集合。
    include_hidden=False 时跳过不可见对象。
    """
    if collection is None or not isinstance(collection, bpy.types.Collection):
        return []

    result = []
    seen: set[int] = set()

    def visit(col):
        for obj in (col.objects or []):
            if not _obj_is_valid(obj):
                continue
            if not include_hidden and not _obj_is_visible(obj):
                continue
            try:
                ptr = int(obj.as_pointer())
            except Exception:
                continue
            if ptr in seen:
                continue
            seen.add(ptr)
            result.append(obj)
        if recursive:
            for child in (col.children or []):
                visit(child)

    visit(collection)
    return result


# ---------------------------------------------------------------------------
# 按类型过滤对象
# ---------------------------------------------------------------------------

def filter_objects_by_type(objects, obj_type: str) -> list:
    """保留指定 type 的对象（如 'ARMATURE'、'MESH'、'EMPTY'）。"""
    result = []
    for obj in (objects or []):
        if not _obj_is_valid(obj):
            continue
        try:
            if obj.type == obj_type:
                result.append(obj)
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# 从场景收集对象
# ---------------------------------------------------------------------------

def objects_from_scene(scene, include_hidden: bool = False) -> list:
    """
    从 bpy.types.Scene 直接收集所有对象（scene.objects 平铺列表，不区分集合层级）。

    等价于把整个场景的所有对象一次性放入物理世界，
    适合快速搭建测试场景或不需要按集合精确筛选时使用。

    include_hidden=False 时跳过不可见对象（与 objects_from_collection 行为一致）。
    """
    if scene is None:
        try:
            scene = bpy.context.scene
        except Exception:
            return []

    if not isinstance(scene, bpy.types.Scene):
        return []

    result = []
    seen: set[int] = set()
    for obj in (scene.objects or []):
        if not _obj_is_valid(obj):
            continue
        if not include_hidden and not _obj_is_visible(obj):
            continue
        try:
            ptr = int(obj.as_pointer())
        except Exception:
            continue
        if ptr in seen:
            continue
        seen.add(ptr)
        result.append(obj)
    return result


def collection_from_scene(scene):
    """返回 Scene 的根 Collection；其 all_objects 是完整场景批量边界。"""
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is None or not isinstance(scene, bpy.types.Scene):
        return None
    return scene.collection


# ---------------------------------------------------------------------------
# 构造 PhysicsObjectScope
# ---------------------------------------------------------------------------

def make_scope(
    objects=None,
    include_passive_collision: bool = True,
    include_bone_collision: bool = True,
    include_rigid_body: bool = True,
    include_rigid_constraint: bool = True,
    include_hidden: bool = False,
    include_field: bool = True,
    *,
    collections=None,
) -> PhysicsObjectScope:
    """从 Collection 批次构造 Scope；objects 参数仅保留给内部兼容调用。"""
    collection_values = dedupe_collections(collections) if collections is not None else []
    if collection_values:
        collection_batches, collection_locations = build_collection_batches(
            collection_values
        )
        deduped = [
            obj
            for batch in collection_batches
            for obj in batch["objects"]
        ]
        include_hidden = True
    else:
        collection_batches = ()
        collection_locations = {}
        deduped = dedupe_objects(objects)
    return PhysicsObjectScope(
        objects=tuple(deduped),
        collections=tuple(collection_values),
        collection_batches=collection_batches,
        collection_locations=collection_locations,
        include_passive_collision=include_passive_collision,
        include_bone_collision=include_bone_collision,
        include_rigid_body=include_rigid_body,
        include_rigid_constraint=include_rigid_constraint,
        include_hidden=include_hidden,
        include_field=include_field,
    )


# ---------------------------------------------------------------------------
# 从 scope 解析 ColliderSource 列表
# ---------------------------------------------------------------------------

def collect_physics_sources(scope: PhysicsObjectScope) -> tuple[list[PhysicsColliderSource], int]:
    """
    遍历 scope.objects，按 include_* flag 解析出 PhysicsColliderSource 列表。

    返回 (sources, invalid_count)：
      sources        — 有效的 collider source 列表
      invalid_count  — 引用失效或跳过的对象数量（供 debug snapshot 使用）
    """
    sources: list[PhysicsColliderSource] = []
    invalid_count = 0

    for obj in scope.objects:
        if not _obj_is_valid(obj):
            invalid_count += 1
            continue

        # 可见性过滤
        if not scope.include_hidden and not _obj_is_visible(obj):
            continue

        try:
            obj_ptr = int(obj.as_pointer())
            obj_type = obj.type
        except Exception:
            invalid_count += 1
            continue

        # Object 级简单碰撞
        if scope.include_passive_collision:
            props = getattr(obj, "hotools_object_collision", None)
            if props is not None:
                if bool(getattr(props, "enabled", False)):
                    data_ptr = int(obj.data.as_pointer()) if obj.data is not None else 0
                    sources.append(PhysicsColliderSource(
                        owner=obj,
                        owner_type="OBJECT",
                        bone_name="",
                        props=props,
                        key=f"obj:{obj_ptr}:{data_ptr}",
                        visible=True,
                    ))

        # Bone 级碰撞（需要 Armature）
        if scope.include_bone_collision and obj_type == "ARMATURE" and obj.data is not None:
            arm_data_ptr = int(obj.data.as_pointer())
            for bone in obj.data.bones:
                props = getattr(bone, "hotools_collision", None)
                if props is None:
                    continue
                collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
                if collision_type == "NONE":
                    continue
                bone_name = str(bone.name or "")
                sources.append(PhysicsColliderSource(
                    owner=obj,
                    owner_type="BONE",
                    bone_name=bone_name,
                    props=props,
                    key=f"bone:{obj_ptr}:{arm_data_ptr}:{bone_name}",
                    visible=True,
                ))

    return sources, invalid_count
