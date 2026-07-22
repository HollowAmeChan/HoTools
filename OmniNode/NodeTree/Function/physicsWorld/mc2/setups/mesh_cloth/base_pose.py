"""
MC2 MeshCloth BasePose 只读对象的集中管理模块。

这个文件只处理物理缓存对象的生命周期和轻量校验：
1. 创建/刷新当前物理 Mesh 对应的 BasePose 只读对象。
2. 将自动生成的对象统一归档到场景集合 HoPhysicsCache。
3. 移除复制体上的共享 Physics World GN 输出，避免新生态写回反馈。
4. 创建时冻结 Mesh 顶点身份/拓扑签名；逐帧只做常数时间 token 与轻量计数校验。

它不负责读取 evaluated mesh、构建 solver state 或执行物理解算；N3 读取由同目录
frame_input.py 负责，其余步骤由新 physicsWorld.mc2 slot/native 路径负责。
"""

import bpy
import numpy as np

from ...mesh_topology_identity import mesh_topology_signature_from_arrays
from ....gn_offset import remove_gn_offset_output
from .delta_output import PhysicsDeltaOutputSpec
from .delta_output import ensure_delta_output as _ensure_delta_output
from .delta_output import remove_delta_output as _remove_delta_output_by_spec


CACHE_COLLECTION_NAME = "HoPhysicsCache"
CACHE_OBJECT_FLAG = "hotools_base_pose_cache"
CACHE_SOURCE_KEY = "hotools_base_pose_source"
CACHE_TOPOLOGY_SIGNATURE_KEY = "hotools_base_pose_topology_signature"
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


def mesh_topology_signature(obj: bpy.types.Object) -> str:
    if not _is_live_mesh_object(obj):
        raise ValueError("拓扑签名目标必须是Mesh")
    mesh = obj.data
    mesh.calc_loop_triangles()
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    polygon_loop_totals = np.empty(len(mesh.polygons), dtype=np.int32)
    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.edges.foreach_get("vertices", edges)
    mesh.polygons.foreach_get("loop_total", polygon_loop_totals)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    mesh.loop_triangles.foreach_get("vertices", triangles)
    return mesh_topology_signature_from_arrays(
        len(mesh.vertices),
        edges,
        polygon_loop_totals,
        loop_vertices,
        triangles,
    )


def validate_base_pose_proxy(
    source_obj: bpy.types.Object,
    base_obj: bpy.types.Object,
    expected_mesh_topology_signature: str | None = None,
) -> None:
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
    expected = str(expected_mesh_topology_signature or "")
    if expected:
        stored = str(base_obj.get(CACHE_TOPOLOGY_SIGNATURE_KEY, "") or "")
        if stored != expected:
            actual = mesh_topology_signature(base_obj)
            if actual != expected:
                raise ValueError("BasePose只读对象的Mesh拓扑签名与预期不一致")
            base_obj[CACHE_TOPOLOGY_SIGNATURE_KEY] = expected


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


def ensure_delta_output(obj: bpy.types.Object) -> None:
    _ensure_delta_output(obj, MC2_DELTA_SPEC)


def _remove_delta_output(obj: bpy.types.Object) -> None:
    _remove_delta_output_by_spec(obj, MC2_DELTA_SPEC)
    remove_gn_offset_output(obj)


def _disable_runtime_flags(obj: bpy.types.Object) -> None:
    props = getattr(obj, "hotools_mesh_collision", None)
    if props is None:
        return
    props.enabled = False
    props.mc2_base_pose_proxy = None


def create_base_pose_proxy(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    expected_mesh_topology_signature: str | None = None,
) -> bpy.types.Object:
    if not _is_live_mesh_object(source_obj):
        raise ValueError("当前物理对象必须是Mesh")

    source_topology_signature = mesh_topology_signature(source_obj)
    expected = str(expected_mesh_topology_signature or "")
    if expected and source_topology_signature != expected:
        raise ValueError("当前Mesh拓扑签名与预期不一致")

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
        base_topology_signature = mesh_topology_signature(base_obj)
        if base_topology_signature != source_topology_signature:
            raise ValueError("BasePose只读对象复制后拓扑签名发生变化")
        base_obj[CACHE_TOPOLOGY_SIGNATURE_KEY] = source_topology_signature
        validate_base_pose_proxy(source_obj, base_obj, expected or source_topology_signature)
    except Exception:
        old_mesh = base_obj.data
        bpy.data.objects.remove(base_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        raise
    return base_obj


def initialize_base_pose_proxy_if_missing(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
) -> tuple[bpy.types.Object, bool]:
    """Create the generated BasePose once; existing assignments are untouched."""
    if not _is_live_mesh_object(source_obj):
        raise ValueError("MC2 MeshCloth source must be a live Mesh object")
    props = getattr(source_obj, "hotools_mesh_collision", None)
    if props is None:
        raise ValueError("MC2 MeshCloth properties are not registered on the source object")
    try:
        base_obj = getattr(props, "mc2_base_pose_proxy", None)
    except ReferenceError:
        base_obj = None
    if base_obj is not None:
        return base_obj, False

    base_obj = create_base_pose_proxy(source_obj, scene)
    props.mc2_base_pose_proxy = base_obj
    return base_obj, True

def refresh_base_pose_proxy(
    source_obj: bpy.types.Object,
    base_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    expected_mesh_topology_signature: str | None = None,
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

    return create_base_pose_proxy(source_obj, scene, expected_mesh_topology_signature)


def ensure_base_pose_proxy(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    refresh: bool = False,
    expected_mesh_topology_signature: str | None = None,
) -> bpy.types.Object:
    props = getattr(source_obj, "hotools_mesh_collision", None)
    if props is None:
        raise ValueError("当前物体没有HoTools简单布料属性")

    try:
        base_obj = getattr(props, "mc2_base_pose_proxy", None)
    except ReferenceError:
        base_obj = None
    if refresh or base_obj is None:
        base_obj = refresh_base_pose_proxy(
            source_obj,
            base_obj,
            scene,
            expected_mesh_topology_signature,
        )
        props.mc2_base_pose_proxy = base_obj
        return base_obj

    try:
        validate_base_pose_proxy(source_obj, base_obj, expected_mesh_topology_signature)
    except ReferenceError:
        base_obj = refresh_base_pose_proxy(
            source_obj,
            None,
            scene,
            expected_mesh_topology_signature,
        )
        props.mc2_base_pose_proxy = base_obj
        return base_obj
    except ValueError:
        if _is_generated_cache_object(base_obj):
            base_obj = refresh_base_pose_proxy(
                source_obj,
                base_obj,
                scene,
                expected_mesh_topology_signature,
            )
            props.mc2_base_pose_proxy = base_obj
            return base_obj
        raise
    return base_obj
