"""EdgeFlow tools vendored into HoTools MeshTools.

Adapted from Benjamin Sauder's EdgeFlow addon (GPL-3.0):
https://github.com/BenjaminSauder/EdgeFlow

This module intentionally keeps Set Flow, Set Curve and Set Linear together
so the shared edge-loop traversal and modal redo state have one owner.
"""

from collections import deque
import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from mathutils import Vector
from mathutils.geometry import interpolate_bezier


# -----------------------------------------------------------------------------
# Edge-loop traversal

def _walk_boundary(start_edge, limit_to_edges=None):
    edge_loop = {start_edge}
    visited = set()
    candidates = [start_edge]
    while True:
        for candidate in candidates:
            for vert in candidate.verts:
                if len(vert.link_edges) > 2:
                    for edge in vert.link_edges:
                        if not edge.is_boundary or edge in edge_loop:
                            continue
                        if limit_to_edges is None or edge in limit_to_edges:
                            edge_loop.add(edge)
            visited.add(candidate)
        candidates = edge_loop - visited
        if len(visited) == len(edge_loop):
            break

    raw = list(edge_loop)
    start_edge = raw.pop()
    ordered = deque([start_edge])
    add = ordered.append
    for point in start_edge.verts:
        while True:
            edge = next((item for item in raw if point in item.verts), None)
            if edge is None:
                break
            add(edge)
            point = edge.other_vert(point)
            raw.remove(edge)
        add = ordered.appendleft
    return list(ordered)


def _walk_ngon(start_edge, limit_to_edges=None):
    edge_loop = deque([start_edge])
    candidates = [loop for loop in start_edge.link_loops
                  if len(loop.face.verts) > 4]
    if not candidates:
        return list(edge_loop)
    start_loop = max(candidates, key=lambda item: len(item.face.verts))

    loop = start_loop.link_loop_next
    while len(loop.vert.link_edges) < 4 and loop.edge not in edge_loop:
        if limit_to_edges is not None and loop.edge not in limit_to_edges:
            break
        edge_loop.append(loop.edge)
        loop = loop.link_loop_next

    loop = start_loop.link_loop_prev
    while len(loop.edge.other_vert(loop.vert).link_edges) < 4 and loop.edge not in edge_loop:
        if limit_to_edges is not None and loop.edge not in limit_to_edges:
            break
        edge_loop.appendleft(loop.edge)
        loop = loop.link_loop_prev
    return list(edge_loop)


def _walk_edge_loop(start_edge, limit_to_edges=None):
    edge_loop = deque([start_edge])
    add = edge_loop.append
    for loop in start_edge.link_loops:
        start_valence = len(loop.vert.link_edges)
        if start_valence <= 4:
            while True:
                if len(loop.vert.link_edges) != 4 or start_valence != 4:
                    break
                loop = loop.link_loop_prev.link_loop_radial_prev.link_loop_prev
                if loop.edge in edge_loop:
                    break
                if limit_to_edges is not None and loop.edge not in limit_to_edges:
                    break
                add(loop.edge)
        add = edge_loop.appendleft
    return list(edge_loop)


def _get_edge_loop(bm, start_edge, limit_to_edges=None):
    is_ngon = any(len(loop.face.verts) > 4 for loop in start_edge.link_loops)
    quad_flow = all(len(vertex.link_edges) == 4 for vertex in start_edge.verts)
    loop_end = (
        len(start_edge.verts[0].link_edges) > 4
        and len(start_edge.verts[1].link_edges) == 4
    ) or (
        len(start_edge.verts[0].link_edges) == 4
        and len(start_edge.verts[1].link_edges) > 4
    )
    if is_ngon and not quad_flow and not loop_end:
        edges = _walk_ngon(start_edge, limit_to_edges)
    elif start_edge.is_boundary:
        edges = _walk_boundary(start_edge, limit_to_edges)
    else:
        edges = _walk_edge_loop(start_edge, limit_to_edges)
    return _EdgeLoop(bm, edges)


def _get_edge_loops(bm, edges):
    remaining = set(edges)
    result = []
    while remaining:
        edge = remaining.pop()
        loop = _get_edge_loop(bm, edge, remaining)
        result.append(loop)
        remaining.difference_update(loop.edges)
    return result


