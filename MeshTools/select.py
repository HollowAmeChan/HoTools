"""MESHmachine-style selection helpers for MeshTools."""

from math import degrees

import bmesh
import bpy
from bpy.props import BoolProperty, IntProperty
from mathutils import Vector

def _is_edit_mesh(context):
    return (
        context.mode == 'EDIT_MESH'
        and context.active_object is not None
        and context.active_object.type == 'MESH'
    )


def _mesh_mode(context):
    return tuple(context.scene.tool_settings.mesh_select_mode)


def _selected_edges(bm):
    return [edge for edge in bm.edges if edge.select and not edge.hide]


def _selected_faces(bm):
    return [face for face in bm.faces if face.select and not face.hide]


def _selected_vertices(bm):
    return [vert for vert in bm.verts if vert.select and not vert.hide]


def _isolated_edges(edges):
    edge_set = set(edges)
    return [
        edge for edge in edges
        if not any(
            other in edge_set
            for vert in edge.verts
            for other in vert.link_edges
            if other is not edge
        )
    ]


def _select_sharp_chain(bm):
    selected = [edge for edge in bm.edges if edge.select and not edge.smooth]
    chain = list(selected)
    pending = list(selected)
    while pending:
        edge = pending.pop()
        for vert in edge.verts:
            for neighbor in vert.link_edges:
                if not neighbor.smooth and neighbor not in chain:
                    chain.append(neighbor)
                    pending.append(neighbor)
    for edge in chain:
        edge.select_set(True)
    return chain


def _edge_continuation(edge, vertex, min_angle):
    direction = edge.other_vert(vertex).co - vertex.co
    if direction.length_squared == 0:
        return None
    direction.normalize()
    candidates = []
    for candidate in vertex.link_edges:
        if candidate is edge or candidate.hide:
            continue
        other = candidate.other_vert(vertex)
        vector = other.co - vertex.co
        if vector.length_squared == 0:
            continue
        vector.normalize()
        continuation = degrees(direction.angle(-vector))
        if continuation <= min_angle:
            candidates.append((continuation, candidate))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _select_edge_loops(bm, edges, min_angle):
    selected = set(edges)
    for edge in edges:
        for vertex in edge.verts:
            previous = edge
            current_vertex = vertex
            while True:
                continuation = _edge_continuation(previous, current_vertex, min_angle)
                if continuation is None or continuation in selected:
                    break
                selected.add(continuation)
                continuation.select_set(True)
                current_vertex = continuation.other_vert(current_vertex)
                previous = continuation
    return selected


class OP_SelectVertexGroup(bpy.types.Operator):
    bl_idname = 'ho.vselect'
    bl_label = '顶点组选择'
    bl_description = '选择属于一个或多个顶点组的顶点'
    bl_options = {'REGISTER', 'UNDO'}

    sel_idx: IntProperty(name='组索引', default=0)  # type: ignore

    @classmethod
    def poll(cls, context):
        return _is_edit_mesh(context) and bool(context.active_object.vertex_groups)

    def _group_vertices(self, obj, group_index):
        return [
            vertex.index
            for vertex in obj.data.vertices
            if any(
                item.group == group_index and item.weight > 0.0
                for item in vertex.groups
            )
        ]

    def _prepare(self, context):
        if hasattr(self, 'group_indices') and hasattr(self, 'active_group'):
            return bool(self.group_indices)
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        selected = _selected_vertices(bm)
        groups = []
        for group in obj.vertex_groups:
            if any(
                any(item.group == group.index for item in obj.data.vertices[vert.index].groups)
                for vert in selected
            ):
                groups.append(group.index)
        if not groups:
            return False
        self.group_indices = groups
        self.sel_idx %= len(groups)
        self.active_group = groups[self.sel_idx]
        self.select_all_groups = False
        return True

    def invoke(self, context, event):
        if not self._prepare(context):
            return {'CANCELLED'}
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'} if len(self.group_indices) > 1 else self.execute(context)

    def modal(self, context, event):
        if event.type in {'WHEELUPMOUSE', 'ONE'} and event.value == 'PRESS':
            self.sel_idx = (self.sel_idx + 1) % len(self.group_indices)
            self.active_group = self.group_indices[self.sel_idx]
        elif event.type in {'WHEELDOWNMOUSE', 'TWO'} and event.value == 'PRESS':
            self.sel_idx = (self.sel_idx - 1) % len(self.group_indices)
            self.active_group = self.group_indices[self.sel_idx]
        elif event.type == 'A' and event.value == 'PRESS':
            self.select_all_groups = not self.select_all_groups
        elif event.type in {'LEFTMOUSE', 'SPACE'} and event.value == 'PRESS':
            return self.execute(context)
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            return {'CANCELLED'}
        elif event.type == 'MIDDLEMOUSE' or (
            event.alt and event.type in {'LEFTMOUSE', 'RIGHTMOUSE'}
        ) or event.type.startswith('NDOF'):
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self._prepare(context):
            return {'CANCELLED'}
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        groups = self.group_indices if getattr(self, 'select_all_groups', False) else [self.active_group]
        indices = {
            vertex_index
            for group_index in groups
            for vertex_index in self._group_vertices(obj, group_index)
        }
        for vertex in bm.verts:
            if vertex.index in indices:
                vertex.select_set(True)
        bm.select_flush(True)
        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class OP_SelectSharpChain(bpy.types.Operator):
    bl_idname = 'ho.sselect'
    bl_label = '锐边链选择'
    bl_description = '选择与当前选择相连的所有锐边'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not _is_edit_mesh(context):
            return False
        bm = bmesh.from_edit_mesh(context.active_object.data)
        return any(edge.select and not edge.smooth for edge in bm.edges)

    def execute(self, context):
        active = context.active_object
        bm = bmesh.from_edit_mesh(active.data)
        _select_sharp_chain(bm)
        bmesh.update_edit_mesh(active.data)
        return {'FINISHED'}


