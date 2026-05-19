---
name: material-node-ir
description: Export, inspect, or evolve HoTools Blender material node IR for AI-readable shader graphs, glTF material migration, and Unity material mapping. Use when working on Blender shader nodes, material node serialization, node group traversal, texture/color-space capture, or conversion rules from Blender materials to glTF/Unity.
---

# Material Node IR

Use this skill when changing HoTools material node IR export or using exported IR to design glTF/Unity material mapping.

## One-Line Handoff

Tell another AI: `Use SpecialTools/skills/material-node-ir/SKILL.md as the rules, use SpecialTools/material_ir_ai.py to inspect the exported material IR JSON, and base every Blender-to-glTF/Unity decision on the JSON evidence.`

## Workflow

1. Inspect `SpecialTools/material_node_ir.py` first; keep the IR schema stable unless the user asks for a breaking change.
2. Prefer adding fields over renaming fields. If a field must change meaning, bump the schema string.
3. Preserve both outputs:
   - JSON is the canonical full-fidelity exchange format.
   - Markdown is a compact AI-facing reading view.
4. Keep Blender-side serialization dependency-free. Use `bpy`, RNA properties, node sockets, links, images, and node groups directly.
5. For external projects, do not import Blender or HoTools. Run or copy `SpecialTools/material_ir_ai.py`; it uses only the Python standard library.
6. For Unity/glTF migration work, read `references/ir-schema.md` before proposing mapping rules.

## Helper Entrypoints

- `python SpecialTools/material_ir_ai.py material_ir.json --mode context`: print a compact AI prompt packet.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode summary`: print JSON counts, node types, and images.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode pbr`: print likely glTF PBR source sockets from the root Principled BSDF.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode source`: print official Blender source URLs for node types in the IR.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode source --source-profile goo`: print Goo Engine fork source URLs when the user says the material is from Goo Engine.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode source --source-profile both`: print official Blender and Goo Engine source URL candidates side by side.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode cleanup`: find nodes that do not reach material/group outputs.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode groups`: inspect node group interfaces, nested trees, drivers, and internal unused nodes.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode annotations`: inspect Blender node editor frames, labels, and custom node colors as author intent hints.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode colors`: inspect ColorRamp and RGB/Float/Vector Curve nodes; reports missing detail when the IR needs re-export.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode goo`: report Goo Engine/forked Blender suspicion, unknown ShaderNode types, and Goo source search links.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode images`: inspect duplicate images, file formats, color space, sampling, packed/dirty state, and direct uses.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode drivers`: report whether driven socket values exist without expanding driver internals.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode inputs`: find context-dependent inputs such as UV maps, object info, attributes, geometry, vertex color, and tangent data.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode translate`: output a compact translation view with `NodeReroute` nodes collapsed and node group trees split into separate records. This is derived from the raw IR and should not replace the canonical JSON.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode audit`: run the main AI conversion-readiness checks together.
- `python SpecialTools/material_ir_ai.py material_ir.json --mode preview`: print a chat-friendly human estimate of node-tree capabilities, likely design, expected migration changes, risks, and boundaries.
- In code, call `load_ir`, `summarize_ir`, `build_ai_context`, `build_user_preview`, `build_translation_view`, `extract_gltf_pbr_candidates`, `collect_source_urls`, `analyze_material_audit`, `analyze_cleanup`, `analyze_groups`, `analyze_annotations`, `analyze_color_transforms`, `analyze_images`, `analyze_drivers`, `analyze_custom_inputs`, or `trace_input`.

## AI Analysis Checklist

Run `--mode audit` before proposing Blender-to-glTF/Unity migration. Use specific modes when the audit flags detail:

0. User-facing preview:
   - Use `--mode preview` when the user wants a quick conversation-level estimate.
   - Summarize capability, likely design intent, migration deltas, risks, and boundaries.
   - Do not present the preview as a final conversion plan.
1. Cleanup:
   - Use `--mode cleanup` to identify nodes not reachable from output nodes.
   - Do not delete automatically. Frames, notes, muted experiments, and intentionally parked nodes may be useful.
2. Node groups:
   - Use `--mode groups` for interfaces, nested graphs, driven internals, and unused internal nodes.
   - Treat not-inlined groups or empty interfaces as `needs-review`.
3. Visual annotations:
   - Use `--mode annotations` for Frame nodes, node labels, and custom node colors.
   - Treat frames as author-intended visual/semantic regions that may need to be explained or migrated together.
   - Preserve frame/label/color meaning in generated reports when possible; do not treat them as shader math.
4. Color transforms:
   - Use `--mode colors` for ColorRamp and RGB/Float/Vector Curve nodes.
   - For new IR, preserve ramp elements and curve points as look-development evidence.
   - If `missing_detail_count` is nonzero, ask the user to re-export from Blender with the updated exporter.
   - Treat these as Shader Graph Gradient/Curve, LUT, baked texture, or custom shader work.
5. Images:
   - Use `--mode images` to catch duplicate file use, packed/dirty images, extension/projection/interpolation settings, color-space risks, and direct socket uses.
   - Do not infer usage from filename alone.
6. Drivers:
   - Use `--mode drivers` to detect animated/driven value sockets.
   - The IR only needs to know that a driver exists. Do not freeze or evaluate driver contents unless the user asks for a Blender-side evaluation feature.
7. Context-dependent inputs:
   - Use `--mode inputs` for UVMap, Texture Coordinate, Attribute, Object Info, Geometry, Vertex Color, Tangent, Camera/Light/Particle/Hair info nodes.
   - Mark these as requiring mesh/importer/context support beyond raw material conversion.
8. Goo Engine/forked Blender:
   - If the user says the material came from Goo Engine, use `--mode goo` and `--mode source --source-profile goo`.
   - If the user does not know, use Goo suspicion as a conservative signal. Say "possibly Goo Engine/forked Blender" when unknown ShaderNode types, Goo metadata, or NPR/toon/matcap naming hints appear.
   - Do not assert Goo as fact unless app metadata or the user confirms it.
   - Treat Goo/NPR closure and render-pipeline behavior as a migration boundary.
9. Translation view:
   - Use `--mode translate` before code generation or shader graph translation on large graphs.
   - Treat it as a speed-oriented derived view: reroutes are collapsed, groups are split into separate tree records, and original JSON remains the source of truth.
   - If any collapsed link looks suspicious, inspect the original IR links before finalizing conversion.

## Blender Source Lookup

Use Blender source as evidence, not as a promise of direct engine parity.

1. Match source by exported Blender version:
   - Read `blender_version` from the IR.
   - Prefer exact official tags such as `v4.5.0`, `v4.5.9`.
   - If the exact patch tag is unavailable, use the nearest patch tag for the same major/minor and state the mismatch.
   - Use `main` only for development-build IR or exploratory reading.
2. Start with the node C++ file in `source/blender/nodes/shader/nodes/`.
   - Use `node_declare` and registration code for socket names, default values, properties, and enum behavior.
   - Use GPU/MaterialX hooks as hints for procedural behavior and export support.
3. For procedural/value nodes, source lookup is often actionable:
   - Math, Vector Math, Map Range, Mix, ColorRamp, Noise/Voronoi/Wave/White Noise, Bump, Normal Map.
4. For closure/rendering nodes, source lookup sets a boundary:
   - BSDF, Volume, Add Shader, Mix Shader, Output nodes depend on renderer, lighting, color management, sampling, and target engine BRDF.
   - Do not attempt exact migration from Blender source alone. Mark as `needs-review` or map only known PBR sockets when evidence exists.
5. Prefer official URLs:
   - GitHub mirror: `https://github.com/blender/blender/blob/<tag>/...`
   - Blender upstream: `https://projects.blender.org/blender/blender/src/tag/<tag>/...`

