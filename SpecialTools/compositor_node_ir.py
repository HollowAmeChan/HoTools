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


SCHEMA = "hotools.compositor_node_ir.v1"

DATABLOCK_PROPS = (
    "image",
    "mask",
    "movie_clip",
    "scene",
    "collection",
    "texture",
    "node_tree",
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
    filepath = getattr(data, "filepath", None)
    abs_path = ""
    if filepath:
        try:
            abs_path = bpy.path.abspath(filepath)
        except Exception:
            abs_path = filepath
    return {
        "name": getattr(data, "name", None),
        "type": data.__class__.__name__,
        "library": getattr(getattr(data, "library", None), "filepath", None),
        "users": getattr(data, "users", None),
        "filepath": filepath,
        "filepath_abs": abs_path,
    }


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


def _serialize_image(image):
    if image is None:
        return None
    data = _datablock_ref(image)
    data.update(
        {
            "source": getattr(image, "source", None),
            "size": list(getattr(image, "size", [])),
            "colorspace": getattr(getattr(image, "colorspace_settings", None), "name", None),
            "alpha_mode": getattr(image, "alpha_mode", None),
            "is_dirty": bool(getattr(image, "is_dirty", False)),
            "packed": getattr(image, "packed_file", None) is not None,
        }
    )
    return data


def _serialize_color_ramp(color_ramp):
    if color_ramp is None:
        return None
    return {
        "interpolation": getattr(color_ramp, "interpolation", None),
        "hue_interpolation": getattr(color_ramp, "hue_interpolation", None),
        "color_mode": getattr(color_ramp, "color_mode", None),
        "elements": [
            {
                "position": _safe_value(getattr(element, "position", None)),
                "color": _safe_value(getattr(element, "color", None)),
            }
            for element in getattr(color_ramp, "elements", [])
        ],
    }


def _serialize_curve_mapping(curve_mapping):
    if curve_mapping is None:
        return None
    curves = []
    for curve_index, curve in enumerate(getattr(curve_mapping, "curves", [])):
        curves.append(
            {
                "index": curve_index,
                "points": [
                    {
                        "location": _safe_value(getattr(point, "location", None)),
                        "handle_type": getattr(point, "handle_type", None),
                    }
                    for point in getattr(curve, "points", [])
                ],
            }
        )
    return {
        "use_clip": getattr(curve_mapping, "use_clip", None),
        "clip_min_x": getattr(curve_mapping, "clip_min_x", None),
        "clip_min_y": getattr(curve_mapping, "clip_min_y", None),
        "clip_max_x": getattr(curve_mapping, "clip_max_x", None),
        "clip_max_y": getattr(curve_mapping, "clip_max_y", None),
        "black_level": _safe_value(getattr(curve_mapping, "black_level", None)),
        "white_level": _safe_value(getattr(curve_mapping, "white_level", None)),
        "tone": getattr(curve_mapping, "tone", None),
        "curves": curves,
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


def _serialize_node_datablocks(node):
    refs = {}
    for prop_name in DATABLOCK_PROPS:
        try:
            data = getattr(node, prop_name, None)
        except Exception:
            continue
        if data is None:
            continue
        if prop_name == "image":
            refs[prop_name] = _serialize_image(data)
        else:
            refs[prop_name] = _datablock_ref(data)
    return refs


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

    datablocks = _serialize_node_datablocks(node)
    if datablocks:
        node_data["datablocks"] = datablocks

    if hasattr(node, "color_ramp"):
        node_data["color_ramp"] = _serialize_color_ramp(getattr(node, "color_ramp", None))

    mapping = getattr(node, "mapping", None)
    if mapping is not None:
        node_data["curve_mapping"] = _serialize_curve_mapping(mapping)

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
        return {
            "name": node_tree.name,
            "bl_idname": node_tree.bl_idname,
            "interface": _serialize_node_tree_interface(node_tree),
            "has_drivers": bool(drivers),
            "drivers": drivers,
            "nodes": [
                _serialize_node(node, include_groups, tree_stack, driver_paths)
                for node in node_tree.nodes
            ],
            "links": [_serialize_link(link) for link in node_tree.links],
        }
    finally:
        tree_stack.remove(tree_key)


def build_compositor_node_ir(scene, include_groups=True):
    if scene is None:
        raise ValueError("No scene to export.")
    node_tree = getattr(scene, "node_tree", None)
    if not getattr(scene, "use_nodes", False) or node_tree is None:
        raise ValueError(f"Scene '{scene.name}' does not use compositor nodes.")

    nodes = list(getattr(node_tree, "nodes", []))
    node_types = Counter(getattr(node, "bl_idname", "") for node in nodes)
    return {
        "schema": SCHEMA,
        "blender_version": list(bpy.app.version),
        "app": _app_metadata(),
        "scene": {
            "name": scene.name,
            "frame_current": getattr(scene, "frame_current", None),
            "use_nodes": bool(getattr(scene, "use_nodes", False)),
        },
        "summary": {
            "node_count": len(nodes),
            "link_count": len(getattr(node_tree, "links", [])),
            "node_type_counts": dict(sorted(node_types.items())),
        },
        "node_tree": _serialize_node_tree(
            node_tree,
            include_groups=include_groups,
        ),
    }


def _replace_ext(filepath, suffix):
    base, _ = os.path.splitext(filepath)
    return base + suffix


def format_compositor_node_markdown(ir):
    summary = ir.get("summary", {})
    lines = [
        f"# Compositor Node IR: {ir.get('scene', {}).get('name')}",
        "",
        f"- Schema: `{ir.get('schema')}`",
        f"- Blender: `{'.'.join(str(v) for v in ir.get('blender_version', []))}`",
        f"- Nodes: `{summary.get('node_count', 0)}`",
        f"- Links: `{summary.get('link_count', 0)}`",
        f"- Node types: `{json.dumps(summary.get('node_type_counts', {}), ensure_ascii=False)}`",
        "",
    ]
    for node in ir.get("node_tree", {}).get("nodes", []):
        lines.append(f"- `{node.get('name')}` `{node.get('bl_idname')}` mute=`{node.get('mute')}`")
    return "\n".join(lines).rstrip() + "\n"


def write_compositor_node_ir(ir, filepath, export_format):
    paths = []
    if export_format in {"JSON", "BOTH"}:
        json_path = _replace_ext(filepath, ".compositor_node.json")
        temp_path = json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(ir, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, json_path)
        paths.append(json_path)
    if export_format in {"MARKDOWN", "BOTH"}:
        md_path = _replace_ext(filepath, ".compositor_node.md")
        temp_path = md_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(format_compositor_node_markdown(ir))
        os.replace(temp_path, md_path)
        paths.append(md_path)
    return paths


def _argv_after_double_dash(argv):
    if "--" not in argv:
        return []
    return argv[argv.index("--") + 1 :]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export Compositor Node IR from Blender/Goo via bpy.")
    parser.add_argument("--scene", help="Scene name. Defaults to active scene.")
    parser.add_argument("--output", help="Output path. If omitted, print JSON to stdout.")
    parser.add_argument("--format", choices=("JSON", "MARKDOWN", "BOTH"), default="JSON")
    parser.add_argument("--no-groups", action="store_true", help="Do not inline nested compositor node groups.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print stdout JSON when --output is omitted.")
    args = parser.parse_args(argv)

    scene = bpy.data.scenes.get(args.scene) if args.scene else bpy.context.scene
    ir = build_compositor_node_ir(scene, include_groups=not args.no_groups)
    if args.output:
        paths = write_compositor_node_ir(ir, args.output, args.format)
        print(json.dumps({"schema": SCHEMA, "paths": paths, "summary": ir.get("summary", {})}, ensure_ascii=False))
    else:
        print(json.dumps(ir, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


class HO_OT_export_compositor_node_ir(Operator, ExportHelper):
    bl_idname = "ho.export_compositor_node_ir"
    bl_label = "Export Compositor Node IR"
    bl_description = "Export the active scene compositor node tree as AI-readable IR"

    filename_ext = ".json"
    filter_glob: StringProperty(
        default="*.json;*.md",
        options={"HIDDEN"},
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
            self.filepath = bpy.path.clean_name(context.scene.name) + ".compositor_node.json"
        return super().invoke(context, event)

    def execute(self, context):
        try:
            ir = build_compositor_node_ir(
                context.scene,
                include_groups=self.include_groups,
            )
            paths = write_compositor_node_ir(ir, self.filepath, self.export_format)
            if self.copy_to_clipboard:
                if self.export_format == "MARKDOWN":
                    context.window_manager.clipboard = format_compositor_node_markdown(ir)
                else:
                    context.window_manager.clipboard = json.dumps(ir, ensure_ascii=False, indent=2)
            self.report({"INFO"}, f"Compositor Node IR exported: {', '.join(paths)}")
            return {"FINISHED"}
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Compositor Node IR export failed: {exc}")
            return {"CANCELLED"}


class HO_PT_compositor_node_ir(Panel):
    bl_idname = "NODE_PT_ho_compositor_node_ir"
    bl_label = "Compositor Node IR"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HoTools"

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return context.scene is not None and getattr(space, "tree_type", "") == "CompositorNodeTree"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.label(text=f"Scene: {scene.name}", icon="NODE_COMPOSITING")
        layout.label(text=f"Use Nodes: {bool(getattr(scene, 'use_nodes', False))}")
        op = layout.operator(HO_OT_export_compositor_node_ir.bl_idname, text="Export Compositor JSON", icon="FILE_TEXT")
        op.export_format = "JSON"
        op = layout.operator(HO_OT_export_compositor_node_ir.bl_idname, text="Export JSON + Markdown", icon="EXPORT")
        op.export_format = "BOTH"


CLASSES = (
    HO_OT_export_compositor_node_ir,
    HO_PT_compositor_node_ir,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    raise SystemExit(main(_argv_after_double_dash(sys.argv)))
