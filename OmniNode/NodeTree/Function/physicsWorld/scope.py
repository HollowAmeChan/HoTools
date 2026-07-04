"""
physicsWorld.scope — object scope 工具函数

职责：
  - object 列表去重、过滤
  - scope key 计算（双指针，防止 Blender 指针复用导致 scope 变化未被检测）
  - 从 scope 解析 PhysicsColliderSource 列表
"""

from __future__ import annotations

import bpy
from .types import PhysicsObjectScope, PhysicsColliderSource


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
    except (ReferenceError, AttributeError):
        return False


def _obj_is_visible(obj) -> bool:
    """判断对象在当前视口是否可见。"""
    try:
        return bool(obj.visible_get())
    except Exception:
        return True  # 无法判断时默认视为可见，不跳过


# ---------------------------------------------------------------------------
# Scope Key
# ---------------------------------------------------------------------------

def build_scope_key(scope: PhysicsObjectScope) -> frozenset:
    """
    计算 scope key，用于检测对象范围是否变化。

    使用 (obj_ptr, data_ptr) 双指针，而不是单 obj_ptr：
    Blender 删除对象后会释放地址，新建对象可能复用同一整数指针，
    单指针无法感知"删除旧对象、新建不同对象但指针相同"的变化。

    data_ptr 感知 mesh / armature 数据被替换（obj 同一个但 .data 换了）的情况。

    include_flags 也纳入 key，flag 变化同样触发 restart。
    """
    entries: list[tuple] = []
    for obj in scope.objects:
        if not _obj_is_valid(obj):
            # 引用已失效：记录标记值而不是跳过
            # 跳过会导致对象数量稳定但内容变了，无法触发 restart
            entries.append((-1, id(obj)))
            continue
        try:
            obj_ptr = int(obj.as_pointer())
            data_ptr = int(obj.data.as_pointer()) if obj.data is not None else 0
            entries.append((obj_ptr, data_ptr))
        except Exception:
            entries.append((-1, id(obj)))

    include_flags = (
        bool(scope.include_passive_collision),
        bool(scope.include_bone_collision),
        bool(scope.include_mesh_collision),
        bool(scope.include_rigid_body),
        bool(scope.include_rigid_constraint),
        bool(scope.include_hidden),
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
# 构造 PhysicsObjectScope
# ---------------------------------------------------------------------------

def make_scope(
    objects,
    include_passive_collision: bool = True,
    include_bone_collision: bool = True,
    include_mesh_collision: bool = True,
    include_rigid_body: bool = True,
    include_rigid_constraint: bool = True,
    include_hidden: bool = False,
) -> PhysicsObjectScope:
    """从 object 列表构造 PhysicsObjectScope，自动去重。"""
    deduped = dedupe_objects(objects)
    return PhysicsObjectScope(
        objects=tuple(deduped),
        include_passive_collision=include_passive_collision,
        include_bone_collision=include_bone_collision,
        include_mesh_collision=include_mesh_collision,
        include_rigid_body=include_rigid_body,
        include_rigid_constraint=include_rigid_constraint,
        include_hidden=include_hidden,
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

        # Mesh 碰撞配置（vertex collision / self collision / base pose proxy）
        if scope.include_mesh_collision and obj_type == "MESH" and obj.data is not None:
            props = getattr(obj, "hotools_mesh_collision", None)
            if props is not None and bool(getattr(props, "enabled", False)):
                mesh_ptr = int(obj.data.as_pointer())
                sources.append(PhysicsColliderSource(
                    owner=obj,
                    owner_type="MESH",
                    bone_name="",
                    props=props,
                    key=f"mesh:{obj_ptr}:{mesh_ptr}",
                    visible=True,
                ))

    return sources, invalid_count
