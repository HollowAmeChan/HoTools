import json
import os
import traceback

import bpy
from bpy.types import Operator, Panel
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper


SCHEMA = "hotools.material_node_ir.v1"


def _app_attr(name, default=""):
    return _safe_value(getattr(bpy.app, name, default))


def _detect_source_flavor(fields):
    evidence = []
    for field, value in fields.items():
        text = str(value)
        if "goo" in text.lower():
            evidence.append({"field": field, "value": value})

    if evidence:
        return {
            "source_flavor_hint": "goo",
            "source_flavor_confidence": "strong",
            "source_flavor_label": "Goo Engine",
            "source_flavor_evidence": evidence,
        }

    return {
        "source_flavor_hint": "blender",
        "source_flavor_confidence": "metadata",
        "source_flavor_label": "Blender",
        "source_flavor_evidence": [],
    }


def _app_metadata():
    fields = {
        "binary_path": _app_attr("binary_path"),
        "version_string": _app_attr("version_string"),
        "build_branch": _app_attr("build_branch"),
        "build_hash": _app_attr("build_hash"),
        "build_commit_date": _app_attr("build_commit_date"),
        "build_commit_time": _app_attr("build_commit_time"),
        "build_platform": _app_attr("build_platform"),
        "build_type": _app_attr("build_type"),
    }
    fields["binary_dir"] = os.path.dirname(fields["binary_path"]) if fields["binary_path"] else ""
    fields["executable_name"] = os.path.basename(fields["binary_path"]) if fields["binary_path"] else ""
    fields.update(_detect_source_flavor(fields))
    return fields


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
        return {str(k): _safe_value(v, depth + 1) for k, v in value.items()}
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
    }
    skip_ids.update(skip)

    rna = getattr(rna_obj, "bl_rna", None)
    if rna is None:
        return result

    for prop in rna.properties:
        identifier = prop.identifier
        if identifier in skip_ids:
            continue
        if prop.type in {"POINTER", "COLLECTION"}:
            continue
        try:
            value = getattr(rna_obj, identifier)
        except Exception:
            continue
        result[identifier] = _safe_value(value)
    return result


def _serialize_image(image):
    if image is None:
        return None
    filepath = getattr(image, "filepath", "")
    try:
        abs_path = bpy.path.abspath(filepath) if filepath else ""
    except Exception:
        abs_path = filepath

    colorspace = getattr(getattr(image, "colorspace_settings", None), "name", None)
    packed_file = getattr(image, "packed_file", None)
    return {
        "name": image.name,
        "source": getattr(image, "source", None),
        "type": getattr(image, "type", None),
        "filepath": filepath,
        "filepath_abs": abs_path,
        "colorspace": colorspace,
        "size": list(getattr(image, "size", [])),
        "alpha_mode": getattr(image, "alpha_mode", None),
        "is_dirty": bool(getattr(image, "is_dirty", False)),
        "packed": packed_file is not None,
    }


def _serialize_color_ramp(color_ramp):
    if color_ramp is None:
        return None
    elements = []
    for element in getattr(color_ramp, "elements", []):
        elements.append(
            {
                "position": _safe_value(getattr(element, "position", None)),
                "color": _safe_value(getattr(element, "color", None)),
            }
        )
    return {
        "interpolation": getattr(color_ramp, "interpolation", None),
        "hue_interpolation": getattr(color_ramp, "hue_interpolation", None),
        "color_mode": getattr(color_ramp, "color_mode", None),
        "elements": elements,
    }


