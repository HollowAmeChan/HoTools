"""
MC2 BasePose 只读对象的集中管理模块。

这个文件只处理物理缓存对象的生命周期和轻量校验：
1. 创建/刷新当前物理 Mesh 对应的 BasePose 只读对象。
2. 将自动生成的对象统一归档到场景集合 HoPhysicsCache。
3. 移除复制体上的 MC2 输出 shape key，避免只读输入混入物理写回结果。
4. 检查当前物理对象与 BasePose 对象的顶点数、Loop 数、面数是否一致。

它不负责读取 evaluated mesh、构建 solver state 或执行物理解算；这些仍由
OmniNode/physicsMC2 后端处理。
"""

import bpy


CACHE_COLLECTION_NAME = "HoPhysicsCache"
CACHE_OBJECT_FLAG = "hotools_base_pose_cache"
CACHE_SOURCE_KEY = "hotools_base_pose_source"
DELTA_ATTRIBUTE_NAME = "mc2_delta"
DELTA_MODIFIER_NAME = "MC2 后置位移"
DELTA_NODE_GROUP_NAME = "HoTools_MC2_ApplyDelta"


def mesh_light_key(obj: bpy.types.Object) -> tuple[int, int, int]:
    mesh = getattr(obj, "data", None)
    if obj is None or obj.type != "MESH" or mesh is None:
        return (0, 0, 0)
    return (len(mesh.vertices), len(mesh.loops), len(mesh.polygons))


def validate_base_pose_proxy(source_obj: bpy.types.Object, base_obj: bpy.types.Object) -> None:
    if source_obj is None or source_obj.type != "MESH":
        raise ValueError("当前物理对象必须是Mesh")
    if base_obj is None or base_obj.type != "MESH":
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


def _new_geometry_nodes_group() -> bpy.types.NodeTree:
    group = bpy.data.node_groups.new(DELTA_NODE_GROUP_NAME, "GeometryNodeTree")
    if hasattr(group, "interface"):
        group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        group.inputs.new("NodeSocketGeometry", "Geometry")
        group.outputs.new("NodeSocketGeometry", "Geometry")

    nodes = group.nodes
    links = group.links
    input_node = nodes.new("NodeGroupInput")
    output_node = nodes.new("NodeGroupOutput")
    named_attr = nodes.new("GeometryNodeInputNamedAttribute")
    set_position = nodes.new("GeometryNodeSetPosition")

    input_node.location = (-600, 0)
    named_attr.location = (-600, -180)
    set_position.location = (-260, 0)
    output_node.location = (80, 0)

    named_attr.data_type = "FLOAT_VECTOR"
    if "Name" in named_attr.inputs:
        named_attr.inputs["Name"].default_value = DELTA_ATTRIBUTE_NAME

    links.new(input_node.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(named_attr.outputs["Attribute"], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], output_node.inputs["Geometry"])
    return group


def ensure_delta_node_group() -> bpy.types.NodeTree:
    group = bpy.data.node_groups.get(DELTA_NODE_GROUP_NAME)
    if group is not None and getattr(group, "bl_idname", "") == "GeometryNodeTree":
        return group
    return _new_geometry_nodes_group()


def _move_modifier_to_bottom(obj: bpy.types.Object, modifier) -> None:
    modifiers = obj.modifiers
    index = modifiers.find(modifier.name)
    if index < 0 or index >= len(modifiers) - 1:
        return
    if hasattr(modifiers, "move"):
        modifiers.move(index, len(modifiers) - 1)
        return
    active = bpy.context.view_layer.objects.active
    try:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_move_to_index(modifier=modifier.name, index=len(modifiers) - 1)
    finally:
        bpy.context.view_layer.objects.active = active


