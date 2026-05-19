"""Pure-Python helpers for reading HoTools object/scene IR."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


IRDict = Dict[str, Any]


def load_ir(path: str | Path) -> IRDict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _counter_to_dict(counter: Counter) -> Dict[str, int]:
    return {str(key): value for key, value in sorted(counter.items())}


def summarize_ir(ir: IRDict) -> IRDict:
    objects = ir.get("objects", [])
    object_types = Counter()
    material_names = Counter()
    modifier_types = Counter()
    uv_names = Counter()
    color_attribute_names = Counter()
    attribute_names = Counter()
    geometry_node_modifiers = []
    totals = Counter()

    for obj in objects:
        object_types[obj.get("type")] += 1
        for slot in obj.get("material_slots", []):
            material = slot.get("material")
            if material:
                material_names[material.get("name")] += 1
        for modifier in obj.get("modifiers", []):
            modifier_types[modifier.get("type")] += 1
            if modifier.get("type") == "NODES":
                geometry_node_modifiers.append(
                    {
                        "object": obj.get("name"),
                        "modifier": modifier.get("name"),
                        "node_group": modifier.get("node_group"),
                    }
                )
        mesh = obj.get("mesh") or {}
        totals["vertices"] += mesh.get("vertex_count", 0) or 0
        totals["edges"] += mesh.get("edge_count", 0) or 0
        totals["polygons"] += mesh.get("polygon_count", 0) or 0
        totals["triangles"] += mesh.get("triangle_count", 0) or 0
        for uv in mesh.get("uv_layers", []):
            uv_names[uv.get("name")] += 1
        for attr in mesh.get("color_attributes", []):
            color_attribute_names[attr.get("name")] += 1
        for attr in mesh.get("attributes", []):
            if not attr.get("is_internal"):
                attribute_names[attr.get("name")] += 1

    return {
        "schema": ir.get("schema"),
        "scene": ir.get("scene", {}).get("name"),
        "scope": ir.get("export", {}).get("scope"),
        "object_count": len(objects),
        "object_type_counts": _counter_to_dict(object_types),
        "mesh_totals": dict(totals),
        "material_names": _counter_to_dict(material_names),
        "modifier_type_counts": _counter_to_dict(modifier_types),
        "uv_layer_names": _counter_to_dict(uv_names),
        "color_attribute_names": _counter_to_dict(color_attribute_names),
        "attribute_names": _counter_to_dict(attribute_names),
        "geometry_node_modifier_count": len(geometry_node_modifiers),
        "geometry_node_modifiers": geometry_node_modifiers,
    }


def audit_for_material_migration(ir: IRDict) -> IRDict:
    issues = []
    for obj in ir.get("objects", []):
        mesh = obj.get("mesh") or {}
        if obj.get("type") == "MESH" and not mesh.get("uv_layers"):
            issues.append(
                {
                    "severity": "medium",
                    "object": obj.get("name"),
                    "kind": "missing_uv",
                    "message": "Mesh has no UV layers; image-texture materials may not migrate correctly.",
                }
            )
        material_slots = obj.get("material_slots", [])
        if obj.get("type") == "MESH" and not material_slots:
            issues.append(
                {
                    "severity": "low",
                    "object": obj.get("name"),
                    "kind": "missing_material_slots",
                    "message": "Mesh has no material slots.",
                }
            )
        for modifier in obj.get("modifiers", []):
            if modifier.get("type") == "NODES":
                issues.append(
                    {
                        "severity": "high",
                        "object": obj.get("name"),
                        "kind": "geometry_nodes_modifier",
                        "modifier": modifier.get("name"),
                        "node_group": modifier.get("node_group"),
                        "message": "Geometry Nodes modifier exists; export a geometry-node IR before exact migration.",
                    }
                )
        shape_keys = mesh.get("shape_keys", {})
        if shape_keys.get("count", 0) > 1:
            issues.append(
                {
                    "severity": "medium",
                    "object": obj.get("name"),
                    "kind": "shape_keys",
                    "count": shape_keys.get("count"),
                    "message": "Shape keys may require mesh blend shape migration.",
                }
            )
    return {
        "scene": ir.get("scene", {}).get("name"),
        "issue_count": len(issues),
        "issues": issues,
    }


def build_preview(ir: IRDict) -> str:
    summary = summarize_ir(ir)
    audit = audit_for_material_migration(ir)
    lines = [
        f"# Object Scene Preview: {summary.get('scene')}",
        "",
        f"- Objects: `{summary['object_count']}`",
        f"- Types: `{json.dumps(summary['object_type_counts'], ensure_ascii=False)}`",
        f"- Mesh totals: `{json.dumps(summary['mesh_totals'], ensure_ascii=False)}`",
        f"- Materials: `{len(summary['material_names'])}` unique",
        f"- UV names: `{', '.join(summary['uv_layer_names'].keys())}`",
        f"- Color attributes: `{', '.join(summary['color_attribute_names'].keys())}`",
        f"- Attributes: `{', '.join(summary['attribute_names'].keys())}`",
        f"- Geometry Nodes modifiers: `{summary['geometry_node_modifier_count']}`",
        f"- Migration issues: `{audit['issue_count']}`",
    ]
    if audit["issues"]:
        lines.append("")
        lines.append("## Issues")
        for issue in audit["issues"][:30]:
            lines.append(f"- `{issue['severity']}` {issue['object']}: {issue['message']}")
    return "\n".join(lines).rstrip() + "\n"


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect HoTools object/scene IR JSON.")
    parser.add_argument("ir_json", help="Path to exported object scene IR JSON.")
    parser.add_argument(
        "--mode",
        choices=("summary", "audit", "preview"),
        default="preview",
    )
    args = parser.parse_args(argv)
    ir = load_ir(args.ir_json)
    if args.mode == "summary":
        print_json(summarize_ir(ir))
    elif args.mode == "audit":
        print_json(audit_for_material_migration(ir))
    else:
        print(build_preview(ir), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
