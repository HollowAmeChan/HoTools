"""简单布料 BasePose 只读对象的公共生命周期。"""

from __future__ import annotations

import bpy
import numpy as np

from ..utils.blender_scene import (
    ensure_scene_collection,
    is_live_blender_id,
    link_object_to_scene_collection,
    resolve_object_scene,
)
from .delta_output import (
    PhysicsDeltaOutputSpec,
    ensure_delta_output as _ensure_delta_output,
)
from .topology_identity import mesh_topology_signature_from_arrays


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


def _is_live_mesh_object(value) -> bool:
    if not is_live_blender_id(value) or not isinstance(value, bpy.types.Object):
        return False
    try:
        return (
            value.type == "MESH"
            and value.data is not None
            and is_live_blender_id(value.data)
        )
    except ReferenceError:
        return False


def _is_generated_cache_object(value) -> bool:
    if not is_live_blender_id(value):
        return False
    try:
        return bool(value.get(CACHE_OBJECT_FLAG, False))
    except ReferenceError:
        return False


def _source_cache_key(source_obj: bpy.types.Object) -> str:
    return (
        f"object:{int(source_obj.as_pointer())}:"
        f"data:{int(source_obj.data.as_pointer())}"
    )


def _generated_source_matches(
    source_obj: bpy.types.Object,
    base_obj: bpy.types.Object,
) -> bool:
    if not _is_generated_cache_object(base_obj):
        return False
    stored = str(base_obj.get(CACHE_SOURCE_KEY, "") or "")
    if stored == _source_cache_key(source_obj):
        return True
    # 旧版本只保存 name + object pointer；首次发现后升级为新身份。
    if stored.endswith(f":{int(source_obj.as_pointer())}"):
        base_obj[CACHE_SOURCE_KEY] = _source_cache_key(source_obj)
        return True
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


def ensure_cache_collection(
    scene: bpy.types.Scene = None,
) -> bpy.types.Collection:
    scene = scene or bpy.context.scene
    collection, _view_layers = ensure_scene_collection(scene, CACHE_COLLECTION_NAME)
    return collection


def move_to_cache_collection(
    obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
) -> None:
    target_scene = resolve_object_scene(obj, scene, purpose="物理缓存对象")
    link_object_to_scene_collection(
        obj,
        target_scene,
        CACHE_COLLECTION_NAME,
        hide_in_viewport=True,
        unlink_other_collections=True,
    )


def ensure_delta_output(obj: bpy.types.Object) -> None:
    """保留旧 MC2 delta 资源的加载兼容；新写回使用 Simple Cloth GN offset。"""
    _ensure_delta_output(obj, MC2_DELTA_SPEC)


def _disable_runtime_flags(obj: bpy.types.Object) -> None:
    """让 BasePose 成为不会再次进入任何 Object 级物理域的只读对象。"""
    switches = (
        ("hotools_mesh_collision", "enabled", False),
        ("hotools_object_collision", "enabled", False),
        ("hotools_rigid_body", "enabled", False),
        ("hotools_rigid_constraint", "enabled", False),
        ("hotools_field", "enabled", False),
    )
    for group_name, property_name, value in switches:
        props = getattr(obj, group_name, None)
        if props is not None and hasattr(props, property_name):
            setattr(props, property_name, value)

    mesh_props = getattr(obj, "hotools_mesh_collision", None)
    if mesh_props is not None:
        mesh_props.mc2_base_pose_proxy = None


_TOPOLOGY_CHANGING_MODIFIER_TYPES = frozenset({
    "ARRAY",
    "BEVEL",
    "BOOLEAN",
    "BUILD",
    "DECIMATE",
    "EDGE_SPLIT",
    "EXPLODE",
    "FLUID",
    "MASK",
    "MIRROR",
    "MULTIRES",
    "OCEAN",
    "PARTICLE_INSTANCE",
    "PARTICLE_SYSTEM",
    "REMESH",
    "SCREW",
    "SKIN",
    "SOLIDIFY",
    "SUBSURF",
    "TRIANGULATE",
    "VOLUME_TO_MESH",
    "WELD",
    "WIREFRAME",
})