def ensure_delta_modifier(obj: bpy.types.Object) -> bpy.types.Modifier:
    if obj is None or obj.type != "MESH":
        raise ValueError("MC2 后置位移只能添加到 Mesh 对象")
    group = ensure_delta_node_group()
    modifier = obj.modifiers.get(DELTA_MODIFIER_NAME)
    if modifier is None:
        modifier = obj.modifiers.new(DELTA_MODIFIER_NAME, "NODES")
    modifier.node_group = group
    # 这个修改器必须位于 Armature/基础变形之后；运行时只写 mc2_delta 顶点属性。
    _move_modifier_to_bottom(obj, modifier)
    return modifier


def ensure_delta_attribute(obj: bpy.types.Object) -> bpy.types.Attribute:
    if obj is None or obj.type != "MESH" or obj.data is None:
        raise ValueError("MC2 后置位移属性只能写入 Mesh 对象")
    mesh = obj.data
    attr = mesh.attributes.get(DELTA_ATTRIBUTE_NAME)
    if attr is not None and (attr.domain != "POINT" or attr.data_type != "FLOAT_VECTOR"):
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(DELTA_ATTRIBUTE_NAME, "FLOAT_VECTOR", "POINT")
    return attr


def ensure_delta_output(obj: bpy.types.Object) -> None:
    ensure_delta_attribute(obj)
    ensure_delta_modifier(obj)


def _remove_shape_key(obj: bpy.types.Object, shape_key_name: str) -> None:
    if not shape_key_name or obj.data.shape_keys is None:
        return
    key = obj.data.shape_keys.key_blocks.get(shape_key_name)
    if key is None or key == obj.data.shape_keys.reference_key:
        return
    obj.shape_key_remove(key)


def _remove_delta_output(obj: bpy.types.Object) -> None:
    modifier = obj.modifiers.get(DELTA_MODIFIER_NAME)
    if modifier is not None:
        obj.modifiers.remove(modifier)
    if obj.data is not None:
        attr = obj.data.attributes.get(DELTA_ATTRIBUTE_NAME)
        if attr is not None:
            obj.data.attributes.remove(attr)


def _disable_runtime_flags(obj: bpy.types.Object) -> None:
    props = getattr(obj, "hotools_mesh_collision", None)
    if props is None:
        return
    props.enabled = False
    props.mc2_base_pose_proxy = None


def create_base_pose_proxy(
    source_obj: bpy.types.Object,
    shape_key_name: str,
    scene: bpy.types.Scene = None,
) -> bpy.types.Object:
    if source_obj is None or source_obj.type != "MESH":
        raise ValueError("当前物理对象必须是Mesh")

    base_obj = source_obj.copy()
    base_obj.data = source_obj.data.copy()
    base_obj.name = f"{source_obj.name}_BasePose"
    base_obj.data.name = f"{source_obj.data.name}_BasePose"
    try:
        ensure_cache_collection(scene).objects.link(base_obj)
        _remove_shape_key(base_obj, shape_key_name)
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
    shape_key_name: str,
    scene: bpy.types.Scene = None,
) -> bpy.types.Object:
    if base_obj is not None and base_obj != source_obj and base_obj.type == "MESH":
        remove_old = bool(base_obj.get(CACHE_OBJECT_FLAG, False))
    else:
        remove_old = False

    if remove_old and base_obj is not None:
        old_mesh = base_obj.data
        bpy.data.objects.remove(base_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

    return create_base_pose_proxy(source_obj, shape_key_name, scene)


def ensure_base_pose_proxy(
    source_obj: bpy.types.Object,
    shape_key_name: str,
    scene: bpy.types.Scene = None,
    refresh: bool = False,
) -> bpy.types.Object:
    props = getattr(source_obj, "hotools_mesh_collision", None)
    if props is None:
        raise ValueError("当前物体没有HoTools网格碰撞属性")

    base_obj = getattr(props, "mc2_base_pose_proxy", None)
    if refresh or base_obj is None:
        base_obj = refresh_base_pose_proxy(source_obj, base_obj, shape_key_name, scene)
        props.mc2_base_pose_proxy = base_obj
        return base_obj

    validate_base_pose_proxy(source_obj, base_obj)
    return base_obj
