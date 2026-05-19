import argparse
import json
import os
import sys
import traceback
from collections import Counter

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper


SCHEMA = "hotools.geometry_node_ir.v1"

ZONE_INPUT_TYPES = {
    "GeometryNodeSimulationInput": "simulation",
    "GeometryNodeRepeatInput": "repeat",
    "GeometryNodeForeachGeometryElementInput": "foreach_geometry_element",
    "GeometryNodeClosureInput": "closure",
}

ZONE_OUTPUT_TYPES = {
    "GeometryNodeSimulationOutput": "simulation",
    "GeometryNodeRepeatOutput": "repeat",
    "GeometryNodeForeachGeometryElementOutput": "foreach_geometry_element",
    "GeometryNodeClosureOutput": "closure",
}

ZONE_ITEM_COLLECTIONS = (
    "state_items",
    "repeat_items",
    "input_items",
    "main_items",
    "generation_items",
    "output_items",
)

SPECIAL_ITEM_COLLECTIONS = (
    "bake_items",
    "capture_items",
    "enum_definition",
    "menu_items",
)

NODE_DATABLOCK_PROPS = (
    "node_tree",
    "object",
    "collection",
    "material",
    "texture",
    "image",
)


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


def _datablock_ref(data):
    if data is None:
        return None
    return {
        "name": getattr(data, "name", None),
        "type": data.__class__.__name__,
        "library": getattr(getattr(data, "library", None), "filepath", None),
        "users": getattr(data, "users", None),
    }


def _custom_properties(id_obj):
    result = {}
    if id_obj is None or not hasattr(id_obj, "keys"):
        return result
    try:
        keys = list(id_obj.keys())
    except Exception:
        return result
    for key in keys:
        if key == "_RNA_UI":
            continue
        try:
            result[str(key)] = _safe_value(id_obj[key])
        except Exception:
            continue
    return result


