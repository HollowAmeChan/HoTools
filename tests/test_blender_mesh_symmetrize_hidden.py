"""Alt-X must not lose geometry when its source side is hidden."""

import sys
from pathlib import Path
from unittest.mock import patch

import bmesh
import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Utils.symmetrize import symmetrize


def make_scene(hidden_side, axis=0):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new("Mesh")
    obj = bpy.data.objects.new("Mesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    for x in (-2, 2):
        offset = [0, 0, 0]
        offset[axis] = x
        bmesh.ops.create_cube(bm, size=1, matrix=Matrix.Translation(offset))
    bm.to_mesh(mesh)
    bm.free()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(mesh)
    for face in bm.faces:
        if face.calc_center_median()[axis] * hidden_side > 0:
            face.hide_set(True)
    for vert in bm.verts:
        if vert.hide:
            vert.select_set(False)
    bmesh.update_edit_mesh(mesh)
    return obj


def visibility(bm):
    return tuple(sorted(
        (tuple(sorted(tuple(v.co) for v in ([e] if isinstance(e, bmesh.types.BMVert) else e.verts))), e.hide)
        for e in elements
    ) for elements in (bm.verts, bm.edges, bm.faces))


# Source and destination masks are independent, across all axes/directions.
for axis, axis_name in enumerate("XYZ"):
    for direction in ("POSITIVE", "NEGATIVE"):
        for hidden_side in (-1, 1):
            obj = make_scene(hidden_side, axis)
            before = visibility(bmesh.from_edit_mesh(obj.data))
            symmetrize(obj, direction=f"{direction}_{axis_name}")
            bm = bmesh.from_edit_mesh(obj.data)
            assert len(bm.verts) == 16 and len(bm.faces) == 12, "隐藏一侧时对称导致几何丢失或重复"
            assert visibility(bm) == before, "顶点、边或面的隐藏状态改变"
            assert not any(e.hide and e.select for elements in (bm.verts, bm.edges, bm.faces) for e in elements)

# The hidden source's deformation must actually reach the visible destination.
obj = make_scene(1)
bm = bmesh.from_edit_mesh(obj.data)
for vert in bm.verts:
    if vert.co.x > 0:
        vert.co.z += 0.3
source_coords = {tuple(vert.co) for vert in bm.verts if vert.co.x > 0}
symmetrize(obj, direction="POSITIVE_X")
bm = bmesh.from_edit_mesh(obj.data)
assert {tuple(vert.co) for vert in bm.verts if vert.co.x > 0} == source_coords
assert {(-vert.co.x, vert.co.y, vert.co.z) for vert in bm.verts if vert.co.x < 0} == source_coords
assert all(vert.hide == (vert.co.x > 0) for vert in bm.verts)

# Remove mode includes hidden geometry and keeps the remaining side's mask.
for hidden_side in (-1, 1):
    obj = make_scene(hidden_side)
    symmetrize(obj, direction="POSITIVE_X", remove=True)
    bm = bmesh.from_edit_mesh(obj.data)
    assert len(bm.verts) == 8 and len(bm.faces) == 6
    assert all(vert.co.x > 0 and vert.hide == (hidden_side == 1) for vert in bm.verts)

# No temporary reveal may leak when the operation fails.
obj = make_scene(1)
before = visibility(bmesh.from_edit_mesh(obj.data))
with patch("Utils.symmetrize._symmetrize_mesh", side_effect=RuntimeError("expected")):
    try:
        symmetrize(obj)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected the injected failure")
assert visibility(bmesh.from_edit_mesh(obj.data)) == before

# Faces may be hidden independently without hiding their boundary vertices.
obj = make_scene(0)
bm = bmesh.from_edit_mesh(obj.data)
next(face for face in bm.faces if face.calc_center_median().x > 0).hide = True
before = visibility(bm)
symmetrize(obj)
assert visibility(bmesh.from_edit_mesh(obj.data)) == before

# Native operators act on all meshes in multi-object Edit Mode.
obj = make_scene(1)
bpy.ops.object.mode_set(mode="OBJECT")
other = obj.copy()
other.data = obj.data.copy()
bpy.context.scene.collection.objects.link(other)
other.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
before = {item.name: visibility(bmesh.from_edit_mesh(item.data)) for item in (obj, other)}
symmetrize(obj)
for item in (obj, other):
    bm = bmesh.from_edit_mesh(item.data)
    assert len(bm.verts) == 16 and len(bm.faces) == 12
    assert visibility(bm) == before[item.name]

print("MESH_SYMMETRIZE_HIDDEN_OK")
