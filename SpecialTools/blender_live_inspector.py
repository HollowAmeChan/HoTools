"""Live Blender/Goo inspector for HoTools IR workflows.

Run inside the Blender Python runtime:

  blender --background scene.blend --python blender_live_inspector.py -- --mode materials

This script is intentionally file-light. It prints compact JSON to stdout and
does not create cache/state files. Use it when a full scene bundle would be too
large or when live Blender/Goo data should be compared with an exported IR.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

try:
    import bpy
except Exception as exc:  # pragma: no cover - only meaningful outside Blender.
    raise SystemExit(f"blender_live_inspector.py must run inside Blender/Goo Python: {exc}")


IRDict = Dict[str, Any]
TreePath = Tuple[str, ...]


CUSTOM_INPUT_NODE_IDS = {
    "ShaderNodeAttribute",
    "ShaderNodeCameraData",
    "ShaderNodeGeometry",
    "ShaderNodeNewGeometry",
    "ShaderNodeHairInfo",
    "ShaderNodeLayerWeight",
    "ShaderNodeLightPath",
    "ShaderNodeObjectInfo",
    "ShaderNodeParticleInfo",
    "ShaderNodePointInfo",
    "ShaderNodeTangent",
    "ShaderNodeTexCoord",
    "ShaderNodeUVAlongStroke",
    "ShaderNodeUVMap",
    "ShaderNodeVertexColor",
}

COLOR_TRANSFORM_NODE_IDS = {
    "ShaderNodeValToRGB",
    "ShaderNodeRGBCurve",
    "ShaderNodeFloatCurve",
    "ShaderNodeVectorCurve",
}

IMAGE_NODE_IDS = {"ShaderNodeTexImage", "ShaderNodeTexEnvironment"}
GOO_NODE_IDS = {"ShaderNodeShaderInfo", "ShaderNodeScreenspaceInfo"}


def _safe(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return repr(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        for encoding in ("utf-8", "latin-1"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                continue
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(_safe(key, depth + 1)): _safe(item, depth + 1) for key, item in value.items()}
    if hasattr(value, "to_tuple"):
        try:
            return [_safe(item, depth + 1) for item in value.to_tuple()]
        except Exception:
            pass
    return repr(value)


def app_metadata() -> IRDict:
    binary_path = _safe(getattr(bpy.app, "binary_path", ""))
    fields = {
        "binary_path": binary_path,
        "version_string": _safe(getattr(bpy.app, "version_string", "")),
        "version": _safe(getattr(bpy.app, "version", "")),
        "build_branch": _safe(getattr(bpy.app, "build_branch", "")),
        "build_hash": _safe(getattr(bpy.app, "build_hash", "")),
        "build_commit_date": _safe(getattr(bpy.app, "build_commit_date", "")),
        "build_commit_time": _safe(getattr(bpy.app, "build_commit_time", "")),
        "build_platform": _safe(getattr(bpy.app, "build_platform", "")),
        "build_type": _safe(getattr(bpy.app, "build_type", "")),
    }
    text = " ".join(str(value) for value in fields.values()).lower()
    fields["source_flavor_hint"] = "goo" if "goo" in text else "blender"
    return fields


def material_by_name(name: Optional[str]) -> Optional[Any]:
    if name:
        return bpy.data.materials.get(name)
    obj = bpy.context.object
    if obj and getattr(obj, "active_material", None):
        return obj.active_material
    return next((mat for mat in bpy.data.materials if mat.use_nodes), None)


def iter_node_trees(node_tree: Any, include_groups: bool = True, path: TreePath = ()) -> Iterator[Tuple[TreePath, Any]]:
    if not node_tree:
        return
    current_path = path or (getattr(node_tree, "name", "<node_tree>"),)
    yield current_path, node_tree
    if not include_groups:
        return
    for node in getattr(node_tree, "nodes", []):
        group_tree = getattr(node, "node_tree", None)
        if group_tree:
            next_path = current_path + (getattr(node, "name", "<group>"), getattr(group_tree, "name", "<group_tree>"))
            yield from iter_node_trees(group_tree, include_groups=True, path=next_path)


def iter_nodes(node_tree: Any, include_groups: bool = True) -> Iterator[Tuple[TreePath, Any]]:
    for tree_path, tree in iter_node_trees(node_tree, include_groups=include_groups):
        for node in getattr(tree, "nodes", []):
            yield tree_path, node


def socket_record(socket: Any, index: int) -> IRDict:
    return {
        "name": getattr(socket, "name", ""),
        "index": index,
        "identifier": getattr(socket, "identifier", ""),
        "type": getattr(socket, "type", ""),
        "is_linked": bool(getattr(socket, "is_linked", False)),
        "default_value": _safe(getattr(socket, "default_value", None)),
    }


def image_record(node: Any) -> Optional[IRDict]:
    image = getattr(node, "image", None)
    if not image:
        return None
    return {
        "node": getattr(node, "name", ""),
        "node_type": getattr(node, "bl_idname", ""),
        "image": getattr(image, "name", ""),
        "filepath": _safe(getattr(image, "filepath", "")),
        "filepath_from_user": _safe(getattr(image, "filepath_from_user", lambda: "")()),
        "size": _safe(getattr(image, "size", [])),
        "colorspace": getattr(getattr(image, "colorspace_settings", None), "name", ""),
        "alpha_mode": getattr(image, "alpha_mode", ""),
        "source": getattr(image, "source", ""),
        "type": getattr(image, "type", ""),
        "packed": bool(getattr(image, "packed_file", None)),
        "is_dirty": bool(getattr(image, "is_dirty", False)),
        "sampling": {
            "interpolation": _safe(getattr(node, "interpolation", "")),
            "extension": _safe(getattr(node, "extension", "")),
            "projection": _safe(getattr(node, "projection", "")),
            "projection_blend": _safe(getattr(node, "projection_blend", "")),
        },
    }


def group_name(node: Any) -> str:
    group_tree = getattr(node, "node_tree", None)
    return getattr(group_tree, "name", "") if group_tree else ""


def quick_material_summary(material: Any, include_groups: bool = True) -> IRDict:
    node_tree = getattr(material, "node_tree", None)
    nodes = list(iter_nodes(node_tree, include_groups=include_groups)) if node_tree else []
    trees = list(iter_node_trees(node_tree, include_groups=include_groups)) if node_tree else []
    node_type_counts = Counter(getattr(node, "bl_idname", "") for _, node in nodes)
    images = []
    groups = []
    custom_inputs = []
    color_transforms = []
    annotations = {"frame_count": 0, "labeled_node_count": 0, "colored_node_count": 0, "sample_frames": []}
    goo_nodes = []

    for tree_path, node in nodes:
        bl_idname = getattr(node, "bl_idname", "")
        node_type = getattr(node, "type", "")
        node_text = " ".join(
            item
            for item in (
                bl_idname,
                getattr(node, "name", ""),
                getattr(node, "label", ""),
                group_name(node),
            )
            if item
        )
        if bl_idname in IMAGE_NODE_IDS:
            record = image_record(node)
            if record:
                record["tree"] = " / ".join(tree_path)
                images.append(record)
        if bl_idname == "ShaderNodeGroup":
            groups.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": getattr(node, "name", ""),
                    "group_name": group_name(node),
                    "input_count": len(getattr(node, "inputs", [])),
                    "output_count": len(getattr(node, "outputs", [])),
                }
            )
        if bl_idname in CUSTOM_INPUT_NODE_IDS:
            custom_inputs.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": getattr(node, "name", ""),
                    "bl_idname": bl_idname,
                    "linked_outputs": [
                        socket_record(socket, index)
                        for index, socket in enumerate(getattr(node, "outputs", []))
                        if getattr(socket, "is_linked", False)
                    ],
                }
            )
        if bl_idname in COLOR_TRANSFORM_NODE_IDS:
            color_transforms.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": getattr(node, "name", ""),
                    "bl_idname": bl_idname,
                    "parent": getattr(getattr(node, "parent", None), "name", None),
                }
            )
        if node_type == "FRAME" or bl_idname == "NodeFrame":
            annotations["frame_count"] += 1
            if len(annotations["sample_frames"]) < 25:
                annotations["sample_frames"].append(
                    {
                        "tree": " / ".join(tree_path),
                        "node": getattr(node, "name", ""),
                        "label": getattr(node, "label", ""),
                        "color": _safe(getattr(node, "color", None)) if getattr(node, "use_custom_color", False) else None,
                    }
                )
        elif getattr(node, "label", ""):
            annotations["labeled_node_count"] += 1
        if getattr(node, "use_custom_color", False):
            annotations["colored_node_count"] += 1
        if (
            bl_idname in GOO_NODE_IDS
            or bl_idname == "NodeUndefined"
            or node_type == "CUSTOM"
            or any(word in node_text.lower() for word in ("goo", "toon", "matcap", "npr"))
        ):
            goo_nodes.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": getattr(node, "name", ""),
                    "label": getattr(node, "label", ""),
                    "bl_idname": bl_idname,
                    "type": node_type,
                    "inputs": [
                        socket_record(socket, index)
                        for index, socket in enumerate(getattr(node, "inputs", []))
                    ],
                    "outputs": [
                        socket_record(socket, index)
                        for index, socket in enumerate(getattr(node, "outputs", []))
                    ],
                }
            )

    return {
        "material": getattr(material, "name", ""),
        "use_nodes": bool(getattr(material, "use_nodes", False)),
        "node_tree": getattr(node_tree, "name", "") if node_tree else None,
        "tree_count": len(trees),
        "node_count": len(nodes),
        "link_count": sum(len(getattr(tree, "links", [])) for _, tree in trees),
        "node_type_counts": dict(node_type_counts.most_common()),
        "image_count": len(images),
        "images": images,
        "group_count": len(groups),
        "groups": groups[:100],
        "custom_input_count": len(custom_inputs),
        "custom_inputs": custom_inputs[:100],
        "color_transform_count": len(color_transforms),
        "color_transforms": color_transforms[:100],
        "annotations": annotations,
        "goo_signal_count": len(goo_nodes),
        "goo_signals": goo_nodes[:100],
    }


def scene_summary() -> IRDict:
    object_type_counts = Counter(obj.type for obj in bpy.context.scene.objects)
    material_slot_counts = Counter()
    uv_layer_names = Counter()
    color_attribute_names = Counter()
    attribute_names = Counter()
    modifier_type_counts = Counter()

    for obj in bpy.context.scene.objects:
        for slot in getattr(obj, "material_slots", []):
            if slot.material:
                material_slot_counts[slot.material.name] += 1
        mesh = obj.data if obj.type == "MESH" else None
        if mesh:
            for layer in getattr(mesh, "uv_layers", []):
                uv_layer_names[layer.name] += 1
            for attr in getattr(mesh, "color_attributes", []):
                color_attribute_names[attr.name] += 1
            for attr in getattr(mesh, "attributes", []):
                attribute_names[attr.name] += 1
        for modifier in getattr(obj, "modifiers", []):
            modifier_type_counts[modifier.type] += 1

    return {
        "scene": {
            "name": bpy.context.scene.name,
            "frame_current": bpy.context.scene.frame_current,
            "unit_system": bpy.context.scene.unit_settings.system,
        },
        "object_count": len(bpy.context.scene.objects),
        "material_count": len(bpy.data.materials),
        "object_type_counts": dict(object_type_counts),
        "material_slot_material_counts": dict(material_slot_counts),
        "uv_layer_names": dict(uv_layer_names),
        "color_attribute_names": dict(color_attribute_names),
        "attribute_names": dict(attribute_names),
        "modifier_type_counts": dict(modifier_type_counts),
    }


def list_materials(include_groups: bool = True) -> IRDict:
    materials = []
    for material in bpy.data.materials:
        if not material.use_nodes:
            materials.append({"name": material.name, "use_nodes": False})
            continue
        summary = quick_material_summary(material, include_groups=include_groups)
        materials.append(
            {
                "name": material.name,
                "use_nodes": True,
                "node_count": summary["node_count"],
                "tree_count": summary["tree_count"],
                "image_count": summary["image_count"],
                "group_count": summary["group_count"],
                "custom_input_count": summary["custom_input_count"],
                "color_transform_count": summary["color_transform_count"],
                "goo_signal_count": summary["goo_signal_count"],
                "top_node_types": list(summary["node_type_counts"].items())[:12],
            }
        )
    return {"materials": materials, "material_count": len(materials)}


def node_query(material: Any, pattern: str, include_groups: bool = True, limit: int = 80) -> IRDict:
    pattern_lower = pattern.lower()
    matches = []
    for tree_path, node in iter_nodes(material.node_tree, include_groups=include_groups):
        fields = [
            getattr(node, "name", ""),
            getattr(node, "label", ""),
            getattr(node, "bl_idname", ""),
            getattr(node, "type", ""),
            group_name(node),
        ]
        if pattern_lower not in " ".join(fields).lower():
            continue
        matches.append(
            {
                "tree": " / ".join(tree_path),
                "node": getattr(node, "name", ""),
                "label": getattr(node, "label", ""),
                "bl_idname": getattr(node, "bl_idname", ""),
                "type": getattr(node, "type", ""),
                "group_name": group_name(node),
                "inputs": [
                    socket_record(socket, index)
                    for index, socket in enumerate(getattr(node, "inputs", []))
                ],
                "outputs": [
                    socket_record(socket, index)
                    for index, socket in enumerate(getattr(node, "outputs", []))
                ],
            }
        )
        if len(matches) >= limit:
            break
    return {"material": material.name, "pattern": pattern, "match_count": len(matches), "matches": matches}


def _load_json(path: str) -> IRDict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _material_ir_summary(ir: IRDict) -> IRDict:
    nodes = []
    trees = []

    def walk(tree: IRDict, path: TreePath) -> None:
        trees.append((path, tree))
        for node in tree.get("nodes", []):
            nodes.append((path, node))
            group_tree = node.get("group_tree")
            if isinstance(group_tree, dict):
                walk(group_tree, path + (str(node.get("name", "")), str(group_tree.get("name", ""))))

    root = ir.get("node_tree") or {}
    walk(root, (str(root.get("name", "<node_tree>")),))
    node_type_counts = Counter(str(node.get("bl_idname", "")) for _, node in nodes)
    images = []
    groups = []
    goo_nodes = []
    for path, node in nodes:
        bl_idname = str(node.get("bl_idname", ""))
        node_type = str(node.get("type", ""))
        if bl_idname in IMAGE_NODE_IDS:
            image = node.get("image") or {}
            images.append(
                {
                    "tree": " / ".join(path),
                    "node": node.get("name"),
                    "image": image.get("name"),
                    "filepath": image.get("filepath"),
                    "colorspace": image.get("colorspace"),
                }
            )
        if bl_idname == "ShaderNodeGroup":
            group_tree = node.get("group_tree") or {}
            groups.append({"tree": " / ".join(path), "node": node.get("name"), "group_name": group_tree.get("name")})
        if bl_idname in GOO_NODE_IDS or bl_idname == "NodeUndefined" or node_type == "CUSTOM":
            goo_nodes.append({"tree": " / ".join(path), "node": node.get("name"), "bl_idname": bl_idname, "type": node_type})
    return {
        "schema": ir.get("schema"),
        "app": ir.get("app", {}),
        "material": (ir.get("material") or {}).get("name"),
        "tree_count": len(trees),
        "node_count": len(nodes),
        "link_count": sum(len(tree.get("links", [])) for _, tree in trees),
        "node_type_counts": dict(node_type_counts.most_common()),
        "image_count": len(images),
        "images": images,
        "group_count": len(groups),
        "groups": groups,
        "goo_node_count": len(goo_nodes),
        "goo_nodes": goo_nodes,
    }


def _diff_counts(live: IRDict, exported: IRDict, keys: Iterable[str]) -> List[IRDict]:
    diffs = []
    for key in keys:
        if live.get(key) != exported.get(key):
            diffs.append({"field": key, "live": live.get(key), "exported": exported.get(key)})
    return diffs


def _diff_counter_dict(live: IRDict, exported: IRDict, key: str) -> IRDict:
    live_counter = Counter(live.get(key, {}))
    exported_counter = Counter(exported.get(key, {}))
    added = {name: live_counter[name] - exported_counter.get(name, 0) for name in live_counter if live_counter[name] != exported_counter.get(name, 0)}
    removed = {name: exported_counter[name] - live_counter.get(name, 0) for name in exported_counter if exported_counter[name] != live_counter.get(name, 0)}
    return {"field": key, "live_delta": added, "exported_delta": removed}


def import_local_module(name: str) -> Any:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    return __import__(name)


def compare_material_ir(material: Any, ir_path: str, include_groups: bool = True) -> IRDict:
    material_node_ir = import_local_module("material_node_ir")
    live_ir = material_node_ir.build_material_ir(material, include_groups=include_groups)
    exported_ir = _load_json(ir_path)
    live_summary = _material_ir_summary(live_ir)
    exported_summary = _material_ir_summary(exported_ir)
    count_diffs = _diff_counts(live_summary, exported_summary, ("material", "tree_count", "node_count", "link_count", "image_count", "group_count", "goo_node_count"))
    type_diff = _diff_counter_dict(live_summary, exported_summary, "node_type_counts")
    image_live = Counter((item.get("image"), item.get("filepath"), item.get("colorspace")) for item in live_summary.get("images", []))
    image_exported = Counter((item.get("image"), item.get("filepath"), item.get("colorspace")) for item in exported_summary.get("images", []))
    group_live = Counter(item.get("group_name") for item in live_summary.get("groups", []))
    group_exported = Counter(item.get("group_name") for item in exported_summary.get("groups", []))
    return {
        "mode": "compare-material-ir",
        "material": material.name,
        "ir_path": ir_path,
        "live_app": live_summary.get("app"),
        "exported_app": exported_summary.get("app"),
        "match": not count_diffs and not type_diff["live_delta"] and not type_diff["exported_delta"] and image_live == image_exported and group_live == group_exported,
        "count_diffs": count_diffs,
        "node_type_diff": type_diff,
        "image_diff": {
            "live_only": [list(key) + [count] for key, count in (image_live - image_exported).items()],
            "exported_only": [list(key) + [count] for key, count in (image_exported - image_live).items()],
        },
        "group_diff": {
            "live_only": dict(group_live - group_exported),
            "exported_only": dict(group_exported - group_live),
        },
        "live_summary": {key: live_summary[key] for key in ("tree_count", "node_count", "link_count", "image_count", "group_count", "goo_node_count")},
        "exported_summary": {key: exported_summary[key] for key in ("tree_count", "node_count", "link_count", "image_count", "group_count", "goo_node_count")},
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Blender/Goo scene data live via bpy.")
    parser.add_argument("--mode", choices=("app", "scene", "materials", "material", "node", "compare-material-ir"), default="scene")
    parser.add_argument("--material", help="Material name. Defaults to active material, then first node material.")
    parser.add_argument("--node", help="Substring for --mode node.")
    parser.add_argument("--ir", help="Exported material IR JSON path for compare-material-ir.")
    parser.add_argument("--no-groups", action="store_true", help="Do not traverse nested node groups.")
    parser.add_argument("--limit", type=int, default=80, help="Maximum node query results.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    include_groups = not args.no_groups
    if args.mode == "app":
        result = {"mode": args.mode, "app": app_metadata()}
    elif args.mode == "scene":
        result = {"mode": args.mode, "app": app_metadata(), "summary": scene_summary()}
    elif args.mode == "materials":
        result = {"mode": args.mode, "app": app_metadata(), **list_materials(include_groups=include_groups)}
    else:
        material = material_by_name(args.material)
        if material is None:
            raise SystemExit(f"Material not found: {args.material or '<active/first node material>'}")
        if args.mode == "material":
            result = {"mode": args.mode, "app": app_metadata(), **quick_material_summary(material, include_groups=include_groups)}
        elif args.mode == "node":
            if not args.node:
                raise SystemExit("--mode node requires --node <substring>")
            result = {"mode": args.mode, "app": app_metadata(), **node_query(material, args.node, include_groups=include_groups, limit=args.limit)}
        elif args.mode == "compare-material-ir":
            if not args.ir:
                raise SystemExit("--mode compare-material-ir requires --ir <material_ir.json>")
            result = {"app": app_metadata(), **compare_material_ir(material, args.ir, include_groups=include_groups)}
        else:
            raise SystemExit(f"Unsupported mode: {args.mode}")
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
