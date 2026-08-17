"""Explicit rigid-fracture asset authoring helpers."""

from __future__ import annotations

import hashlib
import json
import math
import random
import uuid

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from ..rigid.schema import RIGID_BODY_RNA_FIELDS
from .geometry_nodes import (
    FRACTURE_METHOD_VORONOI_UNIFORM,
    FRACTURE_PIECE_ID_ATTRIBUTE,
    is_current_fracture_group,
    is_legacy_passthrough_group,
    is_managed_fracture_group,
    modifier_input_values,
    new_fracture_group,
    set_fracture_cutter_object,
    set_modifier_input_values,
)


FRACTURE_SCHEMA_VERSION = 4
DEFAULT_FRACTURE_MODIFIER_NAME = "HoTools Fracture Preview"
_HELPER_COLLECTION_NAME = "HoTools Fracture Helpers"
_CUTTER_OWNER_KEY = "hotools_fracture_cutter_owner"
_PREVIEW_PENDING_OBJECTS: set[str] = set()
_PREVIEW_HANDLER_BUSY = False


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


def _fracture_method(props) -> str:
    return str(
        getattr(props, "fracture_method", FRACTURE_METHOD_VORONOI_UNIFORM)
        or FRACTURE_METHOD_VORONOI_UNIFORM
    )


