import json
import os
import traceback
from collections import Counter

import bpy
import mathutils
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper

try:
    from . import material_node_ir
except Exception:
    material_node_ir = None


SCHEMA = "hotools.object_scene_ir.v1"
SCENE_BUNDLE_SCHEMA = "hotools.scene_asset_ir.v1"


def _safe_value(value, depth=0):
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, set):
        return sorted(_safe_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return {str(key): _safe_value(val, depth + 1) for key, val in value.items()}
    if hasattr(value, "to_tuple"):
        try:
            return list(value.to_tuple())
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in value]
    try:
        return [_safe_value(item, depth + 1) for item in value]
    except Exception:
        return str(value)


def _app_metadata():
    fields = {
        "binary_path": _safe_value(getattr(bpy.app, "binary_path", "")),
        "version_string": _safe_value(getattr(bpy.app, "version_string", "")),
        "build_branch": _safe_value(getattr(bpy.app, "build_branch", "")),
        "build_hash": _safe_value(getattr(bpy.app, "build_hash", "")),
        "build_commit_date": _safe_value(getattr(bpy.app, "build_commit_date", "")),
        "build_commit_time": _safe_value(getattr(bpy.app, "build_commit_time", "")),
        "build_platform": _safe_value(getattr(bpy.app, "build_platform", "")),
        "build_type": _safe_value(getattr(bpy.app, "build_type", "")),
    }
    fields["binary_dir"] = os.path.dirname(fields["binary_path"]) if fields["binary_path"] else ""
    fields["executable_name"] = os.path.basename(fields["binary_path"]) if fields["binary_path"] else ""
    text = " ".join(str(value) for value in fields.values()).lower()
    fields["source_flavor_hint"] = "goo" if "goo" in text else "blender"
    return fields


def _serialize_rna_properties(rna_obj, skip=()):
    result = {}
    skip_ids = {
        "rna_type",
        "name",
        "type",
        "id_data",
        "error_location",
        "execution_time",
    }
    skip_ids.update(skip)

    rna = getattr(rna_obj, "bl_rna", None)
    if rna is None:
        return result

    for prop in rna.properties:
        identifier = prop.identifier
        if identifier in skip_ids or prop.type in {"POINTER", "COLLECTION"}:
            continue
        try:
            result[identifier] = _safe_value(getattr(rna_obj, identifier))
        except Exception:
            continue
    return result


def _datablock_ref(data):
    if data is None:
        return None
    return {
        "name": getattr(data, "name", None),
        "library": getattr(getattr(data, "library", None), "filepath", None),
        "users": getattr(data, "users", None),
    }


def _custom_properties(id_obj):
    result = {}
    if id_obj is None or not hasattr(id_obj, "keys"):
        return result
    for key in id_obj.keys():
        if key == "_RNA_UI":
            continue
        try:
            result[str(key)] = _safe_value(id_obj[key])
        except Exception:
            continue
    return result


def _object_collection_names(obj):
    return [collection.name for collection in getattr(obj, "users_collection", [])]


def _world_bounds(obj):
    try:
        corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    except Exception:
        return None
    mins = [min(corner[i] for corner in corners) for i in range(3)]
    maxs = [max(corner[i] for corner in corners) for i in range(3)]
    return {"min": _safe_value(mins), "max": _safe_value(maxs)}


def _material_slots(obj):
    slots = []
    for index, slot in enumerate(getattr(obj, "material_slots", [])):
        material = getattr(slot, "material", None)
        slots.append(
            {
                "index": index,
                "slot_name": getattr(slot, "name", ""),
                "link": getattr(slot, "link", None),
                "material": None
                if material is None
                else {
                    "name": material.name,
                    "library": material.library.filepath if material.library else None,
                    "use_nodes": bool(getattr(material, "use_nodes", False)),
                    "node_tree": getattr(getattr(material, "node_tree", None), "name", None),
                    "surface_render_method": getattr(material, "surface_render_method", None),
                    "blend_method": getattr(material, "blend_method", None),
                    "alpha_threshold": getattr(material, "alpha_threshold", None),
                },
            }
        )
    return slots