class OP_SelectLoop(bpy.types.Operator):
    bl_idname = 'ho.lselect'
    bl_label = '循环选择'
    bl_description = '将孤立边选择扩展为循环边或面环'
    bl_options = {'REGISTER', 'UNDO'}

    min_angle: IntProperty(name='最小角度', default=60, min=0, max=180)  # type: ignore

    @classmethod
    def poll(cls, context):
        if not _is_edit_mesh(context):
            return False
        bm = bmesh.from_edit_mesh(context.active_object.data)
        mode = _mesh_mode(context)
        if mode == (False, True, False):
            return bool(_selected_edges(bm))
        return mode == (False, False, True) and len(_selected_faces(bm)) == 2

    def execute(self, context):
        active = context.active_object
        bm = bmesh.from_edit_mesh(active.data)
        mode = _mesh_mode(context)
        if mode == (False, True, False):
            edges = _selected_edges(bm)
            _select_edge_loops(bm, _isolated_edges(edges), 180 - self.min_angle)
        elif mode == (False, False, True):
            faces = _selected_faces(bm)
            if len(faces) == 2:
                common = set(faces[0].edges).intersection(faces[1].edges)
                if common:
                    center = common.pop()
                    for face in faces:
                        for edge in face.edges:
                            if edge is not center:
                                edge.select_set(True)
        bmesh.update_edit_mesh(active.data)
        return {'FINISHED'}


class OP_EnhancedSelect(bpy.types.Operator):
    bl_idname = 'ho.select'
    bl_label = '增强选择'
    bl_description = '根据当前选择模式分派顶点组、循环、锐边或 Blender 默认选择'
    bl_options = {'REGISTER', 'UNDO'}

    loop: BoolProperty(name='循环选择', default=False)  # type: ignore
    min_angle: IntProperty(name='最小角度', default=60, min=0, max=180)  # type: ignore
    draw_props: BoolProperty(name='显示参数', default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        return _is_edit_mesh(context)

    def draw(self, context):
        if self.draw_props:
            row = self.layout.row(align=True)
            row.prop(self, 'loop', text='循环' if self.loop else '锐边', toggle=True)
            sub = row.row(align=True)
            sub.active = self.loop
            sub.prop(self, 'min_angle')

    def _dispatch(self, context):
        mode = _mesh_mode(context)
        bm = bmesh.from_edit_mesh(context.active_object.data)
        if mode == (True, False, False):
            if context.active_object.vertex_groups and _selected_vertices(bm):
                return bpy.ops.ho.vselect('INVOKE_DEFAULT')
        elif mode == (False, True, False):
            edges = _selected_edges(bm)
            if edges:
                if self.loop or all(edge.smooth for edge in edges):
                    return bpy.ops.ho.lselect(min_angle=self.min_angle)
                return bpy.ops.ho.sselect()
        elif mode == (False, False, True) and len(_selected_faces(bm)) == 2:
            return bpy.ops.ho.lselect()
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        self.draw_props = False
        return self._dispatch(context)

    def execute(self, context):
        return self._dispatch(context)