def _rollback_created_cutter(props, previous_cutter) -> None:
    cutter = getattr(props, "cutter_object", None)
    if cutter is None or cutter == previous_cutter:
        return
    mesh = getattr(cutter, "data", None)
    props.cutter_object = previous_cutter
    bpy.data.objects.remove(cutter, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def switch_fracture_preview_modifier(source, method: str):
    """Switch an existing managed preview to *method*; do not create one implicitly."""
    if source is None or source.type != "MESH":
        raise FractureAssetError("碎块预览只能添加到 Mesh 对象")
    props = source.hotools_rigid_fracture
    modifier = source.modifiers.get(str(props.modifier_name or ""))
    if modifier is None:
        return None
    if modifier.type != "NODES":
        raise FractureAssetError("当前碎块预览修改器不是 Geometry Nodes")
    group = modifier.node_group
    if not (is_managed_fracture_group(group) or is_legacy_passthrough_group(group)):
        raise FractureAssetError("只能切换 HoTools 管理的碎块预览")
    previous_status = str(props.product_status)
    previous_piece_id_attribute = str(props.piece_id_attribute)
    previous_cutter = getattr(props, "cutter_object", None)
    replacement = None
    try:
        if not is_current_fracture_group(group, method):
            old_values = modifier_input_values(modifier) if group is not None else {}
            replacement = new_fracture_group(
                f"{source.name}_FracturePreview_{method}",
                method,
                getattr(props, "cutter_object", None),
            )
            modifier.node_group = replacement
            set_modifier_input_values(modifier, old_values)
            props.product_status = "OUTDATED" if props.product_revision else "EMPTY"
        props.piece_id_attribute = FRACTURE_PIECE_ID_ATTRIBUTE
        rebuild_fracture_preview(source, modifier)
    except Exception as exc:
        if replacement is not None:
            modifier.node_group = group
            if replacement.users == 0:
                bpy.data.node_groups.remove(replacement)
        _rollback_created_cutter(props, previous_cutter)
        props.product_status = previous_status
        props.piece_id_attribute = previous_piece_id_attribute
        if isinstance(exc, FractureAssetError):
            raise
        raise FractureAssetError(str(exc)) from exc
    if replacement is not None and group is not None and group.users == 0:
        bpy.data.node_groups.remove(group)
    return modifier


def ensure_fracture_preview_modifier(source):
    if source is None or source.type != "MESH":
        raise FractureAssetError("碎块预览只能添加到 Mesh 对象")
    props = source.hotools_rigid_fracture
    method = _fracture_method(props)
    current = source.modifiers.get(str(props.modifier_name or ""))
    if current is not None and current.type == "NODES":
        group = current.node_group
        if is_managed_fracture_group(group) or is_legacy_passthrough_group(group):
            return switch_fracture_preview_modifier(source, method)

    previous_modifier_name = str(props.modifier_name)
    previous_piece_id_attribute = str(props.piece_id_attribute)
    previous_status = str(props.product_status)
    previous_cutter = getattr(props, "cutter_object", None)
    modifier = source.modifiers.new(DEFAULT_FRACTURE_MODIFIER_NAME, "NODES")
    group = None
    try:
        group = new_fracture_group(f"{source.name}_FracturePreview_{method}", method)
        modifier.node_group = group
        props.modifier_name = modifier.name
        props.piece_id_attribute = FRACTURE_PIECE_ID_ATTRIBUTE
        props.product_status = "OUTDATED" if props.product_revision else "EMPTY"
        rebuild_fracture_preview(source, modifier)
    except Exception as exc:
        source.modifiers.remove(modifier)
        if group is not None and group.users == 0:
            bpy.data.node_groups.remove(group)
        _rollback_created_cutter(props, previous_cutter)
        props.modifier_name = previous_modifier_name
        props.piece_id_attribute = previous_piece_id_attribute
        props.product_status = previous_status
        if isinstance(exc, FractureAssetError):
            raise
        raise FractureAssetError(str(exc)) from exc
    return modifier


def ensure_default_fracture_modifier(source):
    """Compatibility alias for callers predating fracture-method selection."""
    return ensure_fracture_preview_modifier(source)


def _source_local_bounds(source) -> tuple[Vector, Vector]:
    corners = [Vector(point) for point in source.bound_box]
    if not corners:
        raise FractureAssetError("本体没有可用的局部包围盒")
    minimum = Vector(tuple(min(point[axis] for point in corners) for axis in range(3)))
    maximum = Vector(tuple(max(point[axis] for point in corners) for axis in range(3)))
    if max(maximum - minimum) <= 1.0e-8:
        raise FractureAssetError("本体尺寸过小，无法生成 Voronoi 单元")
    return minimum, maximum


def _uniform_voronoi_seeds(
    minimum: Vector,
    maximum: Vector,
    *,
    density: int,
    seed: int,
    randomness: float,
) -> tuple[list[Vector], tuple[int, int, int], Vector]:
    size = maximum - minimum
    longest = max(float(value) for value in size)
    density = max(2, min(int(density), 30))
    counts = tuple(
        max(1, int(round(density * max(float(size[axis]), 0.0) / longest)))
        for axis in range(3)
    )
    spacing = Vector(tuple(
        float(size[axis]) / counts[axis] if counts[axis] else longest
        for axis in range(3)
    ))
    rng = random.Random(int(seed))
    jitter_amount = max(0.0, min(float(randomness), 1.0)) * 0.42
    seeds = []
    for x in range(counts[0]):
        for y in range(counts[1]):
            for z in range(counts[2]):
                indices = (x, y, z)
                coordinate = []
                for axis in range(3):
                    jitter = rng.uniform(-jitter_amount, jitter_amount)
                    coordinate.append(
                        float(minimum[axis])
                        + (indices[axis] + 0.5 + jitter) * float(spacing[axis])
                    )
                seeds.append(Vector(coordinate))
    return seeds, counts, spacing


def _box_polygons(minimum: Vector, maximum: Vector) -> list[list[Vector]]:
    vertices = [
        Vector((x, y, z))
        for x, y, z in (
            (minimum.x, minimum.y, minimum.z),
            (maximum.x, minimum.y, minimum.z),
            (maximum.x, maximum.y, minimum.z),
            (minimum.x, maximum.y, minimum.z),
            (minimum.x, minimum.y, maximum.z),
            (maximum.x, minimum.y, maximum.z),
            (maximum.x, maximum.y, maximum.z),
            (minimum.x, maximum.y, maximum.z),
        )
    ]
    return [
        [vertices[index] for index in face]
        for face in (
            (0, 3, 2, 1),
            (4, 5, 6, 7),
            (0, 1, 5, 4),
            (1, 2, 6, 5),
            (2, 3, 7, 6),
            (3, 0, 4, 7),
        )
    ]


def _deduplicate_polygon(points: list[Vector], tolerance: float) -> list[Vector]:
    result = []
    for point in points:
        if not result or (point - result[-1]).length > tolerance:
            result.append(point)
    if len(result) > 1 and (result[0] - result[-1]).length <= tolerance:
        result.pop()
    return result


def _clip_convex_polygons(
    polygons: list[list[Vector]],
    *,
    plane_point: Vector,
    plane_normal: Vector,
    tolerance: float,
) -> list[list[Vector]]:
    """Clip a closed convex polyhedron, retaining the negative plane halfspace."""
    clipped = []
    cut_points = []
    for polygon in polygons:
        output = []
        previous = polygon[-1]
        previous_distance = (previous - plane_point).dot(plane_normal)
        previous_inside = previous_distance <= tolerance
        for current in polygon:
            current_distance = (current - plane_point).dot(plane_normal)
            current_inside = current_distance <= tolerance
            if current_inside != previous_inside:
                denominator = previous_distance - current_distance
                if abs(denominator) > tolerance:
                    factor = previous_distance / denominator
                    intersection = previous.lerp(current, factor)
                    output.append(intersection)
                    cut_points.append(intersection)
            if current_inside:
                output.append(current.copy())
            previous = current
            previous_distance = current_distance
            previous_inside = current_inside
        output = _deduplicate_polygon(output, tolerance)
        if len(output) >= 3:
            clipped.append(output)

    unique_cut = []
    for point in cut_points:
        if not any((point - existing).length <= tolerance for existing in unique_cut):
            unique_cut.append(point)
    if len(unique_cut) >= 3:
        center = sum(unique_cut, Vector()) / len(unique_cut)
        reference = Vector((1.0, 0.0, 0.0))
        if abs(plane_normal.x) > 0.9:
            reference = Vector((0.0, 1.0, 0.0))
        axis_u = plane_normal.cross(reference).normalized()
        axis_v = plane_normal.cross(axis_u).normalized()
        unique_cut.sort(key=lambda point: math.atan2(
            (point - center).dot(axis_v),
            (point - center).dot(axis_u),
        ))
        cap = _deduplicate_polygon(unique_cut, tolerance)
        if len(cap) >= 3:
            normal = (cap[1] - cap[0]).cross(cap[2] - cap[0])
            if normal.dot(plane_normal) < 0.0:
                cap.reverse()
            clipped.append(cap)
    return clipped


def _build_voronoi_cutter_geometry(
    source,
    *,
    density: int,
    seed: int,
    randomness: float,
    gap: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]], tuple[int, int, int]]:
    minimum, maximum = _source_local_bounds(source)
    seeds, counts, spacing = _uniform_voronoi_seeds(
        minimum,
        maximum,
        density=density,
        seed=seed,
        randomness=randomness,
    )
    longest = max(float(value) for value in maximum - minimum)
    tolerance = max(longest * 1.0e-8, 1.0e-9)
    positive_spacing = [float(value) for value in spacing if float(value) > tolerance]
    average_cell_size = sum(positive_spacing) / len(positive_spacing)
    world_gap = max(0.0, min(float(gap), 0.25)) * average_cell_size
    margin = max(positive_spacing) * 1.25
    start_minimum = minimum - Vector((margin, margin, margin))
    start_maximum = maximum + Vector((margin, margin, margin))

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for index, center in enumerate(seeds):
        polygons = _box_polygons(start_minimum, start_maximum)
        for other_index, other in enumerate(seeds):
            if other_index == index:
                continue
            delta = other - center
            distance = delta.length
            if distance <= tolerance:
                continue
            normal = delta / distance
            plane_point = (center + other) * 0.5 - normal * (world_gap * 0.5)
            polygons = _clip_convex_polygons(
                polygons,
                plane_point=plane_point,
                plane_normal=normal,
                tolerance=tolerance,
            )
            if not polygons:
                break
        if not polygons:
            continue

        local_vertices = []
        local_lookup = {}
        local_faces = []
        quantization = 1.0 / tolerance
        for polygon in polygons:
            face = []
            for point in polygon:
                key = tuple(int(round(float(value) * quantization)) for value in point)
                vertex_index = local_lookup.get(key)
                if vertex_index is None:
                    vertex_index = len(local_vertices)
                    local_lookup[key] = vertex_index
                    local_vertices.append(tuple(float(value) for value in point))
                face.append(vertex_index)
            if len(set(face)) >= 3:
                local_faces.append(tuple(face))
        if not local_faces:
            continue
        offset = len(vertices)
        vertices.extend(local_vertices)
        faces.extend(tuple(offset + vertex_index for vertex_index in face) for face in local_faces)
    if not faces:
        raise FractureAssetError("Voronoi 切割器没有生成有效单元")
    return vertices, faces, counts


