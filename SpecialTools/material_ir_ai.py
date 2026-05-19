"""Pure-Python helpers for reading HoTools material node IR.

This file intentionally has no Blender or HoTools runtime dependency. It can be
copied into another project and run directly against exported IR JSON files.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


IRDict = Dict[str, Any]
TreePath = Tuple[str, ...]


PBR_INPUT_ALIASES = {
    "base_color": ("Base Color", "Color", "BaseColor", "base_color"),
    "metallic": ("Metallic", "Metalness", "metallic"),
    "roughness": ("Roughness", "roughness"),
    "alpha": ("Alpha", "Opacity", "alpha"),
    "normal": ("Normal", "normal"),
    "emission_color": ("Emission Color", "Emission", "Emissive Color"),
    "emission_strength": ("Emission Strength", "Emissive Strength"),
}


SHADER_NODE_SOURCE_DIR = "source/blender/nodes/shader/nodes"
GPU_MATERIAL_SOURCE_DIR = "source/blender/gpu/shaders/material"
BLENDER_REPO = "blender/blender"
GOO_REPO = "dillongoostudios/goo-engine"
GOO_REF = "goo-engine-main"


STANDARD_SHADER_NODES_WITH_GENERIC_SOURCE = {
    "ShaderNodeGroup",
    "ShaderNodeRGBCurve",
    "ShaderNodeFloatCurve",
    "ShaderNodeVectorCurve",
}


SHADER_NODE_SOURCE_FILES = {
    "ShaderNodeAddShader": "node_shader_add_shader.cc",
    "ShaderNodeAmbientOcclusion": "node_shader_ambient_occlusion.cc",
    "ShaderNodeAttribute": "node_shader_attribute.cc",
    "ShaderNodeBackground": "node_shader_background.cc",
    "ShaderNodeBevel": "node_shader_bevel.cc",
    "ShaderNodeBlackbody": "node_shader_blackbody.cc",
    "ShaderNodeBrightContrast": "node_shader_brightness.cc",
    "ShaderNodeBsdfDiffuse": "node_shader_bsdf_diffuse.cc",
    "ShaderNodeBsdfAnisotropic": "node_shader_bsdf_anisotropic.cc",
    "ShaderNodeBsdfGlass": "node_shader_bsdf_glass.cc",
    "ShaderNodeBsdfGlossy": "node_shader_bsdf_glossy.cc",
    "ShaderNodeBsdfHair": "node_shader_bsdf_hair.cc",
    "ShaderNodeBsdfHairPrincipled": "node_shader_bsdf_hair_principled.cc",
    "ShaderNodeBsdfMetallic": "node_shader_bsdf_metallic.cc",
    "ShaderNodeBsdfPrincipled": "node_shader_bsdf_principled.cc",
    "ShaderNodeBsdfRayPortal": "node_shader_bsdf_ray_portal.cc",
    "ShaderNodeBsdfRefraction": "node_shader_bsdf_refraction.cc",
    "ShaderNodeBsdfSheen": "node_shader_bsdf_sheen.cc",
    "ShaderNodeBsdfToon": "node_shader_bsdf_toon.cc",
    "ShaderNodeBsdfTranslucent": "node_shader_bsdf_translucent.cc",
    "ShaderNodeBsdfTransparent": "node_shader_bsdf_transparent.cc",
    "ShaderNodeBump": "node_shader_bump.cc",
    "ShaderNodeCameraData": "node_shader_camera.cc",
    "ShaderNodeClamp": "node_shader_clamp.cc",
    "ShaderNodeCombineColor": "node_shader_sepcomb_color.cc",
    "ShaderNodeCombineXYZ": "node_shader_sepcomb_xyz.cc",
    "ShaderNodeDisplacement": "node_shader_displacement.cc",
    "ShaderNodeEeveeSpecular": "node_shader_eevee_specular.cc",
    "ShaderNodeEmission": "node_shader_emission.cc",
    "ShaderNodeFresnel": "node_shader_fresnel.cc",
    "ShaderNodeGamma": "node_shader_gamma.cc",
    "ShaderNodeGeometry": "node_shader_geometry.cc",
    "ShaderNodeNewGeometry": "node_shader_geometry.cc",
    "ShaderNodeHairInfo": "node_shader_hair_info.cc",
    "ShaderNodeHoldout": "node_shader_holdout.cc",
    "ShaderNodeHueSaturation": "node_shader_hueSatVal.cc",
    "ShaderNodeInvert": "node_shader_invert.cc",
    "ShaderNodeLayerWeight": "node_shader_layer_weight.cc",
    "ShaderNodeLightFalloff": "node_shader_light_falloff.cc",
    "ShaderNodeLightPath": "node_shader_light_path.cc",
    "ShaderNodeMapRange": "node_shader_map_range.cc",
    "ShaderNodeMapping": "node_shader_mapping.cc",
    "ShaderNodeMath": "node_shader_math.cc",
    "ShaderNodeMix": "node_shader_mix.cc",
    "ShaderNodeMixRGB": "node_shader_mix_rgb.cc",
    "ShaderNodeMixShader": "node_shader_mix_shader.cc",
    "ShaderNodeNormal": "node_shader_normal.cc",
    "ShaderNodeNormalMap": "node_shader_normal_map.cc",
    "ShaderNodeObjectInfo": "node_shader_object_info.cc",
    "ShaderNodeOutputAOV": "node_shader_output_aov.cc",
    "ShaderNodeOutputLight": "node_shader_output_light.cc",
    "ShaderNodeOutputLineStyle": "node_shader_output_linestyle.cc",
    "ShaderNodeOutputMaterial": "node_shader_output_material.cc",
    "ShaderNodeOutputWorld": "node_shader_output_world.cc",
    "ShaderNodeParticleInfo": "node_shader_particle_info.cc",
    "ShaderNodePointInfo": "node_shader_point_info.cc",
    "ShaderNodeRGB": "node_shader_rgb.cc",
    "ShaderNodeRGBToBW": "node_shader_rgb_to_bw.cc",
    "ShaderNodeScript": "node_shader_script.cc",
    "ShaderNodeSeparateColor": "node_shader_sepcomb_color.cc",
    "ShaderNodeSeparateXYZ": "node_shader_sepcomb_xyz.cc",
    "ShaderNodeShaderToRGB": "node_shader_shader_to_rgb.cc",
    "ShaderNodeSubsurfaceScattering": "node_shader_subsurface_scattering.cc",
    "ShaderNodeTangent": "node_shader_tangent.cc",
    "ShaderNodeTexBrick": "node_shader_tex_brick.cc",
    "ShaderNodeTexChecker": "node_shader_tex_checker.cc",
    "ShaderNodeTexCoord": "node_shader_tex_coord.cc",
    "ShaderNodeTexEnvironment": "node_shader_tex_environment.cc",
    "ShaderNodeTexGabor": "node_shader_tex_gabor.cc",
    "ShaderNodeTexGradient": "node_shader_tex_gradient.cc",
    "ShaderNodeTexIES": "node_shader_ies_light.cc",
    "ShaderNodeTexImage": "node_shader_tex_image.cc",
    "ShaderNodeTexMagic": "node_shader_tex_magic.cc",
    "ShaderNodeTexNoise": "node_shader_tex_noise.cc",
    "ShaderNodeTexSky": "node_shader_tex_sky.cc",
    "ShaderNodeTexVoronoi": "node_shader_tex_voronoi.cc",
    "ShaderNodeTexWave": "node_shader_tex_wave.cc",
    "ShaderNodeTexWhiteNoise": "node_shader_tex_white_noise.cc",
    "ShaderNodeUVAlongStroke": "node_shader_uv_along_stroke.cc",
    "ShaderNodeUVMap": "node_shader_uvmap.cc",
    "ShaderNodeValToRGB": "node_shader_color_ramp.cc",
    "ShaderNodeValue": "node_shader_value.cc",
    "ShaderNodeVectorDisplacement": "node_shader_vector_displacement.cc",
    "ShaderNodeVectorMath": "node_shader_vector_math.cc",
    "ShaderNodeVectorRotate": "node_shader_vector_rotate.cc",
    "ShaderNodeVectorTransform": "node_shader_vector_transform.cc",
    "ShaderNodeVertexColor": "node_shader_vertex_color.cc",
    "ShaderNodeVolumeAbsorption": "node_shader_volume_absorption.cc",
    "ShaderNodeVolumeCoefficients": "node_shader_volume_coefficients.cc",
    "ShaderNodeVolumeInfo": "node_shader_volume_info.cc",
    "ShaderNodeVolumePrincipled": "node_shader_volume_principled.cc",
    "ShaderNodeVolumeScatter": "node_shader_volume_scatter.cc",
    "ShaderNodeWavelength": "node_shader_wavelength.cc",
    "ShaderNodeWireframe": "node_shader_wireframe.cc",
}


GPU_SOURCE_HINTS = {
    "ShaderNodeTexNoise": ("gpu_shader_material_fractal_noise.glsl",),
    "ShaderNodeTexVoronoi": (
        "gpu_shader_material_voronoi.glsl",
        "gpu_shader_material_fractal_voronoi.glsl",
    ),
    "ShaderNodeTexWave": ("gpu_shader_material_wave.glsl",),
    "ShaderNodeTexWhiteNoise": ("gpu_shader_material_white_noise.glsl",),
    "ShaderNodeTexGabor": ("gpu_shader_material_gabor.glsl",),
    "ShaderNodeBump": ("gpu_shader_material_bump.glsl",),
    "ShaderNodeNormalMap": ("gpu_shader_material_normal_map.glsl",),
}


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


OUTPUT_NODE_IDS = {
    "ShaderNodeOutputAOV",
    "ShaderNodeOutputLight",
    "ShaderNodeOutputLineStyle",
    "ShaderNodeOutputMaterial",
    "ShaderNodeOutputWorld",
    "NodeGroupOutput",
}


NON_TRANSLATION_PROPERTY_IDS = {
    "bl_description",
    "bl_height_default",
    "bl_height_max",
    "bl_height_min",
    "bl_icon",
    "bl_idname",
    "bl_label",
    "bl_static_type",
    "bl_width_default",
    "bl_width_max",
    "bl_width_min",
    "color",
    "color_tag",
    "dimensions",
    "hide",
    "location_absolute",
    "mute",
    "show_options",
    "show_preview",
    "show_texture",
    "type",
    "use_custom_color",
    "warning_propagation",
}


def load_ir(path: str | Path) -> IRDict:
    """Load an exported material node IR JSON file."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def material_name(ir: IRDict) -> str:
    return str(ir.get("material", {}).get("name", "<unnamed material>"))