## Goo Engine Extension

Goo Engine source backend:

- Repository: `https://github.com/dillongoostudios/goo-engine/tree/goo-engine-main`
- Use it when the user explicitly says "Goo Engine", "goo", "Goo Blender", or when the IR has Goo/fork suspicion.
- Use `--source-profile goo` for Goo-only lookup and `--source-profile both` to compare official Blender and Goo Engine candidates.
- Unknown ShaderNode types should be searched in Goo source before migration.
- Goo Engine may alter NPR/render behavior beyond node declarations, so exact visual parity requires target-shader review.

## Design Notes

- Treat node names as local graph identifiers and socket indexes as the stable disambiguator when sockets share display names.
- Inline node groups by default, but guard against recursive group cycles.
- Treat Blender Frame nodes, labels, and node custom colors as author intent metadata. They help explain design, cleanup candidates, and migration grouping.
- Serialize ColorRamp elements and CurveMapping points when exporting from Blender. These are essential for AI to understand gradients and color curves.
- Capture texture image metadata, color space, default socket values, internal node links, and material-level render properties.
- Capture whether socket default values have drivers. Driver internals are intentionally not expanded.
- Do not bake semantic conversion guesses into the raw exporter. Put mapping heuristics in a separate layer so the IR remains useful for diagnosis.
- Do not create cache files or project-local state from helper code. Any generated `__pycache__` is disposable and not part of the module.

## Companion IRs

- Use `SpecialTools/object_scene_ir.py` and the `object-scene-ir` skill when a material depends on object-level context such as UV maps, mesh attributes, color attributes, material slots, shape keys, modifiers, or hierarchy.
- Keep Geometry Nodes as a separate IR project. Material/Object IR may reference Geometry Nodes modifiers or node groups, but should not inline geometry node graphs.