def _helper_collection(scene=None):
    collection = bpy.data.collections.get(_HELPER_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(_HELPER_COLLECTION_NAME)
        collection.hide_render = True
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is not None and collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def _ensure_cutter_object(source):
    props = source.hotools_rigid_fracture
    asset_id = ensure_asset_id(source)
    cutter = getattr(props, "cutter_object", None)
    if cutter is None or cutter.name not in bpy.data.objects:
        mesh = bpy.data.meshes.new(f"{source.name}_VoronoiCutterMesh")
        cutter = bpy.data.objects.new(f"{source.name}_VoronoiCutter", mesh)
        _helper_collection().objects.link(cutter)
        props.cutter_object = cutter
    cutter[_CUTTER_OWNER_KEY] = asset_id
    cutter.display_type = "WIRE"
    cutter.hide_set(True)
    cutter.hide_render = True
    cutter.hide_select = True
    cutter.matrix_world = source.matrix_world
    return cutter


def _preview_signature(source, values: dict) -> str:
    minimum, maximum = _source_local_bounds(source)
    payload = {
        "bounds": [tuple(round(float(value), 8) for value in minimum),
                   tuple(round(float(value), 8) for value in maximum)],
        "matrix_world": [
            round(float(value), 8)
            for row in source.matrix_world
            for value in row
        ],
        "density": int(values.get("碎块密度", 6)),
        "seed": int(values.get("随机种子", 0)),
        "randomness": round(float(values.get("随机度", 0.72)), 8),
        "gap": round(float(values.get("裂缝宽度", 0.045)), 8),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def rebuild_fracture_preview(source, modifier=None, *, force: bool = False):
    """Rebuild closed Voronoi cells and bind them to the managed GN preview."""
    props = source.hotools_rigid_fracture
    modifier = modifier or _target_modifier(source, props)
    if _fracture_method(props) != FRACTURE_METHOD_VORONOI_UNIFORM:
        raise FractureAssetError("当前切割算法没有可用的预览生成器")
    values = modifier_input_values(modifier)
    cutter = _ensure_cutter_object(source)
    signature = _preview_signature(source, values)
    changed = force or str(cutter.get("hotools_preview_signature", "")) != signature
    if changed:
        vertices, faces, counts = _build_voronoi_cutter_geometry(
            source,
            density=int(values.get("碎块密度", 6)),
            seed=int(values.get("随机种子", 0)),
            randomness=float(values.get("随机度", 0.72)),
            gap=float(values.get("裂缝宽度", 0.045)),
        )
        mesh = cutter.data
        mesh.clear_geometry()
        mesh.from_pydata(vertices, [], faces)
        mesh.validate(verbose=False, clean_customdata=False)
        mesh.update(calc_edges=True)
        cutter["hotools_preview_signature"] = signature
        cutter["hotools_voronoi_counts"] = tuple(int(value) for value in counts)
    cutter.matrix_world = source.matrix_world
    set_fracture_cutter_object(modifier.node_group, cutter)
    if changed:
        props.product_status = "OUTDATED" if props.product_revision else "EMPTY"
    return cutter


def _flush_pending_fracture_previews():
    global _PREVIEW_HANDLER_BUSY
    if _PREVIEW_HANDLER_BUSY:
        return 0.05
    names = tuple(_PREVIEW_PENDING_OBJECTS)
    _PREVIEW_PENDING_OBJECTS.clear()
    _PREVIEW_HANDLER_BUSY = True
    try:
        for name in names:
            source = bpy.data.objects.get(name)
            props = getattr(source, "hotools_rigid_fracture", None) if source else None
            if props is None:
                continue
            modifier = source.modifiers.get(str(getattr(props, "modifier_name", "") or ""))
            if modifier is None or modifier.type != "NODES":
                continue
            if not is_current_fracture_group(modifier.node_group, _fracture_method(props)):
                continue
            try:
                rebuild_fracture_preview(source, modifier)
                bpy.context.view_layer.update()
            except Exception as exc:
                props.last_error = str(exc)
    finally:
        _PREVIEW_HANDLER_BUSY = False
    return None


@persistent
def _fracture_preview_depsgraph_update(_scene, depsgraph):
    if _PREVIEW_HANDLER_BUSY:
        return
    for update in depsgraph.updates:
        updated = getattr(update, "id", None)
        source = getattr(updated, "original", updated)
        if source is None or not isinstance(source, bpy.types.Object):
            continue
        props = getattr(source, "hotools_rigid_fracture", None)
        if props is None or not str(getattr(props, "modifier_name", "") or ""):
            continue
        modifier = source.modifiers.get(str(props.modifier_name))
        if modifier is None or modifier.type != "NODES":
            continue
        if not is_current_fracture_group(modifier.node_group, _fracture_method(props)):
            continue
        _PREVIEW_PENDING_OBJECTS.add(source.name_full)
    if _PREVIEW_PENDING_OBJECTS and not bpy.app.timers.is_registered(
        _flush_pending_fracture_previews
    ):
        bpy.app.timers.register(_flush_pending_fracture_previews, first_interval=0.05)


def register_fracture_preview_lifecycle() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _fracture_preview_depsgraph_update not in handlers:
        handlers.append(_fracture_preview_depsgraph_update)


def unregister_fracture_preview_lifecycle() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    if _fracture_preview_depsgraph_update in handlers:
        handlers.remove(_fracture_preview_depsgraph_update)
    _PREVIEW_PENDING_OBJECTS.clear()


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
    if attribute_name != FRACTURE_PIECE_ID_ATTRIBUTE:
        raise FractureAssetError("碎块 ID 属性是 HoTools 内部契约，不能自定义")
    attribute = mesh.attributes.get(FRACTURE_PIECE_ID_ATTRIBUTE)
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


def _mesh_volume(mesh) -> float:
    mesh.calc_loop_triangles()
    signed = 0.0
    for triangle in mesh.loop_triangles:
        a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
        signed += a.dot(b.cross(c)) / 6.0
    return abs(float(signed))


def _object_world_volume(obj) -> float:
    local_volume = _mesh_volume(obj.data)
    scale = abs(float(obj.matrix_world.to_3x3().determinant()))
    volume = local_volume * scale
    if volume > 1.0e-12:
        return volume
    dimensions = tuple(max(abs(float(value)), 0.0) for value in obj.dimensions)
    return dimensions[0] * dimensions[1] * dimensions[2]


def apply_piece_defaults(source, pieces=None) -> int:
    targets = list(pieces) if pieces is not None else managed_pieces(source, current_revision_only=True)
    volumes = {int(obj.as_pointer()): _object_world_volume(obj) for obj in targets}
    total_volume = sum(volumes.values())
    if targets and total_volume <= 1.0e-12:
        raise FractureAssetError("碎块体积为零，无法计算质量")

    source_rigid = source.hotools_rigid_body
    template = _snapshot_rigid_body(source)
    for obj in targets:
        rigid = obj.hotools_rigid_body
        _restore_rigid_body(obj, template)
        rigid.enabled = True
        rigid.shape_type = "BOX"
        dimensions = tuple(max(float(value) * 0.5, 0.001) for value in obj.dimensions)
        rigid.shape_half_extents = dimensions
        volume = volumes.get(int(obj.as_pointer()), _object_world_volume(obj))
        fraction = volume / total_volume
        mass = float(source_rigid.mass) * fraction
        rigid.mass = max(mass, 0.001)
        rigid.start_deactivated = bool(rigid.start_deactivated and rigid.body_type == "DYNAMIC")
        obj.hotools_rigid_fracture_piece.breakable = True
        obj.hotools_rigid_fracture_piece.volume = volume
        obj.hotools_rigid_fracture_piece.mass_fraction = fraction
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
        modifier = _target_modifier(source, props)
        rebuild_fracture_preview(source, modifier)
        bpy.context.view_layer.update()
        collection = ensure_product_collection(source)
        depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
        evaluated_object = source.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_object.to_mesh(
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        components = _union_find_components(evaluated_mesh)
        props.piece_id_attribute = FRACTURE_PIECE_ID_ATTRIBUTE
        _assign_piece_ids(evaluated_mesh, components, FRACTURE_PIECE_ID_ATTRIBUTE)
        payloads = [_component_payload(evaluated_mesh, component) for component in components]
        fingerprint = _fingerprint(payloads)

        old_pieces = managed_pieces(source)
        old_ids = set()
        for old in old_pieces:
            piece_id = str(old.hotools_rigid_fracture_piece.piece_id or "")
            if not piece_id or piece_id in old_ids:
                raise FractureAssetError(f"旧产物存在空或重复 Piece ID: {piece_id!r}")
            old_ids.add(piece_id)

        revision = int(props.product_revision) + 1
        for payload in payloads:
            obj = _new_piece_object(source, payload, asset_id, revision)
            created.append(obj)

        for obj in created:
            collection.objects.link(obj)
        apply_piece_defaults(source, created)
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


def delete_fracture_products(source) -> int:
    """Delete the dedicated product collection and all pieces owned by *source*."""
    if source is None or source.type != "MESH":
        raise FractureAssetError("刚体破碎 Source 必须是 Mesh 对象")
    props = source.hotools_rigid_fracture
    collection = getattr(props, "product_collection", None)
    if collection is None:
        return 0
    owned = managed_pieces(source)
    owned_pointers = {int(obj.as_pointer()) for obj in owned}
    unmanaged = [
        obj.name_full
        for obj in collection.all_objects
        if int(obj.as_pointer()) not in owned_pointers
    ]
    if unmanaged or collection.children:
        details = ", ".join(unmanaged[:3]) if unmanaged else "子集合"
        raise FractureAssetError(f"碎块集合包含非受管内容，不能删除: {details}")
    for obj in owned:
        _remove_object_and_orphan_mesh(obj)
    props.product_collection = None
    bpy.data.collections.remove(collection)
    props.product_revision = 0
    props.product_status = "EMPTY"
    props.product_fingerprint = ""
    props.last_error = ""
    source.hide_set(False)
    source.hide_render = False
    invalidate_physics_runtime()
    return len(owned)


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
    "delete_fracture_products",
    "ensure_asset_id",
    "ensure_default_fracture_modifier",
    "ensure_fracture_preview_modifier",
    "ensure_product_collection",
    "invalidate_physics_runtime",
    "managed_pieces",
    "rebuild_fracture_preview",
    "register_fracture_preview_lifecycle",
    "refresh_fracture_products",
    "select_managed_pieces",
    "set_fracture_visibility",
    "switch_fracture_preview_modifier",
    "unregister_fracture_preview_lifecycle",
    "validate_fracture_manifest",
]
