---
name: geometry-node-ir
description: Export, inspect, audit, or evolve HoTools Geometry Nodes IR for Blender/Goo Geometry Nodes modifiers, node groups, fields, attributes, instances, bake nodes, and zone nodes such as Simulation, Repeat, For Each Geometry Element, and Closure.
---

# Geometry Nodes IR

Use this skill when a Blender/Goo asset has `NODES` modifiers or the user asks how procedural geometry affects export, Unity migration, glTF baking, generated attributes, or runtime parity.

## Core Rule

Geometry Nodes IR records graph structure and migration evidence. It does not promise to execute the graph outside Blender. Treat zones, fields, simulation state, and scene-dependent sampling as procedural behavior that usually needs baking or custom Unity logic.

## Export Entrypoints

In Blender, use the HoTools View3D panel `Geometry Nodes IR` or run:

```powershell
& 'D:\Blender\blender-4.5.8-windows-x64\blender.exe' --factory-startup --background 'asset.blend' --python 'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\SpecialTools\geometry_node_ir.py' -- --scope SCENE --output 'C:\Temp\asset.geometry_node.json' --format JSON
```

Use matching runtimes:

- Official Blender GN asset: use official Blender with the same major/minor version when possible.
- Goo-authored file: use Goo Engine's real `blender.exe`, not `blender-launcher.exe`.
- In background mode, prefer `--python SpecialTools/geometry_node_ir.py -- ...` over importing the whole HoTools package. Some unrelated UI/GPU add-on modules may not be background-safe.

## Helper Entrypoints

- `python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode preview`: human-readable overview.
- `python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode summary`: counts, modifiers, node types, zone counts.
- `python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode zones`: list Simulation/Repeat/For Each/Closure zone pairs and items.
- `python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode effects`: list nodes that affect generated geometry, attributes, instances, sampling, or materials.
- `python SpecialTools/geometry_node_ir_ai.py asset.geometry_node.json --mode audit`: migration risks and required bake/custom-code review.

## Zone Handling

Blender zone nodes are not ordinary isolated nodes. The IR preserves:

- input node name and output node name.
- zone kind: `simulation`, `repeat`, `foreach_geometry_element`, or `closure`.
- pairing status: `paired`, `unpaired`, or `output_without_detected_input`.
- output-side item collections such as `state_items`, `repeat_items`, `input_items`, `main_items`, `generation_items`, and `output_items`.

When analyzing zones:

1. Inspect `zones` before individual node sockets.
2. Treat Simulation zones as high-risk for Unity/glTF unless the evaluated result is baked.
3. Treat Repeat and For Each zones as procedural loops. They can sometimes be approximated if the generated output is simple, but do not assume direct shader/material mapping.
4. Treat Closure zones as newer Blender procedural abstraction. Preserve structure and mark semantic execution as `needs-review` unless the target pipeline has a known equivalent.

## Migration Audit Heuristics

Flag these as important:

- Named/captured/stored attributes: verify Unity vertex streams, mesh attributes, or baked mesh output.
- Instances: decide whether to realize instances before export.
- Sampling/raycast/proximity: usually requires baking or custom runtime logic.
- Set Material/Set Position/Delete Geometry/Join Geometry: affects final mesh and material slots.
- Bake nodes: check whether Blender cached data should be used or live graph output should be evaluated.
- Drivers on socket defaults: record presence, do not attempt to evaluate expressions.

## Relationship To Other IR

- Object Scene IR tells which objects have `NODES` modifiers and which node groups they reference.
- Geometry Nodes IR serializes those modifier node graphs.
- Material Node IR remains separate; GN can assign materials or generate attributes that materials later consume.
- Scene Bundle may reference the existence of GN, but exact procedural migration should use this dedicated IR.

## References

Read `references/ir-schema.md` when changing the schema or writing a converter.

## Blender Source Lookup

Use the Blender version from IR `app.build_branch`, `app.build_hash`, and `blender_version` before reading source. Prefer a tag/branch matching that runtime, for example `blender-v4.5-release` for Blender 4.5 LTS, and use `main` only when no matching branch is needed.

Official mirror roots:

- GitHub mirror: `https://github.com/blender/blender`
- Upstream project: `https://projects.blender.org/blender/blender`

Fast path for GN nodes:

- Ordinary Geometry Nodes: `source/blender/nodes/geometry/nodes/node_geo_*.cc`
- Repeat zone node definitions: `source/blender/nodes/geometry/nodes/node_geo_repeat.cc`
- Simulation zone node definitions: `source/blender/nodes/geometry/nodes/node_geo_simulation.cc`
- For Each Geometry Element definitions: `source/blender/nodes/geometry/nodes/node_geo_foreach_geometry_element.cc`
- Bake node definitions: `source/blender/nodes/geometry/nodes/node_geo_bake.cc`
- Zone execution/lazy function internals: `source/blender/nodes/intern/geometry_nodes_*_zone.cc`
- Main GN lazy execution: `source/blender/nodes/intern/geometry_nodes_lazy_function.cc`
- GN modifier integration: `source/blender/modifiers/intern/MOD_nodes.cc`
- Python/UI operators for zones/items: `scripts/startup/bl_operators/node.py`

Practical lookup rules:

1. Convert `bl_idname` such as `GeometryNodeRaycast` to likely filename `node_geo_raycast.cc`.
2. For `GeometryNodeStoreNamedAttribute`, look for `node_geo_store_named_attribute.cc`; for `GeometryNodeMeshToVolume`, look for `node_geo_mesh_to_volume.cc`.
3. For zone semantics, read both the `node_geo_*.cc` definition and `nodes/intern/geometry_nodes_*_zone.cc`.
4. Do not overfit converters to C++ internals. Use source to confirm sockets/items/bounds/semantics, then keep IR evidence from Python as the migration source of truth.
5. BSDF/render pipeline and GN execution are not portable by reading source alone; mark exact runtime parity as `needs-bake` or `needs-custom-runtime`.

## Files

- Exporter: `SpecialTools/geometry_node_ir.py`
- AI helper: `SpecialTools/geometry_node_ir_ai.py`
- Schema reference: `SpecialTools/skills/geometry-node-ir/references/ir-schema.md`
