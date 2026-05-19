"""Pure-Python helpers for reading HoTools Compositor Node IR."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


IRDict = Dict[str, Any]
TreePath = Tuple[str, ...]

INPUT_NODE_TYPES = {
    "CompositorNodeImage",
    "CompositorNodeMovieClip",
    "CompositorNodeMask",
    "CompositorNodeRLayers",
    "CompositorNodeTexture",
    "CompositorNodeBokehImage",
}

OUTPUT_NODE_TYPES = {
    "CompositorNodeComposite",
    "CompositorNodeViewer",
    "CompositorNodeOutputFile",
    "CompositorNodeSplitViewer",
}

COLOR_NODE_TYPES = {
    "CompositorNodeBrightContrast",
    "CompositorNodeColorBalance",
    "CompositorNodeColorCorrection",
    "CompositorNodeCurveRGB",
    "CompositorNodeHueSat",
    "CompositorNodeTonemap",
    "CompositorNodeExposure",
    "CompositorNodeGamma",
    "CompositorNodeInvert",
    "CompositorNodePosterize",
    "CompositorNodeValToRGB",
}

FILTER_NODE_TYPES = {
    "CompositorNodeBlur",
    "CompositorNodeBilateralblur",
    "CompositorNodeBokehBlur",
    "CompositorNodeDBlur",
    "CompositorNodeDefocus",
    "CompositorNodeDenoise",
    "CompositorNodeDespeckle",
    "CompositorNodeDilateErode",
    "CompositorNodeFilter",
    "CompositorNodeGlare",
    "CompositorNodeKuwahara",
    "CompositorNodeLensdist",
    "CompositorNodeSunBeams",
    "CompositorNodeVecBlur",
}

KEYING_MASK_NODE_TYPES = {
    "CompositorNodeChromaMatte",
    "CompositorNodeColorMatte",
    "CompositorNodeColorSpill",
    "CompositorNodeCryptomatte",
    "CompositorNodeCryptomatteV2",
    "CompositorNodeDiffMatte",
    "CompositorNodeDistanceMatte",
    "CompositorNodeKeying",
    "CompositorNodeKeyingScreen",
    "CompositorNodeLumaMatte",
}

TRANSFORM_NODE_TYPES = {
    "CompositorNodeCrop",
    "CompositorNodeFlip",
    "CompositorNodeMapUV",
    "CompositorNodePlaneTrackDeform",
    "CompositorNodeRotate",
    "CompositorNodeScale",
    "CompositorNodeStabilize",
    "CompositorNodeTransform",
    "CompositorNodeTranslate",
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


def iter_nodes(ir: IRDict, include_groups: bool = True) -> Iterator[Tuple[TreePath, IRDict]]:
    root = ir.get("node_tree") or {}
    for path, tree in iter_node_trees(root, include_groups=include_groups):
        for node in tree.get("nodes", []):
            yield path, node


def summarize_ir(ir: IRDict) -> IRDict:
    node_types = Counter()
    muted = []
    framed = Counter()
    link_count = 0
    tree_count = 0
    node_count = 0
    for path, tree in iter_node_trees(ir.get("node_tree") or {}, include_groups=True):
        tree_count += 1
        nodes = tree.get("nodes", [])
        node_count += len(nodes)
        link_count += len(tree.get("links", []))
        for node in nodes:
            node_types[node.get("bl_idname")] += 1
            if node.get("mute"):
                muted.append({"tree_path": " / ".join(path), "node": node.get("name"), "bl_idname": node.get("bl_idname")})
            if node.get("parent"):
                framed[node.get("parent")] += 1
    return {
        "schema": ir.get("schema"),
        "scene": ir.get("scene", {}).get("name"),
        "tree_count": tree_count,
        "node_count": node_count,
        "link_count": link_count,
        "node_type_counts": _counter_to_dict(node_types),
        "muted_nodes": muted,
        "frame_child_counts": _counter_to_dict(framed),
    }


def _node_ref(path: TreePath, node: IRDict) -> IRDict:
    return {
        "tree_path": " / ".join(path),
        "node": node.get("name"),
        "label": node.get("label"),
        "bl_idname": node.get("bl_idname"),
        "mute": node.get("mute"),
        "properties": node.get("properties", {}),
        "datablocks": node.get("datablocks", {}),
    }


def collect_io(ir: IRDict) -> IRDict:
    inputs = []
    outputs = []
    for path, node in iter_nodes(ir, include_groups=True):
        bl_idname = node.get("bl_idname")
        if bl_idname in INPUT_NODE_TYPES:
            inputs.append(_node_ref(path, node))
        if bl_idname in OUTPUT_NODE_TYPES:
            outputs.append(_node_ref(path, node))
    return {"inputs": inputs, "outputs": outputs}


def collect_effects(ir: IRDict) -> IRDict:
    effects = {
        "color_nodes": [],
        "filter_nodes": [],
        "keying_mask_nodes": [],
        "transform_nodes": [],
    }
    for path, node in iter_nodes(ir, include_groups=True):
        bl_idname = node.get("bl_idname")
        ref = _node_ref(path, node)
        if bl_idname in COLOR_NODE_TYPES:
            effects["color_nodes"].append(ref)
        if bl_idname in FILTER_NODE_TYPES:
            effects["filter_nodes"].append(ref)
        if bl_idname in KEYING_MASK_NODE_TYPES:
            effects["keying_mask_nodes"].append(ref)
        if bl_idname in TRANSFORM_NODE_TYPES:
            effects["transform_nodes"].append(ref)
    return effects


def audit_for_migration(ir: IRDict) -> IRDict:
    issues = []
    io = collect_io(ir)
    effects = collect_effects(ir)

    if not io["outputs"]:
        issues.append(
            {
                "severity": "high",
                "kind": "missing_output",
                "message": "Compositor tree has no Composite/Viewer/File Output node.",
            }
        )
    for node in io["outputs"]:
        if node.get("bl_idname") == "CompositorNodeOutputFile":
            issues.append(
                {
                    "severity": "medium",
                    "kind": "file_output",
                    "node": node.get("node"),
                    "message": "File Output node writes external passes; record output paths before reproducing in Unity/tools.",
                }
            )
    for node in io["inputs"]:
        if node.get("bl_idname") == "CompositorNodeRLayers":
            issues.append(
                {
                    "severity": "medium",
                    "kind": "render_layers_input",
                    "node": node.get("node"),
                    "message": "Render Layers input depends on Blender render passes. This IR records node use but does not export render settings.",
                }
            )
        if node.get("bl_idname") in {"CompositorNodeMovieClip", "CompositorNodeMask"}:
            issues.append(
                {
                    "severity": "medium",
                    "kind": "time_or_mask_input",
                    "node": node.get("node"),
                    "message": "Movie clip or mask input is timeline/data-block dependent; verify source asset paths and frame range.",
                }
            )
    for node in effects["filter_nodes"]:
        severity = "medium"
        if node.get("bl_idname") in {"CompositorNodeDenoise", "CompositorNodeDefocus", "CompositorNodeVecBlur"}:
            severity = "high"
        issues.append(
            {
                "severity": severity,
                "kind": "filter_effect",
                "node": node.get("node"),
                "bl_idname": node.get("bl_idname"),
                "message": "Filter/post effect may need a Unity post-process equivalent or offline bake.",
            }
        )
    for node in effects["keying_mask_nodes"]:
        issues.append(
            {
                "severity": "medium",
                "kind": "keying_or_mask",
                "node": node.get("node"),
                "bl_idname": node.get("bl_idname"),
                "message": "Keying/matte/cryptomatte logic needs explicit mask/pass support outside Blender.",
            }
        )

    return {"scene": ir.get("scene", {}).get("name"), "issue_count": len(issues), "issues": issues}


def build_preview(ir: IRDict) -> str:
    summary = summarize_ir(ir)
    io = collect_io(ir)
    effects = collect_effects(ir)
    audit = audit_for_migration(ir)
    lines = [
        f"# Compositor Node Preview: {summary.get('scene')}",
        "",
        f"- Nodes: `{summary['node_count']}`",
        f"- Links: `{summary['link_count']}`",
        f"- Inputs: `{len(io['inputs'])}`",
        f"- Outputs: `{len(io['outputs'])}`",
        f"- Color nodes: `{len(effects['color_nodes'])}`",
        f"- Filter nodes: `{len(effects['filter_nodes'])}`",
        f"- Keying/mask nodes: `{len(effects['keying_mask_nodes'])}`",
        f"- Transform nodes: `{len(effects['transform_nodes'])}`",
        f"- Issues: `{audit['issue_count']}`",
    ]
    if io["inputs"]:
        lines.append("")
        lines.append("## Inputs")
        for node in io["inputs"][:30]:
            lines.append(f"- `{node.get('node')}` `{node.get('bl_idname')}`")
    if io["outputs"]:
        lines.append("")
        lines.append("## Outputs")
        for node in io["outputs"][:30]:
            lines.append(f"- `{node.get('node')}` `{node.get('bl_idname')}`")
    if audit["issues"]:
        lines.append("")
        lines.append("## Issues")
        for issue in audit["issues"][:40]:
            label = issue.get("node") or issue.get("kind")
            lines.append(f"- `{issue['severity']}` {label}: {issue['message']}")
    return "\n".join(lines).rstrip() + "\n"


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect HoTools Compositor Node IR JSON.")
    parser.add_argument("ir_json", help="Path to exported compositor node IR JSON.")
    parser.add_argument(
        "--mode",
        choices=("preview", "summary", "io", "effects", "audit"),
        default="preview",
    )
    args = parser.parse_args(argv)
    ir = load_ir(args.ir_json)
    if args.mode == "summary":
        print_json(summarize_ir(ir))
    elif args.mode == "io":
        print_json(collect_io(ir))
    elif args.mode == "effects":
        print_json(collect_effects(ir))
    elif args.mode == "audit":
        print_json(audit_for_migration(ir))
    else:
        print(build_preview(ir), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
