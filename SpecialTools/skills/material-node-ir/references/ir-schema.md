# HoTools Material Node IR Schema

Canonical schema id: `hotools.material_node_ir.v1`

## Top Level

- `schema`: versioned schema id.
- `blender_version`: Blender version array.
- `material`: material metadata and RNA-backed properties.
- `node_tree`: serialized shader node tree.

## Node Tree

- `name`: Blender node tree name.
- `bl_idname`: node tree RNA id.
- `interface`: node group interface items when available.
- `nodes`: serialized nodes.
- `links`: graph edges between output sockets and input sockets.

## Node

- `name`: graph-local node identifier.
- `label`: optional UI label.
- `type`: Blender node category enum.
- `bl_idname`: concrete Blender node type.
- `location`, `width`, `height`: editor layout, useful for visual reconstruction.
- `inputs`, `outputs`: sockets with indexes, names, identifiers, types, link state, and default values.
- `properties`: scalar RNA properties safe to serialize.
- `image`: image texture metadata when the node references a Blender image.
- `group_tree`: recursively serialized nested node group when enabled.

## Link

- `from_node`, `from_socket`: source node and socket reference.
- `to_node`, `to_socket`: destination node and socket reference.
- `is_muted`, `is_valid`: Blender link flags.

## Migration Guidance

Use the JSON as source of truth. Map Blender shader semantics in a later pass:

- Principled BSDF inputs usually map to glTF PBR fields.
- Image texture nodes should preserve color space before Unity import settings are inferred.
- Math, Mix, ColorRamp, NormalMap, Bump, and custom node groups often need Unity Shader Graph or custom shader translation rather than direct glTF fields.

## Pure Python AI Helper

`SpecialTools/material_ir_ai.py` is the external-project helper. It has no Blender dependency and should remain standard-library only.

Useful functions:

- `load_ir(path)`: load exported JSON.
- `summarize_ir(ir)`: produce counts, node type histogram, and image metadata.
- `build_ai_context(ir)`: create a compact markdown packet for AI prompts.
- `build_user_preview(ir)`: create a chat-friendly user estimate covering capabilities, likely design, migration changes, risks, and boundaries.
- `extract_gltf_pbr_candidates(ir)`: identify root Principled BSDF inputs and whether each field is linked or defaulted.
- `collect_source_urls(ir)`: create official Blender source lookup URLs for node types in the IR.
- `analyze_cleanup(ir)`: find nodes not reachable from output nodes.
- `analyze_groups(ir)`: inspect node group interfaces, nested trees, drivers, and internal unused nodes.
- `analyze_annotations(ir)`: inspect node editor Frame regions, labels, and custom node colors.
- `analyze_color_transforms(ir)`: inspect ColorRamp and RGB/Float/Vector Curve nodes, including serialized ramp elements and curve points when present.
- `analyze_images(ir)`: inspect duplicate images, file format hints, color space, sampling, packed/dirty state, and direct uses.
- `analyze_drivers(ir)`: report tree drivers and driven sockets without expanding driver logic.
- `analyze_custom_inputs(ir)`: find UV/object/attribute/geometry/context-dependent input nodes.
- `analyze_goo_engine(ir)`: report Goo Engine/forked Blender suspicion, unknown ShaderNode types, and Goo source search URLs.
- `analyze_material_audit(ir)`: run the main conversion-readiness checks together.
- `trace_input(tree, node_name, socket_name_or_index)`: show upstream source chains inside one node tree.

Use this helper for AI orientation. Keep actual conversion decisions explicit and reviewable.

## Analysis Boundaries

- Cleanup only reports reachability. It must not auto-delete nodes.
- Frame nodes, labels, and custom colors are author annotations. They should influence explanation and grouping, not shader evaluation.
- ColorRamp/Curve nodes are look-development transforms. If ramp elements or curve points are missing, the material must be re-exported with the updated Blender-side exporter before precise migration.
- Driver analysis only reports existence and target sockets. Driver logic/evaluation remains Blender-side work.
- Image analysis can flag likely color-space risks, but final texture role should come from graph links and user review.
- Context input analysis flags dependencies that may exceed the current material-only IR, such as UV set selection, mesh attributes, object coordinates, object random, and vertex colors.
- Goo Engine analysis is conservative. User confirmation or app metadata is strong evidence; unknown/fork-like nodes and NPR naming are only suspicion.

## Blender Source Boundaries

Blender shader node source is useful at different confidence levels:

- High usefulness: socket declarations, enum names, default values, image/color-space metadata handling, procedural value-node formulas.
- Medium usefulness: GPU shader helper code for viewport/EEVEE and MaterialX export hooks. These are useful implementation clues, but not always the final render truth.
- Boundary only: BSDF, Volume, Add Shader, Mix Shader, and Output nodes. Their appearance depends on renderer internals, pipeline lighting, color management, sampling, and target-engine BRDF choices.

When source and IR disagree, trust the IR for the exported file and note the Blender source version checked.