def root_tree(ir: IRDict) -> IRDict:
    return ir.get("node_tree", {})


def blender_tag_from_ir(ir: IRDict, fallback: str = "main") -> str:
    """Return a Blender source tag such as v4.5.9 from IR version metadata."""
    version = ir.get("blender_version")
    if not isinstance(version, list) or len(version) < 2:
        return fallback
    try:
        major = int(version[0])
        minor = int(version[1])
        patch = int(version[2]) if len(version) > 2 else 0
    except (TypeError, ValueError):
        return fallback
    return f"v{major}.{minor}.{patch}"


def _github_blob_url(ref: str, path: str) -> str:
    return f"https://github.com/{BLENDER_REPO}/blob/{ref}/{path}"


def _github_repo_blob_url(repo: str, ref: str, path: str) -> str:
    return f"https://github.com/{repo}/blob/{ref}/{path}"


def _github_repo_search_url(repo: str, query: str) -> str:
    return f"https://github.com/{repo}/search?q={query}&type=code"


def _projects_url(ref: str, path: str) -> str:
    if ref == "main":
        return f"https://projects.blender.org/blender/blender/src/branch/main/{path}"
    return f"https://projects.blender.org/blender/blender/src/tag/{ref}/{path}"


def shader_node_source_file(bl_idname: str) -> Optional[str]:
    """Map a Blender ShaderNode bl_idname to the likely C++ source file."""
    return SHADER_NODE_SOURCE_FILES.get(bl_idname)


def blender_source_urls_for_node(node: IRDict, ref: str = "main") -> IRDict:
    """Build official source URLs for a node without fetching network data."""
    bl_idname = str(node.get("bl_idname", ""))
    source_file = shader_node_source_file(bl_idname)
    paths = []
    if source_file:
        paths.append(
            {
                "kind": "node_declaration_cpp",
                "path": f"{SHADER_NODE_SOURCE_DIR}/{source_file}",
                "purpose": "Sockets, labels, storage properties, registration, GPU/MaterialX hooks.",
            }
        )
    for gpu_file in GPU_SOURCE_HINTS.get(bl_idname, ()):
        paths.append(
            {
                "kind": "gpu_material_glsl",
                "path": f"{GPU_MATERIAL_SOURCE_DIR}/{gpu_file}",
                "purpose": "Viewport/EEVEE-side helper functions; useful for procedural math, not final BSDF parity.",
            }
        )

    return {
        "node": node.get("name"),
        "bl_idname": bl_idname,
        "ref": ref,
        "paths": [
            {
                **item,
                "github": _github_blob_url(ref, item["path"]),
                "projects_blender": _projects_url(ref, item["path"]),
            }
            for item in paths
        ],
        "notes": source_lookup_notes(bl_idname),
    }


def goo_source_urls_for_node(node: IRDict, ref: str = GOO_REF) -> IRDict:
    """Build Goo Engine source URLs for a node without fetching network data."""
    bl_idname = str(node.get("bl_idname", ""))
    source_file = shader_node_source_file(bl_idname)
    paths = []
    if source_file:
        paths.append(
            {
                "kind": "goo_node_declaration_cpp",
                "path": f"{SHADER_NODE_SOURCE_DIR}/{source_file}",
                "purpose": "Goo Engine fork source for matching Blender shader node declarations and possible fork behavior.",
            }
        )
    for gpu_file in GPU_SOURCE_HINTS.get(bl_idname, ()):
        paths.append(
            {
                "kind": "goo_gpu_material_glsl",
                "path": f"{GPU_MATERIAL_SOURCE_DIR}/{gpu_file}",
                "purpose": "Goo Engine fork GPU shader helper candidate; useful for NPR/viewport behavior clues.",
            }
        )

    return {
        "node": node.get("name"),
        "bl_idname": bl_idname,
        "ref": ref,
        "paths": [
            {
                **item,
                "github": _github_repo_blob_url(GOO_REPO, ref, item["path"]),
            }
            for item in paths
        ],
        "search": [
            _github_repo_search_url(GOO_REPO, bl_idname),
            _github_repo_search_url(GOO_REPO, str(node.get("type", ""))),
        ],
        "notes": goo_source_lookup_notes(bl_idname),
    }


def source_lookup_notes(bl_idname: str) -> List[str]:
    notes = [
        "Match the source ref to the exporting Blender version whenever possible.",
        "Use node_declare for socket names/defaults; use GPU/MaterialX hooks only as implementation hints.",
    ]
    if "Bsdf" in bl_idname or "Volume" in bl_idname or bl_idname in {
        "ShaderNodeAddShader",
        "ShaderNodeMixShader",
    }:
        notes.append(
            "This is a closure/shader node. Treat source as a boundary marker; exact migration depends on Blender render pipeline, Cycles/EEVEE behavior, target engine BRDF, lighting, color management, and sampling."
        )
    if bl_idname.startswith("ShaderNodeTex") or bl_idname in {
        "ShaderNodeMath",
        "ShaderNodeVectorMath",
        "ShaderNodeMapRange",
        "ShaderNodeValToRGB",
        "ShaderNodeMix",
        "ShaderNodeMixRGB",
    }:
        notes.append(
            "This node is often more translatable than BSDF closures, but validate color space, clamp behavior, interpolation, dimensions, and target shader graph equivalents."
        )
    return notes


def goo_source_lookup_notes(bl_idname: str) -> List[str]:
    notes = [
        "Use the Goo Engine fork as a Blender dialect source, not as official Blender behavior.",
        "Prefer the goo-engine-main branch unless the user identifies a specific Goo Engine release/build.",
        "If a node has no mapped file, use the search URLs for bl_idname/type and inspect registration/declaration manually.",
    ]
    if "Bsdf" in bl_idname or "Volume" in bl_idname or bl_idname in {
        "ShaderNodeAddShader",
        "ShaderNodeMixShader",
    }:
        notes.append(
            "Goo/NPR closure behavior is a migration boundary. It may depend on forked EEVEE/render-pipeline behavior and cannot be reproduced from node sockets alone."
        )
    return notes


def _source_profile_from_ir(ir: IRDict) -> str:
    app = ir.get("app", {})
    hint = str(app.get("source_flavor_hint", "")).lower()
    if "goo" in hint:
        return "goo"
    evidence = app.get("source_flavor_evidence")
    if isinstance(evidence, list) and evidence:
        text = " ".join(str(item) for item in evidence).lower()
        if "goo" in text:
            return "goo"
    text = " ".join(
        str(app.get(key, ""))
        for key in (
            "binary_path",
            "binary_dir",
            "executable_name",
            "version_string",
            "build_branch",
            "build_hash",
            "source_flavor_label",
        )
    ).lower()
    if "goo" in text:
        return "goo"
    return "blender"


