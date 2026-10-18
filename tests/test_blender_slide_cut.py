"""Slide cuts must continue across triangle fans along a selected rim."""

import sys
import inspect
from pathlib import Path
from types import MethodType, SimpleNamespace

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from MeshTools import offset_edges_modal as cut


def make_strip(triangles=3, closed=False):
    # Two selected rim edges meet at the apex of an arbitrary triangle fan.
    coords = [(-3, 1, 0), (0, 1, 0), (3, 1, 0), (-3, -1, 0)]
    coords.extend((-1 + 2 * i / max(1, triangles), -1, 0.3 * (i % 2)) for i in range(triangles + 1))
    end = len(coords)
    coords.append((3, -1, 0))
    faces = [(0, 3, 4, 1)]
    faces.extend((1, 4 + i, 5 + i) for i in range(triangles))
    faces.append((1, 4 + triangles, end, 2))
    keys = {(0, 1), (1, 2)}
    if closed:
        top, outside = len(coords), len(coords) + 1
        coords.extend([(0, 3, 0), (0, 5, 0)])
        faces.extend([(2, end, outside, top), (top, outside, 3, 0)])
        keys.update({tuple(sorted((2, top))), (0, top)})
    mesh = bpy.data.meshes.new("SlideCutFan")
    mesh.from_pydata(coords, [], faces)
    return mesh, keys


def selected_components(bm):
    remaining = {e for e in bm.edges if e.select}
    components = []
    while remaining:
        pending = [remaining.pop()]
        current = set(pending)
        while pending:
            edge = pending.pop()
            for vert in edge.verts:
                for linked in vert.link_edges:
                    if linked in remaining:
                        remaining.remove(linked)
                        current.add(linked)
                        pending.append(linked)
        components.append(current)
    return components


for triangles in (0, 1, 3, 7):
    for closed in (False, True):
        mesh, keys = make_strip(triangles, closed)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        cut._ensure_tables(bm)
        specs = cut._collect_inner_specs(bm, keys)
        bm.free()
        cache = cut._build_inner_cut_cache(mesh, specs, 0.5)
        try:
            components = selected_components(cache["bm"])
            assert len(components) == 1, f"三角面扇区切线断开：{triangles=} {closed=} {len(components)=}"
            edges = components[0]
            assert len(edges) == triangles + (4 if closed else 2), "扇区里的每个三角面都必须切到"
            vertices = {v for e in edges for v in e.verts}
            degrees = [sum(e in edges for e in v.link_edges) for v in vertices]
            assert degrees.count(1) == (0 if closed else 2)
            assert all(degree in (1, 2) for degree in degrees), "切线不应分叉"
            assert all(e.is_manifold for e in edges), "切线必须真正分面，不能是悬空线"
        finally:
            cut._free_inner_cut_cache(cache)
            bpy.data.meshes.remove(mesh)

# Exercise the same cached preview updates and cancel path used by the modal.
mesh, keys = make_strip(5, closed=True)
obj = bpy.data.objects.new("SlideCutPreview", mesh)
bpy.context.scene.collection.objects.link(obj)
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.context.tool_settings.mesh_select_mode = (False, True, False)
bpy.ops.object.mode_set(mode="EDIT")
bm = bmesh.from_edit_mesh(mesh)
cut._ensure_tables(bm)
for face in bm.faces:
    face.select_set(False)
for vert in bm.verts:
    vert.select_set(False)
for edge in bm.edges:
    edge.select_set(cut._edge_key(edge) in keys)
bm.select_flush_mode()
before = (len(bm.verts), len(bm.edges), len(bm.faces))
op = SimpleNamespace(
    _source_object=obj, _snapshot=cut._mesh_snapshot(obj),
    _selected_edge_keys=cut._selected_edge_keys(obj), _inner_cache=None,
    _handle_text=None, _offset_infos=None, _edge_indices=None,
)
for name, method in vars(cut.OP_SlideCut).items():
    if inspect.isfunction(method):
        setattr(op, name, MethodType(method, op))
op._prepare_inner()
for factor in (0.05, 0.25, 0.5, 0.95):
    op.slide_factor = factor
    op._rebuild_inner()
    bm = bmesh.from_edit_mesh(mesh)
    components = selected_components(bm)
    assert len(components) == 1 and len(components[0]) == 9
    for point, start, end in op._inner_cache["points"]:
        assert (point.co - start.lerp(end, factor)).length < 1e-6
assert op._cancel(bpy.context) == {"CANCELLED"}
bm = bmesh.from_edit_mesh(mesh)
cut._ensure_tables(bm)
assert (len(bm.verts), len(bm.edges), len(bm.faces)) == before
assert cut._selected_edge_keys(obj) == keys, "取消滑切应恢复原始选边"
bpy.ops.object.mode_set(mode="OBJECT")
bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.meshes.remove(mesh)

print("SLIDE_CUT_OK")