def _serialize_curve_mapping(curve_mapping):
    if curve_mapping is None:
        return None
    curves = []
    for curve_index, curve in enumerate(getattr(curve_mapping, "curves", [])):
        points = []
        for point in getattr(curve, "points", []):
            points.append(
                {
                    "location": _safe_value(getattr(point, "location", None)),
                    "handle_type": getattr(point, "handle_type", None),
                }
            )
        curves.append(
            {
                "index": curve_index,
                "points": points,
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

    internal_links = getattr(node, "internal_links", None)
    if internal_links:
        node_data["internal_links"] = [
            _serialize_internal_link(node, link) for link in internal_links
        ]

    image = getattr(node, "image", None)
    if image is not None:
        node_data["image"] = _serialize_image(image)

    color_ramp = getattr(node, "color_ramp", None)
    if color_ramp is not None:
        node_data["color_ramp"] = _serialize_color_ramp(color_ramp)

    curve_mapping = getattr(node, "mapping", None)
    if curve_mapping is not None and node.bl_idname in {
        "ShaderNodeRGBCurve",
        "ShaderNodeFloatCurve",
        "ShaderNodeVectorCurve",
    }:
        node_data["curve_mapping"] = _serialize_curve_mapping(curve_mapping)

    color_mapping = getattr(node, "color_mapping", None)
    if color_mapping is not None:
        node_data["color_mapping"] = _serialize_rna_properties(color_mapping)

    texture_mapping = getattr(node, "texture_mapping", None)
    if texture_mapping is not None:
        node_data["texture_mapping"] = _serialize_rna_properties(texture_mapping)

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


def _serialize_interface_item(item):
    data = {
        "name": getattr(item, "name", None),
        "item_type": getattr(item, "item_type", None),
        "identifier": getattr(item, "identifier", None),
        "socket_type": getattr(item, "socket_type", None),
        "in_out": getattr(item, "in_out", None),
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


def _serialize_material_properties(material):
    data = _serialize_rna_properties(
        material,
        skip={
            "node_tree",
            "preview_render_type",
            "diffuse_color",
            "line_color",
        },
    )
    data["diffuse_color"] = _safe_value(getattr(material, "diffuse_color", None))
    return data


def build_material_ir(material, include_groups=True):
    if material is None:
        raise ValueError("No material to export.")
    if not material.use_nodes or material.node_tree is None:
        raise ValueError(f"Material '{material.name}' does not use nodes.")

    return {
        "schema": SCHEMA,
        "blender_version": list(bpy.app.version),
        "app": _app_metadata(),
        "material": {
            "name": material.name,
            "library": material.library.filepath if material.library else None,
            "use_nodes": material.use_nodes,
            "properties": _serialize_material_properties(material),
        },
        "node_tree": _serialize_node_tree(
            material.node_tree,
            include_groups=include_groups,
        ),
    }


def _links_by_input(node_tree):
    links = {}
    for link in node_tree.get("links", []):
        key = (link["to_node"], link["to_socket"]["index"])
        links.setdefault(key, []).append(link)
    return links


def _format_default(socket):
    if "default_value" not in socket:
        return ""
    return f" = {json.dumps(socket['default_value'], ensure_ascii=False)}"


def _format_node_tree_markdown(node_tree, level=2):
    heading = "#" * level
    lines = [
        f"{heading} Node Tree: {node_tree['name']}",
        "",
        f"- Type: `{node_tree['bl_idname']}`",
        f"- Nodes: {len(node_tree.get('nodes', []))}",
        f"- Links: {len(node_tree.get('links', []))}",
        "",
    ]

    links_by_input = _links_by_input(node_tree)
    for node in node_tree.get("nodes", []):
        lines.append(f"{heading}# Node: {node['name']}")
        lines.append("")
        if node.get("label"):
            lines.append(f"- Label: {node['label']}")
        lines.append(f"- Type: `{node['bl_idname']}` / `{node['type']}`")
        if node.get("image"):
            image = node["image"]
            lines.append(
                f"- Image: `{image.get('name')}` colorspace=`{image.get('colorspace')}` path=`{image.get('filepath')}`"
            )

        if node.get("inputs"):
            lines.append("- Inputs:")
            for socket in node["inputs"]:
                linked = links_by_input.get((node["name"], socket["index"]), [])
                if linked:
                    source = ", ".join(
                        f"{link['from_node']}.{link['from_socket']['name']}"
                        for link in linked
                    )
                    lines.append(
                        f"  - `{socket['name']}` <- {source}{_format_default(socket)}"
                    )
                else:
                    lines.append(f"  - `{socket['name']}`{_format_default(socket)}")

        if node.get("outputs"):
            output_names = ", ".join(f"`{socket['name']}`" for socket in node["outputs"])
            lines.append(f"- Outputs: {output_names}")

        if node.get("group_tree"):
            lines.append("")
            lines.extend(_format_node_tree_markdown(node["group_tree"], level + 1))

        lines.append("")
    return lines


def format_material_markdown(ir):
    material = ir["material"]
    app = ir.get("app", {})
    evidence = app.get("source_flavor_evidence") or []
    lines = [
        f"# Material Node IR: {material['name']}",
        "",
        f"- Schema: `{ir['schema']}`",
        f"- Blender: `{'.'.join(str(v) for v in ir['blender_version'])}`",
        f"- Export App: `{app.get('source_flavor_label', app.get('source_flavor_hint', 'unknown'))}`",
        f"- Export Binary: `{app.get('binary_path', '')}`",
        f"- Build: branch=`{app.get('build_branch', '')}` hash=`{app.get('build_hash', '')}` date=`{app.get('build_commit_date', '')}`",
        f"- Source Flavor: `{app.get('source_flavor_hint', 'unknown')}` confidence=`{app.get('source_flavor_confidence', 'unknown')}`",
        "",
    ]
    if evidence:
        lines.append("## Export Environment Evidence")
        lines.append("")
        for item in evidence:
            lines.append(f"- `{item.get('field')}` contains Goo hint: `{item.get('value')}`")
        lines.append("")
    lines.extend(_format_node_tree_markdown(ir["node_tree"]))
    return "\n".join(lines).rstrip() + "\n"


def _get_context_material(context):
    material = getattr(context, "material", None)
    if material is not None:
        return material
    obj = getattr(context, "active_object", None)
    if obj is not None:
        return getattr(obj, "active_material", None)
    return None


def _replace_ext(filepath, ext):
    root, current_ext = os.path.splitext(filepath)
    if current_ext.lower() == ext.lower():
        return filepath
    if current_ext:
        return root + ext
    return filepath + ext


def write_material_ir(ir, filepath, export_format):
    paths = []
    if export_format in {"JSON", "BOTH"}:
        json_path = _replace_ext(filepath, ".json")
        temp_path = json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(ir, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, json_path)
        paths.append(json_path)

    if export_format in {"MARKDOWN", "BOTH"}:
        markdown_path = _replace_ext(filepath, ".md")
        temp_path = markdown_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(format_material_markdown(ir))
        os.replace(temp_path, markdown_path)
        paths.append(markdown_path)

    return paths


class HO_OT_export_material_node_ir(Operator, ExportHelper):
    bl_idname = "ho.export_material_node_ir"
    bl_label = "Export Material Node IR"
    bl_description = "Export the active material shader node tree as AI-readable IR"

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
        material = _get_context_material(context)
        return material is not None and material.use_nodes and material.node_tree is not None

    def invoke(self, context, event):
        material = _get_context_material(context)
        if material is not None and not self.filepath:
            self.filepath = bpy.path.clean_name(material.name) + ".json"
        return super().invoke(context, event)

    def execute(self, context):
        material = _get_context_material(context)
        try:
            ir = build_material_ir(material, include_groups=self.include_groups)
            paths = write_material_ir(ir, self.filepath, self.export_format)
            if self.copy_to_clipboard:
                if self.export_format == "MARKDOWN":
                    context.window_manager.clipboard = format_material_markdown(ir)
                else:
                    context.window_manager.clipboard = json.dumps(
                        ir,
                        ensure_ascii=False,
                        indent=2,
                    )
            self.report({"INFO"}, f"Material IR exported: {', '.join(paths)}")
            return {"FINISHED"}
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Material IR export failed: {exc}")
            return {"CANCELLED"}


class HO_PT_material_node_ir(Panel):
    bl_idname = "NODE_PT_ho_material_node_ir"
    bl_label = "Material Node IR"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HoTools"

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        if space is None or getattr(space, "tree_type", None) != "ShaderNodeTree":
            return False
        return _get_context_material(context) is not None

    def draw(self, context):
        layout = self.layout
        material = _get_context_material(context)
        if material is None:
            layout.label(text="No active material")
            return
        layout.label(text=material.name, icon="MATERIAL")
        if not material.use_nodes or material.node_tree is None:
            layout.label(text="Material does not use nodes", icon="ERROR")
            return

        row = layout.row(align=True)
        op = row.operator(HO_OT_export_material_node_ir.bl_idname, text="JSON", icon="FILE_TEXT")
        op.export_format = "JSON"
        op = row.operator(HO_OT_export_material_node_ir.bl_idname, text="MD", icon="TEXT")
        op.export_format = "MARKDOWN"
        op = layout.operator(
            HO_OT_export_material_node_ir.bl_idname,
            text="Export JSON + Markdown",
            icon="EXPORT",
        )
        op.export_format = "BOTH"


CLASSES = (
    HO_OT_export_material_node_ir,
    HO_PT_material_node_ir,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
