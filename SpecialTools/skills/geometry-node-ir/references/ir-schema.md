# HoTools Geometry Nodes IR Schema

Canonical schema id: `hotools.geometry_node_ir.v1`

## Root

- `schema`: schema id.
- `blender_version`: Blender/Goo version tuple.
- `app`: runtime metadata and source flavor hint.
- `scene`: scene name and current frame.
- `export`: scope, object count, modifier count, and whether nested groups were inlined.
- `summary`: aggregate Geometry Nodes modifier count, node type counts, zone counts, and failure count.
- `modifiers`: one record per Geometry Nodes modifier.
- `export_failures`: modifier-level export errors.

## Modifier Record

- `object`: object name, type, library, and object data reference.
- `modifier`: modifier name, flags, RNA scalar properties, custom properties, and node group reference.
- `summary`: tree count, node count, link count, node type counts, and zone counts for this modifier.
- `node_tree`: serialized `GeometryNodeTree`.
- `export_error`: error string when this modifier could not be serialized.

## Node Tree

- `name`, `bl_idname`.
- `interface`: tree interface items, including socket identifier, type, direction, and parent panel when available.
- `has_drivers`, `drivers`: driver presence on node tree data.
- `nodes`: serialized nodes.
- `links`: links by node name and socket index/identifier.
- `zones`: zone pair summaries for this tree.

## Node

- `name`, `label`, `type`, `bl_idname`.
- `location`, `width`, `height`, `mute`, `hide`, color and frame parent metadata.
- `inputs`, `outputs`: socket names, identifiers, default values, link state, min/max, and driver presence.
- `properties`: scalar RNA properties.
- `datablocks`: references such as `node_tree`, `object`, `collection`, `material`, `texture`, or `image`.
- `item_collections`: special collections such as zone items, bake items, capture items, and menu items.
- `group_tree`: inlined nested node group when enabled.
- `group_tree_ref`: node group reference when nested groups are not inlined.

## Zones

Each `zones` item records:

- `kind`: `simulation`, `repeat`, `foreach_geometry_element`, or `closure`.
- `input_node`, `input_bl_idname`.
- `output_node`, `output_bl_idname`.
- `status`: `paired`, `unpaired`, or `output_without_detected_input`.
- `items`: output-side item collections such as `state_items`, `repeat_items`, `input_items`, `main_items`, `generation_items`, and `output_items`.
- `output_properties`: scalar RNA properties on the output node.

## Boundary

This schema preserves enough graph evidence for AI reasoning and converter planning. It is not a Blender evaluator. Exact generated mesh output still requires evaluating the modifier in Blender, exporting an evaluated mesh, or implementing equivalent runtime logic.

Blender UI red values or missing field resources should be treated as `fallback-suspected`, not proof that the node tree is unusable. Named Attribute may return default values or `Exists=false`; invalid domains and missing resources can still produce empty/default fields. When migration depends on the result, compare the IR with evaluated mesh evidence.
