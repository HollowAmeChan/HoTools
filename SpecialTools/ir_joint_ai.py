"""Joint analysis for HoTools IR files.

This module composes the specialized helpers:
- material_ir_ai.py for material node graphs.
- object_scene_ir_ai.py for object/mesh/scene context.

It intentionally stays pure Python and does not import Blender.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import material_ir_ai
import object_scene_ir_ai


IRDict = Dict[str, Any]


def _load_json(path: str | Path) -> IRDict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _material_name(ir: IRDict) -> str:
    return str(ir.get("material", {}).get("name", "<unnamed material>"))


def _object_mesh_names(obj: IRDict, key: str) -> List[str]:
    mesh = obj.get("mesh") or {}
    return [str(item.get("name", "")) for item in mesh.get(key, []) if item.get("name")]


def _object_attribute_names(obj: IRDict) -> List[str]:
    names = set(_object_mesh_names(obj, "attributes"))
    names.update(_object_mesh_names(obj, "color_attributes"))
    names.update(str(key) for key in obj.get("custom_properties", {}).keys())
    for modifier in obj.get("modifiers", []):
        names.update(str(key) for key in modifier.get("custom_properties", {}).keys())
    return sorted(names)


def _objects_using_material(object_scene_ir: Optional[IRDict], material_name: str) -> List[IRDict]:
    if not object_scene_ir:
        return []
    result = []
    for obj in object_scene_ir.get("objects", []):
        for slot in obj.get("material_slots", []):
            material = slot.get("material")
            if material and material.get("name") == material_name:
                result.append(obj)
                break
    return result


def extract_material_context_requirements(material_ir: IRDict) -> IRDict:
    """Extract object/scene context required by a material graph."""
    requirements = {
        "material": _material_name(material_ir),
        "attribute_names": [],
        "uv_map_names": [],
        "needs_default_uv": False,
        "texture_coordinate_outputs": [],
        "geometry_outputs": [],
        "needs_tangent": False,
        "needs_camera_data": False,
        "needs_gn_or_custom_shader_review": False,
        "goo_unknown_nodes": [],
    }

    for _, node in material_ir_ai.iter_nodes(material_ir, include_groups=True):
        bl_idname = node.get("bl_idname")
        props = node.get("properties", {})
        if bl_idname == "ShaderNodeAttribute":
            name = props.get("attribute_name")
            if name:
                requirements["attribute_names"].append(str(name))
        elif bl_idname == "ShaderNodeUVMap":
            uv_map = props.get("uv_map") or ""
            if uv_map:
                requirements["uv_map_names"].append(str(uv_map))
            else:
                requirements["needs_default_uv"] = True
        elif bl_idname == "ShaderNodeTexCoord":
            for socket in node.get("outputs", []):
                if socket.get("is_linked"):
                    requirements["texture_coordinate_outputs"].append(str(socket.get("name")))
                    if socket.get("name") == "UV":
                        requirements["needs_default_uv"] = True
        elif bl_idname in {"ShaderNodeGeometry", "ShaderNodeNewGeometry"}:
            for socket in node.get("outputs", []):
                if socket.get("is_linked"):
                    requirements["geometry_outputs"].append(str(socket.get("name")))
        elif bl_idname == "ShaderNodeTangent":
            requirements["needs_tangent"] = True
        elif bl_idname == "ShaderNodeCameraData":
            requirements["needs_camera_data"] = True

    goo = material_ir_ai.analyze_goo_engine(material_ir, include_groups=True)
    requirements["goo_unknown_nodes"] = goo.get("unknown_shader_nodes", [])
    requirements["needs_gn_or_custom_shader_review"] = bool(
        requirements["goo_unknown_nodes"]
        or goo.get("unresolved_custom_nodes")
        or goo.get("suspicion", {}).get("level") in {"possible", "strong"}
    )

    for key in ("attribute_names", "uv_map_names", "texture_coordinate_outputs", "geometry_outputs"):
        requirements[key] = sorted(set(item for item in requirements[key] if item))
    return requirements


def _check_uv_requirements(material_name: str, requirements: IRDict, objects: List[IRDict]) -> List[IRDict]:
    issues = []
    if not objects:
        return issues
    for obj in objects:
        if obj.get("type") != "MESH":
            continue
        uv_names = _object_mesh_names(obj, "uv_layers")
        if requirements.get("needs_default_uv") and not uv_names:
            issues.append(
                {
                    "severity": "high",
                    "material": material_name,
                    "object": obj.get("name"),
                    "kind": "missing_default_uv",
                    "message": "Material uses default/texture-coordinate UV, but this mesh has no UV layer.",
                }
            )
        for uv_name in requirements.get("uv_map_names", []):
            if uv_name not in uv_names:
                issues.append(
                    {
                        "severity": "high",
                        "material": material_name,
                        "object": obj.get("name"),
                        "kind": "missing_named_uv",
                        "uv_map": uv_name,
                        "message": f"Material requires UV map '{uv_name}', but object mesh does not expose it.",
                    }
                )
    return issues


def _check_attribute_requirements(material_name: str, requirements: IRDict, objects: List[IRDict]) -> List[IRDict]:
    issues = []
    if not objects:
        return issues
    for attr_name in requirements.get("attribute_names", []):
        missing = []
        present_somewhere = False
        for obj in objects:
            if obj.get("type") != "MESH":
                continue
            object_attrs = _object_attribute_names(obj)
            if attr_name in object_attrs:
                present_somewhere = True
            else:
                missing.append(obj.get("name"))
        if missing:
            severity = "medium" if present_somewhere else "high"
            issues.append(
                {
                    "severity": severity,
                    "material": material_name,
                    "kind": "attribute_missing_or_global",
                    "attribute": attr_name,
                    "missing_objects": missing,
                    "message": (
                        f"Material references Attribute '{attr_name}'. It is missing on some assigned objects, "
                        "or it may need to be supplied as a global/object parameter."
                    ),
                }
            )
    return issues


def _check_object_modifiers(material_name: str, objects: List[IRDict]) -> List[IRDict]:
    issues = []
    for obj in objects:
        for modifier in obj.get("modifiers", []):
            if modifier.get("type") == "NODES":
                issues.append(
                    {
                        "severity": "high",
                        "material": material_name,
                        "object": obj.get("name"),
                        "kind": "geometry_nodes_modifier",
                        "modifier": modifier.get("name"),
                        "node_group": modifier.get("node_group"),
                        "message": "Assigned object has Geometry Nodes modifier; export Geometry Nodes IR for exact migration.",
                    }
                )
    return issues


def cross_audit_material_object(material_ir: IRDict, object_scene_ir: Optional[IRDict]) -> IRDict:
    material_name = _material_name(material_ir)
    requirements = extract_material_context_requirements(material_ir)
    assigned_objects = _objects_using_material(object_scene_ir, material_name)
    issues = []

    if object_scene_ir is not None and not assigned_objects:
        issues.append(
            {
                "severity": "medium",
                "material": material_name,
                "kind": "material_not_assigned",
                "message": "Material IR name was not found in any Object Scene IR material slot.",
            }
        )

    issues.extend(_check_uv_requirements(material_name, requirements, assigned_objects))
    issues.extend(_check_attribute_requirements(material_name, requirements, assigned_objects))
    issues.extend(_check_object_modifiers(material_name, assigned_objects))

    if requirements.get("texture_coordinate_outputs"):
        outputs = ", ".join(requirements["texture_coordinate_outputs"])
        issues.append(
            {
                "severity": "info",
                "material": material_name,
                "kind": "texture_coordinate_context",
                "outputs": requirements["texture_coordinate_outputs"],
                "message": f"Material uses Texture Coordinate outputs: {outputs}. Target shader must provide equivalent coordinate spaces.",
            }
        )
    if requirements.get("geometry_outputs"):
        issues.append(
            {
                "severity": "info",
                "material": material_name,
                "kind": "geometry_context",
                "outputs": requirements["geometry_outputs"],
                "message": "Material uses Geometry node outputs; target shader needs equivalent per-fragment geometry data.",
            }
        )
    if requirements.get("needs_camera_data"):
        issues.append(
            {
                "severity": "medium",
                "material": material_name,
                "kind": "camera_context",
                "message": "Material uses Camera Data; target shader needs camera/view-vector support.",
            }
        )
    if requirements.get("goo_unknown_nodes"):
        issues.append(
            {
                "severity": "high",
                "material": material_name,
                "kind": "goo_unknown_nodes",
                "count": len(requirements["goo_unknown_nodes"]),
                "message": "Material contains Goo/fork-specific shader nodes; inspect source or custom shader equivalents.",
            }
        )

    return {
        "material": material_name,
        "assigned_object_count": len(assigned_objects),
        "assigned_objects": [obj.get("name") for obj in assigned_objects],
        "requirements": requirements,
        "issue_count": len(issues),
        "issues": issues,
    }


def _analyze_material_record(
    material_ir: IRDict,
    label: str,
    object_scene_ir: Optional[IRDict],
    include_translation_view: bool,
) -> IRDict:
    summary = material_ir_ai.summarize_ir(material_ir, include_groups=True)
    goo = material_ir_ai.analyze_goo_engine(material_ir, include_groups=True)
    images = material_ir_ai.analyze_images(material_ir, include_groups=True)
    pbr = material_ir_ai.extract_gltf_pbr_candidates(material_ir)
    translation_stats = None
    if include_translation_view:
        translation_stats = material_ir_ai.build_translation_view(material_ir, include_groups=True).get("stats")
    return {
        "path": label,
        "material": _material_name(material_ir),
        "summary": summary,
        "pbr_candidates": pbr,
        "goo_engine": goo,
        "images": {
            "image_count": images.get("image_count"),
            "duplicate_image_count": images.get("duplicate_image_count"),
            "packed_image_count": sum(1 for image in images.get("images", []) if image.get("packed")),
        },
        "translation_view_stats": translation_stats,
        "cross_audit": cross_audit_material_object(material_ir, object_scene_ir),
    }


def analyze_joint_from_irs(
    material_items: Iterable[tuple[str, IRDict]],
    object_scene_ir: Optional[IRDict] = None,
    *,
    include_translation_view: bool = True,
    input_labels: Optional[IRDict] = None,
) -> IRDict:
    material_records = [
        _analyze_material_record(material_ir, label, object_scene_ir, include_translation_view)
        for label, material_ir in material_items
    ]

    object_summary = object_scene_ir_ai.summarize_ir(object_scene_ir) if object_scene_ir else None
    object_audit = object_scene_ir_ai.audit_for_material_migration(object_scene_ir) if object_scene_ir else None
    all_issues = []
    if object_audit:
        all_issues.extend(object_audit.get("issues", []))
    for record in material_records:
        all_issues.extend(record.get("cross_audit", {}).get("issues", []))

    return {
        "schema": "hotools.ir_joint_analysis.v1",
        "inputs": input_labels or {},
        "object_scene": {
            "summary": object_summary,
            "audit": object_audit,
        },
        "materials": material_records,
        "issue_count": len(all_issues),
        "issues": all_issues,
    }


def analyze_joint(
    material_paths: Iterable[str | Path],
    object_scene_path: Optional[str | Path] = None,
    *,
    include_translation_view: bool = True,
) -> IRDict:
    object_scene_ir = _load_json(object_scene_path) if object_scene_path else None
    material_items = [(str(path), _load_json(path)) for path in material_paths]
    return analyze_joint_from_irs(
        material_items,
        object_scene_ir,
        include_translation_view=include_translation_view,
        input_labels={
            "materials": [str(path) for path in material_paths],
            "object_scene": str(object_scene_path) if object_scene_path else None,
        },
    )


def analyze_scene_bundle(
    scene_bundle_path: str | Path,
    *,
    include_translation_view: bool = True,
) -> IRDict:
    bundle = _load_json(scene_bundle_path)
    object_scene_ir = bundle.get("object_scene")
    material_items = []
    skipped = []
    for record in bundle.get("materials", []):
        material_ir = record.get("ir")
        if material_ir:
            material_items.append((f"{scene_bundle_path}#{record.get('name')}", material_ir))
        else:
            skipped.append(record.get("name"))
    report = analyze_joint_from_irs(
        material_items,
        object_scene_ir,
        include_translation_view=include_translation_view,
        input_labels={
            "scene_bundle": str(scene_bundle_path),
            "materials_from_bundle": len(material_items),
            "materials_without_node_ir": skipped,
        },
    )
    report["scene_bundle"] = {
        "schema": bundle.get("schema"),
        "export": bundle.get("export"),
        "material_export_failures": bundle.get("material_export_failures", []),
    }
    return report


def build_preview(report: IRDict) -> str:
    object_summary = report.get("object_scene", {}).get("summary")
    lines = [
        "# HoTools Joint IR Preview",
        "",
        f"- Materials: `{len(report.get('materials', []))}`",
        f"- Object Scene: `{'yes' if object_summary else 'no'}`",
        f"- Total issues: `{report.get('issue_count', 0)}`",
    ]
    if object_summary:
        lines.extend(
            [
                f"- Objects: `{object_summary.get('object_count')}`",
                f"- Mesh totals: `{json.dumps(object_summary.get('mesh_totals', {}), ensure_ascii=False)}`",
                f"- Geometry Nodes modifiers: `{object_summary.get('geometry_node_modifier_count')}`",
            ]
        )
    lines.append("")
    lines.append("## Materials")
    for record in report.get("materials", []):
        cross = record.get("cross_audit", {})
        translation = record.get("translation_view_stats") or {}
        lines.append(f"- `{record.get('material')}`: assigned_objects=`{cross.get('assigned_object_count')}`, cross_issues=`{cross.get('issue_count')}`, reroutes_removed=`{translation.get('reroute_count_removed', 'n/a')}`")
    if report.get("issues"):
        lines.append("")
        lines.append("## Top Issues")
        severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        issues = sorted(report["issues"], key=lambda item: severity_order.get(item.get("severity"), 9))
        for issue in issues[:40]:
            label = issue.get("material") or issue.get("object") or issue.get("kind")
            lines.append(f"- `{issue.get('severity', 'info')}` {label}: {issue.get('message')}")
    return "\n".join(lines).rstrip() + "\n"


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Jointly inspect HoTools material and object/scene IR JSON files.")
    parser.add_argument(
        "--material",
        action="append",
        default=[],
        help="Path to a material node IR JSON. Repeat for multiple materials.",
    )
    parser.add_argument(
        "--object-scene",
        help="Path to an object scene IR JSON.",
    )
    parser.add_argument(
        "--scene-bundle",
        help="Path to a scene asset bundle IR JSON exported by Object Scene IR.",
    )
    parser.add_argument(
        "--mode",
        choices=("preview", "summary", "audit", "bundle"),
        default="preview",
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Skip material translation-view statistics.",
    )
    args = parser.parse_args(argv)
    if args.scene_bundle and (args.material or args.object_scene):
        parser.error("Use either --scene-bundle, or --material/--object-scene inputs, not both.")
    if not args.scene_bundle and not args.material and not args.object_scene:
        parser.error("Provide --scene-bundle, or at least --material or --object-scene.")

    if args.scene_bundle:
        report = analyze_scene_bundle(
            args.scene_bundle,
            include_translation_view=not args.no_translate,
        )
    else:
        report = analyze_joint(
            args.material,
            args.object_scene,
            include_translation_view=not args.no_translate,
        )

    if args.mode == "preview":
        print(build_preview(report), end="")
    elif args.mode == "summary":
        summary = {
            "schema": report["schema"],
            "inputs": report["inputs"],
            "object_scene_summary": report.get("object_scene", {}).get("summary"),
            "materials": [
                {
                    "material": record.get("material"),
                    "node_count": record.get("summary", {}).get("node_count"),
                    "image_count": record.get("images", {}).get("image_count"),
                    "goo_level": record.get("goo_engine", {}).get("suspicion", {}).get("level"),
                    "assigned_object_count": record.get("cross_audit", {}).get("assigned_object_count"),
                    "cross_issue_count": record.get("cross_audit", {}).get("issue_count"),
                    "translation_view_stats": record.get("translation_view_stats"),
                }
                for record in report.get("materials", [])
            ],
            "issue_count": report.get("issue_count", 0),
        }
        print_json(summary)
    elif args.mode == "audit":
        print_json({"issue_count": report.get("issue_count", 0), "issues": report.get("issues", [])})
    else:
        print_json(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