def goo_suspicion(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Return a conservative Goo/fork suspicion report."""
    app = ir.get("app", {})
    reasons = []
    profile = _source_profile_from_ir(ir)
    if profile == "goo":
        reasons.append("IR app metadata contains Goo/build hints.")

    unknown_nodes = []
    unresolved_custom_nodes = []
    npr_names = []
    for tree_path, node in iter_nodes(ir, include_groups=include_groups):
        bl_idname = str(node.get("bl_idname", ""))
        node_name = str(node.get("name", ""))
        label = str(node.get("label", ""))
        group_name = str(node.get("group_tree", {}).get("name", ""))
        haystack = " ".join((bl_idname, node_name, label, group_name)).lower()
        if (
            bl_idname.startswith("ShaderNode")
            and not shader_node_source_file(bl_idname)
            and bl_idname not in STANDARD_SHADER_NODES_WITH_GENERIC_SOURCE
        ):
            unknown_nodes.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": node.get("name"),
                    "bl_idname": bl_idname,
                    "type": node.get("type"),
                }
            )
        if bl_idname == "NodeUndefined" or node.get("type") == "CUSTOM":
            unresolved_custom_nodes.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": node.get("name"),
                    "label": node.get("label"),
                    "bl_idname": bl_idname,
                    "type": node.get("type"),
                }
            )
        if any(word in haystack for word in ("goo", "toon", "matcap", "npr", "cel", "anime")):
            npr_names.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": node.get("name"),
                    "bl_idname": bl_idname,
                    "matched_text": " ".join(
                        item for item in (node_name, label, group_name) if item
                    ),
                }
            )

    if unknown_nodes:
        reasons.append("Unknown ShaderNode types exist; they may be fork-specific.")
    if unresolved_custom_nodes:
        reasons.append("Undefined/custom nodes exist; they may require the original Blender fork or add-on.")
    if npr_names:
        reasons.append("NPR/toon/matcap naming hints exist; Goo Engine is common in this material family.")

    level = "none"
    if profile == "goo" or unknown_nodes or unresolved_custom_nodes:
        level = "strong"
    elif npr_names:
        level = "possible"

    return {
        "level": level,
        "detected_source_profile": profile,
        "app": {
            "source_flavor_hint": app.get("source_flavor_hint"),
            "build_branch": app.get("build_branch"),
            "build_hash": app.get("build_hash"),
            "binary_path": app.get("binary_path"),
        },
        "reasons": reasons,
        "unknown_shader_nodes": unknown_nodes,
        "unresolved_custom_nodes": unresolved_custom_nodes,
        "npr_name_hints": npr_names[:25],
        "user_override": "If the user says this was authored in Goo Engine, use --source-profile goo even when auto detection is weak.",
    }


def collect_source_urls(
    ir: IRDict,
    include_groups: bool = True,
    ref: Optional[str] = None,
    source_profile: str = "auto",
) -> IRDict:
    """Collect source lookup URLs for node types present in the IR."""
    profile = _source_profile_from_ir(ir) if source_profile == "auto" else source_profile
    source_ref = ref or (GOO_REF if profile == "goo" else blender_tag_from_ir(ir))
    seen = set()
    nodes = []
    for _, node in iter_nodes(ir, include_groups=include_groups):
        bl_idname = node.get("bl_idname")
        if not bl_idname or bl_idname in seen:
            continue
        seen.add(bl_idname)
        if profile == "goo":
            nodes.append(goo_source_urls_for_node(node, source_ref))
        elif profile == "both":
            nodes.append(
                {
                    "node": node.get("name"),
                    "bl_idname": bl_idname,
                    "blender": blender_source_urls_for_node(node, ref or blender_tag_from_ir(ir)),
                    "goo": goo_source_urls_for_node(node, GOO_REF),
                }
            )
        else:
            nodes.append(blender_source_urls_for_node(node, source_ref))
    return {
        "material": material_name(ir),
        "source_profile": profile,
        "ref": source_ref,
        "nodes": nodes,
        "reference_policy": [
            "Prefer exact tags such as v4.5.9; if unavailable, use the nearest patch tag for the same major.minor and say so.",
            "Do not use main for final migration decisions unless the IR was exported from a development build.",
            "For Goo Engine materials, use dillongoostudios/goo-engine goo-engine-main as a fork-specific source backend and mark fork behavior as a migration boundary.",
        ],
    }


def analyze_goo_engine(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Report Goo Engine fork signals and nodes that need fork-specific lookup."""
    suspicion = goo_suspicion(ir, include_groups=include_groups)
    profile = suspicion["detected_source_profile"]
    unknown_shader_nodes = []
    unresolved_custom_nodes = []
    for tree_path, node in iter_nodes(ir, include_groups=include_groups):
        bl_idname = str(node.get("bl_idname", ""))
        node_type = str(node.get("type", ""))
        if bl_idname == "NodeUndefined" or node_type == "CUSTOM":
            search_terms = [
                term
                for term in (str(node.get("name", "")), str(node.get("label", "")), bl_idname, node_type)
                if term
            ]
            unresolved_custom_nodes.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": node.get("name"),
                    "label": node.get("label"),
                    "bl_idname": bl_idname,
                    "type": node.get("type"),
                    "inputs": [
                        {
                            "name": socket.get("name"),
                            "index": socket.get("index"),
                            "type": socket.get("type"),
                            "is_linked": socket.get("is_linked"),
                        }
                        for socket in node.get("inputs", [])
                    ],
                    "outputs": [
                        {
                            "name": socket.get("name"),
                            "index": socket.get("index"),
                            "type": socket.get("type"),
                            "is_linked": socket.get("is_linked"),
                        }
                        for socket in node.get("outputs", [])
                    ],
                    "goo_search": [
                        _github_repo_search_url(GOO_REPO, term)
                        for term in search_terms[:4]
                    ],
                    "risk": "Undefined/custom node. Reopen in the original fork/add-on or inspect Goo Engine/custom source before migration.",
                }
            )
            continue
        if bl_idname.startswith("ShaderNode"):
            if shader_node_source_file(bl_idname) or bl_idname in STANDARD_SHADER_NODES_WITH_GENERIC_SOURCE:
                continue
            unknown_shader_nodes.append(
                {
                    "tree": " / ".join(tree_path),
                    "node": node.get("name"),
                    "bl_idname": bl_idname,
                    "type": node.get("type"),
                    "goo_search": [
                        _github_repo_search_url(GOO_REPO, bl_idname),
                        _github_repo_search_url(GOO_REPO, node_type),
                    ],
                    "risk": "Unknown or fork-specific ShaderNode. Inspect Goo Engine source before migration.",
                }
            )
    return {
        "material": material_name(ir),
        "detected_source_profile": profile,
        "suspicion": suspicion,
        "goo_repo": f"https://github.com/{GOO_REPO}/tree/{GOO_REF}",
        "unknown_shader_node_count": len(unknown_shader_nodes),
        "unknown_shader_nodes": unknown_shader_nodes,
        "unresolved_custom_node_count": len(unresolved_custom_nodes),
        "unresolved_custom_nodes": unresolved_custom_nodes,
        "notes": [
            "Goo Engine is a Blender fork used by many anime/NPR pipelines.",
            "If the file was authored in Goo Engine, official Blender source may miss fork-specific nodes or render behavior.",
            "Treat Goo closure/NPR/render-pipeline behavior as a migration boundary unless source and target shader implementation are both reviewed.",
        ],
    }


def iter_node_trees(
    ir_or_tree: IRDict,
    include_groups: bool = True,
    path: TreePath = (),
) -> Iterator[Tuple[TreePath, IRDict]]:
    """Yield the root tree and nested node group trees."""
    tree = ir_or_tree.get("node_tree", ir_or_tree)
    tree_name = str(tree.get("name", "<node tree>"))
    tree_path = path + (tree_name,)
    yield tree_path, tree

    if not include_groups:
        return

    for node in tree.get("nodes", []):
        group_tree = node.get("group_tree")
        if isinstance(group_tree, dict):
            yield from iter_node_trees(group_tree, True, tree_path + (node.get("name", "<node>"),))


def iter_nodes(ir: IRDict, include_groups: bool = True) -> Iterator[Tuple[TreePath, IRDict]]:
    for tree_path, tree in iter_node_trees(ir, include_groups=include_groups):
        for node in tree.get("nodes", []):
            yield tree_path, node


def iter_links(ir: IRDict, include_groups: bool = True) -> Iterator[Tuple[TreePath, IRDict]]:
    for tree_path, tree in iter_node_trees(ir, include_groups=include_groups):
        for link in tree.get("links", []):
            yield tree_path, link


def find_nodes(
    ir: IRDict,
    *,
    bl_idname: Optional[str] = None,
    node_type: Optional[str] = None,
    name_contains: Optional[str] = None,
    include_groups: bool = True,
) -> List[Tuple[TreePath, IRDict]]:
    """Find nodes by Blender type, display type, or name substring."""
    result = []
    needle = name_contains.lower() if name_contains else None
    for tree_path, node in iter_nodes(ir, include_groups=include_groups):
        if bl_idname and node.get("bl_idname") != bl_idname:
            continue
        if node_type and node.get("type") != node_type:
            continue
        if needle and needle not in str(node.get("name", "")).lower():
            continue
        result.append((tree_path, node))
    return result


def node_by_name(tree: IRDict, name: str) -> Optional[IRDict]:
    for node in tree.get("nodes", []):
        if node.get("name") == name:
            return node
    return None


def socket_label(socket_ref: IRDict) -> str:
    name = socket_ref.get("name")
    index = socket_ref.get("index")
    if name is None:
        return f"socket[{index}]"
    return f"{name}[{index}]"


def socket_by_name_or_index(node: IRDict, direction: str, key: str | int) -> Optional[IRDict]:
    sockets = node.get(direction, [])
    if isinstance(key, int) or str(key).isdigit():
        index = int(key)
        for socket in sockets:
            if socket.get("index") == index:
                return socket
    key_lower = str(key).lower()
    for socket in sockets:
        if str(socket.get("name", "")).lower() == key_lower:
            return socket
    return None


