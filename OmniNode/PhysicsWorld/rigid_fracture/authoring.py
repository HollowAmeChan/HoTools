"""Explicit rigid-fracture asset authoring helpers."""

from __future__ import annotations

import hashlib
import json
import uuid

import bpy
from mathutils import Matrix, Vector

from ..rigid.schema import RIGID_BODY_RNA_FIELDS


FRACTURE_SCHEMA_VERSION = 1
DEFAULT_FRACTURE_MODIFIER_NAME = "HoTools Rigid Fracture"


class FractureAssetError(RuntimeError):
    pass


def ensure_asset_id(source) -> str:
    props = getattr(source, "hotools_rigid_fracture", None)
    if props is None:
        raise FractureAssetError("对象缺少刚体破碎属性")
    asset_id = str(getattr(props, "asset_id", "") or "").strip()
    if not asset_id:
        asset_id = str(uuid.uuid4())
        props.asset_id = asset_id
    props.schema_version = FRACTURE_SCHEMA_VERSION
    return asset_id


def ensure_product_collection(source, scene=None):
    props = getattr(source, "hotools_rigid_fracture", None)
    if props is None:
        raise FractureAssetError("对象缺少刚体破碎属性")
    collection = getattr(props, "product_collection", None)
    if collection is None:
        collection = bpy.data.collections.new(f"{source.name}_FracturePieces")
        props.product_collection = collection
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is not None and collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def ensure_default_fracture_modifier(source):
    if source is None or source.type != "MESH":
        raise FractureAssetError("默认破碎 GN 只能添加到 Mesh 对象")
    props = source.hotools_rigid_fracture
    current = source.modifiers.get(str(props.modifier_name or ""))
    if current is not None and current.type == "NODES":
        return current

    group = bpy.data.node_groups.new(
        f"{source.name}_RigidFracture",
        "GeometryNodeTree",
    )
    group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    input_node = group.nodes.new("NodeGroupInput")
    output_node = group.nodes.new("NodeGroupOutput")
    input_node.location = (-180.0, 0.0)
    output_node.location = (180.0, 0.0)
    group.links.new(input_node.outputs["Geometry"], output_node.inputs["Geometry"])

    modifier = source.modifiers.new(DEFAULT_FRACTURE_MODIFIER_NAME, "NODES")
    modifier.node_group = group
    props.modifier_name = modifier.name
    props.product_status = "OUTDATED" if props.product_revision else "EMPTY"
    return modifier


def managed_pieces(source, *, current_revision_only: bool = False) -> list:
    props = getattr(source, "hotools_rigid_fracture", None)
    collection = getattr(props, "product_collection", None) if props is not None else None
    asset_id = str(getattr(props, "asset_id", "") or "") if props is not None else ""
    if collection is None or not asset_id:
        return []
    result = []
    for obj in collection.all_objects:
        piece = getattr(obj, "hotools_rigid_fracture_piece", None)
        if piece is None or not bool(getattr(piece, "managed", False)):
            continue
        if str(getattr(piece, "owner_asset_id", "") or "") != asset_id:
            continue
        if current_revision_only and int(getattr(piece, "product_revision", -1)) != int(props.product_revision):
            continue
        result.append(obj)
    result.sort(key=lambda obj: (
        str(getattr(obj.hotools_rigid_fracture_piece, "piece_id", "") or ""),
        obj.name_full,
    ))
    return result


