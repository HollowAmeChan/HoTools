"""Pure-Python helpers for reading HoTools Geometry Nodes IR."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


IRDict = Dict[str, Any]
TreePath = Tuple[str, ...]

ZONE_NODE_TYPES = {
    "GeometryNodeSimulationInput",
    "GeometryNodeSimulationOutput",
    "GeometryNodeRepeatInput",
    "GeometryNodeRepeatOutput",
    "GeometryNodeForeachGeometryElementInput",
    "GeometryNodeForeachGeometryElementOutput",
    "GeometryNodeClosureInput",
    "GeometryNodeClosureOutput",
}

ATTRIBUTE_NODE_TYPES = {
    "GeometryNodeInputNamedAttribute",
    "GeometryNodeStoreNamedAttribute",
    "GeometryNodeRemoveAttribute",
    "GeometryNodeCaptureAttribute",
}

INSTANCE_NODE_TYPES = {
    "GeometryNodeInstanceOnPoints",
    "GeometryNodeInstancesToPoints",
    "GeometryNodeRealizeInstances",
    "GeometryNodeRotateInstances",
    "GeometryNodeScaleInstances",
    "GeometryNodeTranslateInstances",
}

SAMPLING_NODE_TYPES = {
    "GeometryNodeSampleIndex",
    "GeometryNodeSampleNearest",
    "GeometryNodeSampleNearestSurface",
    "GeometryNodeRaycast",
    "GeometryNodeProximity",
}

OUTPUT_AFFECTING_TYPES = {
    "GeometryNodeSetMaterial",
    "GeometryNodeSetMaterialIndex",
    "GeometryNodeSetPosition",
    "GeometryNodeSetShadeSmooth",
    "GeometryNodeSetCurveRadius",
    "GeometryNodeSetCurveTilt",
    "GeometryNodeStoreNamedAttribute",
    "GeometryNodeRemoveAttribute",
    "GeometryNodeDeleteGeometry",
    "GeometryNodeJoinGeometry",
    "GeometryNodeRealizeInstances",
}


def load_ir(path: str | Path) -> IRDict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _counter_to_dict(counter: Counter) -> Dict[str, int]:
    return {str(key): value for key, value in sorted(counter.items())}


def iter_node_trees(tree: IRDict, include_groups: bool = True, path: TreePath = ()) -> Iterator[Tuple[TreePath, IRDict]]:
    if not tree:
        return
    current_path = path or (str(tree.get("name", "<node_tree>")),)
    yield current_path, tree
    if not include_groups:
        return
    for node in tree.get("nodes", []):
        group_tree = node.get("group_tree")
        if group_tree:
            yield from iter_node_trees(group_tree, include_groups=True, path=current_path + (node.get("name", "<group>"),))


def iter_modifier_trees(ir: IRDict, include_groups: bool = True) -> Iterator[Tuple[IRDict, TreePath, IRDict]]:
    for modifier in ir.get("modifiers", []):
        tree = modifier.get("node_tree")
        if not tree:
            continue
        for path, node_tree in iter_node_trees(tree, include_groups=include_groups):
            yield modifier, path, node_tree


def iter_nodes(ir: IRDict, include_groups: bool = True) -> Iterator[Tuple[IRDict, TreePath, IRDict]]:
    for modifier, path, tree in iter_modifier_trees(ir, include_groups=include_groups):
        for node in tree.get("nodes", []):
            yield modifier, path, node


def _node_type_counts(ir: IRDict, include_groups: bool = True) -> Counter:
    counts = Counter()
    for _, _, node in iter_nodes(ir, include_groups=include_groups):
        counts[node.get("bl_idname")] += 1
    return counts


def summarize_ir(ir: IRDict) -> IRDict:
    node_types = _node_type_counts(ir)
    zone_counts = Counter()
    tree_count = 0
    link_count = 0
    node_count = 0
    modifiers = []

    for modifier in ir.get("modifiers", []):
        obj = modifier.get("object") or {}
        mod = modifier.get("modifier") or {}
        summary = modifier.get("summary") or {}
        modifiers.append(
            {
                "object": obj.get("name"),
                "modifier": mod.get("name"),
                "node_group": (mod.get("node_group") or {}).get("name"),
                "node_count": summary.get("node_count", 0),
                "link_count": summary.get("link_count", 0),
                "zone_counts": summary.get("zone_counts", {}),
                "export_error": modifier.get("export_error"),
            }
        )
        node_count += summary.get("node_count", 0) or 0
        link_count += summary.get("link_count", 0) or 0
        tree_count += summary.get("tree_count", 0) or 0
        for kind, count in (summary.get("zone_counts") or {}).items():
            zone_counts[kind] += count

    return {
        "schema": ir.get("schema"),
        "scene": ir.get("scene", {}).get("name"),
        "scope": ir.get("export", {}).get("scope"),
        "modifier_count": len(ir.get("modifiers", [])),
        "tree_count": tree_count,
        "node_count": node_count,
        "link_count": link_count,
        "zone_counts": _counter_to_dict(zone_counts),
        "node_type_counts": _counter_to_dict(node_types),
        "modifiers": modifiers,
        "export_failures": ir.get("export_failures", []),
    }


def collect_zones(ir: IRDict) -> List[IRDict]:
    zones = []
    for modifier, path, tree in iter_modifier_trees(ir, include_groups=True):
        obj = modifier.get("object") or {}
        mod = modifier.get("modifier") or {}
        for zone in tree.get("zones", []):
            zones.append(
                {
                    "object": obj.get("name"),
                    "modifier": mod.get("name"),
                    "tree_path": " / ".join(path),
                    **zone,
                }
            )
    return zones


def _collect_node_hits(ir: IRDict, node_types: Iterable[str]) -> List[IRDict]:
    wanted = set(node_types)
    hits = []
    for modifier, path, node in iter_nodes(ir, include_groups=True):
        if node.get("bl_idname") not in wanted:
            continue
        obj = modifier.get("object") or {}
        mod = modifier.get("modifier") or {}
        hits.append(
            {
                "object": obj.get("name"),
                "modifier": mod.get("name"),
                "tree_path": " / ".join(path),
                "node": node.get("name"),
                "label": node.get("label"),
                "bl_idname": node.get("bl_idname"),
                "properties": node.get("properties", {}),
                "inputs": node.get("inputs", []),
                "outputs": node.get("outputs", []),
                "item_collections": node.get("item_collections", {}),
            }
        )
    return hits


def _socket_by_name(node: IRDict, in_out: str, name: str) -> Optional[IRDict]:
    for socket in node.get(in_out, []):
        if socket.get("name") == name or socket.get("identifier") == name:
            return socket
    return None


def _socket_default(node: IRDict, in_out: str, name: str) -> Any:
    socket = _socket_by_name(node, in_out, name)
    if not socket:
        return None
    return socket.get("default_value")


def _attribute_name_from_node(node: IRDict) -> Optional[str]:
    value = _socket_default(node, "inputs", "Name")
    if value is None:
        return None
    return str(value)


def _annotate_attribute_hit(hit: IRDict) -> IRDict:
    annotated = dict(hit)
    annotated["attribute_name"] = _attribute_name_from_node(hit)
    annotated["data_type"] = hit.get("properties", {}).get("data_type")
    annotated["domain"] = hit.get("properties", {}).get("domain")
    return annotated


def audit_for_migration(ir: IRDict) -> IRDict:
    issues = []
    zones = collect_zones(ir)
    for zone in zones:
        severity = "high"
        if zone.get("kind") in {"repeat", "closure"}:
            severity = "medium"
        issues.append(
            {
                "severity": severity,
                "kind": f"{zone.get('kind')}_zone",
                "object": zone.get("object"),
                "modifier": zone.get("modifier"),
                "tree_path": zone.get("tree_path"),
                "message": "Zone nodes describe procedural execution flow; export structure is preserved, but Unity/glTF migration needs a custom bake or runtime strategy.",
            }
        )

    for hit in (_annotate_attribute_hit(item) for item in _collect_node_hits(ir, ATTRIBUTE_NODE_TYPES)):
        issues.append(
            {
                "severity": "high",
                "kind": "attribute_read_write",
                "object": hit.get("object"),
                "modifier": hit.get("modifier"),
                "node": hit.get("node"),
                "bl_idname": hit.get("bl_idname"),
                "attribute_name": hit.get("attribute_name"),
                "domain": hit.get("domain"),
                "data_type": hit.get("data_type"),
                "message": "Named/captured/stored attributes affect generated mesh data; verify equivalent vertex streams or bake result.",
            }
        )

    for hit in _collect_node_hits(ir, INSTANCE_NODE_TYPES):
        issues.append(
            {
                "severity": "medium",
                "kind": "instances",
                "object": hit.get("object"),
                "modifier": hit.get("modifier"),
                "node": hit.get("node"),
                "bl_idname": hit.get("bl_idname"),
                "message": "Instances may need realization or custom import handling before Unity migration.",
            }
        )

    for hit in _collect_node_hits(ir, SAMPLING_NODE_TYPES):
        issues.append(
            {
                "severity": "medium",
                "kind": "sampling_or_raycast",
                "object": hit.get("object"),
                "modifier": hit.get("modifier"),
                "node": hit.get("node"),
                "bl_idname": hit.get("bl_idname"),
                "message": "Sampling/proximity/raycast logic is procedural and usually cannot be represented directly in glTF.",
            }
        )

    for hit in _collect_node_hits(ir, {"GeometryNodeBake"}):
        issues.append(
            {
                "severity": "medium",
                "kind": "bake_node",
                "object": hit.get("object"),
                "modifier": hit.get("modifier"),
                "node": hit.get("node"),
                "message": "Bake node exists; check whether cached results or live procedural output should be migrated.",
            }
        )

    for modifier in ir.get("modifiers", []):
        if modifier.get("export_error"):
            obj = modifier.get("object") or {}
            mod = modifier.get("modifier") or {}
            issues.append(
                {
                    "severity": "high",
                    "kind": "export_error",
                    "object": obj.get("name"),
                    "modifier": mod.get("name"),
                    "message": modifier.get("export_error"),
                }
            )

    return {
        "scene": ir.get("scene", {}).get("name"),
        "issue_count": len(issues),
        "issues": issues,
    }


def collect_output_effects(ir: IRDict) -> IRDict:
    return {
        "output_affecting_nodes": _collect_node_hits(ir, OUTPUT_AFFECTING_TYPES),
        "attribute_nodes": [
            _annotate_attribute_hit(item)
            for item in _collect_node_hits(ir, ATTRIBUTE_NODE_TYPES)
        ],
        "instance_nodes": _collect_node_hits(ir, INSTANCE_NODE_TYPES),
        "sampling_nodes": _collect_node_hits(ir, SAMPLING_NODE_TYPES),
    }


def build_preview(ir: IRDict) -> str:
    summary = summarize_ir(ir)
    audit = audit_for_migration(ir)
    lines = [
        f"# Geometry Nodes Preview: {summary.get('scene')}",
        "",
        f"- Modifiers: `{summary['modifier_count']}`",
        f"- Trees: `{summary['tree_count']}`",
        f"- Nodes: `{summary['node_count']}`",
        f"- Links: `{summary['link_count']}`",
        f"- Zones: `{json.dumps(summary['zone_counts'], ensure_ascii=False)}`",
        f"- Migration issues: `{audit['issue_count']}`",
        "",
        "## Modifiers",
    ]
    for record in summary["modifiers"][:40]:
        lines.append(
            f"- `{record.get('object')}` / `{record.get('modifier')}` group=`{record.get('node_group')}` "
            f"nodes=`{record.get('node_count')}` zones=`{json.dumps(record.get('zone_counts'), ensure_ascii=False)}`"
        )
    if audit["issues"]:
        lines.append("")
        lines.append("## Issues")
        for issue in audit["issues"][:40]:
            where = " / ".join(str(issue.get(key, "")) for key in ("object", "modifier", "node") if issue.get(key))
            lines.append(f"- `{issue['severity']}` {where}: {issue['message']}")
    return "\n".join(lines).rstrip() + "\n"


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect HoTools Geometry Nodes IR JSON.")
    parser.add_argument("ir_json", help="Path to exported geometry node IR JSON.")
    parser.add_argument(
        "--mode",
        choices=("summary", "audit", "preview", "zones", "effects"),
        default="preview",
    )
    args = parser.parse_args(argv)
    ir = load_ir(args.ir_json)
    if args.mode == "summary":
        print_json(summarize_ir(ir))
    elif args.mode == "audit":
        print_json(audit_for_migration(ir))
    elif args.mode == "zones":
        print_json(collect_zones(ir))
    elif args.mode == "effects":
        print_json(collect_output_effects(ir))
    else:
        print(build_preview(ir), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