def _remove_topology_changing_modifiers(obj: bpy.types.Object) -> None:
    """移除已知会改变拓扑的修改器；Geometry Nodes 保留并交给校验判定。"""
    for modifier in tuple(obj.modifiers):
        if str(modifier.type) in _TOPOLOGY_CHANGING_MODIFIER_TYPES:
            obj.modifiers.remove(modifier)


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

    target_scene = resolve_object_scene(source_obj, scene, purpose="BasePose Source")
    base_obj = source_obj.copy()
    base_obj.data = source_obj.data.copy()
    base_obj.name = f"{source_obj.name}_BasePose"
    base_obj.data.name = f"{source_obj.data.name}_BasePose"
    try:
        link_object_to_scene_collection(
            base_obj,
            target_scene,
            CACHE_COLLECTION_NAME,
            hide_in_viewport=True,
        )
        _remove_topology_changing_modifiers(base_obj)
        _disable_runtime_flags(base_obj)
        base_obj.display_type = "WIRE"
        base_obj.hide_render = True
        base_obj.hide_select = True
        base_obj[CACHE_OBJECT_FLAG] = True
        base_obj[CACHE_SOURCE_KEY] = _source_cache_key(source_obj)
        base_topology_signature = mesh_topology_signature(base_obj)
        if base_topology_signature != source_topology_signature:
            raise ValueError("BasePose只读对象复制后拓扑签名发生变化")
        base_obj[CACHE_TOPOLOGY_SIGNATURE_KEY] = source_topology_signature
        validate_base_pose_proxy(
            source_obj,
            base_obj,
            expected or source_topology_signature,
        )
    except Exception:
        old_mesh = base_obj.data
        bpy.data.objects.remove(base_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        raise
    return base_obj


def find_generated_base_pose_proxy(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
) -> bpy.types.Object | None:
    target_scene = resolve_object_scene(source_obj, scene, purpose="BasePose Source")
    collection = ensure_cache_collection(target_scene)
    source_key = _source_cache_key(source_obj)
    legacy_suffix = f":{int(source_obj.as_pointer())}"
    for candidate in tuple(collection.objects):
        try:
            candidate_key = str(candidate.get(CACHE_SOURCE_KEY, "") or "")
            if (
                bool(candidate.get(CACHE_OBJECT_FLAG, False))
                and (
                    candidate_key == source_key
                    or candidate_key.endswith(legacy_suffix)
                )
            ):
                candidate[CACHE_SOURCE_KEY] = source_key
                return candidate
        except ReferenceError:
            continue
    return None


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
    replacement = create_base_pose_proxy(
        source_obj,
        scene,
        expected_mesh_topology_signature,
    )
    if remove_old and base_obj is not None:
        old_mesh = base_obj.data
        bpy.data.objects.remove(base_obj, do_unlink=True)
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        replacement.name = f"{source_obj.name}_BasePose"
        replacement.data.name = f"{source_obj.data.name}_BasePose"
    return replacement


def ensure_generated_base_pose_proxy(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    expected_mesh_topology_signature: str | None = None,
) -> tuple[bpy.types.Object, bool]:
    target_scene = resolve_object_scene(source_obj, scene, purpose="BasePose Source")
    expected = expected_mesh_topology_signature or mesh_topology_signature(source_obj)
    base_obj = find_generated_base_pose_proxy(source_obj, target_scene)
    created = base_obj is None
    if base_obj is None:
        base_obj = create_base_pose_proxy(source_obj, target_scene, expected)
    else:
        try:
            validate_base_pose_proxy(source_obj, base_obj, expected)
        except (ReferenceError, ValueError):
            base_obj = refresh_base_pose_proxy(
                source_obj,
                base_obj,
                target_scene,
                expected,
            )
            created = True
        link_object_to_scene_collection(
            base_obj,
            target_scene,
            CACHE_COLLECTION_NAME,
            hide_in_viewport=True,
            unlink_other_collections=True,
        )
    return base_obj, created


def initialize_base_pose_proxy_if_missing(
    source_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
) -> tuple[bpy.types.Object, bool]:
    """确保面板 BasePose 引用存在；仅供公共对象准备和兼容调用。"""
    if not _is_live_mesh_object(source_obj):
        raise ValueError("简单布料 source 必须是有效 Mesh 对象")
    props = getattr(source_obj, "hotools_mesh_collision", None)
    if props is None:
        raise ValueError("简单布料属性没有注册到 source 对象")
    try:
        base_obj = getattr(props, "mc2_base_pose_proxy", None)
    except ReferenceError:
        base_obj = None
    if base_obj is not None:
        validate_base_pose_proxy(source_obj, base_obj)
        if _is_generated_cache_object(base_obj):
            target_scene = resolve_object_scene(source_obj, scene, purpose="BasePose Source")
            link_object_to_scene_collection(
                base_obj,
                target_scene,
                CACHE_COLLECTION_NAME,
                hide_in_viewport=True,
                unlink_other_collections=True,
            )
        return base_obj, False
    base_obj, created = ensure_generated_base_pose_proxy(source_obj, scene)
    props.mc2_base_pose_proxy = base_obj
    return base_obj, created


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
    if refresh:
        base_obj = refresh_base_pose_proxy(
            source_obj,
            base_obj,
            scene,
            expected_mesh_topology_signature,
        )
        props.mc2_base_pose_proxy = base_obj
        return base_obj
    if base_obj is None:
        base_obj, _created = ensure_generated_base_pose_proxy(
            source_obj,
            scene,
            expected_mesh_topology_signature,
        )
        props.mc2_base_pose_proxy = base_obj
        return base_obj
    try:
        validate_base_pose_proxy(
            source_obj,
            base_obj,
            expected_mesh_topology_signature,
        )
    except ReferenceError:
        base_obj = refresh_base_pose_proxy(
            source_obj,
            None,
            scene,
            expected_mesh_topology_signature,
        )
        props.mc2_base_pose_proxy = base_obj
    except ValueError:
        if not _is_generated_cache_object(base_obj):
            raise
        base_obj = refresh_base_pose_proxy(
            source_obj,
            base_obj,
            scene,
            expected_mesh_topology_signature,
        )
        props.mc2_base_pose_proxy = base_obj
    if _is_generated_cache_object(base_obj) and not _generated_source_matches(
        source_obj,
        base_obj,
    ):
        base_obj = refresh_base_pose_proxy(
            source_obj,
            base_obj,
            scene,
            expected_mesh_topology_signature,
        )
        props.mc2_base_pose_proxy = base_obj
    if _is_generated_cache_object(base_obj):
        target_scene = resolve_object_scene(source_obj, scene, purpose="BasePose Source")
        link_object_to_scene_collection(
            base_obj,
            target_scene,
            CACHE_COLLECTION_NAME,
            hide_in_viewport=True,
            unlink_other_collections=True,
        )
    return base_obj


__all__ = [
    "CACHE_COLLECTION_NAME",
    "CACHE_OBJECT_FLAG",
    "CACHE_SOURCE_KEY",
    "CACHE_TOPOLOGY_SIGNATURE_KEY",
    "DELTA_ATTRIBUTE_NAME",
    "DELTA_MODIFIER_NAME",
    "DELTA_NODE_GROUP_NAME",
    "MC2_DELTA_SPEC",
    "create_base_pose_proxy",
    "ensure_base_pose_proxy",
    "ensure_cache_collection",
    "ensure_delta_output",
    "ensure_generated_base_pose_proxy",
    "find_generated_base_pose_proxy",
    "initialize_base_pose_proxy_if_missing",
    "mesh_light_key",
    "mesh_topology_signature",
    "mesh_topology_signature_from_arrays",
    "move_to_cache_collection",
    "refresh_base_pose_proxy",
    "validate_base_pose_proxy",
]