def _map_segment_onto_spline(segment, positions):
    """Place segment vertices at equal arc-length intervals on a spline."""
    if len(segment) <= 2 or len(positions) < 2:
        return
    total_length = sum(
        (positions[index] - positions[index - 1]).length
        for index in range(1, len(positions))
    )
    if total_length <= 1.0e-12:
        return
    step = total_length / float(len(segment) - 1)
    target_index = 1
    travelled = 0.0
    for index in range(1, len(positions)):
        travelled += (positions[index] - positions[index - 1]).length
        while target_index < len(segment) - 1 and travelled >= step * target_index:
            target_distance = step * target_index
            previous_distance = travelled - (positions[index] - positions[index - 1]).length
            fraction = (target_distance - previous_distance) / max(
                (travelled - previous_distance), 1.0e-12)
            segment[target_index].co = positions[index - 1].lerp(
                positions[index], fraction)
            target_index += 1
        if target_index >= len(segment) - 1:
            break


def _hermite_1d(y0, y1, y2, y3, mu, tension, bias=0.0):
    mu2 = mu * mu
    mu3 = mu2 * mu
    m0 = (y1 - y0) * (1 + bias) * (1 - tension) / 2
    m0 += (y2 - y1) * (1 - bias) * (1 - tension) / 2
    m1 = (y2 - y1) * (1 + bias) * (1 - tension) / 2
    m1 += (y3 - y2) * (1 - bias) * (1 - tension) / 2
    a0 = 2 * mu3 - 3 * mu2 + 1
    a1 = mu3 - 2 * mu2 + mu
    a2 = mu3 - mu2
    a3 = -2 * mu3 + 3 * mu2
    return a0 * y1 + a1 * m0 + a2 * m1 + a3 * y2


def _hermite_3d(p1, p2, p3, p4, mu, tension):
    return Vector((
        _hermite_1d(p1.x, p2.x, p3.x, p4.x, mu, tension),
        _hermite_1d(p1.y, p2.y, p3.y, p4.y, mu, tension),
        _hermite_1d(p1.z, p2.z, p3.z, p4.z, mu, tension),
    ))