def validate_fracture_manifest(source) -> tuple:
    props = getattr(source, "hotools_rigid_fracture", None)
    if props is None or not bool(getattr(props, "enabled", False)):
        return ()
    asset_id = str(getattr(props, "asset_id", "") or "").strip()
    if not asset_id:
        raise FractureAssetError(f"{source.name_full}: 破碎资产缺少 asset_id，请刷新产物")
    if str(getattr(props, "product_status", "EMPTY")) != "READY":
        raise FractureAssetError(f"{source.name_full}: 破碎产物尚未 READY，请刷新产物")
    collection = getattr(props, "product_collection", None)
    if collection is None:
        raise FractureAssetError(f"{source.name_full}: 未链接碎块产物集合")

    revision = int(getattr(props, "product_revision", 0))
    pieces = managed_pieces(source, current_revision_only=True)
    if not pieces:
        raise FractureAssetError(f"{source.name_full}: 当前版本没有受管碎块")

    seen_ids = set()
    for obj in pieces:
        piece = obj.hotools_rigid_fracture_piece
        piece_id = str(piece.piece_id or "").strip()
        if obj.type != "MESH":
            raise FractureAssetError(f"{obj.name_full}: 受管碎块必须是 Mesh")
        if not piece_id or piece_id in seen_ids:
            raise FractureAssetError(f"{source.name_full}: 碎块 ID 为空或重复: {piece_id!r}")
        seen_ids.add(piece_id)
    return tuple(pieces)


def _target_modifier(source, props):
    name = str(getattr(props, "modifier_name", "") or "").strip()
    modifier = source.modifiers.get(name) if name else None
    if modifier is None or modifier.type != "NODES" or modifier.node_group is None:
        raise FractureAssetError("请选择有效的 Geometry Nodes 修改器")
    enabled_modifiers = [item for item in source.modifiers if bool(getattr(item, "show_viewport", True))]
    if enabled_modifiers and enabled_modifiers[-1] != modifier:
        raise FractureAssetError("第一版要求破碎 Geometry Nodes 是最后一个启用的修改器")
    return modifier


def _union_find_components(mesh) -> list[dict]:
    vertex_count = len(mesh.vertices)
    parent = list(range(vertex_count))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edge in mesh.edges:
        union(int(edge.vertices[0]), int(edge.vertices[1]))
    for polygon in mesh.polygons:
        vertices = tuple(int(index) for index in polygon.vertices)
        for index in vertices[1:]:
            union(vertices[0], index)

    by_root: dict[int, list[int]] = {}
    for polygon in mesh.polygons:
        vertices = tuple(int(index) for index in polygon.vertices)
        if vertices:
            by_root.setdefault(find(vertices[0]), []).append(int(polygon.index))
    if not by_root:
        raise FractureAssetError("evaluated mesh 没有可拆分的面")

    components = []
    for polygon_indices in by_root.values():
        used = sorted({
            int(vertex_index)
            for polygon_index in polygon_indices
            for vertex_index in mesh.polygons[polygon_index].vertices
        })
        centroid = sum((mesh.vertices[index].co for index in used), Vector()) / len(used)
        components.append({
            "polygon_indices": tuple(polygon_indices),
            "vertex_indices": tuple(used),
            "centroid": tuple(float(value) for value in centroid),
        })
    components.sort(key=lambda item: tuple(round(value, 7) for value in item["centroid"]))
    return components


def _assign_piece_ids(mesh, components, attribute_name: str) -> None:
    attribute = mesh.attributes.get(attribute_name) if attribute_name else None
    use_attribute = bool(
        attribute is not None
        and str(getattr(attribute, "domain", "")) == "FACE"
        and str(getattr(attribute, "data_type", "")) == "INT"
    )
    used_ids = set()
    for index, component in enumerate(components):
        if use_attribute:
            values = {
                int(attribute.data[polygon_index].value)
                for polygon_index in component["polygon_indices"]
            }
            if len(values) != 1:
                raise FractureAssetError("同一连通块内的碎块 ID 属性不一致")
            piece_id = str(next(iter(values)))
        else:
            piece_id = f"component:{index:06d}"
        if piece_id in used_ids:
            raise FractureAssetError(f"碎块 ID 重复: {piece_id}")
        used_ids.add(piece_id)
        component["piece_id"] = piece_id


