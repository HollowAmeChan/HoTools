# HoTools module boundaries

`FastOperators.py` and the temporary legacy implementation have been removed.
Each operation is implemented and registered by its owning module:

| Module | Responsibility | Operators |
| --- | --- | --- |
| `ProjectTools` | Blender session and scene visibility | `ho.restart_blender`, `ho.sync_render_visibility` |
| `ObjectTools` | Object transforms, image references, and lattice setup | `ho.align`, `ho.align_relative`, `ho.placeobjectbottom`, `ho.snap_selected_face_orthogonal`, `ho.auto_place_object_bottom`, `ho.auto_snap_face_orthogonal`, `ho.mesh_to_image_empty`, `ho.quick_add_lattice` |
| `CurveTools` | Curve editing, curve symmetry, menus, and curve shortcuts | `ho.curve_bevel`, `ho.repair_curve_path`, `ho.curve_symmetrize` |
| `MeshTools` | Mesh topology, mesh symmetry, mesh normals, and mesh shortcuts | `ho.symmetrize`, `ho.custom_splitnormal_export`, `ho.custom_splitnormal_import`, `ho.merge_overlapping_vertexnormals` |
| `ModifierTools` | Modifier stack operations | `ho.copyall_modifiers_to_selected` |

MeshTools and CurveTools are independent. They share the `Alt-X` shortcut
convention, but use distinct operator IDs and type-specific `poll` methods.
