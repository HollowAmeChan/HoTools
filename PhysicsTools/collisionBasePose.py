"""
MC2 BasePose 只读对象的集中管理模块。

这个文件只处理物理缓存对象的生命周期和轻量校验：
1. 创建/刷新当前物理 Mesh 对应的 BasePose 只读对象。
2. 将自动生成的对象统一归档到场景集合 HoPhysicsCache。
3. 移除复制体上的物理解算后置 delta 输出，避免只读输入混入写回结果。
4. 检查当前物理对象与 BasePose 对象的顶点数、Loop 数、面数是否一致。

它不负责读取 evaluated mesh、构建 solver state 或执行物理解算；这些仍由
OmniNode/physicsMC2 后端处理。
"""

import bpy

from .deltaOutput import PhysicsDeltaOutputSpec
from .deltaOutput import ensure_delta_attribute as _ensure_delta_attribute
from .deltaOutput import ensure_delta_modifier as _ensure_delta_modifier
from .deltaOutput import ensure_delta_output as _ensure_delta_output
from .deltaOutput import remove_delta_output as _remove_delta_output_by_spec


CACHE_COLLECTION_NAME = "HoPhysicsCache"
CACHE_OBJECT_FLAG = "hotools_base_pose_cache"
CACHE_SOURCE_KEY = "hotools_base_pose_source"
DELTA_ATTRIBUTE_NAME = "mc2_delta"
DELTA_MODIFIER_NAME = "MC2 后置位移"
DELTA_NODE_GROUP_NAME = "HoTools_MC2_ApplyDelta"
MC2_DELTA_SPEC = PhysicsDeltaOutputSpec(
    attribute_name=DELTA_ATTRIBUTE_NAME,
    modifier_name=DELTA_MODIFIER_NAME,
    node_group_name=DELTA_NODE_GROUP_NAME,
    label="MC2 后置位移",
)


def _is_live_id(value) -> bool:
    if value is None:
        return False
    try:
        value.as_pointer()
        return True
    except ReferenceError:
        return False
    except Exception:
        return False


def _is_live_mesh_object(value) -> bool:
    if not _is_live_id(value) or not isinstance(value, bpy.types.Object):
        return False
    try:
        return value.type == "MESH" and value.data is not None and _is_live_id(value.data)
    except ReferenceError:
        return False


def _is_generated_cache_object(value) -> bool:
    if not _is_live_id(value):
        return False
    try:
        return bool(value.get(CACHE_OBJECT_FLAG, False))
    except ReferenceError:
        return False


def mesh_light_key(obj: bpy.types.Object) -> tuple[int, int, int]:
    mesh = getattr(obj, "data", None)
    if not _is_live_mesh_object(obj) or mesh is None:
        return (0, 0, 0)
    return (len(mesh.vertices), len(mesh.loops), len(mesh.polygons))


def validate_base_pose_proxy(source_obj: bpy.types.Object, base_obj: bpy.types.Object) -> None:
    if not _is_live_mesh_object(source_obj):
        raise ValueError("当前物理对象必须是Mesh")
    if not _is_live_mesh_object(base_obj):
        raise ValueError("BasePose只读对象必须是Mesh")
    if base_obj == source_obj:
        raise ValueError("BasePose只读对象不能指向当前物理写入对象")
    source_key = mesh_light_key(source_obj)
    base_key = mesh_light_key(base_obj)
    if source_key != base_key:
        raise ValueError(
            "BasePose只读对象拓扑数量不一致："
            f"当前={source_key[0]}顶点/{source_key[1]}Loop/{source_key[2]}面，"
            f"BasePose={base_key[0]}顶点/{base_key[1]}Loop/{base_key[2]}面"
        )