def _modifier_summary(modifier):
    data = {
        "name": modifier.name,
        "type": modifier.type,
        "show_viewport": bool(getattr(modifier, "show_viewport", False)),
        "show_render": bool(getattr(modifier, "show_render", False)),
        "show_in_editmode": bool(getattr(modifier, "show_in_editmode", False)),
        "properties": _serialize_rna_properties(modifier),
        "custom_properties": _custom_properties(modifier),
    }
    node_group = getattr(modifier, "node_group", None)
    if node_group is not None:
        data["node_group"] = {
            "name": node_group.name,
            "bl_idname": getattr(node_group, "bl_idname", None),
            "interface_count": len(getattr(getattr(node_group, "interface", None), "items_tree", [])),
        }
    return data


def _uv_bounds(layer):
    data = getattr(layer, "data", [])
    if not data:
        return None
    min_u = min_v = float("inf")
    max_u = max_v = float("-inf")
    for item in data:
        uv = getattr(item, "uv", None)
        if uv is None:
            continue
        min_u = min(min_u, uv[0])
        min_v = min(min_v, uv[1])
        max_u = max(max_u, uv[0])
        max_v = max(max_v, uv[1])
    if min_u == float("inf"):
        return None
    return {"min": [min_u, min_v], "max": [max_u, max_v]}


def _mesh_uv_layers(mesh):
    active = getattr(getattr(mesh, "uv_layers", None), "active", None)
    active_render = getattr(getattr(mesh, "uv_layers", None), "active_render", None)
    layers = []
    for index, layer in enumerate(getattr(mesh, "uv_layers", [])):
        layers.append(
            {
                "index": index,
                "name": layer.name,
                "active": layer == active,
                "active_render": layer == active_render,
                "data_count": len(getattr(layer, "data", [])),
                "bounds": _safe_value(_uv_bounds(layer)),
            }
        )
    return layers


def _mesh_color_attributes(mesh):
    active = getattr(getattr(mesh, "color_attributes", None), "active_color", None)
    render = getattr(getattr(mesh, "color_attributes", None), "render_color_index", -1)
    records = []
    for index, attr in enumerate(getattr(mesh, "color_attributes", [])):
        records.append(
            {
                "index": index,
                "name": attr.name,
                "domain": getattr(attr, "domain", None),
                "data_type": getattr(attr, "data_type", None),
                "data_count": len(getattr(attr, "data", [])),
                "active": attr == active,
                "active_render": index == render,
            }
        )
    return records


def _mesh_attributes(mesh):
    records = []
    for index, attr in enumerate(getattr(mesh, "attributes", [])):
        records.append(
            {
                "index": index,
                "name": attr.name,
                "domain": getattr(attr, "domain", None),
                "data_type": getattr(attr, "data_type", None),
                "data_count": len(getattr(attr, "data", [])),
                "is_internal": str(attr.name).startswith("."),
            }
        )
    return records


def _vertex_group_usage(obj):
    groups = {group.index: {"index": group.index, "name": group.name, "vertex_count": 0} for group in obj.vertex_groups}
    mesh = obj.data if getattr(obj, "type", None) == "MESH" else None
    if mesh is not None:
        for vertex in mesh.vertices:
            for assignment in vertex.groups:
                record = groups.get(assignment.group)
                if record is not None:
                    record["vertex_count"] += 1
    return sorted(groups.values(), key=lambda item: item["index"])


def _shape_keys(mesh):
    shape_keys = getattr(mesh, "shape_keys", None)
    if shape_keys is None:
        return {"count": 0, "keys": []}
    keys = []
    for index, key in enumerate(shape_keys.key_blocks):
        keys.append(
            {
                "index": index,
                "name": key.name,
                "value": getattr(key, "value", None),
                "mute": bool(getattr(key, "mute", False)),
                "relative_key": getattr(getattr(key, "relative_key", None), "name", None),
                "slider_min": getattr(key, "slider_min", None),
                "slider_max": getattr(key, "slider_max", None),
                "vertex_group": getattr(key, "vertex_group", ""),
                "interpolation": getattr(key, "interpolation", None),
            }
        )
    return {
        "name": shape_keys.name,
        "count": len(keys),
        "use_relative": bool(getattr(shape_keys, "use_relative", True)),
        "keys": keys,
    }