def _smooth_step(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


class _EdgeLoop:
    """Ordered selected edges plus the three EdgeFlow transformations."""

    def __init__(self, bm, edges):
        self.bm = bm
        self.edges = list(edges)
        if not self.edges:
            self.verts = []
            self.is_cyclic = False
            self.initial_vert_positions = []
            return

        if len(self.edges) == 1:
            self.verts = list(self.edges[0].verts)
        else:
            first = next(
                (vertex for vertex in self.edges[0].verts
                 if vertex not in self.edges[1].verts),
                self.edges[0].verts[0],
            )
            self.verts = [first]
            last = first
            for edge in self.edges:
                last = edge.other_vert(last)
                self.verts.append(last)

        start_sum = self.verts[0].co.x + self.verts[0].co.y + self.verts[0].co.z
        end_sum = self.verts[-1].co.x + self.verts[-1].co.y + self.verts[-1].co.z
        if start_sum < end_sum:
            self.verts.reverse()
            self.edges.reverse()
        self.initial_vert_positions = [vertex.co.copy() for vertex in self.verts]
        self.is_cyclic = self.verts[0] == self.verts[-1]

    def set_linear(self, even_spacing=False):
        count = len(self.edges)
        if count < 2 or self.is_cyclic:
            return
        start = self.verts[0]
        end = self.verts[-1]
        direction = (end.co - start.co) / count
        direction_normalized = direction.normalized() if direction.length else direction
        for index, vertex in enumerate(self.verts[1:-1], 1):
            if even_spacing:
                vertex.co = start.co + direction * index
            else:
                scalar = (vertex.co - start.co).dot(direction_normalized)
                vertex.co = start.co + direction_normalized * scalar

    def set_curve_flow(self, tension, use_rail, rail_mode, rail_start, rail_end):
        count = len(self.edges)
        if count < 2 or self.is_cyclic:
            return
        start = self.verts[0]
        end = self.verts[-1]
        direction_start = self.edges[0].other_vert(start).co - start.co
        direction_end = self.edges[-1].other_vert(end).co - end.co
        if direction_start.length == 0 or direction_end.length == 0:
            return
        unit_start = direction_start.normalized()
        unit_end = direction_end.normalized()
        if use_rail:
            if rail_mode == 'ABSOLUTE':
                p1 = start.co + direction_start - unit_start * rail_start
                p4 = end.co + direction_end - unit_end * rail_end
            else:
                p1 = start.co + direction_start * rail_start
                p4 = end.co + direction_end * rail_end
        else:
            p1, p4 = start.co.copy(), end.co.copy()
        scale = (p1 - p4).length * 0.5 * tension
        p2 = p1 + unit_start * scale
        p3 = p4 + unit_end * scale
        spline = [interpolate_bezier(p1, p2, p3, p4, 1000)[index]
                  for index in range(1000)]
        _map_segment_onto_spline(self.verts, spline)

    def blend_start_end(self, blend_start, blend_end, blend_type):
        if self.is_cyclic or not self.verts:
            return
        count = len(self.verts)
        start_count = min(max(0, blend_start), count - 1)
        end_count = min(max(0, blend_end), count - 1)
        if start_count + end_count >= count:
            if start_count <= end_count:
                start_count = max(count - end_count - 1, 0)
            else:
                end_count = max(count - start_count - 1, 0)

        def apply_blend(blend_range, reverse=False):
            if blend_range <= 0:
                return
            indices = list(range(count))
            if reverse:
                indices.reverse()
            distances = [0.0]
            for index in range(1, blend_range + 1):
                distances.append(distances[-1] + (
                    self.verts[indices[index]].co
                    - self.verts[indices[index - 1]].co).length)
            total = distances[-1]
            if total <= 1.0e-12:
                return
            for index in range(blend_range + 1):
                factor = distances[index] / total
                if blend_type == 'SMOOTH':
                    factor = _smooth_step(factor)
                vertex = self.verts[indices[index]]
                vertex.co = self.initial_vert_positions[indices[index]].lerp(
                    vertex.co, factor)

        apply_blend(start_count)
        apply_blend(end_count, reverse=True)

    def set_flow(self, tension, min_angle):
        for edge in self.edges:
            if edge.is_boundary or len(edge.link_loops) < 2:
                continue
            targets = {}
            for loop in edge.link_loops:
                ring1 = loop.link_loop_next.link_loop_next
                ring2 = loop.link_loop_radial_prev.link_loop_prev.link_loop_prev
                center = edge.other_vert(loop.vert)
                p2 = ring1.vert
                p3 = ring2.link_loop_radial_next.vert

                if not ring1.edge.is_boundary:
                    final = ring1.link_loop_radial_next.link_loop_next
                    p1 = next(vertex for vertex in final.edge.verts if vertex != p2).co.copy()
                    angle = (p1 - p2.co).angle(center.co - p2.co)
                    if angle < min_angle:
                        p1 = p2.co - (p3.co - p2.co) * 0.5
                else:
                    p1 = p2.co - (p3.co - p2.co)

                if not ring2.edge.is_boundary:
                    final = ring2.link_loop_radial_prev.link_loop_prev
                    p4 = next(vertex for vertex in final.edge.verts if vertex != p3).co.copy()
                    angle = (p4 - p3.co).angle(center.co - p3.co)
                    if angle < min_angle:
                        p4 = p3.co - (p2.co - p3.co) * 0.5
                else:
                    p3 = ring2.edge.other_vert(p3)
                    p4 = p3.co - (p2.co - p3.co)
                targets[center] = (p1, p2.co.copy(), p3.co.copy(), p4)

            for vertex, (p1, p2, p3, p4) in targets.items():
                if (p1 - p2).length <= 1.0e-12 or (p3 - p4).length <= 1.0e-12:
                    continue
                distance = (p2 - p3).length * 0.5
                p1 = p2 + distance * (p1 - p2).normalized()
                p4 = p3 + distance * (p4 - p3).normalized()
                vertex.co = _hermite_3d(p1, p2, p3, p4, 0.5, -tension)


# -----------------------------------------------------------------------------
# Operators

class _SetEdgeLoopBase:
    mix: FloatProperty(
        name="Mix", default=1.0, min=0.0, max=1.0,
        subtype='FACTOR',description="Blend between the original and calculated positions",) # type: ignore

    @classmethod
    def poll(cls, context):
        return (
            getattr(getattr(context, "space_data", None), "type", None) == 'VIEW_3D'
            and getattr(getattr(context, "active_object", None), "type", None) == 'MESH'
            and getattr(getattr(context, "active_object", None), "mode", None) == 'EDIT'
        )

    def _prepare(self, context):
        selected = list(getattr(context, "selected_editable_objects", ()) or ())
        if not selected and context.active_object is not None:
            selected = [context.active_object]
        self._objects = []
        self._bmeshes = {}
        self._edgeloops = {}
        self._initial_positions = {}
        for obj in selected:
            if obj.type != 'MESH' or obj.mode != 'EDIT':
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            edges = [edge for edge in bm.edges if edge.select]
            if not edges:
                continue
            loops = _get_edge_loops(bm, edges)
            self._objects.append(obj)
            self._bmeshes[obj] = bm
            self._edgeloops[obj] = loops
            self._initial_positions[obj] = {
                vertex.index: vertex.co.copy()
                for edge in edges for vertex in edge.verts
            }
        self._prepared = True

    def _reset_positions(self):
        for obj in self._objects:
            bm = self._bmeshes[obj]
            for index, position in self._initial_positions[obj].items():
                bm.verts[index].co = position

    def _apply_mix(self):
        if self.mix >= 1.0:
            return
        for obj in self._objects:
            bm = self._bmeshes[obj]
            for loop in self._edgeloops[obj]:
                for vertex in loop.verts:
                    initial = self._initial_positions[obj].get(vertex.index)
                    if initial is not None:
                        vertex.co = initial.lerp(vertex.co, self.mix)

    def invoke(self, context, event):
        self._prepare(context)
        if event is not None and not event.alt:
            self._reset_defaults()
        return self.execute(context)

    def _reset_defaults(self):
        pass


class HO_OT_SetEdgeFlow(bpy.types.Operator, _SetEdgeLoopBase):
    bl_idname = "ho.set_edge_flow"
    bl_label = "设置流"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "调整选中边环以匹配周围曲面；按住 Alt 重用上次设置"

    blend_mode: EnumProperty(
        name="混合模式", items=(
            ('ABSOLUTE', "绝对数量", "按顶点数量混合"),
            ('FACTOR', "比例", "按边环比例混合"),
        ), default='ABSOLUTE',
    ) # type: ignore
    blend_type: EnumProperty(
        name="混合曲线", items=(
            ('LINEAR', "线性", ""), ('SMOOTH', "平滑", ""),
        ), default='LINEAR',
    ) # type: ignore
    tension: IntProperty(name="张力", default=180, min=-500, max=500) # type: ignore
    iterations: IntProperty(name="迭代", default=8, min=1, soft_max=32) # type: ignore
    min_angle: IntProperty(name="最小角度", default=0, min=0, max=180) # type: ignore
    blend_start_int: IntProperty(name="起始混合", default=0, min=0) # type: ignore
    blend_end_int: IntProperty(name="结束混合", default=0, min=0) # type: ignore
    blend_start_float: FloatProperty(name="起始混合", default=0.0, min=0.0, max=1.0, subtype='FACTOR') # type: ignore
    blend_end_float: FloatProperty(name="结束混合", default=0.0, min=0.0, max=1.0, subtype='FACTOR') # type: ignore

    def _reset_defaults(self):
        self.mix = 1.0
        self.tension = 180
        self.iterations = 16
        self.min_angle = 0
        self.blend_start_int = 0
        self.blend_end_int = 0
        self.blend_start_float = 0.0
        self.blend_end_float = 0.0

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "mix")
        layout.prop(self, "tension")
        layout.prop(self, "iterations")
        layout.prop(self, "min_angle")
        layout.prop(self, "blend_mode", expand=True)
        if self.blend_mode == 'ABSOLUTE':
            layout.prop(self, "blend_start_int")
            layout.prop(self, "blend_end_int")
        else:
            layout.prop(self, "blend_start_float")
            layout.prop(self, "blend_end_float")
        layout.prop(self, "blend_type", expand=True)

    def execute(self, context):
        if not getattr(self, "_prepared", False):
            self._prepare(context)
        self._reset_positions()
        for obj in self._objects:
            for _ in range(self.iterations):
                for loop in self._edgeloops[obj]:
                    loop.set_flow(self.tension / 100.0, math.radians(self.min_angle))
            for loop in self._edgeloops[obj]:
                if self.blend_mode == 'ABSOLUTE':
                    start, end = self.blend_start_int, self.blend_end_int
                else:
                    count = len(loop.verts)
                    start = round(count * self.blend_start_float)
                    end = round(count * self.blend_end_float)
                loop.blend_start_end(start, end, self.blend_type)
            self._bmeshes[obj].normal_update()
            bmesh.update_edit_mesh(obj.data)
        self._apply_mix()
        for obj in self._objects:
            bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class HO_OT_SetEdgeCurve(bpy.types.Operator, _SetEdgeLoopBase):
    bl_idname = "ho.set_edge_curve"
    bl_label = "设置曲线"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "沿边环方向设置曲线；按住 Alt 重用上次设置"

    rail_mode: EnumProperty(
        name="导轨模式", items=(
            ('ABSOLUTE', "绝对长度", ""), ('FACTOR', "比例", ""),
        ), default='FACTOR',
    ) # type: ignore
    tension: IntProperty(name="张力", default=100, soft_min=-500, soft_max=500) # type: ignore
    use_rail: BoolProperty(name="使用导轨", default=False) # type: ignore
    rail_start_width: FloatProperty(name="起始导轨", default=1.0, subtype='DISTANCE') # type: ignore
    rail_end_width: FloatProperty(name="结束导轨", default=1.0, subtype='DISTANCE') # type: ignore
    rail_start_factor: FloatProperty(name="起始导轨", default=1.0, soft_min=0.0, soft_max=1.5, subtype='FACTOR') # type: ignore
    rail_end_factor: FloatProperty(name="结束导轨", default=1.0, soft_min=0.0, soft_max=1.5, subtype='FACTOR') # type: ignore

    def _reset_defaults(self):
        self.tension = 100
        self.mix = 1.0

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "mix")
        layout.prop(self, "tension")
        layout.prop(self, "use_rail")
        column = layout.column(align=True)
        column.enabled = self.use_rail
        column.prop(self, "rail_mode", expand=True)
        if self.rail_mode == 'ABSOLUTE':
            column.prop(self, "rail_start_width", slider=False)
            column.prop(self, "rail_end_width", slider=False)
        else:
            column.prop(self, "rail_start_factor")
            column.prop(self, "rail_end_factor")

    def execute(self, context):
        if not getattr(self, "_prepared", False):
            self._prepare(context)
        self._reset_positions()
        for obj in self._objects:
            for loop in self._edgeloops[obj]:
                if self.rail_mode == 'ABSOLUTE':
                    start, end = self.rail_start_width, self.rail_end_width
                else:
                    start, end = self.rail_start_factor, self.rail_end_factor
                loop.set_curve_flow(self.tension / 100.0, self.use_rail, self.rail_mode, start, end)
            self._bmeshes[obj].normal_update()
            bmesh.update_edit_mesh(obj.data)
        self._apply_mix()
        for obj in self._objects:
            bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class HO_OT_SetEdgeLinear(bpy.types.Operator, _SetEdgeLoopBase):
    bl_idname = "ho.set_edge_linear"
    bl_label = "设置直线"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "将选中边环拉直"

    space_evenly: BoolProperty(name="均匀间距", default=False, description="以均匀距离分布顶点") # type: ignore

    def _reset_defaults(self):
        self.mix = 1.0

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "mix")
        layout.prop(self, "space_evenly")

    def execute(self, context):
        if not getattr(self, "_prepared", False):
            self._prepare(context)
        self._reset_positions()
        for obj in self._objects:
            for loop in self._edgeloops[obj]:
                loop.set_linear(self.space_evenly)
            self._bmeshes[obj].normal_update()
            bmesh.update_edit_mesh(obj.data)
        self._apply_mix()
        for obj in self._objects:
            bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


EDGE_FLOW_CLASSES = (HO_OT_SetEdgeFlow, HO_OT_SetEdgeCurve, HO_OT_SetEdgeLinear)


__all__ = [
    "HO_OT_SetEdgeFlow", "HO_OT_SetEdgeCurve", "HO_OT_SetEdgeLinear",
    "EDGE_FLOW_CLASSES",
]
