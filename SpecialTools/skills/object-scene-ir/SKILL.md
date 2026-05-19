---
name: object-scene-ir
description: Export, inspect, live-query, compare, or evolve HoTools Blender object/scene IR for mesh statistics, UVs, material slots, modifiers, shape keys, color attributes, hierarchy, and material migration context.
---

# Object Scene IR

Use this skill when working on object-level scene context for Blender material or asset migration.

## Workflow

1. Export object context from Blender with `SpecialTools/object_scene_ir.py`.
2. Use JSON as the canonical source of truth. Markdown is only a compact reading view.
3. Use `SpecialTools/object_scene_ir_ai.py` outside Blender for summaries and migration-readiness checks.
4. Keep Geometry Nodes graph serialization separate. Object Scene IR may record that a `NODES` modifier exists and which node group it references; use the `geometry-node-ir` skill for the actual node graph.
5. When a `.blend` is available and a full scene bundle is too large, use `SpecialTools/blender_live_inspector.py` through the matching Blender/Goo runtime for quick object/material/attribute checks.
6. For Blender-side automation, import `from SpecialTools import object_scene_ir` after adding the HoTools add-on folder to `sys.path`; avoid importing top-level `HoTools` unless the full UI add-on is required.

## Helper Entrypoints

- `python SpecialTools/object_scene_ir_ai.py object_scene_ir.json --mode preview`: chat-friendly object/scene estimate.
- `python SpecialTools/object_scene_ir_ai.py object_scene_ir.json --mode summary`: object counts, mesh totals, materials, UVs, attributes, modifiers.
- `python SpecialTools/object_scene_ir_ai.py object_scene_ir.json --mode audit`: migration risks such as missing UVs, shape keys, and Geometry Nodes modifiers.
- `python SpecialTools/ir_joint_ai.py --scene-bundle scene.scene_asset.json --mode preview`: jointly inspect the one-click scene bundle containing all scene objects, material node IRs, and Geometry Nodes IR when enabled.
- `python SpecialTools/ir_joint_ai.py --object-scene scene.object_scene.json --material mat.json --mode preview`: jointly inspect separately exported object and material IR files.
- `blender --factory-startup --background asset.blend --python SpecialTools/blender_live_inspector.py -- --mode scene`: inspect live scene/object context without exporting a scene bundle.
- `blender --factory-startup --background asset.blend --python SpecialTools/blender_live_inspector.py -- --mode materials`: inspect live material sizes and Goo/fork signals before choosing which material to export.

## Export Scope

The Blender exporter supports:

- `ACTIVE`: active object only.
- `SELECTED`: selected objects.
- `VISIBLE`: visible objects in the current scene.
- `SCENE`: all objects in the current scene.

## Migration Boundaries

- Object Scene IR helps answer whether a material's required UVs, attributes, color attributes, shape keys, material slots, hierarchy, and modifiers exist.
- It does not replace Material Node IR.
- Use Geometry Nodes IR when modifier settings, node groups, fields, simulation zones, and generated attributes need exact graph evidence.
- If Material/GN IR references a missing UV/attribute, remember Blender may render with fallback behavior instead of hard failure. Object Scene IR should be used to confirm whether the named data really exists; missing data should be reported as `fallback-suspected` or `needs-evaluated-check`, not silently mapped.

## Scene Bundle

The View3D panel provides `Export Scene Bundle: Objects + Materials`. It writes `hotools.scene_asset_ir.v1`, containing:

- Full `object_scene` IR for all scene objects.
- Full Material Node IR for every material referenced by scene object material slots.
- Full Geometry Nodes IR for scene `NODES` modifiers when `Include Geometry Nodes IR` is enabled.
- Export failures for materials that could not be serialized.

Use scene bundles for whole-scene migration readiness and use the original specialized IR sections for detailed evidence.

## Live Inspector

Live inspector is a fast query path, not a replacement for the canonical scene bundle:

- Use it to check whether UVs, color attributes, mesh attributes, material slots, and Geometry Nodes modifiers exist in the live file.
- Use it before generating a 100MB+ scene bundle when the user only needs a small answer.
- Use it with Goo Engine for Goo-authored scenes so fork-specific nodes are not lost.
- Use exported Object Scene IR or Scene Bundle when the result must be archived, shared, or processed outside Blender.