def _mesh_stats(obj, include_evaluated=False, depsgraph=None):
    mesh = getattr(obj, "data", None)
    if mesh is None:
        return None

    source_mesh = mesh
    temp_mesh = None
    if include_evaluated and depsgraph is not None:
        try:
            evaluated = obj.evaluated_get(depsgraph)
            temp_mesh = evaluated.to_mesh()
            source_mesh = temp_mesh
        except Exception:
            source_mesh = mesh

    try:
        try:
            source_mesh.calc_loop_triangles()
        except Exception:
            pass
        material_counts = Counter(poly.material_index for poly in source_mesh.polygons)
        return {
            "data": _datablock_ref(mesh),
            "evaluated": bool(temp_mesh),
            "vertex_count": len(source_mesh.vertices),
            "edge_count": len(source_mesh.edges),
            "polygon_count": len(source_mesh.polygons),
            "loop_count": len(source_mesh.loops),
            "triangle_count": len(getattr(source_mesh, "loop_triangles", [])),
            "material_index_histogram": {str(key): value for key, value in sorted(material_counts.items())},
            "uv_layers": _mesh_uv_layers(source_mesh),
            "color_attributes": _mesh_color_attributes(source_mesh),
            "attributes": _mesh_attributes(source_mesh),
            "shape_keys": _shape_keys(mesh),
        }
    finally:
        if temp_mesh is not None:
            try:
                evaluated.to_mesh_clear()
            except Exception:
                pass


def _object_record(obj, include_evaluated_mesh=False, depsgraph=None):
    record = {
        "name": obj.name,
        "type": obj.type,
        "library": obj.library.filepath if obj.library else None,
        "data": _datablock_ref(getattr(obj, "data", None)),
        "parent": getattr(getattr(obj, "parent", None), "name", None),
        "children": [child.name for child in getattr(obj, "children", [])],
        "collections": _object_collection_names(obj),
        "visible_get": bool(obj.visible_get()),
        "hide_viewport": bool(getattr(obj, "hide_viewport", False)),
        "hide_render": bool(getattr(obj, "hide_render", False)),
        "select_get": bool(obj.select_get()),
        "matrix_world": _safe_value(obj.matrix_world),
        "matrix_local": _safe_value(obj.matrix_local),
        "location": _safe_value(obj.location),
        "rotation_mode": getattr(obj, "rotation_mode", None),
        "rotation_euler": _safe_value(obj.rotation_euler),
        "rotation_quaternion": _safe_value(obj.rotation_quaternion),
        "scale": _safe_value(obj.scale),
        "bound_box_world": _safe_value(_world_bounds(obj)),
        "custom_properties": _custom_properties(obj),
        "material_slots": _material_slots(obj),
        "modifiers": [_modifier_summary(modifier) for modifier in obj.modifiers],
        "vertex_groups": _vertex_group_usage(obj),
    }
    if obj.type == "MESH":
        record["mesh"] = _mesh_stats(obj, include_evaluated_mesh, depsgraph)
    return record


def _selected_objects(context):
    return list(getattr(context, "selected_objects", []) or [])


def _objects_for_scope(context, scope):
    if scope == "ACTIVE":
        return [context.active_object] if context.active_object else []
    if scope == "SELECTED":
        return _selected_objects(context)
    if scope == "VISIBLE":
        return [obj for obj in context.scene.objects if obj.visible_get()]
    return list(context.scene.objects)


def build_object_scene_ir(context, scope="SELECTED", include_evaluated_mesh=False):
    depsgraph = context.evaluated_depsgraph_get() if include_evaluated_mesh else None
    objects = [obj for obj in _objects_for_scope(context, scope) if obj is not None]
    object_records = [_object_record(obj, include_evaluated_mesh, depsgraph) for obj in objects]
    type_counts = Counter(record["type"] for record in object_records)
    material_counts = Counter()
    uv_names = Counter()
    color_attribute_names = Counter()
    attribute_names = Counter()
    modifier_types = Counter()

    for record in object_records:
        for slot in record.get("material_slots", []):
            material = slot.get("material")
            if material:
                material_counts[material.get("name")] += 1
        for modifier in record.get("modifiers", []):
            modifier_types[modifier.get("type")] += 1
        mesh = record.get("mesh") or {}
        for uv in mesh.get("uv_layers", []):
            uv_names[uv.get("name")] += 1
        for attr in mesh.get("color_attributes", []):
            color_attribute_names[attr.get("name")] += 1
        for attr in mesh.get("attributes", []):
            if not attr.get("is_internal"):
                attribute_names[attr.get("name")] += 1

    return {
        "schema": SCHEMA,
        "blender_version": list(bpy.app.version),
        "app": _app_metadata(),
        "scene": {
            "name": context.scene.name,
            "frame_current": context.scene.frame_current,
            "unit_system": getattr(context.scene.unit_settings, "system", None),
        },
        "export": {
            "scope": scope,
            "include_evaluated_mesh": include_evaluated_mesh,
            "object_count": len(object_records),
        },
        "summary": {
            "object_type_counts": dict(sorted(type_counts.items())),
            "material_slot_material_counts": dict(sorted(material_counts.items())),
            "uv_layer_names": dict(sorted(uv_names.items())),
            "color_attribute_names": dict(sorted(color_attribute_names.items())),
            "attribute_names": dict(sorted(attribute_names.items())),
            "modifier_type_counts": dict(sorted(modifier_types.items())),
        },
        "objects": object_records,
    }


