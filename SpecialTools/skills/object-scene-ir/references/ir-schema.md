# HoTools Object Scene IR Schema

Canonical schema id: `hotools.object_scene_ir.v1`

Scene bundle schema id: `hotools.scene_asset_ir.v1`

## Top Level

- `schema`: versioned schema id.
- `blender_version`: Blender version array.
- `app`: export environment metadata.
- `scene`: scene name, frame, and unit system.
- `export`: scope, evaluated-mesh flag, and object count.
- `summary`: aggregate counts for quick review.
- `objects`: serialized object records.

## Object

- `name`, `type`, `library`, `data`: object and datablock identity.
- `parent`, `children`, `collections`: hierarchy and collection membership.
- `visible_get`, `hide_viewport`, `hide_render`, `select_get`: scene state.
- `matrix_world`, `matrix_local`, `location`, `rotation_*`, `scale`: transforms.
- `bound_box_world`: world-space bounds when available.
- `material_slots`: material slot order and linked material metadata.
- `modifiers`: modifier names, types, viewport/render flags, scalar RNA properties, and Geometry Nodes node group reference when present.
- `vertex_groups`: group names and assigned vertex counts.
- `mesh`: mesh data when `type == "MESH"`.

## Mesh

- `vertex_count`, `edge_count`, `polygon_count`, `loop_count`, `triangle_count`.
- `material_index_histogram`: polygon material index usage.
- `uv_layers`: names, active flags, data counts, and UV bounds.
- `color_attributes`: names, domains, data types, active/render flags.
- `attributes`: general mesh attributes, including non-color attributes used by shaders.
- `shape_keys`: shape key names, values, ranges, relative keys, and vertex group masks.

## Boundaries

- Evaluated mesh stats can be requested but are optional because they may allocate temporary meshes.
- This IR records Geometry Nodes modifiers but does not serialize Geometry Nodes graphs. Use `hotools.geometry_node_ir.v1` for the graph.
- Use Material Node IR for shader logic and Object Scene IR for scene/object context.

## Live Inspector

`SpecialTools/blender_live_inspector.py` can query live Blender/Goo data without writing a full scene bundle:

```powershell
blender --factory-startup --background asset.blend --python SpecialTools/blender_live_inspector.py -- --mode scene
```

Useful modes:

- `scene`: live object/material counts, UV layer names, color attributes, mesh attributes, and modifier types.
- `materials`: compact material list with node/image/group/Goo signal counts.
- `material`: inspect a specific live material.
- `compare-material-ir`: compare a live material against an exported Material Node IR JSON.

Use live inspector for quick verification or stale-export checks. Use Object Scene IR / Scene Bundle when the result must be archived or analyzed outside Blender.

## Scene Bundle

`hotools.scene_asset_ir.v1` is a convenience bundle for whole-scene migration analysis:

- `object_scene`: a complete `hotools.object_scene_ir.v1` payload for every object in the scene.
- `materials`: material records referenced by scene object material slots. Node materials include embedded `hotools.material_node_ir.v1` payloads.
- `geometry_nodes`: embedded `hotools.geometry_node_ir.v1` payload for scene Geometry Nodes modifiers, when enabled.
- `material_export_failures`: materials that could not be serialized and their error messages.
- `geometry_node_export_failures`: Geometry Nodes graph export errors.

The bundle is intentionally redundant. It is optimized for one-file AI analysis, while the embedded specialized IR payloads remain the evidence.

For very large scenes, prefer this order:

1. Live inspector for a quick question.
2. Separate Object Scene IR plus selected Material Node IR files for focused migration.
3. Full Scene Bundle only when whole-scene evidence is needed in one file.