def _component_payload(mesh, component) -> dict:
    old_to_new = {old: new for new, old in enumerate(component["vertex_indices"])}
    coordinates = [mesh.vertices[index].co.copy() for index in component["vertex_indices"]]
    minimum = Vector((min(value[axis] for value in coordinates) for axis in range(3)))
    maximum = Vector((max(value[axis] for value in coordinates) for axis in range(3)))
    center = (minimum + maximum) * 0.5
    vertices = [tuple(float(value) for value in coordinate - center) for coordinate in coordinates]
    faces = []
    material_indices = []
    for polygon_index in component["polygon_indices"]:
        polygon = mesh.polygons[polygon_index]
        faces.append(tuple(old_to_new[int(index)] for index in polygon.vertices))
        material_indices.append(int(polygon.material_index))
    half_extents = tuple(max(float((maximum - minimum)[axis]) * 0.5, 0.001) for axis in range(3))
    return {
        "piece_id": component["piece_id"],
        "center": center,
        "vertices": vertices,
        "faces": faces,
        "material_indices": material_indices,
        "half_extents": half_extents,
    }


def _fingerprint(payloads) -> str:
    canonical = [
        {
            "piece_id": item["piece_id"],
            "vertices": [[round(value, 7) for value in vertex] for vertex in item["vertices"]],
            "faces": item["faces"],
        }
        for item in payloads
    ]
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_rigid_body(obj) -> dict:
    rigid = getattr(obj, "hotools_rigid_body", None)
    if rigid is None:
        return {}
    snapshot = {}
    for field in RIGID_BODY_RNA_FIELDS:
        name = str(field["name"])
        value = getattr(rigid, name)
        if hasattr(value, "to_tuple"):
            value = tuple(value)
        snapshot[name] = value
    return snapshot


def _restore_rigid_body(obj, snapshot: dict) -> None:
    rigid = obj.hotools_rigid_body
    for name, value in snapshot.items():
        setattr(rigid, name, value)


def apply_piece_defaults(source, pieces=None) -> int:
    props = source.hotools_rigid_fracture
    targets = list(pieces) if pieces is not None else managed_pieces(source, current_revision_only=True)
    for obj in targets:
        rigid = obj.hotools_rigid_body
        rigid.enabled = True
        rigid.body_type = props.piece_body_type
        rigid.mass = props.piece_mass
        rigid.friction = props.piece_friction
        rigid.restitution = props.piece_restitution
        rigid.shape_type = "BOX"
        dimensions = tuple(max(float(value) * 0.5, 0.001) for value in obj.dimensions)
        rigid.shape_half_extents = dimensions
        rigid.start_deactivated = bool(props.piece_start_deactivated and props.piece_body_type == "DYNAMIC")
        obj.hotools_rigid_fracture_piece.breakable = bool(props.piece_breakable)
    return len(targets)


def _new_piece_object(source, payload, asset_id: str, revision: int):
    safe_id = str(payload["piece_id"]).replace("/", "_").replace("\\", "_")
    mesh = bpy.data.meshes.new(f"{source.name}_piece_{safe_id}_Mesh")
    mesh.from_pydata(payload["vertices"], [], payload["faces"])
    mesh.update(calc_edges=True)
    for material in source.data.materials:
        mesh.materials.append(material)
    for polygon, material_index in zip(mesh.polygons, payload["material_indices"]):
        polygon.material_index = min(material_index, max(len(mesh.materials) - 1, 0))

    obj = bpy.data.objects.new(f"{source.name}_piece_{safe_id}", mesh)
    obj.matrix_world = source.matrix_world @ Matrix.Translation(payload["center"])
    piece = obj.hotools_rigid_fracture_piece
    piece.managed = True
    piece.owner_asset_id = asset_id
    piece.piece_id = str(payload["piece_id"])
    piece.product_revision = revision
    return obj


def _remove_object_and_orphan_mesh(obj) -> None:
    mesh = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and getattr(mesh, "users", 1) == 0:
        bpy.data.meshes.remove(mesh)


def invalidate_physics_runtime() -> None:
    try:
        from ... import OmniRuntimeState

        OmniRuntimeState.clear_all()
    except Exception:
        pass