def ensure_cache_collection(scene: bpy.types.Scene = None) -> bpy.types.Collection:
    scene = scene or bpy.context.scene
    collection = bpy.data.collections.get(CACHE_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(CACHE_COLLECTION_NAME)
    if not any(child == collection for child in scene.collection.children):
        try:
            scene.collection.children.link(collection)
        except RuntimeError:
            pass
    return collection


def _unlink_from_other_collections(obj: bpy.types.Object, keep_collection: bpy.types.Collection) -> None:
    for collection in list(obj.users_collection):
        if collection == keep_collection:
            continue
        collection.objects.unlink(obj)


def move_to_cache_collection(obj: bpy.types.Object, scene: bpy.types.Scene = None) -> None:
    collection = ensure_cache_collection(scene)
    if not any(item == obj for item in collection.objects):
        collection.objects.link(obj)
    _unlink_from_other_collections(obj, collection)


def ensure_delta_modifier(obj: bpy.types.Object) -> bpy.types.Modifier:
    # 这个修改器必须位于 Armature/基础变形之后；运行时只写 mc2_delta 顶点属性。
    return _ensure_delta_modifier(obj, MC2_DELTA_SPEC)


def ensure_delta_attribute(obj: bpy.types.Object) -> bpy.types.Attribute:
    return _ensure_delta_attribute(obj, MC2_DELTA_SPEC)


def ensure_delta_output(obj: bpy.types.Object) -> None:
    _ensure_delta_output(obj, MC2_DELTA_SPEC)


def _remove_delta_output(obj: bpy.types.Object) -> None:
    _remove_delta_output_by_spec(obj, MC2_DELTA_SPEC)


def _disable_runtime_flags(obj: bpy.types.Object) -> None:
    props = getattr(obj, "hotools_mesh_collision", None)
    if props is None:
        return
    props.enabled = False
    props.mc2_base_pose_proxy = None


def create_base_pose_proxy(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
) -> bpy.types.Object:
    if not _is_live_mesh_object(source_obj):
        raise ValueError("当前物理对象必须是Mesh")

    base_obj = source_obj.copy()
    base_obj.data = source_obj.data.copy()
    base_obj.name = f"{source_obj.name}_BasePose"
    base_obj.data.name = f"{source_obj.data.name}_BasePose"
    try:
        ensure_cache_collection(scene).objects.link(base_obj)
        _remove_delta_output(base_obj)
        _disable_runtime_flags(base_obj)
        base_obj.display_type = "WIRE"
        base_obj.hide_render = True
        base_obj.hide_select = True
        base_obj[CACHE_OBJECT_FLAG] = True
        # Blender IDProperty 的整数不是 64 位安全的，不能直接保存 as_pointer()。
        base_obj[CACHE_SOURCE_KEY] = f"{source_obj.name_full}:{int(source_obj.as_pointer())}"
        validate_base_pose_proxy(source_obj, base_obj)
    except Exception:
        old_mesh = base_obj.data
        bpy.data.objects.remove(base_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        raise
    return base_obj


def refresh_base_pose_proxy(
    source_obj: bpy.types.Object,
    base_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
) -> bpy.types.Object:
    base_obj_live = _is_live_mesh_object(base_obj)
    same_object = False
    if base_obj_live:
        try:
            same_object = bool(base_obj == source_obj)
        except ReferenceError:
            same_object = False
    remove_old = base_obj_live and not same_object and _is_generated_cache_object(base_obj)

    if remove_old and base_obj is not None:
        old_mesh = base_obj.data
        bpy.data.objects.remove(base_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

    return create_base_pose_proxy(source_obj, scene)


def ensure_base_pose_proxy(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    refresh: bool = False,
) -> bpy.types.Object:
    props = getattr(source_obj, "hotools_mesh_collision", None)
    if props is None:
        raise ValueError("当前物体没有HoTools网格碰撞属性")

    try:
        base_obj = getattr(props, "mc2_base_pose_proxy", None)
    except ReferenceError:
        base_obj = None
    if refresh or base_obj is None:
        base_obj = refresh_base_pose_proxy(source_obj, base_obj, scene)
        props.mc2_base_pose_proxy = base_obj
        return base_obj

    try:
        validate_base_pose_proxy(source_obj, base_obj)
    except ReferenceError:
        base_obj = refresh_base_pose_proxy(source_obj, None, scene)
        props.mc2_base_pose_proxy = base_obj
        return base_obj
    except ValueError:
        if _is_generated_cache_object(base_obj):
            base_obj = refresh_base_pose_proxy(source_obj, base_obj, scene)
            props.mc2_base_pose_proxy = base_obj
            return base_obj
        raise
    return base_obj