def incoming_links(tree: IRDict, node_name: str, socket_index: Optional[int] = None) -> List[IRDict]:
    links = []
    for link in tree.get("links", []):
        if link.get("to_node") != node_name:
            continue
        if socket_index is not None and link.get("to_socket", {}).get("index") != socket_index:
            continue
        links.append(link)
    return links


def outgoing_links(tree: IRDict, node_name: str, socket_index: Optional[int] = None) -> List[IRDict]:
    links = []
    for link in tree.get("links", []):
        if link.get("from_node") != node_name:
            continue
        if socket_index is not None and link.get("from_socket", {}).get("index") != socket_index:
            continue
        links.append(link)
    return links


def is_output_node(node: IRDict) -> bool:
    bl_idname = node.get("bl_idname")
    node_type = node.get("type")
    return (
        bl_idname in OUTPUT_NODE_IDS
        or str(bl_idname).startswith("ShaderNodeOutput")
        or str(node_type).startswith("OUTPUT")
    )


def reachable_nodes_from_outputs(tree: IRDict) -> List[str]:
    """Return node names that can flow into output nodes within one tree."""
    nodes = {node.get("name"): node for node in tree.get("nodes", [])}
    reachable = set()
    pending = [name for name, node in nodes.items() if is_output_node(node)]

    while pending:
        node_name = pending.pop()
        if node_name in reachable:
            continue
        reachable.add(node_name)
        for link in tree.get("links", []):
            if link.get("to_node") != node_name:
                continue
            if link.get("is_muted") or link.get("is_valid") is False:
                continue
            source = link.get("from_node")
            if source and source not in reachable:
                pending.append(source)

    return sorted(reachable)