def refresh_fracture_products(source, *, depsgraph=None) -> tuple:
    if source is None or source.type != "MESH":
        raise FractureAssetError("刚体破碎 Source 必须是 Mesh 对象")
    if str(getattr(source, "mode", "OBJECT")) != "OBJECT":
        raise FractureAssetError("刷新碎块前请切回 Object Mode")

    props = source.hotools_rigid_fracture
    previous_status = str(props.product_status)
    created = []
    evaluated_mesh = None
    evaluated_object = None
    try:
        asset_id = ensure_asset_id(source)
        _target_modifier(source, props)
        collection = ensure_product_collection(source)
        depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
        evaluated_object = source.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_object.to_mesh(
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        components = _union_find_components(evaluated_mesh)
        _assign_piece_ids(evaluated_mesh, components, str(props.piece_id_attribute or ""))
        payloads = [_component_payload(evaluated_mesh, component) for component in components]
        fingerprint = _fingerprint(payloads)

        old_pieces = managed_pieces(source)
        old_by_id = {}
        for old in old_pieces:
            piece_id = str(old.hotools_rigid_fracture_piece.piece_id or "")
            if not piece_id or piece_id in old_by_id:
                raise FractureAssetError(f"旧产物存在空或重复 Piece ID: {piece_id!r}")
            old_by_id[piece_id] = (
                _snapshot_rigid_body(old),
                bool(old.hotools_rigid_fracture_piece.breakable),
            )

        revision = int(props.product_revision) + 1
        for payload in payloads:
            obj = _new_piece_object(source, payload, asset_id, revision)
            created.append(obj)
            apply_piece_defaults(source, (obj,))
            preserved = old_by_id.get(str(payload["piece_id"]))
            if preserved is not None:
                _restore_rigid_body(obj, preserved[0])
                obj.hotools_rigid_fracture_piece.breakable = preserved[1]

        for obj in created:
            collection.objects.link(obj)
        for old in old_pieces:
            _remove_object_and_orphan_mesh(old)

        props.product_revision = revision
        props.product_fingerprint = fingerprint
        props.product_status = "READY"
        props.last_error = ""
        invalidate_physics_runtime()
        return tuple(created)
    except Exception as exc:
        for obj in list(created):
            if obj.name in bpy.data.objects:
                _remove_object_and_orphan_mesh(obj)
        props.last_error = str(exc)
        if previous_status != "READY":
            props.product_status = "ERROR"
        if isinstance(exc, FractureAssetError):
            raise
        raise FractureAssetError(str(exc)) from exc
    finally:
        if evaluated_object is not None and evaluated_mesh is not None:
            evaluated_object.to_mesh_clear()


def set_fracture_visibility(source, mode: str) -> int:
    mode = str(mode or "BOTH")
    if mode not in {"SOURCE", "PIECES", "BOTH"}:
        raise FractureAssetError(f"未知显示模式: {mode}")
    source_hidden = mode == "PIECES"
    pieces_hidden = mode == "SOURCE"
    source.hide_set(source_hidden)
    source.hide_render = source_hidden
    pieces = managed_pieces(source)
    for obj in pieces:
        obj.hide_set(pieces_hidden)
        obj.hide_render = pieces_hidden
    return len(pieces)


def select_managed_pieces(source) -> int:
    pieces = managed_pieces(source, current_revision_only=True)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in pieces:
        obj.hide_set(False)
        obj.select_set(True)
    if pieces:
        bpy.context.view_layer.objects.active = pieces[0]
    return len(pieces)


__all__ = [
    "DEFAULT_FRACTURE_MODIFIER_NAME",
    "FRACTURE_SCHEMA_VERSION",
    "FractureAssetError",
    "apply_piece_defaults",
    "ensure_asset_id",
    "ensure_default_fracture_modifier",
    "ensure_product_collection",
    "invalidate_physics_runtime",
    "managed_pieces",
    "refresh_fracture_products",
    "select_managed_pieces",
    "set_fracture_visibility",
    "validate_fracture_manifest",
]
