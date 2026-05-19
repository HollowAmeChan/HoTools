---
name: object-scene-ir
description: Export, inspect, or evolve HoTools Blender object/scene IR for mesh statistics, UVs, material slots, modifiers, shape keys, color attributes, hierarchy, and material migration context.
---

# Object Scene IR

Use this skill when working on object-level scene context for Blender material or asset migration.

## Workflow

1. Export object context from Blender with `SpecialTools/object_scene_ir.py`.
2. Use JSON as the canonical source of truth. Markdown is only a compact reading view.
3. Use `SpecialTools/object_scene_ir_ai.py` outside Blender for summaries and migration-readiness checks.
4. Keep Geometry Nodes graph serialization separate. Object Scene IR may record that a `NODES` modifier exists and which node group it references, but it should not inline the geometry node graph.

## Helper Entrypoints

- `python SpecialTools/object_scene_ir_ai.py object_scene_ir.json --mode preview`: chat-friendly object/scene estimate.
- `python SpecialTools/object_scene_ir_ai.py object_scene_ir.json --mode summary`: object counts, mesh totals, materials, UVs, attributes, modifiers.
- `python SpecialTools/object_scene_ir_ai.py object_scene_ir.json --mode audit`: migration risks such as missing UVs, shape keys, and Geometry Nodes modifiers.
- `python SpecialTools/ir_joint_ai.py --scene-bundle scene.scene_asset.json --mode preview`: jointly inspect the one-click scene bundle containing all scene objects and material node IRs.
- `python SpecialTools/ir_joint_ai.py --object-scene scene.object_scene.json --material mat.json --mode preview`: jointly inspect separately exported object and material IR files.

## Export Scope

The Blender exporter supports:

- `ACTIVE`: active object only.
- `SELECTED`: selected objects.
- `VISIBLE`: visible objects in the current scene.
- `SCENE`: all objects in the current scene.

## Migration Boundaries

- Object Scene IR helps answer whether a material's required UVs, attributes, color attributes, shape keys, material slots, hierarchy, and modifiers exist.
- It does not replace Material Node IR.
- Geometry Nodes should get its own IR because modifier settings, node groups, fields, simulation zones, and generated attributes need a dedicated graph model.

## Scene Bundle

The View3D panel provides `Export Scene Bundle: Objects + Materials`. It writes `hotools.scene_asset_ir.v1`, containing:

- Full `object_scene` IR for all scene objects.
- Full Material Node IR for every material referenced by scene object material slots.
- Export failures for materials that could not be serialized.

Use scene bundles for whole-scene migration readiness and use the original specialized IR sections for detailed evidence.
