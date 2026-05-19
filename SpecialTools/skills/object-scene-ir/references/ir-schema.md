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
- This IR records Geometry Nodes modifiers but does not serialize Geometry Nodes graphs.
- Use Material Node IR for shader logic and Object Scene IR for scene/object context.

## Scene Bundle

`hotools.scene_asset_ir.v1` is a convenience bundle for whole-scene migration analysis:

- `object_scene`: a complete `hotools.object_scene_ir.v1` payload for every object in the scene.
- `materials`: material records referenced by scene object material slots. Node materials include embedded `hotools.material_node_ir.v1` payloads.
- `material_export_failures`: materials that could not be serialized and their error messages.

The bundle is intentionally redundant. It is optimized for one-file AI analysis, while the embedded specialized IR payloads remain the evidence.