def _serialize_rna_properties(rna_obj, skip=()):
    result = {}
    skip_ids = {
        "rna_type",
        "name",
        "label",
        "location",
        "width",
        "height",
        "dimensions",
        "inputs",
        "outputs",
        "internal_links",
        "select",
        "parent",
        "id_data",
        "node_tree",
        "paired_output",
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


def _socket_identifier(socket, fallback_index):
    identifier = getattr(socket, "identifier", None)
    if identifier:
        return identifier
    return f"{socket.name}:{fallback_index}"


def _socket_index(sockets, socket):
    for index, item in enumerate(sockets):
        if item == socket:
            return index
    return -1


def _serialize_drivers(id_data):
    animation_data = getattr(id_data, "animation_data", None)
    if animation_data is None or animation_data.drivers is None:
        return []

    result = []
    for fcurve in animation_data.drivers:
        driver = getattr(fcurve, "driver", None)
        result.append(
            {
                "data_path": getattr(fcurve, "data_path", ""),
                "array_index": getattr(fcurve, "array_index", -1),
                "driver_type": getattr(driver, "type", None) if driver else None,
                "variable_count": len(getattr(driver, "variables", [])) if driver else 0,
                "is_valid": bool(getattr(fcurve, "is_valid", True)),
            }
        )
    return result


def _socket_has_driver(socket, driver_paths):
    if not driver_paths or not hasattr(socket, "path_from_id"):
        return False
    try:
        socket_path = socket.path_from_id("default_value")
    except Exception:
        return False
    return any(path == socket_path or path.startswith(socket_path + "[") for path in driver_paths)


def _serialize_socket(socket, index, driver_paths=None):
    if driver_paths is None:
        driver_paths = set()
    data = {
        "index": index,
        "name": socket.name,
        "identifier": _socket_identifier(socket, index),
        "bl_idname": getattr(socket, "bl_idname", None),
        "type": getattr(socket, "type", None),
        "enabled": bool(getattr(socket, "enabled", True)),
        "hide": bool(getattr(socket, "hide", False)),
        "is_linked": bool(getattr(socket, "is_linked", False)),
        "link_limit": getattr(socket, "link_limit", None),
        "has_driver": _socket_has_driver(socket, driver_paths),
    }
    if hasattr(socket, "default_value"):
        try:
            data["default_value"] = _safe_value(socket.default_value)
        except Exception:
            data["default_value_error"] = "unreadable"
    if hasattr(socket, "min_value"):
        data["min_value"] = _safe_value(getattr(socket, "min_value", None))
    if hasattr(socket, "max_value"):
        data["max_value"] = _safe_value(getattr(socket, "max_value", None))
    return data


def _serialize_internal_link(node, link):
    from_index = _socket_index(node.inputs, link.from_socket)
    to_index = _socket_index(node.outputs, link.to_socket)
    return {
        "from_input": {
            "index": from_index,
            "name": link.from_socket.name,
            "identifier": _socket_identifier(link.from_socket, from_index),
        },
        "to_output": {
            "index": to_index,
            "name": link.to_socket.name,
            "identifier": _socket_identifier(link.to_socket, to_index),
        },
    }


def _serialize_interface_item(item):
    data = {
        "name": getattr(item, "name", None),
        "item_type": getattr(item, "item_type", None),
        "identifier": getattr(item, "identifier", None),
        "socket_type": getattr(item, "socket_type", None),
        "in_out": getattr(item, "in_out", None),
        "description": getattr(item, "description", None),
        "parent": getattr(getattr(item, "parent", None), "name", None),
    }
    return {key: value for key, value in data.items() if value is not None}


def _serialize_node_tree_interface(node_tree):
    interface = getattr(node_tree, "interface", None)
    if interface is None:
        return []
    try:
        return [_serialize_interface_item(item) for item in interface.items_tree]
    except Exception:
        return []


def _serialize_item(item):
    data = {
        "name": getattr(item, "name", None),
        "socket_type": getattr(item, "socket_type", None),
        "data_type": getattr(item, "data_type", None),
        "attribute_domain": getattr(item, "attribute_domain", None),
        "domain": getattr(item, "domain", None),
        "identifier": getattr(item, "identifier", None),
    }
    data.update(_serialize_rna_properties(item))
    return {key: value for key, value in data.items() if value is not None}


def _serialize_collection_items(owner, collection_names):
    result = {}
    for name in collection_names:
        collection = getattr(owner, name, None)
        if collection is None:
            continue
        try:
            result[name] = [_serialize_item(item) for item in collection]
        except Exception as exc:
            result[name] = {"error": str(exc)}
    return result


def _serialize_node_datablocks(node):
    refs = {}
    for prop_name in NODE_DATABLOCK_PROPS:
        try:
            data = getattr(node, prop_name, None)
        except Exception:
            continue
        ref = _datablock_ref(data)
        if ref:
            refs[prop_name] = ref
    return refs


def _node_pointer_key(node):
    try:
        return str(node.as_pointer())
    except Exception:
        return node.name


def _paired_output_name(node):
    try:
        paired = getattr(node, "paired_output", None)
    except Exception:
        paired = None
    return getattr(paired, "name", None) if paired is not None else None


def _serialize_node(node, include_groups, tree_stack, driver_paths=None):
    if driver_paths is None:
        driver_paths = set()
    node_data = {
        "name": node.name,
        "label": node.label,
        "type": node.type,
        "bl_idname": node.bl_idname,
        "location": _safe_value(node.location),
        "width": node.width,
        "height": node.height,
        "mute": bool(getattr(node, "mute", False)),
        "hide": bool(getattr(node, "hide", False)),
        "use_custom_color": bool(getattr(node, "use_custom_color", False)),
        "color": _safe_value(getattr(node, "color", None)),
        "parent": node.parent.name if getattr(node, "parent", None) else None,
        "inputs": [
            _serialize_socket(socket, i, driver_paths)
            for i, socket in enumerate(node.inputs)
        ],
        "outputs": [
            _serialize_socket(socket, i, driver_paths)
            for i, socket in enumerate(node.outputs)
        ],
        "properties": _serialize_rna_properties(node),
    }

    if node.bl_idname == "NodeFrame":
        node_data["frame"] = {
            "label": node.label,
            "text": getattr(getattr(node, "text", None), "name", None),
            "shrink": bool(getattr(node, "shrink", False)),
        }

    paired_output = _paired_output_name(node)
    if paired_output:
        node_data["paired_output"] = paired_output

    datablocks = _serialize_node_datablocks(node)
    if datablocks:
        node_data["datablocks"] = datablocks

    item_collections = _serialize_collection_items(
        node,
        ZONE_ITEM_COLLECTIONS + SPECIAL_ITEM_COLLECTIONS,
    )
    if item_collections:
        node_data["item_collections"] = item_collections

    internal_links = getattr(node, "internal_links", None)
    if internal_links:
        node_data["internal_links"] = [
            _serialize_internal_link(node, link) for link in internal_links
        ]

    group_tree = getattr(node, "node_tree", None)
    if include_groups and group_tree is not None:
        node_data["group_tree"] = _serialize_node_tree(
            group_tree,
            include_groups=include_groups,
            tree_stack=tree_stack,
        )
    elif group_tree is not None:
        node_data["group_tree_ref"] = {
            "name": group_tree.name,
            "bl_idname": group_tree.bl_idname,
        }

    return node_data


def _serialize_link(link):
    from_index = _socket_index(link.from_node.outputs, link.from_socket)
    to_index = _socket_index(link.to_node.inputs, link.to_socket)
    return {
        "from_node": link.from_node.name,
        "from_socket": {
            "index": from_index,
            "name": link.from_socket.name,
            "identifier": _socket_identifier(link.from_socket, from_index),
        },
        "to_node": link.to_node.name,
        "to_socket": {
            "index": to_index,
            "name": link.to_socket.name,
            "identifier": _socket_identifier(link.to_socket, to_index),
        },
        "is_muted": bool(getattr(link, "is_muted", False)),
        "is_valid": bool(getattr(link, "is_valid", True)),
    }


def _serialize_zone_input(node, output_lookup):
    kind = ZONE_INPUT_TYPES.get(node.bl_idname)
    output_name = _paired_output_name(node)
    output = output_lookup.get(output_name)
    zone = {
        "kind": kind,
        "input_node": node.name,
        "input_bl_idname": node.bl_idname,
        "output_node": output_name,
        "output_bl_idname": getattr(output, "bl_idname", None) if output else None,
        "status": "paired" if output else "unpaired",
    }
    if output is not None:
        item_collections = _serialize_collection_items(output, ZONE_ITEM_COLLECTIONS)
        if item_collections:
            zone["items"] = item_collections
        zone["output_properties"] = _serialize_rna_properties(output)
    return zone


def _serialize_zones(node_tree):
    nodes = list(getattr(node_tree, "nodes", []))
    output_lookup = {node.name: node for node in nodes}
    zones = []
    paired_outputs = set()
    for node in nodes:
        if node.bl_idname not in ZONE_INPUT_TYPES:
            continue
        zone = _serialize_zone_input(node, output_lookup)
        if zone.get("output_node"):
            paired_outputs.add(zone["output_node"])
        zones.append(zone)

    for node in nodes:
        if node.bl_idname not in ZONE_OUTPUT_TYPES or node.name in paired_outputs:
            continue
        zones.append(
            {
                "kind": ZONE_OUTPUT_TYPES[node.bl_idname],
                "input_node": None,
                "input_bl_idname": None,
                "output_node": node.name,
                "output_bl_idname": node.bl_idname,
                "status": "output_without_detected_input",
                "items": _serialize_collection_items(node, ZONE_ITEM_COLLECTIONS),
                "output_properties": _serialize_rna_properties(node),
            }
        )
    return zones


def _serialize_node_tree(node_tree, include_groups=True, tree_stack=None):
    if tree_stack is None:
        tree_stack = set()

    try:
        tree_key = str(node_tree.as_pointer())
    except Exception:
        tree_key = node_tree.name

    if tree_key in tree_stack:
        return {
            "name": node_tree.name,
            "bl_idname": node_tree.bl_idname,
            "cycle_ref": True,
        }

    tree_stack.add(tree_key)
    try:
        drivers = _serialize_drivers(node_tree)
        driver_paths = {driver.get("data_path", "") for driver in drivers}
        nodes = [
            _serialize_node(node, include_groups, tree_stack, driver_paths)
            for node in node_tree.nodes
        ]
        zones = _serialize_zones(node_tree)
        return {
            "name": node_tree.name,
            "bl_idname": node_tree.bl_idname,
            "interface": _serialize_node_tree_interface(node_tree),
            "has_drivers": bool(drivers),
            "drivers": drivers,
            "nodes": nodes,
            "links": [_serialize_link(link) for link in node_tree.links],
            "zones": zones,
        }
    finally:
        tree_stack.remove(tree_key)


def _object_ref(obj):
    if obj is None:
        return None
    return {
        "name": obj.name,
        "type": getattr(obj, "type", None),
        "library": getattr(getattr(obj, "library", None), "filepath", None),
        "data": _datablock_ref(getattr(obj, "data", None)),
    }


def _modifier_summary(modifier):
    node_group = getattr(modifier, "node_group", None)
    return {
        "name": modifier.name,
        "type": modifier.type,
        "show_viewport": bool(getattr(modifier, "show_viewport", False)),
        "show_render": bool(getattr(modifier, "show_render", False)),
        "show_in_editmode": bool(getattr(modifier, "show_in_editmode", False)),
        "properties": _serialize_rna_properties(modifier),
        "custom_properties": _custom_properties(modifier),
        "node_group": _datablock_ref(node_group),
    }


def _selected_objects(context):
    return list(getattr(context, "selected_objects", []) or [])


def _objects_for_scope(context, scope):
    if scope == "ACTIVE":
        return [context.object] if context.object else []
    if scope == "SELECTED":
        return _selected_objects(context)
    if scope == "VISIBLE":
        return list(context.visible_objects)
    if scope == "SCENE":
        return list(context.scene.objects)
    return []


def _tree_key(tree):
    try:
        return str(tree.as_pointer())
    except Exception:
        return getattr(tree, "name", "")


def _iter_node_trees(tree, include_groups=True, visited=None):
    if not tree:
        return
    if visited is None:
        visited = set()
    key = _tree_key(tree)
    if key in visited:
        return
    visited.add(key)
    yield tree
    if not include_groups:
        return
    for node in getattr(tree, "nodes", []):
        group_tree = getattr(node, "node_tree", None)
        if group_tree is not None:
            yield from _iter_node_trees(group_tree, include_groups=True, visited=visited)


def _summarize_tree(tree, include_groups=True):
    node_types = Counter()
    zone_kinds = Counter()
    node_count = 0
    link_count = 0
    tree_count = 0
    for current_tree in _iter_node_trees(tree, include_groups=include_groups):
        tree_count += 1
        nodes = list(getattr(current_tree, "nodes", []))
        node_count += len(nodes)
        link_count += len(getattr(current_tree, "links", []))
        for node in nodes:
            node_types[getattr(node, "bl_idname", "")] += 1
        for zone in _serialize_zones(current_tree):
            zone_kinds[zone.get("kind")] += 1
    return {
        "tree_count": tree_count,
        "node_count": node_count,
        "link_count": link_count,
        "node_type_counts": dict(sorted(node_types.items())),
        "zone_counts": dict(sorted(zone_kinds.items())),
    }


def _build_modifier_record(obj, modifier, include_groups=True):
    node_group = getattr(modifier, "node_group", None)
    record = {
        "object": _object_ref(obj),
        "modifier": _modifier_summary(modifier),
        "node_tree": None,
        "summary": {},
        "export_error": None,
    }
    if node_group is None:
        record["export_error"] = "Geometry Nodes modifier has no node_group."
        return record
    try:
        record["summary"] = _summarize_tree(node_group, include_groups=include_groups)
        record["node_tree"] = _serialize_node_tree(
            node_group,
            include_groups=include_groups,
        )
    except Exception as exc:
        record["export_error"] = str(exc)
    return record


def build_geometry_node_ir(context, scope="SELECTED", include_groups=True):
    objects = _objects_for_scope(context, scope)
    records = []
    failures = []
    aggregate_node_types = Counter()
    aggregate_zone_counts = Counter()

    for obj in objects:
        for modifier in getattr(obj, "modifiers", []):
            if getattr(modifier, "type", None) != "NODES":
                continue
            record = _build_modifier_record(obj, modifier, include_groups=include_groups)
            records.append(record)
            if record.get("export_error"):
                failures.append(
                    {
                        "object": getattr(obj, "name", None),
                        "modifier": getattr(modifier, "name", None),
                        "error": record["export_error"],
                    }
                )
            for key, value in record.get("summary", {}).get("node_type_counts", {}).items():
                aggregate_node_types[key] += value
            for key, value in record.get("summary", {}).get("zone_counts", {}).items():
                aggregate_zone_counts[key] += value

    return {
        "schema": SCHEMA,
        "blender_version": list(bpy.app.version),
        "app": _app_metadata(),
        "scene": {
            "name": context.scene.name if context.scene else None,
            "frame_current": context.scene.frame_current if context.scene else None,
        },
        "export": {
            "scope": scope,
            "object_count": len(objects),
            "modifier_count": len(records),
            "include_groups": include_groups,
        },
        "summary": {
            "geometry_node_modifier_count": len(records),
            "node_type_counts": dict(sorted(aggregate_node_types.items())),
            "zone_counts": dict(sorted(aggregate_zone_counts.items())),
            "failure_count": len(failures),
        },
        "modifiers": records,
        "export_failures": failures,
    }


def _replace_ext(filepath, suffix):
    base, _ = os.path.splitext(filepath)
    return base + suffix


def format_geometry_node_markdown(ir):
    summary = ir.get("summary", {})
    lines = [
        f"# Geometry Nodes IR: {ir.get('scene', {}).get('name')}",
        "",
        f"- Schema: `{ir.get('schema')}`",
        f"- Blender: `{'.'.join(str(v) for v in ir.get('blender_version', []))}`",
        f"- Scope: `{ir.get('export', {}).get('scope')}`",
        f"- Modifiers: `{summary.get('geometry_node_modifier_count', 0)}`",
        f"- Zones: `{json.dumps(summary.get('zone_counts', {}), ensure_ascii=False)}`",
        f"- Export failures: `{summary.get('failure_count', 0)}`",
        "",
        "## Modifiers",
        "",
    ]
    for record in ir.get("modifiers", []):
        obj = record.get("object") or {}
        mod = record.get("modifier") or {}
        tree = record.get("node_tree") or {}
        rec_summary = record.get("summary") or {}
        lines.append(
            f"- `{obj.get('name')}` / `{mod.get('name')}` group=`{tree.get('name')}` "
            f"nodes=`{rec_summary.get('node_count', 0)}` links=`{rec_summary.get('link_count', 0)}`"
        )
        zone_counts = rec_summary.get("zone_counts") or {}
        if zone_counts:
            lines.append(f"  - Zones: `{json.dumps(zone_counts, ensure_ascii=False)}`")
        if record.get("export_error"):
            lines.append(f"  - Error: {record.get('export_error')}")
    return "\n".join(lines).rstrip() + "\n"


def write_geometry_node_ir(ir, filepath, export_format):
    paths = []
    if export_format in {"JSON", "BOTH"}:
        json_path = _replace_ext(filepath, ".geometry_node.json")
        temp_path = json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(ir, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, json_path)
        paths.append(json_path)
    if export_format in {"MARKDOWN", "BOTH"}:
        md_path = _replace_ext(filepath, ".geometry_node.md")
        temp_path = md_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(format_geometry_node_markdown(ir))
        os.replace(temp_path, md_path)
        paths.append(md_path)
    return paths


def _argv_after_double_dash(argv):
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export Geometry Nodes IR from Blender/Goo via bpy.")
    parser.add_argument("--scope", choices=("ACTIVE", "SELECTED", "VISIBLE", "SCENE"), default="SCENE")
    parser.add_argument("--output", help="Output path. If omitted, print JSON to stdout.")
    parser.add_argument("--format", choices=("JSON", "MARKDOWN", "BOTH"), default="JSON")
    parser.add_argument("--no-groups", action="store_true", help="Do not inline nested node groups.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print stdout JSON when --output is omitted.")
    args = parser.parse_args(argv)

    ir = build_geometry_node_ir(
        bpy.context,
        scope=args.scope,
        include_groups=not args.no_groups,
    )
    if args.output:
        paths = write_geometry_node_ir(ir, args.output, args.format)
        print(json.dumps({"schema": SCHEMA, "paths": paths, "summary": ir.get("summary", {})}, ensure_ascii=False))
    else:
        print(json.dumps(ir, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


class HO_OT_export_geometry_node_ir(Operator, ExportHelper):
    bl_idname = "ho.export_geometry_node_ir"
    bl_label = "Export Geometry Nodes IR"
    bl_description = "Export Geometry Nodes modifiers as AI-readable graph IR, including zone pairs"

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
    include_groups: BoolProperty(
        name="Inline Node Groups",
        default=True,
        description="Recursively include nested Geometry Nodes groups.",
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
            self.filepath = bpy.path.clean_name(context.scene.name) + ".geometry_node.json"
        return super().invoke(context, event)

    def execute(self, context):
        try:
            ir = build_geometry_node_ir(
                context,
                scope=self.scope,
                include_groups=self.include_groups,
            )
            paths = write_geometry_node_ir(ir, self.filepath, self.export_format)
            if self.copy_to_clipboard:
                if self.export_format == "MARKDOWN":
                    context.window_manager.clipboard = format_geometry_node_markdown(ir)
                else:
                    context.window_manager.clipboard = json.dumps(ir, ensure_ascii=False, indent=2)
            self.report({"INFO"}, f"Geometry Nodes IR exported: {', '.join(paths)}")
            return {"FINISHED"}
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Geometry Nodes IR export failed: {exc}")
            return {"CANCELLED"}


class HO_PT_geometry_node_ir(Panel):
    bl_idname = "VIEW3D_PT_ho_geometry_node_ir"
    bl_label = "Geometry Nodes IR"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"

    def draw(self, context):
        layout = self.layout
        selected_count = len(_selected_objects(context))
        layout.label(text=f"Selected: {selected_count}", icon="GEOMETRY_NODES")
        row = layout.row(align=True)
        op = row.operator(HO_OT_export_geometry_node_ir.bl_idname, text="Selected JSON", icon="FILE_TEXT")
        op.scope = "SELECTED"
        op.export_format = "JSON"
        op = row.operator(HO_OT_export_geometry_node_ir.bl_idname, text="Visible JSON", icon="OUTLINER")
        op.scope = "VISIBLE"
        op.export_format = "JSON"
        op = layout.operator(HO_OT_export_geometry_node_ir.bl_idname, text="Export Scene GN JSON + Markdown", icon="EXPORT")
        op.scope = "SCENE"
        op.export_format = "BOTH"


CLASSES = (
    HO_OT_export_geometry_node_ir,
    HO_PT_geometry_node_ir,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    raise SystemExit(main(_argv_after_double_dash(sys.argv)))