def format_object_scene_markdown(ir):
    lines = [
        f"# Object Scene IR: {ir['scene']['name']}",
        "",
        f"- Schema: `{ir['schema']}`",
        f"- Blender: `{'.'.join(str(v) for v in ir['blender_version'])}`",
        f"- Export App: `{ir.get('app', {}).get('source_flavor_hint', 'unknown')}`",
        f"- Scope: `{ir['export']['scope']}`",
        f"- Objects: `{ir['export']['object_count']}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in ir.get("summary", {}).items():
        lines.append(f"- {key}: `{json.dumps(value, ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Objects")
    lines.append("")
    for obj in ir.get("objects", []):
        mesh = obj.get("mesh") or {}
        lines.append(f"### {obj['name']}")
        lines.append("")
        lines.append(f"- Type: `{obj['type']}`")
        if obj.get("parent"):
            lines.append(f"- Parent: `{obj['parent']}`")
        lines.append(f"- Collections: `{', '.join(obj.get('collections', []))}`")
        lines.append(f"- Materials: `{', '.join((slot.get('material') or {}).get('name', '<empty>') for slot in obj.get('material_slots', []))}`")
        lines.append(f"- Modifiers: `{', '.join(mod.get('type', '') for mod in obj.get('modifiers', []))}`")
        if mesh:
            lines.append(
                f"- Mesh: vertices=`{mesh.get('vertex_count')}` polygons=`{mesh.get('polygon_count')}` triangles=`{mesh.get('triangle_count')}`"
            )
            lines.append(f"- UVs: `{', '.join(uv.get('name', '') for uv in mesh.get('uv_layers', []))}`")
            lines.append(f"- Color Attributes: `{', '.join(attr.get('name', '') for attr in mesh.get('color_attributes', []))}`")
            lines.append(f"- Shape Keys: `{mesh.get('shape_keys', {}).get('count', 0)}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _replace_ext(filepath, ext):
    root, current_ext = os.path.splitext(filepath)
    if current_ext.lower() == ext.lower():
        return filepath
    if current_ext:
        return root + ext
    return filepath + ext


def write_object_scene_ir(ir, filepath, export_format):
    paths = []
    if export_format in {"JSON", "BOTH"}:
        json_path = _replace_ext(filepath, ".object_scene.json")
        temp_path = json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(ir, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, json_path)
        paths.append(json_path)
    if export_format in {"MARKDOWN", "BOTH"}:
        md_path = _replace_ext(filepath, ".object_scene.md")
        temp_path = md_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(format_object_scene_markdown(ir))
        os.replace(temp_path, md_path)
        paths.append(md_path)
    return paths


def _materials_used_by_objects(objects):
    seen = set()
    materials = []
    for obj in objects:
        for slot in getattr(obj, "material_slots", []):
            material = getattr(slot, "material", None)
            if material is None:
                continue
            key = material.as_pointer()
            if key in seen:
                continue
            seen.add(key)
            materials.append(material)
    return materials


def build_scene_asset_ir(
    context,
    include_material_groups=True,
    include_evaluated_mesh=False,
):
    object_ir = build_object_scene_ir(
        context,
        scope="SCENE",
        include_evaluated_mesh=include_evaluated_mesh,
    )
    objects = list(context.scene.objects)
    material_records = []
    failures = []
    for material in _materials_used_by_objects(objects):
        record = {
            "name": material.name,
            "library": material.library.filepath if material.library else None,
            "use_nodes": bool(getattr(material, "use_nodes", False)),
        }
        if material_node_ir is None:
            failures.append({"material": material.name, "error": "material_node_ir module is unavailable"})
        elif material.use_nodes and material.node_tree is not None:
            try:
                record["ir"] = material_node_ir.build_material_ir(
                    material,
                    include_groups=include_material_groups,
                )
            except Exception as exc:
                failures.append({"material": material.name, "error": str(exc)})
        else:
            record["properties"] = _serialize_rna_properties(material)
            record["diffuse_color"] = _safe_value(getattr(material, "diffuse_color", None))
        material_records.append(record)

    return {
        "schema": SCENE_BUNDLE_SCHEMA,
        "blender_version": list(bpy.app.version),
        "app": _app_metadata(),
        "scene": object_ir.get("scene", {}),
        "export": {
            "scope": "SCENE",
            "object_count": len(object_ir.get("objects", [])),
            "material_count": len(material_records),
            "include_material_groups": include_material_groups,
            "include_evaluated_mesh": include_evaluated_mesh,
        },
        "object_scene": object_ir,
        "materials": material_records,
        "material_export_failures": failures,
    }


def format_scene_asset_markdown(ir):
    object_ir = ir.get("object_scene", {})
    lines = [
        f"# Scene Asset IR: {ir.get('scene', {}).get('name')}",
        "",
        f"- Schema: `{ir.get('schema')}`",
        f"- Blender: `{'.'.join(str(v) for v in ir.get('blender_version', []))}`",
        f"- Objects: `{ir.get('export', {}).get('object_count')}`",
        f"- Materials: `{ir.get('export', {}).get('material_count')}`",
        f"- Material Export Failures: `{len(ir.get('material_export_failures', []))}`",
        "",
        "## Object Summary",
        "",
    ]
    for key, value in object_ir.get("summary", {}).items():
        lines.append(f"- {key}: `{json.dumps(value, ensure_ascii=False)}`")

    lines.append("")
    lines.append("## Materials")
    lines.append("")
    for record in ir.get("materials", []):
        material_ir = record.get("ir")
        if material_ir:
            node_tree = material_ir.get("node_tree", {})
            lines.append(
                f"- `{record.get('name')}` nodes=`{len(node_tree.get('nodes', []))}` use_nodes=`true`"
            )
        else:
            lines.append(f"- `{record.get('name')}` use_nodes=`{record.get('use_nodes')}`")

    if ir.get("material_export_failures"):
        lines.append("")
        lines.append("## Material Export Failures")
        for failure in ir.get("material_export_failures", []):
            lines.append(f"- `{failure.get('material')}`: {failure.get('error')}")
    return "\n".join(lines).rstrip() + "\n"


def write_scene_asset_ir(ir, filepath, export_format):
    paths = []
    if export_format in {"JSON", "BOTH"}:
        json_path = _replace_ext(filepath, ".scene_asset.json")
        temp_path = json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(ir, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, json_path)
        paths.append(json_path)
    if export_format in {"MARKDOWN", "BOTH"}:
        md_path = _replace_ext(filepath, ".scene_asset.md")
        temp_path = md_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(format_scene_asset_markdown(ir))
        os.replace(temp_path, md_path)
        paths.append(md_path)
    return paths


class HO_OT_export_object_scene_ir(Operator, ExportHelper):
    bl_idname = "ho.export_object_scene_ir"
    bl_label = "Export Object Scene IR"
    bl_description = "Export selected, visible, or scene objects as AI-readable scene/object IR"

    filename_ext = ".json"
    filter_glob: StringProperty(
        default="*.json;*.md",
        options={"HIDDEN"},
    )  # type: ignore
    scope: EnumProperty(
        name="Scope",
        items=(
            ("SELECTED", "Selected", "Export selected objects"),
            ("ACTIVE", "Active", "Export active object only"),
            ("VISIBLE", "Visible", "Export visible scene objects"),
            ("SCENE", "Scene", "Export every object in the current scene"),
        ),
        default="SELECTED",
    )  # type: ignore
    export_format: EnumProperty(
        name="Format",
        items=(
            ("JSON", "JSON", "Machine-readable full IR"),
            ("MARKDOWN", "Markdown", "AI-readable text summary"),
            ("BOTH", "JSON + Markdown", "Write both files"),
        ),
        default="JSON",
    )  # type: ignore
    include_evaluated_mesh: BoolProperty(
        name="Use Evaluated Mesh Stats",
        default=False,
        description="Apply modifiers for mesh counts. Slower and may allocate temporary meshes.",
    )  # type: ignore
    copy_to_clipboard: BoolProperty(
        name="Copy Text To Clipboard",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = bpy.path.clean_name(context.scene.name) + ".object_scene.json"
        return super().invoke(context, event)

    def execute(self, context):
        try:
            ir = build_object_scene_ir(
                context,
                scope=self.scope,
                include_evaluated_mesh=self.include_evaluated_mesh,
            )
            paths = write_object_scene_ir(ir, self.filepath, self.export_format)
            if self.copy_to_clipboard:
                if self.export_format == "MARKDOWN":
                    context.window_manager.clipboard = format_object_scene_markdown(ir)
                else:
                    context.window_manager.clipboard = json.dumps(ir, ensure_ascii=False, indent=2)
            self.report({"INFO"}, f"Object Scene IR exported: {', '.join(paths)}")
            return {"FINISHED"}
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Object Scene IR export failed: {exc}")
            return {"CANCELLED"}


class HO_OT_export_scene_asset_ir(Operator, ExportHelper):
    bl_idname = "ho.export_scene_asset_ir"
    bl_label = "Export Scene Asset IR"
    bl_description = "Export the whole scene: all objects plus all material node IRs referenced by material slots"

    filename_ext = ".json"
    filter_glob: StringProperty(
        default="*.json;*.md",
        options={"HIDDEN"},
    )  # type: ignore
    export_format: EnumProperty(
        name="Format",
        items=(
            ("JSON", "JSON", "Machine-readable full scene bundle"),
            ("MARKDOWN", "Markdown", "AI-readable text summary"),
            ("BOTH", "JSON + Markdown", "Write both files"),
        ),
        default="JSON",
    )  # type: ignore
    include_material_groups: BoolProperty(
        name="Inline Material Node Groups",
        default=True,
    )  # type: ignore
    include_evaluated_mesh: BoolProperty(
        name="Use Evaluated Mesh Stats",
        default=False,
        description="Apply modifiers for mesh counts. Slower and may allocate temporary meshes.",
    )  # type: ignore
    copy_to_clipboard: BoolProperty(
        name="Copy Text To Clipboard",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = bpy.path.clean_name(context.scene.name) + ".scene_asset.json"
        return super().invoke(context, event)

    def execute(self, context):
        try:
            ir = build_scene_asset_ir(
                context,
                include_material_groups=self.include_material_groups,
                include_evaluated_mesh=self.include_evaluated_mesh,
            )
            paths = write_scene_asset_ir(ir, self.filepath, self.export_format)
            if self.copy_to_clipboard:
                if self.export_format == "MARKDOWN":
                    context.window_manager.clipboard = format_scene_asset_markdown(ir)
                else:
                    context.window_manager.clipboard = json.dumps(ir, ensure_ascii=False, indent=2)
            self.report({"INFO"}, f"Scene Asset IR exported: {', '.join(paths)}")
            return {"FINISHED"}
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Scene Asset IR export failed: {exc}")
            return {"CANCELLED"}


class HO_PT_object_scene_ir(Panel):
    bl_idname = "VIEW3D_PT_ho_object_scene_ir"
    bl_label = "Object Scene IR"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"

    def draw(self, context):
        layout = self.layout
        selected_count = len(_selected_objects(context))
        layout.label(text=f"Selected: {selected_count}", icon="OBJECT_DATA")
        row = layout.row(align=True)
        op = row.operator(HO_OT_export_object_scene_ir.bl_idname, text="Selected JSON", icon="FILE_TEXT")
        op.scope = "SELECTED"
        op.export_format = "JSON"
        op = row.operator(HO_OT_export_object_scene_ir.bl_idname, text="Visible JSON", icon="OUTLINER")
        op.scope = "VISIBLE"
        op.export_format = "JSON"
        op = layout.operator(HO_OT_export_object_scene_ir.bl_idname, text="Export Scene JSON + Markdown", icon="EXPORT")
        op.scope = "SCENE"
        op.export_format = "BOTH"
        layout.separator()
        bundle = layout.operator(
            HO_OT_export_scene_asset_ir.bl_idname,
            text="Export Scene Bundle: Objects + Materials",
            icon="PACKAGE",
        )
        bundle.export_format = "JSON"


CLASSES = (
    HO_OT_export_object_scene_ir,
    HO_OT_export_scene_asset_ir,
    HO_PT_object_scene_ir,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
