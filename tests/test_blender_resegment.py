"""Blender regression checks for MeshTools resegmentation."""

import sys
import math
import inspect
from types import MethodType, SimpleNamespace
from pathlib import Path

import bmesh
import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from MeshTools import resegment


def make_grid(width=3, height=4):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new("ResegmentGrid")
    coords = []
    for y in range(height + 1):
        for x in range(width + 1):
            coords.append((float(x), float(y), 0.15 * x * y))
    faces = []
    row_width = width + 1
    for y in range(height):
        for x in range(width):
            bottom = y * row_width + x
            faces.append((
                bottom,
                bottom + 1,
                bottom + row_width + 1,
                bottom + row_width,
            ))
    mesh.from_pydata(coords, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("ResegmentGrid", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    return obj


def make_cyclic_grid(width=8, height=4):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new("ResegmentCyclicGrid")
    coords = []
    for y in range(height + 1):
        for x in range(width):
            angle = 2.0 * math.pi * x / width
            coords.append((
                2.0 * math.cos(angle),
                float(y),
                2.0 * math.sin(angle),
            ))
    faces = []
    for y in range(height):
        for x in range(width):
            first = y * width + x
            second = y * width + (x + 1) % width
            next_first = (y + 1) * width + x
            next_second = (y + 1) * width + (x + 1) % width
            faces.append((first, second, next_second, next_first))
    mesh.from_pydata(coords, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("ResegmentCyclicGrid", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    return obj


def select_horizontal_rows(obj, rows):
    bm = bmesh.from_edit_mesh(obj.data)
    for element in (*bm.verts, *bm.edges, *bm.faces):
        element.select_set(False)
    for edge in bm.edges:
        first, second = edge.verts
        if (
            abs(first.co.y - second.co.y) < 1.0e-6
            and round(first.co.y) in rows
        ):
            edge.select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def select_vertical_rails(obj, x_values):
    bm = bmesh.from_edit_mesh(obj.data)
    for element in (*bm.verts, *bm.edges, *bm.faces):
        element.select_set(False)
    for edge in bm.edges:
        first, second = edge.verts
        if (
            abs(first.co.x - second.co.x) < 1.0e-6
            and round(first.co.x) in x_values
        ):
            edge.select_set(True)
    bmesh.update_edit_mesh(obj.data)


def select_capped_vertical_rails(obj, x_values, end_rows):
    select_vertical_rails(obj, x_values)
    bm = bmesh.from_edit_mesh(obj.data)
    for edge in bm.edges:
        first, second = edge.verts
        if (
            abs(first.co.y - second.co.y) < 1.0e-6
            and round(first.co.y) in end_rows
        ):
            edge.select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def select_all_vertical_rails(obj, first_row, last_row):
    bm = bmesh.from_edit_mesh(obj.data)
    for element in (*bm.verts, *bm.edges, *bm.faces):
        element.select_set(False)
    for edge in bm.edges:
        first, second = edge.verts
        if (
            abs(first.co.x - second.co.x) < 1.0e-6
            and abs(first.co.y - second.co.y) > 1.0e-6
            and min(first.co.y, second.co.y) >= first_row - 1.0e-6
            and max(first.co.y, second.co.y) <= last_row + 1.0e-6
        ):
            edge.select_set(True)
    bmesh.update_edit_mesh(obj.data)


def snapshot_mesh(obj):
    snapshot = resegment._mesh_snapshot(obj)
    return snapshot


def apply_preview(obj, descriptor, segment_count, smoothness,
                  slide_strength=0.0):
    snapshot = snapshot_mesh(obj)
    work = bmesh.new()
    try:
        work.from_mesh(snapshot)
        internal = [
            edge for ring in descriptor.ring_edge_keys[1:-1]
            for key in ring
            for edge in work.edges
            if resegment._edge_key(edge) == key
        ]
        bmesh.ops.dissolve_edges(
            work,
            edges=internal,
            use_verts=True,
            use_face_split=False,
        )
        work.free()
        work = bmesh.new()
        work.from_mesh(snapshot)
        new_edges = resegment._apply_descriptor(
            work,
            descriptor,
            segment_count,
            smoothness,
            slide_strength,
        )
        return (
            len(work.verts),
            len(work.edges),
            len(work.faces),
            len(new_edges),
        )
    finally:
        work.free()
        if snapshot.users == 0:
            bpy.data.meshes.remove(snapshot)


obj = make_grid()
select_horizontal_rows(obj, {0, 2, 4})
descriptor = resegment._build_descriptor(bpy.context, "LOOPS")
assert descriptor.segment_count == 4
assert descriptor.vertex_count == 4
assert descriptor.column_count == 3
assert apply_preview(obj, descriptor, 6, 0.0) == (28, 45, 18, 15)
assert apply_preview(obj, descriptor, 2, 0.0) == (12, 17, 6, 3)

select_horizontal_rows(obj, {0, 4})
descriptor = resegment._build_descriptor(bpy.context, "LOOPS")
assert descriptor.segment_count == 4
assert descriptor.vertex_count == 4

bm = bmesh.from_edit_mesh(obj.data)
for vertex in bm.verts:
    row = round(vertex.co.y)
    if abs(vertex.co.y - row) < 1.0e-6:
        vertex.co.y = (0.0, 0.5, 2.2, 3.1, 5.0)[row]
bmesh.update_edit_mesh(obj.data)
descriptor = resegment._build_descriptor(bpy.context, "LOOPS")
target_positions = resegment._target_positions(
    descriptor,
    descriptor.segment_count,
    0.0,
    1.0,
)
for column in range(descriptor.vertex_count):
    source_path = tuple(
        ring[column] for ring in descriptor.source_positions
    )
    for index in range(descriptor.segment_count + 1):
        expected = resegment._linear_sample(
            source_path,
            descriptor.column_parameters[column],
            index / float(descriptor.segment_count),
        )
        assert (
            target_positions[index][column] - expected
        ).length < 1.0e-6
assert (
    target_positions[1][0] - descriptor.source_positions[1][0]
).length > 0.25
assert apply_preview(
    obj,
    descriptor,
    descriptor.segment_count,
    0.0,
    1.0,
) == (20, 31, 12, 9)
for vertex in bm.verts:
    vertex.co.y = (0.0, 1.0, 2.0, 3.0, 4.0)[vertex.index // 4]
bmesh.update_edit_mesh(obj.data)

select_capped_vertical_rails(obj, {0, 3}, {0, 4})
descriptor = resegment._build_descriptor(bpy.context, "STRIP")
assert descriptor.segment_count == 4
assert descriptor.vertex_count == 4

select_vertical_rails(obj, {0, 3})
descriptor = resegment._build_descriptor(bpy.context, "STRIP")
assert descriptor.segment_count == 4
assert descriptor.vertex_count == 4
assert descriptor.column_count == 3
assert apply_preview(obj, descriptor, 6, 0.0) == (28, 45, 18, 15)

select_all_vertical_rails(obj, 1, 3)
descriptor = resegment._build_descriptor(bpy.context, "STRIP")
assert descriptor.segment_count == 2
assert descriptor.vertex_count == 4
assert descriptor.column_count == 3
assert apply_preview(obj, descriptor, 4, 0.0) == (28, 45, 18, 9)

bpy.ops.object.mode_set(mode="OBJECT")
mesh = obj.data
bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.meshes.remove(mesh)

obj = make_cyclic_grid()
select_all_vertical_rails(obj, 1, 3)
descriptor = resegment._build_descriptor(bpy.context, "STRIP")
assert descriptor.cyclic
assert descriptor.segment_count == 2
assert descriptor.vertex_count == 8
assert descriptor.column_count == 8
assert apply_preview(obj, descriptor, 4, 0.0) == (56, 104, 48, 24)

select_horizontal_rows(obj, {0, 2, 4})
descriptor = resegment._build_descriptor(bpy.context, "LOOPS")
assert descriptor.cyclic
assert descriptor.segment_count == 4
assert descriptor.vertex_count == 8
assert descriptor.column_count == 8
assert apply_preview(obj, descriptor, 6, 0.0) == (56, 104, 48, 40)

import MeshTools

MeshTools.register()
before = (
    len(bpy.context.active_object.data.vertices),
    len(bpy.context.active_object.data.edges),
    len(bpy.context.active_object.data.polygons),
)
operator = SimpleNamespace(
    _source_object=None,
    _snapshot=None,
    _descriptor=None,
    _original_selected_edge_keys=None,
    _handle_text=None,
    _timer=None,
    _window_manager=None,
    _preview_dirty=False,
    selection_mode="LOOPS",
    segment_count=1,
    smoothness=0.0,
    slide_strength=0.0,
    report=lambda *_args, **_kwargs: None,
)
for cls in resegment.HO_OT_ResegmentLoops.__mro__:
    for name, method in vars(cls).items():
        if inspect.isfunction(method):
            setattr(operator, name, MethodType(method, operator))
assert operator._prepare(bpy.context)
operator.segment_count = 6
operator.smoothness = 0.0
operator._rebuild(bpy.context)
timer = object()
operator._timer = timer
operator._window_manager = SimpleNamespace(event_timer_remove=lambda _timer: None)
modal_context = SimpleNamespace(active_object=obj, area=None)
alt_wheel = SimpleNamespace(
    type="WHEELUPMOUSE",
    value="PRESS",
    alt=True,
    ctrl=False,
    shift=False,
)
assert operator.modal(modal_context, alt_wheel) == {"RUNNING_MODAL"}
assert operator.slide_strength == 0.05
assert operator._preview_dirty
timer_event = SimpleNamespace(type="TIMER", timer=timer)
assert operator.modal(modal_context, timer_event) == {"RUNNING_MODAL"}
assert not operator._preview_dirty
assert operator._cancel(bpy.context) == {"CANCELLED"}
bm = bmesh.from_edit_mesh(obj.data)
assert (len(bm.verts), len(bm.edges), len(bm.faces)) == before
assert sum(edge.select for edge in bm.edges) == 24

result = bpy.ops.ho.resegment_loops(segment_count=6, smoothness=0.0)
assert result == {"FINISHED"}
bm = bmesh.from_edit_mesh(obj.data)
assert (len(bm.verts), len(bm.edges), len(bm.faces)) == (56, 104, 48)
assert sum(edge.select for edge in bm.edges) == 56
assert not any(
    attribute.name == "hotools_resegment_identity"
    for attribute in obj.data.attributes
)
MeshTools.unregister()

bpy.ops.object.mode_set(mode="OBJECT")
mesh = obj.data
bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.meshes.remove(mesh)
print("RESEGMENT_OK")