def analyze_cleanup(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Find nodes that do not contribute to any output in each node tree."""
    trees = []
    for tree_path, tree in iter_node_trees(ir, include_groups=include_groups):
        all_nodes = [node.get("name") for node in tree.get("nodes", [])]
        reachable = set(reachable_nodes_from_outputs(tree))
        unused = []
        for node in tree.get("nodes", []):
            name = node.get("name")
            if name in reachable:
                continue
            unused.append(
                {
                    "name": name,
                    "bl_idname": node.get("bl_idname"),
                    "type": node.get("type"),
                    "has_driver": any(
                        socket.get("has_driver")
                        for socket in node.get("inputs", []) + node.get("outputs", [])
                    ),
                    "note": "Unused by graph outputs. Review before deleting if it is a documentation, muted, frame, or work-in-progress node.",
                }
            )
        trees.append(
            {
                "tree": " / ".join(tree_path),
                "node_count": len(all_nodes),
                "reachable_count": len(reachable),
                "unused_count": len(unused),
                "unused_nodes": unused,
            }
        )
    return {"material": material_name(ir), "trees": trees}


def _is_reroute(node: IRDict) -> bool:
    return node.get("bl_idname") == "NodeReroute" or node.get("type") == "REROUTE"


def _compact_socket(socket: IRDict) -> IRDict:
    result = {
        "index": socket.get("index"),
        "name": socket.get("name"),
        "identifier": socket.get("identifier"),
        "type": socket.get("type"),
        "is_linked": socket.get("is_linked"),
    }
    if "default_value" in socket:
        result["default_value"] = socket.get("default_value")
    if socket.get("has_driver"):
        result["has_driver"] = True
    return {key: value for key, value in result.items() if value is not None}


def _compact_node_for_translation(node: IRDict, tree_path: TreePath) -> IRDict:
    result = {
        "name": node.get("name"),
        "label": node.get("label") or None,
        "bl_idname": node.get("bl_idname"),
        "type": node.get("type"),
        "parent": node.get("parent"),
    }

    group_tree = node.get("group_tree")
    if isinstance(group_tree, dict):
        result["group_tree"] = {
            "name": group_tree.get("name"),
            "path": " / ".join(
                tree_path
                + (
                    str(node.get("name", "<node>")),
                    str(group_tree.get("name", "<node tree>")),
                )
            ),
        }

    image = node.get("image")
    if image:
        result["image"] = {
            "name": image.get("name"),
            "filepath": image.get("filepath") or image.get("filepath_abs"),
            "colorspace": image.get("colorspace"),
            "size": image.get("size"),
            "alpha_mode": image.get("alpha_mode"),
            "packed": image.get("packed"),
        }

    properties = {
        key: value
        for key, value in node.get("properties", {}).items()
        if key not in NON_TRANSLATION_PROPERTY_IDS
    }
    if properties:
        result["properties"] = properties

    if node.get("color_ramp"):
        result["color_ramp"] = node.get("color_ramp")
    if node.get("curve_mapping"):
        result["curve_mapping"] = node.get("curve_mapping")

    inputs = [
        _compact_socket(socket)
        for socket in node.get("inputs", [])
        if socket.get("is_linked") or "default_value" in socket or socket.get("has_driver")
    ]
    outputs = [
        _compact_socket(socket)
        for socket in node.get("outputs", [])
        if socket.get("is_linked") or socket.get("has_driver")
    ]
    if inputs:
        result["inputs"] = inputs
    if outputs:
        result["outputs"] = outputs
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _reroute_collapsed_links(tree: IRDict) -> Tuple[List[IRDict], int, int]:
    nodes = {node.get("name"): node for node in tree.get("nodes", [])}
    valid_links = [
        link
        for link in tree.get("links", [])
        if not link.get("is_muted") and link.get("is_valid") is not False
    ]
    dropped_link_count = len(tree.get("links", [])) - len(valid_links)
    incoming = {}
    for link in valid_links:
        to_key = (link.get("to_node"), link.get("to_socket", {}).get("index"))
        incoming.setdefault(to_key, []).append(link)

    collapsed_count = 0

    def resolve_source(link: IRDict, seen: Optional[set] = None) -> Optional[Tuple[str, IRDict]]:
        nonlocal collapsed_count
        if seen is None:
            seen = set()
        from_node = link.get("from_node")
        if from_node in seen:
            return None
        source_node = nodes.get(from_node)
        if source_node is None or not _is_reroute(source_node):
            return link.get("from_node"), link.get("from_socket", {})

        seen.add(from_node)
        collapsed_count += 1
        source_links = incoming.get((from_node, 0), [])
        if not source_links:
            return None
        return resolve_source(source_links[0], seen)

    result = []
    seen_links = set()
    for link in valid_links:
        target_node = nodes.get(link.get("to_node"))
        if target_node is not None and _is_reroute(target_node):
            continue
        resolved = resolve_source(link)
        if resolved is None:
            continue
        from_node, from_socket = resolved
        record = {
            "from_node": from_node,
            "from_socket": from_socket,
            "to_node": link.get("to_node"),
            "to_socket": link.get("to_socket", {}),
        }
        key = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if key in seen_links:
            continue
        seen_links.add(key)
        result.append(record)

    return result, collapsed_count, dropped_link_count


def build_translation_view(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Build a compact, non-destructive graph view for AI/code translation.

    The raw IR remains the source of truth. This view removes reroute nodes from
    executable node lists, collapses links through them, and lists group trees as
    separate translation units instead of repeatedly inlining them.
    """
    trees = []
    total_nodes = 0
    total_reroutes = 0
    total_collapsed_links = 0
    total_dropped_links = 0

    for tree_path, tree in iter_node_trees(ir, include_groups=include_groups):
        nodes = tree.get("nodes", [])
        reroute_count = sum(1 for node in nodes if _is_reroute(node))
        compact_nodes = [
            _compact_node_for_translation(node, tree_path)
            for node in nodes
            if not _is_reroute(node)
        ]
        links, collapsed_link_count, dropped_link_count = _reroute_collapsed_links(tree)
        trees.append(
            {
                "path": " / ".join(tree_path),
                "name": tree.get("name"),
                "bl_idname": tree.get("bl_idname"),
                "interface": tree.get("interface", []),
                "node_count_raw": len(nodes),
                "node_count_without_reroutes": len(compact_nodes),
                "reroute_count": reroute_count,
                "link_count_raw": len(tree.get("links", [])),
                "link_count_collapsed": len(links),
                "collapsed_reroute_link_steps": collapsed_link_count,
                "dropped_invalid_or_muted_links": dropped_link_count,
                "nodes": compact_nodes,
                "links": links,
            }
        )
        total_nodes += len(nodes)
        total_reroutes += reroute_count
        total_collapsed_links += collapsed_link_count
        total_dropped_links += dropped_link_count

    return {
        "material": material_name(ir),
        "schema": "hotools.material_node_ir.translation_view.v1",
        "source_schema": ir.get("schema"),
        "source_app": ir.get("app", {}),
        "policy": [
            "This is a derived view for translation speed; keep the original IR as canonical evidence.",
            "NodeReroute nodes are removed and valid links are rewired through them.",
            "Node group trees are emitted as separate tree records; group nodes keep group_tree references.",
            "Frames, labels, images, color ramps, curves, Goo/custom nodes, sockets, and defaults are preserved when useful for translation.",
        ],
        "stats": {
            "tree_count": len(trees),
            "raw_node_count": total_nodes,
            "reroute_count_removed": total_reroutes,
            "node_count_without_reroutes": total_nodes - total_reroutes,
            "collapsed_reroute_link_steps": total_collapsed_links,
            "dropped_invalid_or_muted_links": total_dropped_links,
        },
        "trees": trees,
    }


def image_nodes(ir: IRDict, include_groups: bool = True) -> List[Tuple[TreePath, IRDict]]:
    return [
        (tree_path, node)
        for tree_path, node in iter_nodes(ir, include_groups=include_groups)
        if node.get("image")
    ]


def _image_key(image: IRDict) -> str:
    return str(
        image.get("filepath_abs")
        or image.get("filepath")
        or image.get("name")
        or "<embedded image>"
    ).lower()


def _path_suffix(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    suffix = Path(str(path)).suffix.lower()
    return suffix or None


def _image_direct_uses(tree: IRDict, node: IRDict) -> List[IRDict]:
    uses = []
    for link in outgoing_links(tree, str(node.get("name"))):
        uses.append(
            {
                "to_node": link.get("to_node"),
                "to_socket": link.get("to_socket", {}),
                "hint": _usage_hint_from_socket(link.get("to_socket", {}).get("name")),
            }
        )
    return uses


def _usage_hint_from_socket(socket_name: Any) -> str:
    name = str(socket_name or "").lower()
    if "normal" in name:
        return "normal_or_vector_data"
    if "rough" in name or "metal" in name or "height" in name or "factor" in name:
        return "linear_data_candidate"
    if "alpha" in name:
        return "alpha_candidate"
    if "base" in name or "color" in name:
        return "color_candidate"
    return "unknown"


def analyze_images(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Analyze image texture metadata, duplicates, sampling, and color-space risks."""
    records = []
    by_key: Dict[str, List[IRDict]] = {}

    for tree_path, tree in iter_node_trees(ir, include_groups=include_groups):
        for node in tree.get("nodes", []):
            image = node.get("image")
            if not image:
                continue
            properties = node.get("properties", {})
            filepath = image.get("filepath_abs") or image.get("filepath")
            record = {
                "tree": " / ".join(tree_path),
                "node": node.get("name"),
                "image": image.get("name"),
                "filepath": filepath,
                "format_hint": _path_suffix(filepath),
                "size": image.get("size"),
                "colorspace": image.get("colorspace"),
                "alpha_mode": image.get("alpha_mode"),
                "source": image.get("source"),
                "type": image.get("type"),
                "packed": image.get("packed"),
                "is_dirty": image.get("is_dirty"),
                "sampling": {
                    key: properties.get(key)
                    for key in (
                        "interpolation",
                        "extension",
                        "projection",
                        "projection_blend",
                    )
                    if key in properties
                },
                "direct_uses": _image_direct_uses(tree, node),
                "risks": [],
            }
            colorspace = str(record.get("colorspace") or "").lower()
            direct_hints = {use.get("hint") for use in record["direct_uses"]}
            if "normal_or_vector_data" in direct_hints and "non-color" not in colorspace:
                record["risks"].append("Normal/vector usage may need Non-Color/Linear data.")
            if "linear_data_candidate" in direct_hints and "srgb" in colorspace:
                record["risks"].append("Scalar mask usage may be wrong if imported as sRGB.")
            if record.get("packed"):
                record["risks"].append("Packed image needs extraction or explicit asset handling.")
            if record.get("is_dirty"):
                record["risks"].append("Image has unsaved changes in Blender.")

            key = _image_key(image)
            by_key.setdefault(key, []).append(record)
            records.append(record)

    duplicates = []
    for key, items in by_key.items():
        if len(items) <= 1:
            continue
        duplicates.append(
            {
                "key": key,
                "count": len(items),
                "nodes": [
                    {
                        "tree": item["tree"],
                        "node": item["node"],
                        "colorspace": item["colorspace"],
                        "sampling": item["sampling"],
                    }
                    for item in items
                ],
                "risk": "Same image is used multiple times. Check whether color space and sampling are intentionally different.",
            }
        )

    return {
        "material": material_name(ir),
        "image_count": len(records),
        "duplicate_image_count": len(duplicates),
        "images": records,
        "duplicates": duplicates,
    }


def analyze_groups(ir: IRDict) -> IRDict:
    """Analyze node group usage, interfaces, nested trees, and internal dead nodes."""
    groups = []
    for tree_path, tree in iter_node_trees(ir, include_groups=True):
        for node in tree.get("nodes", []):
            if not (node.get("group_tree") or node.get("group_tree_ref")):
                continue
            group_tree = node.get("group_tree") or {}
            group_info = {
                "tree": " / ".join(tree_path),
                "node": node.get("name"),
                "bl_idname": node.get("bl_idname"),
                "group_name": group_tree.get("name") or node.get("group_tree_ref", {}).get("name"),
                "inlined": bool(node.get("group_tree")),
                "interface": group_tree.get("interface", []),
                "input_count": len(node.get("inputs", [])),
                "output_count": len(node.get("outputs", [])),
                "internal_node_count": len(group_tree.get("nodes", [])),
                "internal_link_count": len(group_tree.get("links", [])),
                "has_drivers": bool(group_tree.get("has_drivers")),
                "unused_internal_nodes": [],
                "risks": [],
            }
            if group_tree:
                cleanup = analyze_cleanup({"material": {}, "node_tree": group_tree}, include_groups=False)
                trees = cleanup.get("trees", [])
                if trees:
                    group_info["unused_internal_nodes"] = trees[0].get("unused_nodes", [])
            else:
                group_info["risks"].append("Node group was referenced but not inlined in IR.")
            if group_info["has_drivers"]:
                group_info["risks"].append("Node group contains driven values.")
            if not group_info["interface"]:
                group_info["risks"].append("Group interface is empty or unavailable in this IR.")
            groups.append(group_info)
    return {"material": material_name(ir), "group_count": len(groups), "groups": groups}


def analyze_annotations(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Analyze artist-authored node editor hints: frames, labels, and custom colors."""
    tree_records = []
    for tree_path, tree in iter_node_trees(ir, include_groups=include_groups):
        nodes = tree.get("nodes", [])
        by_parent: Dict[str, List[IRDict]] = {}
        for node in nodes:
            parent = node.get("parent")
            if parent:
                by_parent.setdefault(parent, []).append(node)

        frames = []
        labeled_nodes = []
        colored_nodes = []
        for node in nodes:
            label = node.get("label")
            if node.get("bl_idname") == "NodeFrame" or node.get("type") == "FRAME":
                child_nodes = by_parent.get(node.get("name"), [])
                frames.append(
                    {
                        "name": node.get("name"),
                        "label": label,
                        "color": node.get("color") if node.get("use_custom_color") else None,
                        "child_count": len(child_nodes),
                        "children": [
                            {
                                "name": child.get("name"),
                                "label": child.get("label"),
                                "bl_idname": child.get("bl_idname"),
                                "use_custom_color": child.get("use_custom_color"),
                                "color": child.get("color") if child.get("use_custom_color") else None,
                            }
                            for child in child_nodes
                        ],
                        "interpretation": "Frame likely marks a visual/semantic region the author intended to inspect together.",
                    }
                )
            elif label:
                labeled_nodes.append(
                    {
                        "name": node.get("name"),
                        "label": label,
                        "bl_idname": node.get("bl_idname"),
                        "parent": node.get("parent"),
                    }
                )

            if node.get("use_custom_color"):
                colored_nodes.append(
                    {
                        "name": node.get("name"),
                        "label": label,
                        "bl_idname": node.get("bl_idname"),
                        "parent": node.get("parent"),
                        "color": node.get("color"),
                        "interpretation": "Custom node color is an author hint; compare with labels/frames before migration.",
                    }
                )

        tree_records.append(
            {
                "tree": " / ".join(tree_path),
                "frame_count": len(frames),
                "labeled_node_count": len(labeled_nodes),
                "colored_node_count": len(colored_nodes),
                "frames": frames,
                "labeled_nodes": labeled_nodes,
                "colored_nodes": colored_nodes,
            }
        )

    return {
        "material": material_name(ir),
        "trees": tree_records,
        "frame_count": sum(tree["frame_count"] for tree in tree_records),
        "labeled_node_count": sum(tree["labeled_node_count"] for tree in tree_records),
        "colored_node_count": sum(tree["colored_node_count"] for tree in tree_records),
    }


def analyze_color_transforms(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Analyze ColorRamp and curve nodes. New IR exports include ramp/curve details."""
    records = []
    for tree_path, node in iter_nodes(ir, include_groups=include_groups):
        bl_idname = node.get("bl_idname")
        if bl_idname not in {
            "ShaderNodeValToRGB",
            "ShaderNodeRGBCurve",
            "ShaderNodeFloatCurve",
            "ShaderNodeVectorCurve",
        }:
            continue

        record = {
            "tree": " / ".join(tree_path),
            "node": node.get("name"),
            "label": node.get("label"),
            "bl_idname": bl_idname,
            "parent": node.get("parent"),
            "has_serialized_detail": False,
            "risk": "Color transforms are authored look-development logic. Treat as Shader Graph/custom shader work unless directly supported.",
        }
        if bl_idname == "ShaderNodeValToRGB":
            ramp = node.get("color_ramp")
            record["kind"] = "color_ramp"
            record["color_ramp"] = ramp
            record["has_serialized_detail"] = bool(ramp and ramp.get("elements"))
            if ramp:
                record["element_count"] = len(ramp.get("elements", []))
                record["interpolation"] = ramp.get("interpolation")
        else:
            curve_mapping = node.get("curve_mapping")
            record["kind"] = "curve_mapping"
            record["curve_mapping"] = curve_mapping
            record["has_serialized_detail"] = bool(
                curve_mapping
                and any(curve.get("points") for curve in curve_mapping.get("curves", []))
            )
            if curve_mapping:
                record["curve_count"] = len(curve_mapping.get("curves", []))
                record["point_count"] = sum(
                    len(curve.get("points", []))
                    for curve in curve_mapping.get("curves", [])
                )

        if not record["has_serialized_detail"]:
            record["needs_reexport"] = (
                "This IR was likely exported before color_ramp/curve_mapping serialization. Re-export from Blender with the updated HoTools exporter."
            )
        records.append(record)

    missing = [record for record in records if not record["has_serialized_detail"]]
    return {
        "material": material_name(ir),
        "color_transform_count": len(records),
        "missing_detail_count": len(missing),
        "color_transforms": records,
    }


def analyze_drivers(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Report whether value/default sockets have drivers. Driver content is not expanded."""
    tree_records = []
    socket_records = []
    for tree_path, tree in iter_node_trees(ir, include_groups=include_groups):
        drivers = tree.get("drivers", [])
        if drivers:
            tree_records.append(
                {
                    "tree": " / ".join(tree_path),
                    "driver_count": len(drivers),
                    "drivers": [
                        {
                            "data_path": driver.get("data_path"),
                            "array_index": driver.get("array_index"),
                            "is_valid": driver.get("is_valid"),
                        }
                        for driver in drivers
                    ],
                }
            )
        for node in tree.get("nodes", []):
            for direction in ("inputs", "outputs"):
                for socket in node.get(direction, []):
                    if not socket.get("has_driver"):
                        continue
                    socket_records.append(
                        {
                            "tree": " / ".join(tree_path),
                            "node": node.get("name"),
                            "direction": direction,
                            "socket": {
                                "name": socket.get("name"),
                                "index": socket.get("index"),
                                "type": socket.get("type"),
                            },
                            "note": "Driver exists. Treat default value as animated/procedural; do not freeze it silently.",
                        }
                    )
    return {
        "material": material_name(ir),
        "has_drivers": bool(tree_records or socket_records),
        "tree_drivers": tree_records,
        "driven_sockets": socket_records,
    }


def analyze_custom_inputs(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Find context-dependent inputs like UV, object info, attributes, and geometry data."""
    records = []
    for tree_path, node in iter_nodes(ir, include_groups=include_groups):
        bl_idname = node.get("bl_idname")
        if bl_idname not in CUSTOM_INPUT_NODE_IDS:
            continue
        records.append(
            {
                "tree": " / ".join(tree_path),
                "node": node.get("name"),
                "bl_idname": bl_idname,
                "properties": node.get("properties", {}),
                "outputs": [
                    {
                        "name": socket.get("name"),
                        "index": socket.get("index"),
                        "type": socket.get("type"),
                        "is_linked": socket.get("is_linked"),
                    }
                    for socket in node.get("outputs", [])
                ],
                "risk": "Context-dependent input. Unity/glTF may need mesh attributes, UV set mapping, object data, or custom importer support beyond raw material IR.",
            }
        )
    return {
        "material": material_name(ir),
        "custom_input_count": len(records),
        "custom_inputs": records,
    }


def analyze_material_audit(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Run the AI-oriented checks that are most useful before conversion."""
    return {
        "material": material_name(ir),
        "summary": summarize_ir(ir, include_groups=include_groups),
        "cleanup": analyze_cleanup(ir, include_groups=include_groups),
        "groups": analyze_groups(ir),
        "annotations": analyze_annotations(ir, include_groups=include_groups),
        "color_transforms": analyze_color_transforms(ir, include_groups=include_groups),
        "images": analyze_images(ir, include_groups=include_groups),
        "drivers": analyze_drivers(ir, include_groups=include_groups),
        "custom_inputs": analyze_custom_inputs(ir, include_groups=include_groups),
        "goo_engine": analyze_goo_engine(ir, include_groups=include_groups),
        "pbr_candidates": extract_gltf_pbr_candidates(ir),
    }


def _risk_level(audit: IRDict) -> str:
    cleanup_unused = sum(
        tree.get("unused_count", 0)
        for tree in audit.get("cleanup", {}).get("trees", [])
    )
    group_count = audit.get("groups", {}).get("group_count", 0)
    annotation_count = audit.get("annotations", {}).get("frame_count", 0) + audit.get(
        "annotations", {}
    ).get("colored_node_count", 0)
    missing_color_detail = audit.get("color_transforms", {}).get("missing_detail_count", 0)
    image_risks = sum(
        len(image.get("risks", []))
        for image in audit.get("images", {}).get("images", [])
    )
    has_drivers = audit.get("drivers", {}).get("has_drivers", False)
    custom_inputs = audit.get("custom_inputs", {}).get("custom_input_count", 0)
    node_types = audit.get("summary", {}).get("node_type_counts", {})
    closure_complexity = sum(
        count
        for node_type, count in node_types.items()
        if "Bsdf" in node_type
        or "Volume" in node_type
        or node_type in {"ShaderNodeMixShader", "ShaderNodeAddShader"}
    )

    score = 0
    score += min(cleanup_unused, 3)
    score += min(group_count, 3)
    score += min(annotation_count, 2)
    score += min(missing_color_detail, 3)
    score += min(image_risks, 4)
    score += 3 if has_drivers else 0
    score += min(custom_inputs, 4)
    score += min(max(closure_complexity - 1, 0), 3)

    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _capability_tags(audit: IRDict) -> List[str]:
    node_types = audit.get("summary", {}).get("node_type_counts", {})
    tags = []
    if "ShaderNodeBsdfPrincipled" in node_types:
        tags.append("PBR/Principled material")
    if any(node_type.startswith("ShaderNodeTex") for node_type in node_types):
        tags.append("Texture-driven")
    if any(node_type in node_types for node_type in ("ShaderNodeMath", "ShaderNodeVectorMath", "ShaderNodeMapRange")):
        tags.append("Procedural/value remapping")
    if any(node_type in node_types for node_type in ("ShaderNodeValToRGB", "ShaderNodeMix", "ShaderNodeMixRGB")):
        tags.append("Color mixing/ramp logic")
    if any(
        node_type in node_types
        for node_type in ("ShaderNodeRGBCurve", "ShaderNodeFloatCurve", "ShaderNodeVectorCurve")
    ):
        tags.append("Curve-based color/value correction")
    if any(node_type in node_types for node_type in ("ShaderNodeBump", "ShaderNodeNormalMap")):
        tags.append("Normal/detail surface")
    if audit.get("groups", {}).get("group_count", 0):
        tags.append("Node group abstraction")
    if audit.get("annotations", {}).get("frame_count", 0):
        tags.append("Author-framed node regions")
    if audit.get("annotations", {}).get("colored_node_count", 0):
        tags.append("Author color-coded nodes")
    if audit.get("custom_inputs", {}).get("custom_input_count", 0):
        tags.append("Context-dependent inputs")
    if audit.get("drivers", {}).get("has_drivers"):
        tags.append("Driven/animated values")
    goo_level = audit.get("goo_engine", {}).get("suspicion", {}).get("level")
    if goo_level in {"possible", "strong"}:
        tags.append("Possible Goo Engine/fork/add-on material")
    return tags or ["Simple material graph"]


def _design_read(audit: IRDict) -> List[str]:
    node_types = audit.get("summary", {}).get("node_type_counts", {})
    images = audit.get("images", {}).get("images", [])
    lines = []
    if "ShaderNodeBsdfPrincipled" in node_types:
        lines.append("The graph appears to center on a Principled BSDF/PBR-style material.")
    if images:
        lines.append(f"It uses {len(images)} image texture node(s); texture roles should be verified from socket links.")
    if audit.get("groups", {}).get("group_count", 0):
        lines.append("Node groups suggest reusable or artist-authored material logic that should be reviewed as a unit.")
    if audit.get("annotations", {}).get("frame_count", 0):
        lines.append("Frames in the node editor likely mark author-intended regions that should be explained together.")
    if audit.get("annotations", {}).get("colored_node_count", 0):
        lines.append("Custom node colors are author hints and may mark important, risky, or grouped logic.")
    if any(node_type in node_types for node_type in ("ShaderNodeValToRGB", "ShaderNodeMix", "ShaderNodeMixRGB")):
        lines.append("Color ramps or mix nodes indicate authored color blending that may not map to plain glTF fields.")
    if audit.get("color_transforms", {}).get("color_transform_count", 0):
        lines.append("Color ramps/curves are look-development logic; preserve their points or rebuild them in Shader Graph.")
    if any(node_type in node_types for node_type in ("ShaderNodeMath", "ShaderNodeVectorMath", "ShaderNodeMapRange")):
        lines.append("Math/remap nodes indicate value transformation before final shader inputs.")
    if audit.get("custom_inputs", {}).get("custom_input_count", 0):
        lines.append("The material depends on scene/mesh context inputs such as UV, object, attribute, or geometry data.")
    goo_level = audit.get("goo_engine", {}).get("suspicion", {}).get("level")
    if goo_level == "strong":
        lines.append("There are strong fork/add-on/custom-node signals; verify the original Blender/Goo/add-on version before migration.")
    elif goo_level == "possible":
        lines.append("There are possible Goo/NPR material signals; ask the user whether this came from Goo Engine.")
    return lines or ["The graph looks relatively direct from inputs/textures to material output."]


def _migration_change_read(audit: IRDict) -> List[str]:
    changes = []
    pbr = audit.get("pbr_candidates", {})
    if pbr.get("principled_bsdf"):
        fields = pbr.get("fields", {})
        direct = [name for name, data in fields.items() if data.get("source", {}).get("kind") == "default"]
        linked = [name for name, data in fields.items() if data.get("source", {}).get("kind") == "link"]
        if direct:
            changes.append(f"Default PBR values can be copied for: {', '.join(direct)}.")
        if linked:
            changes.append(f"Linked PBR inputs need graph/texture translation for: {', '.join(linked)}.")
    else:
        changes.append("No root Principled BSDF was found; migration likely needs manual shader interpretation.")

    if audit.get("images", {}).get("duplicate_image_count", 0):
        changes.append("Repeated image use may become shared texture references or separate Unity import settings.")
    if audit.get("groups", {}).get("group_count", 0):
        changes.append("Node groups may need flattening, Shader Graph subgraphs, or manual rewrite.")
    if audit.get("color_transforms", {}).get("color_transform_count", 0):
        changes.append("Color ramps and curves may need LUTs, Shader Graph Gradient/Curve equivalents, or baked textures.")
    if audit.get("annotations", {}).get("frame_count", 0):
        changes.append("Frame regions can be preserved as comments/subgraphs in Unity Shader Graph documentation.")
    if audit.get("drivers", {}).get("has_drivers"):
        changes.append("Driven values cannot be represented as static material constants without baking or custom logic.")
    if audit.get("custom_inputs", {}).get("custom_input_count", 0):
        changes.append("Context inputs may require mesh attributes, UV set mapping, object data, or importer extensions.")
    if audit.get("goo_engine", {}).get("suspicion", {}).get("level") in {"possible", "strong"}:
        changes.append("If this depends on Goo or another add-on/fork, custom nodes and render behavior may need custom Unity shader work.")
    return changes


def build_user_preview(ir: IRDict, include_groups: bool = True) -> str:
    """Build a short human-facing estimate for chat UI use."""
    audit = analyze_material_audit(ir, include_groups=include_groups)
    summary = audit["summary"]
    risk_level = _risk_level(audit)
    tags = _capability_tags(audit)
    design = _design_read(audit)
    changes = _migration_change_read(audit)
    cleanup_unused = sum(
        tree.get("unused_count", 0)
        for tree in audit.get("cleanup", {}).get("trees", [])
    )
    image_risk_count = sum(
        len(image.get("risks", []))
        for image in audit.get("images", {}).get("images", [])
    )

    lines = [
        f"# Material Migration Preview: {material_name(ir)}",
        "",
        "## Quick Read",
        f"- Complexity estimate: `{risk_level}`",
        f"- Nodes: {summary['node_count']}, links: {summary['link_count']}, node trees: {summary['tree_count']}",
        f"- Images: {summary['image_count']} ({summary['duplicate_image_count']} duplicate groups)",
        f"- Node groups: {audit['groups']['group_count']}",
        f"- Frames/comments: {audit['annotations']['frame_count']}",
        f"- Color-coded nodes: {audit['annotations']['colored_node_count']}",
        f"- Color ramps/curves: {audit['color_transforms']['color_transform_count']}",
        f"- Context inputs: {audit['custom_inputs']['custom_input_count']}",
        f"- Goo/fork/add-on suspicion: {audit['goo_engine']['suspicion']['level']}",
        f"- Driven values: {'yes' if audit['drivers']['has_drivers'] else 'no'}",
        f"- Possibly unused nodes: {cleanup_unused}",
        "",
        "## What This Node Tree Can Do",
    ]
    for tag in tags:
        lines.append(f"- {tag}")

    lines.append("")
    lines.append("## Likely Design")
    for item in design:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## Migration Changes To Expect")
    for item in changes:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## Risks And Boundaries")
    if image_risk_count:
        lines.append(f"- {image_risk_count} image-related warning(s): review color space, packed/dirty state, and sampling.")
    if audit["drivers"]["has_drivers"]:
        lines.append("- Drivers exist: this preview only reports existence; driver logic is not evaluated.")
    if audit["custom_inputs"]["custom_input_count"]:
        lines.append("- Context inputs exist: material-only conversion may miss mesh/object/attribute data.")
    goo_level = audit["goo_engine"]["suspicion"]["level"]
    if goo_level == "strong":
        lines.append("- Strong fork/add-on/custom-node signals exist: verify the original environment; do not rely only on official Blender behavior.")
    elif goo_level == "possible":
        lines.append("- Possible Goo/NPR signals exist: ask the user if this was authored in Goo Engine.")
    if audit["groups"]["group_count"]:
        lines.append("- Node groups exist: inspect group internals before flattening or translating.")
    if audit["annotations"]["frame_count"] or audit["annotations"]["colored_node_count"]:
        lines.append("- Author annotations exist: use frames, labels, and colors to preserve design intent.")
    if audit["color_transforms"]["missing_detail_count"]:
        lines.append("- Some ColorRamp/Curve nodes lack serialized point data; re-export with the updated exporter.")
    elif audit["color_transforms"]["color_transform_count"]:
        lines.append("- ColorRamp/Curve details exist: use them when rebuilding look-development logic.")
    node_types = summary.get("node_type_counts", {})
    if any("Bsdf" in node_type or "Volume" in node_type for node_type in node_types):
        lines.append("- BSDF/Volume behavior is renderer and pipeline dependent; do not promise exact visual parity.")
    if cleanup_unused:
        lines.append("- Unused nodes are cleanup candidates only; do not delete without user review.")
    if not any(line.startswith("-") for line in lines[lines.index("## Risks And Boundaries") + 1:]):
        lines.append("- No major migration risks were detected from this IR, but visual validation is still required.")

    lines.append("")
    lines.append("## Suggested Next AI Actions")
    lines.append("- Run `--mode audit` for full JSON details.")
    lines.append("- Run `--mode images` before assigning Unity texture import settings.")
    lines.append("- Run `--mode groups` if any node group is present.")
    lines.append("- Run `--mode annotations` if frames, labels, or custom node colors are present.")
    lines.append("- Run `--mode colors` if ColorRamp or RGB/Float/Vector Curve nodes are present.")
    lines.append("- Run `--mode goo` if Goo/fork signals appear or the user says this is from Goo Engine.")
    lines.append("- Run `--mode source` only when node behavior needs source confirmation.")
    return "\n".join(lines).rstrip() + "\n"


def summarize_ir(ir: IRDict, include_groups: bool = True) -> IRDict:
    """Return compact statistics that help an AI orient quickly."""
    node_types = Counter()
    socket_defaults = 0
    trees = 0
    links = 0

    for _, tree in iter_node_trees(ir, include_groups=include_groups):
        trees += 1
        links += len(tree.get("links", []))
        for node in tree.get("nodes", []):
            node_types[node.get("bl_idname", node.get("type", "<unknown>"))] += 1
            for socket in node.get("inputs", []):
                if "default_value" in socket:
                    socket_defaults += 1

    images = analyze_images(ir, include_groups=include_groups)

    return {
        "schema": ir.get("schema"),
        "material": material_name(ir),
        "tree_count": trees,
        "node_count": sum(node_types.values()),
        "link_count": links,
        "node_type_counts": dict(node_types.most_common()),
        "image_count": images["image_count"],
        "images": images["images"],
        "duplicate_image_count": images["duplicate_image_count"],
        "input_default_count": socket_defaults,
    }


def _socket_source(tree: IRDict, node: IRDict, socket: IRDict) -> IRDict:
    node_name = str(node.get("name"))
    socket_index = socket.get("index")
    links = incoming_links(tree, node_name, socket_index)
    if links:
        return {
            "kind": "link",
            "links": [
                {
                    "from_node": link.get("from_node"),
                    "from_socket": link.get("from_socket", {}),
                }
                for link in links
            ],
        }
    return {
        "kind": "default",
        "value": socket.get("default_value"),
    }


def _find_first_principled(ir: IRDict) -> Optional[Tuple[TreePath, IRDict, IRDict]]:
    for tree_path, tree in iter_node_trees(ir, include_groups=False):
        for node in tree.get("nodes", []):
            if node.get("bl_idname") == "ShaderNodeBsdfPrincipled":
                return tree_path, tree, node
    return None


def extract_gltf_pbr_candidates(ir: IRDict) -> IRDict:
    """Extract likely glTF PBR source sockets without making destructive guesses."""
    found = _find_first_principled(ir)
    if found is None:
        return {
            "material": material_name(ir),
            "principled_bsdf": None,
            "fields": {},
            "notes": ["No root-level Principled BSDF node was found."],
        }

    tree_path, tree, node = found
    fields = {}
    for field, aliases in PBR_INPUT_ALIASES.items():
        socket = None
        for alias in aliases:
            socket = socket_by_name_or_index(node, "inputs", alias)
            if socket is not None:
                break
        if socket is not None:
            fields[field] = {
                "socket": {
                    "name": socket.get("name"),
                    "index": socket.get("index"),
                    "type": socket.get("type"),
                },
                "source": _socket_source(tree, node, socket),
            }

    return {
        "material": material_name(ir),
        "tree": " / ".join(tree_path),
        "principled_bsdf": node.get("name"),
        "fields": fields,
        "notes": [
            "Treat linked procedural or grouped sources as conversion work, not direct glTF values.",
            "Image color space should be checked before assigning Unity texture import settings.",
        ],
    }


def trace_input(
    tree: IRDict,
    node_name: str,
    socket_name_or_index: str | int,
    max_depth: int = 6,
) -> List[str]:
    """Return a readable upstream trace for one input socket inside one node tree."""
    start = node_by_name(tree, node_name)
    if start is None:
        return [f"Node not found: {node_name}"]

    socket = socket_by_name_or_index(start, "inputs", socket_name_or_index)
    if socket is None:
        return [f"Input socket not found: {node_name}.{socket_name_or_index}"]

    lines = []

    def walk(current_node: IRDict, input_socket: IRDict, depth: int) -> None:
        indent = "  " * depth
        current_name = current_node.get("name")
        current_socket = socket_label(input_socket)
        links = incoming_links(tree, str(current_name), input_socket.get("index"))
        if not links:
            lines.append(
                f"{indent}{current_name}.{current_socket} = {json.dumps(input_socket.get('default_value'), ensure_ascii=False)}"
            )
            return
        for link in links:
            source_name = link.get("from_node")
            source_socket = link.get("from_socket", {})
            source_node = node_by_name(tree, str(source_name))
            lines.append(
                f"{indent}{current_name}.{current_socket} <- {source_name}.{socket_label(source_socket)}"
            )
            if depth + 1 >= max_depth or source_node is None:
                continue
            for source_input in source_node.get("inputs", []):
                walk(source_node, source_input, depth + 1)

    walk(start, socket, 0)
    return lines


def build_ai_context(ir: IRDict, include_groups: bool = True) -> str:
    """Build a concise markdown packet that can be pasted into an AI prompt."""
    summary = summarize_ir(ir, include_groups=include_groups)
    pbr = extract_gltf_pbr_candidates(ir)
    cleanup = analyze_cleanup(ir, include_groups=include_groups)
    drivers = analyze_drivers(ir, include_groups=include_groups)
    custom_inputs = analyze_custom_inputs(ir, include_groups=include_groups)
    goo = analyze_goo_engine(ir, include_groups=include_groups)

    lines = [
        f"# Material IR Context: {summary['material']}",
        "",
        f"- Schema: `{summary.get('schema')}`",
        f"- Trees: {summary['tree_count']}",
        f"- Nodes: {summary['node_count']}",
        f"- Links: {summary['link_count']}",
        f"- Images: {summary['image_count']}",
        f"- Duplicate Images: {summary['duplicate_image_count']}",
        f"- Driven Values: {'yes' if drivers['has_drivers'] else 'no'}",
        f"- Context Inputs: {custom_inputs['custom_input_count']}",
        f"- Goo/Fork Suspicion: {goo['suspicion']['level']}",
        "",
        "## Node Types",
    ]
    for node_type, count in summary["node_type_counts"].items():
        lines.append(f"- `{node_type}`: {count}")

    lines.append("")
    lines.append("## Images")
    if summary["images"]:
        for image in summary["images"]:
            lines.append(
                f"- `{image['node']}` -> `{image['image']}` colorspace=`{image['colorspace']}` path=`{image['filepath']}`"
            )
    else:
        lines.append("- None")

    unused_total = sum(tree["unused_count"] for tree in cleanup.get("trees", []))
    lines.append("")
    lines.append("## Cleanup Signals")
    lines.append(f"- Nodes not reaching outputs: {unused_total}")
    if unused_total:
        lines.append("- Review `--mode cleanup` before deleting anything.")

    lines.append("")
    lines.append("## Context Input Signals")
    if custom_inputs["custom_inputs"]:
        for item in custom_inputs["custom_inputs"][:12]:
            lines.append(f"- `{item['node']}` `{item['bl_idname']}` in {item['tree']}")
    else:
        lines.append("- None")

    lines.append("")
    lines.append("## glTF PBR Candidates")
    if not pbr.get("principled_bsdf"):
        lines.append("- No root-level Principled BSDF node found.")
    else:
        lines.append(f"- Principled BSDF: `{pbr['principled_bsdf']}`")
        for field, data in pbr.get("fields", {}).items():
            source = data.get("source", {})
            if source.get("kind") == "link":
                sources = ", ".join(
                    f"{item.get('from_node')}.{item.get('from_socket', {}).get('name')}"
                    for item in source.get("links", [])
                )
                lines.append(f"- `{field}` <- {sources}")
            else:
                lines.append(
                    f"- `{field}` = {json.dumps(source.get('value'), ensure_ascii=False)}"
                )

    lines.append("")
    lines.append("## AI Task Rule")
    lines.append(
        "Use JSON fields as evidence. Mark uncertain shader semantics as needs-review instead of inventing a conversion."
    )
    lines.append("")
    lines.append("## Source Lookup")
    lines.append(
        f"- Blender source ref from IR: `{blender_tag_from_ir(ir)}`. Use `--mode source` for official source URLs."
    )
    lines.append(
        "- Source is evidence for sockets/procedural math; BSDF/closure nodes are pipeline-dependent and should be treated as migration boundaries."
    )
    lines.append(
        "- If the user says this is Goo Engine, use `--mode source --source-profile goo` and `--mode goo`."
    )
    if goo["suspicion"]["level"] in {"possible", "strong"}:
        lines.append(
            f"- Goo/fork suspicion is `{goo['suspicion']['level']}`: ask the user whether this was authored in Goo Engine."
        )
    lines.append("")
    lines.append("## User Preview")
    lines.append("- Use `--mode preview` for a chat-friendly estimate of capabilities, design, migration changes, risks, and boundaries.")
    return "\n".join(lines).rstrip() + "\n"


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect HoTools material node IR JSON.")
    parser.add_argument("ir_json", help="Path to exported material node IR JSON.")
    parser.add_argument(
        "--mode",
        choices=(
            "summary",
            "context",
            "pbr",
            "images",
            "source",
            "cleanup",
            "groups",
            "annotations",
            "colors",
            "goo",
            "drivers",
            "inputs",
            "translate",
            "audit",
            "preview",
        ),
        default="context",
        help="Output mode.",
    )
    parser.add_argument(
        "--source-ref",
        help="Blender source ref/tag to use for source URLs, for example v4.5.9. Defaults to the IR blender_version tag.",
    )
    parser.add_argument(
        "--source-profile",
        choices=("auto", "blender", "goo", "both"),
        default="auto",
        help="Source backend for source URLs. Use goo when the user says the material came from Goo Engine.",
    )
    parser.add_argument(
        "--no-groups",
        action="store_true",
        help="Ignore nested node group trees in summary/context modes.",
    )
    args = parser.parse_args(argv)

    ir = load_ir(args.ir_json)
    include_groups = not args.no_groups

    if args.mode == "summary":
        print_json(summarize_ir(ir, include_groups=include_groups))
    elif args.mode == "pbr":
        print_json(extract_gltf_pbr_candidates(ir))
    elif args.mode == "images":
        print_json(analyze_images(ir, include_groups=include_groups))
    elif args.mode == "source":
        print_json(
            collect_source_urls(
                ir,
                include_groups=include_groups,
                ref=args.source_ref,
                source_profile=args.source_profile,
            )
        )
    elif args.mode == "cleanup":
        print_json(analyze_cleanup(ir, include_groups=include_groups))
    elif args.mode == "groups":
        print_json(analyze_groups(ir))
    elif args.mode == "annotations":
        print_json(analyze_annotations(ir, include_groups=include_groups))
    elif args.mode == "colors":
        print_json(analyze_color_transforms(ir, include_groups=include_groups))
    elif args.mode == "goo":
        print_json(analyze_goo_engine(ir, include_groups=include_groups))
    elif args.mode == "drivers":
        print_json(analyze_drivers(ir, include_groups=include_groups))
    elif args.mode == "inputs":
        print_json(analyze_custom_inputs(ir, include_groups=include_groups))
    elif args.mode == "translate":
        print_json(build_translation_view(ir, include_groups=include_groups))
    elif args.mode == "audit":
        print_json(analyze_material_audit(ir, include_groups=include_groups))
    elif args.mode == "preview":
        print(build_user_preview(ir, include_groups=include_groups), end="")
    else:
        print(build_ai_context(ir, include_groups=include_groups), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
