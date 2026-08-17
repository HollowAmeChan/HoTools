import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty
from mathutils import Matrix, Vector
from mathutils.geometry import intersect_point_line

from .utils import edit_bmesh, popup_error, selected_verts


ALIGN_TYPE_ITEMS = (
    ('MIN', '最小值', ''),
    ('MAX', '最大值', ''),
    ('AVERAGE', '平均值', ''),
    ('ZERO', '归零', ''),
    ('CURSOR', '光标', ''),
)
ALIGN_AXIS_ITEMS = (('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', ''))
ALIGN_SPACE_ITEMS = (
    ('LOCAL', '局部', ''),
    ('WORLD', '世界', ''),
    ('CURSOR', '光标', ''),
)
ALIGN_DIRECTION_ITEMS = (
    ('LEFT', '左侧', ''),
    ('RIGHT', '右侧', ''),
    ('TOP', '顶部', ''),
    ('BOTTOM', '底部', ''),
    ('HORIZONTAL', '水平', ''),
    ('VERTICAL', '垂直', ''),
)


def _view_axes(context, matrix):
    region_3d = getattr(getattr(context, 'space_data', None), 'region_3d', None)
    if not region_3d:
        return 0, 1, False, False
    view_right = region_3d.view_rotation @ Vector((1, 0, 0))
    view_up = region_3d.view_rotation @ Vector((0, 1, 0))
    axes = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
    right = max(
        ((view_right.dot(matrix.to_3x3() @ axis), index) for index, axis in enumerate(axes)),
        key=lambda item: abs(item[0]),
    )
    up = max(
        ((view_up.dot(matrix.to_3x3() @ axis), index) for index, axis in enumerate(axes)),
        key=lambda item: abs(item[0]),
    )
    return right[1], up[1], right[0] < 0, up[0] < 0


def _selected_sequences(verts):
    remaining = list(verts)
    result = []
    while remaining:
        starts = [vert for vert in remaining if len([edge for edge in vert.link_edges if edge.select]) == 1]
        current = starts[0] if starts else remaining[0]
        sequence = []
        while current in remaining:
            sequence.append(current)
            remaining.remove(current)
            next_verts = [edge.other_vert(current) for edge in current.link_edges if edge.select and edge.other_vert(current) in remaining]
            if not next_verts:
                break
            current = next_verts[0]
        result.append((sequence, len([edge for edge in sequence[-1].link_edges if edge.select]) == 2))
    return result


def _selected_islands(bm):
    faces = [face for face in bm.faces if face.select]
    islands = []
    while faces:
        pending = [faces.pop(0)]
        island = []
        while pending:
            face = pending.pop()
            island.append(face)
            for edge in face.edges:
                for linked in edge.link_faces:
                    if linked.select and linked in faces:
                        faces.remove(linked)
                        pending.append(linked)
        islands.append(list({vert for face in island for vert in face.verts}))
    return islands


class AlignEditMesh(bpy.types.Operator):
    bl_idname = 'ho.align_editmesh'
    bl_label = 'HoTools：对齐编辑网格'
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(('VIEW', '视图', ''), ('AXES', '坐标轴', '')), default='VIEW')
    type: EnumProperty(items=ALIGN_TYPE_ITEMS, default='MIN')
    axis: EnumProperty(items=ALIGN_AXIS_ITEMS, default='X')
    direction: EnumProperty(items=ALIGN_DIRECTION_ITEMS, default='LEFT')
    space: EnumProperty(items=ALIGN_SPACE_ITEMS, default='LOCAL')
    align_each: BoolProperty(name='分别对齐每个选区', default=False)
    draw_each: BoolProperty(default=False)

    def draw(self, context):
        column = self.layout.column(align=True)
        column.prop(self, 'mode', expand=True)
        column.prop(self, 'space', expand=True)
        column.prop(self, 'axis', expand=True)
        column.prop(self, 'type', expand=True)
        if self.mode == 'VIEW':
            column.prop(self, 'direction', expand=True)
        if self.draw_each:
            column.prop(self, 'align_each', toggle=True)

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH' or not context.active_object:
            return False
        return bool(selected_verts(bmesh.from_edit_mesh(context.active_object.data)))

    def invoke(self, context, event):
        if event.alt and event.ctrl:
            popup_error(self, 'ALT 和 CTRL 不能同时使用')
            return {'CANCELLED'}
        self.space = 'WORLD' if event.alt else 'CURSOR' if event.ctrl else self.space
        if self.mode == 'VIEW':
            right, up, flip_right, flip_up = _view_axes(context, context.active_object.matrix_world)
            if self.direction in {'LEFT', 'RIGHT'}:
                self.axis = 'XYZ'[right]
                self.type = ('MAX' if flip_right else 'MIN') if self.direction == 'LEFT' else ('MIN' if flip_right else 'MAX')
            elif self.direction in {'TOP', 'BOTTOM'}:
                self.axis = 'XYZ'[up]
                self.type = ('MIN' if flip_up else 'MAX') if self.direction == 'TOP' else ('MAX' if flip_up else 'MIN')
            else:
                self.axis = 'XYZ'[right if self.direction == 'HORIZONTAL' else up]
        return self.execute(context)

    def execute(self, context):
        active, bm = edit_bmesh(context)
        verts = selected_verts(bm)
        groups = [verts]
        self.draw_each = False
        selection_mode = tuple(context.scene.tool_settings.mesh_select_mode)
        if self.align_each and selection_mode == (False, True, False):
            groups = [sequence for sequence, _ in _selected_sequences(verts.copy()) if sequence]
        elif self.align_each and selection_mode == (False, False, True):
            groups = _selected_islands(bm) or groups
        if selection_mode in {(False, True, False), (False, False, True)}:
            self.draw_each = len(_selected_sequences(verts.copy())) > 1 if selection_mode == (False, True, False) else len(_selected_islands(bm)) > 1
        axis = 'XYZ'.index(self.axis)
        matrix = active.matrix_world if self.space == 'LOCAL' else Matrix.Identity(4)
        if self.space == 'CURSOR':
            matrix = context.scene.cursor.matrix
        inverse = matrix.inverted_safe()
        active_inverse = active.matrix_world.inverted_safe()
        for group in groups:
            coordinates = [inverse @ active.matrix_world @ vert.co for vert in group]
            values = [coordinate[axis] for coordinate in coordinates]
            if self.type == 'MIN':
                target = min(values)
            elif self.type == 'MAX':
                target = max(values)
            elif self.type == 'AVERAGE':
                target = sum(values) / len(values)
            elif self.type == 'ZERO':
                target = 0.0
            else:
                target = (inverse @ context.scene.cursor.location)[axis]
            for vert, coordinate in zip(group, coordinates):
                coordinate[axis] = target
                vert.co = active_inverse @ matrix @ coordinate
        bmesh.update_edit_mesh(active.data)
        return {'FINISHED'}


class CenterEditMesh(bpy.types.Operator):
    bl_idname = 'ho.center_editmesh'
    bl_label = 'HoTools：居中编辑网格'
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(items=ALIGN_AXIS_ITEMS, default='X')
    direction: EnumProperty(items=ALIGN_DIRECTION_ITEMS, default='HORIZONTAL')
    space: EnumProperty(items=ALIGN_SPACE_ITEMS, default='LOCAL')

    def draw(self, context):
        self.layout.prop(self, 'space', expand=True)
        self.layout.prop(self, 'axis', expand=True)

    @classmethod
    def poll(cls, context):
        return AlignEditMesh.poll(context)

    def invoke(self, context, event):
        if event.alt and event.ctrl:
            popup_error(self, 'ALT 和 CTRL 不能同时使用')
            return {'CANCELLED'}
        self.space = 'WORLD' if event.alt else 'CURSOR' if event.ctrl else self.space
        return self.execute(context)

    def execute(self, context):
        active, bm = edit_bmesh(context)
        verts = selected_verts(bm)
        axis = 'XYZ'.index(self.axis)
        matrix = active.matrix_world if self.space == 'LOCAL' else Matrix.Identity(4)
        if self.space == 'CURSOR':
            matrix = context.scene.cursor.matrix
        coordinates = [matrix.inverted_safe() @ active.matrix_world @ vert.co for vert in verts]
        if context.scene.ho_align_pie_mode == 'VIEW' and self.direction in {'HORIZONTAL', 'VERTICAL'}:
            right, up, _, _ = _view_axes(context, matrix)
            axis = right if self.direction == 'HORIZONTAL' else up
        target = sum(coordinate[axis] for coordinate in coordinates) / len(coordinates)
        for vert, coordinate in zip(verts, coordinates):
            coordinate[axis] = target
            vert.co = active.matrix_world.inverted_safe() @ matrix @ coordinate
        bmesh.update_edit_mesh(active.data)
        return {'FINISHED'}


class AlignObjectToEdge(bpy.types.Operator):
    bl_idname = 'ho.align_object_to_edge'
    bl_label = 'HoTools：对象对齐到边'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH' or not context.active_object:
            return False
        active = context.active_object
        selected = [obj for obj in context.selected_objects if obj != active and obj.type == 'MESH']
        if not selected:
            return False
        return all(len([edge for edge in bmesh.from_edit_mesh(obj.data).edges if edge.select]) == 1 for obj in [active] + selected)

    def invoke(self, context, event):
        target = context.active_object
        target_edge = next(edge for edge in bmesh.from_edit_mesh(target.data).edges if edge.select)
        target_coords = [target.matrix_world @ vert.co for vert in target_edge.verts]
        target_vector = (target_coords[1] - target_coords[0]).normalized()
        target_mid = (target_coords[0] + target_coords[1]) * 0.5
        for obj in [item for item in context.selected_objects if item != target and item.type == 'MESH']:
            edge = next(edge for edge in bmesh.from_edit_mesh(obj.data).edges if edge.select)
            coords = [obj.matrix_world @ vert.co for vert in edge.verts]
            vector = (coords[1] - coords[0]).normalized()
            if vector.dot(target_vector) < 0:
                vector.negate()
            location = obj.matrix_world.translation
            rotation = vector.rotation_difference(target_vector).to_matrix().to_4x4()
            obj.matrix_world = Matrix.Translation(location) @ rotation @ Matrix.Translation(-location) @ obj.matrix_world
            if event.alt or event.ctrl:
                midpoint = obj.matrix_world @ ((edge.verts[0].co + edge.verts[1].co) * 0.5)
                point, _ = intersect_point_line(midpoint, *target_coords)
                if point:
                    matrix = obj.matrix_world.copy()
                    matrix.translation += point - midpoint
                    obj.matrix_world = matrix
                if event.ctrl:
                    matrix = obj.matrix_world.copy()
                    matrix.translation += target_mid - obj.matrix_world @ ((edge.verts[0].co + edge.verts[1].co) * 0.5)
                    obj.matrix_world = matrix
        return {'FINISHED'}


class AlignObjectToVert(bpy.types.Operator):
    bl_idname = 'ho.align_object_to_vert'
    bl_label = 'HoTools：对象对齐到点'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH' or not context.active_object:
            return False
        active = context.active_object
        selected = [obj for obj in context.selected_objects if obj != active and obj.type == 'MESH']
        return bool(selected) and all(len(selected_verts(bmesh.from_edit_mesh(obj.data))) == 1 for obj in [active] + selected)

    def invoke(self, context, event):
        target = context.active_object
        target_vert = selected_verts(bmesh.from_edit_mesh(target.data))[0]
        target_location = target.matrix_world @ target_vert.co
        for obj in [item for item in context.selected_objects if item != target and item.type == 'MESH']:
            vert = selected_verts(bmesh.from_edit_mesh(obj.data))[0]
            matrix = obj.matrix_world.copy()
            matrix.translation += target_location - obj.matrix_world @ vert.co
            obj.matrix_world = matrix
        return {'FINISHED'}


class Straighten(bpy.types.Operator):
    bl_idname = 'ho.straighten'
    bl_label = 'HoTools：拉直'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH' or not context.active_object:
            return False
        bm = bmesh.from_edit_mesh(context.active_object.data)
        return len(selected_verts(bm)) > 2 and not any(face.select for face in bm.faces)

    def execute(self, context):
        active, bm = edit_bmesh(context)
        verts = selected_verts(bm)
        history = list(bm.select_history)
        if len(history) >= 2 and all(isinstance(item, bmesh.types.BMVert) for item in (history[0], history[-1])):
            start, end = history[0], history[-1]
        else:
            start, end = max(((b.co - a.co).length, (a, b)) for index, a in enumerate(verts) for b in verts[index + 1:])[1]
        for vert in verts:
            if vert not in {start, end}:
                vert.co = intersect_point_line(vert.co, start.co, end.co)[0]
        bmesh.update_edit_mesh(active.data)
        return {'FINISHED'}


class AlignUV(bpy.types.Operator):
    bl_idname = 'ho.align_uv'
    bl_label = 'HoTools：对齐 UV'
    bl_options = {'REGISTER', 'UNDO'}
    type: EnumProperty(items=ALIGN_TYPE_ITEMS, default='MIN')
    axis: EnumProperty(items=(('U', 'U', ''), ('V', 'V', '')), default='U')

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and getattr(context.space_data, 'type', None) == 'IMAGE_EDITOR'

    def execute(self, context):
        bm = bmesh.from_edit_mesh(context.active_object.data)
        uv_layer = bm.loops.layers.uv.verify()
        if context.scene.tool_settings.use_uv_select_sync:
            loops = [loop for vert in bm.verts if vert.select for loop in vert.link_loops]
        else:
            loops = [loop for face in bm.faces if face.select for loop in face.loops if loop[uv_layer].select]
        if not loops:
            return {'CANCELLED'}
        axis = 0 if self.axis == 'U' else 1
        values = [loop[uv_layer].uv[axis] for loop in loops]
        if self.type == 'MIN':
            target = min(values)
        elif self.type == 'MAX':
            target = max(values)
        elif self.type == 'AVERAGE':
            target = sum(values) / len(values)
        elif self.type == 'ZERO':
            target = 0.0
        else:
            target = context.space_data.cursor_location[axis]
        for loop in loops:
            loop[uv_layer].uv[axis] = target
        bmesh.update_edit_mesh(context.active_object.data)
        return {'FINISHED'}


class HO_MT_align_pie(bpy.types.Menu):
    bl_label = 'HoTools 对齐'
    bl_idname = 'HO_MT_align_pie'

    def draw(self, context):
        pie = self.layout.menu_pie()
        selected = [obj for obj in context.selected_objects if obj != context.active_object]
        if getattr(context.scene, 'ho_align_pie_mode', 'AXES') == 'VIEW':
            self.draw_view(pie, context, selected)
        else:
            self.draw_axes(pie, context, selected)

    @staticmethod
    def configure(op, mode, axis=None, typ=None, direction=None):
        op.mode = mode
        if axis:
            op.axis = axis
        if typ:
            op.type = typ
        if direction:
            op.direction = direction

    def draw_axes(self, pie, context, selected):
        for text, axis, typ in (('Y 最小值', 'Y', 'MIN'), ('Y 最大值', 'Y', 'MAX')):
            op = pie.operator(AlignEditMesh.bl_idname, text=text)
            self.configure(op, 'AXES', axis, typ)
        box = pie.split()
        column = box.column(align=True)
        column.separator()
        row = column.split(factor=0.2, align=True)
        row.separator()
        row.label(text='居中')
        row = column.row(align=True)
        row.scale_y = 1.2
        for axis in 'XYZ':
            op = row.operator(CenterEditMesh.bl_idname, text=axis)
            op.axis = axis
        column.separator()
        row = column.row(align=True)
        row.scale_y = 1.2
        row.operator(Straighten.bl_idname, text='拉直')
        if selected:
            row = column.row(align=True)
            row.scale_y = 1.2
            row.operator(AlignObjectToVert.bl_idname, text='对象对齐到点')
            row = column.row(align=True)
            row.scale_y = 1.2
            row.operator(AlignObjectToEdge.bl_idname, text='对象对齐到边')
        box = pie.split()
        column = box.column()
        for icon, typ, label in (('ARROW_LEFTRIGHT', 'AVERAGE', '平均值'), ('FREEZE', 'ZERO', '归零'), ('PIVOT_CURSOR', 'CURSOR', '光标')):
            row = column.split(factor=0.2)
            row.label(icon=icon)
            right = row.row(align=True)
            right.scale_y = 1.2
            for axis in 'XYZ':
                op = right.operator(AlignEditMesh.bl_idname, text=axis)
                self.configure(op, 'AXES', axis, typ)
        column.separator()
        row = column.split(factor=0.15)
        row.separator()
        row.prop(context.scene, 'ho_align_pie_mode', expand=True)
        column.separator()
        for text, axis, typ in (('X 最小值', 'X', 'MIN'), ('X 最大值', 'X', 'MAX'), ('Z 最小值', 'Z', 'MIN'), ('Z 最大值', 'Z', 'MAX')):
            op = pie.operator(AlignEditMesh.bl_idname, text=text)
            self.configure(op, 'AXES', axis, typ)

    def draw_view(self, pie, context, selected):
        for text, direction in (('左侧', 'LEFT'), ('右侧', 'RIGHT'), ('底部', 'BOTTOM'), ('顶部', 'TOP')):
            op = pie.operator(AlignEditMesh.bl_idname, text=text)
            self.configure(op, 'VIEW', direction=direction)
        pie.separator()
        box = pie.split()
        column = box.column()
        row = column.row(align=True)
        row.prop(context.scene, 'ho_align_pie_mode', expand=True)
        box = pie.split()
        column = box.column(align=True)
        column.separator()
        row = column.split(factor=0.25)
        row.label(text='居中')
        right = row.row(align=True)
        right.scale_y = 1.2
        for text, direction in (('水平', 'HORIZONTAL'), ('垂直', 'VERTICAL')):
            op = right.operator(CenterEditMesh.bl_idname, text=text)
            op.direction = direction
        column.separator()
        row = column.split(factor=0.25, align=True)
        row.separator()
        row.operator(Straighten.bl_idname, text='拉直')
        if selected:
            row = column.split(factor=0.25, align=True)
            row.separator()
            row.operator(AlignObjectToVert.bl_idname, text='对象对齐到点')
            row = column.split(factor=0.25, align=True)
            row.separator()
            row.operator(AlignObjectToEdge.bl_idname, text='对象对齐到边')
        box = pie.split()
        column = box.column(align=True)
        for icon, typ in (('ARROW_LEFTRIGHT', 'AVERAGE'), ('FREEZE', 'ZERO'), ('PIVOT_CURSOR', 'CURSOR')):
            row = column.split(factor=0.2, align=True)
            row.label(icon=icon)
            right = row.row(align=True)
            right.scale_y = 1.2
            for text, direction in (('水平', 'HORIZONTAL'), ('垂直', 'VERTICAL')):
                op = right.operator(AlignEditMesh.bl_idname, text=text)
                self.configure(op, 'VIEW', typ=typ, direction=direction)


class HO_MT_uv_align_pie(bpy.types.Menu):
    bl_label = 'HoTools UV 对齐'
    bl_idname = 'HO_MT_uv_align_pie'

    def draw(self, context):
        pie = self.layout.menu_pie()
        mode = getattr(context.scene, 'ho_align_pie_mode', 'AXES')
        if mode == 'VIEW':
            items = (('左侧', 'U', 'MIN'), ('右侧', 'U', 'MAX'), ('底部', 'V', 'MIN'), ('顶部', 'V', 'MAX'))
        else:
            items = (('V 最小值', 'V', 'MIN'), ('V 最大值', 'V', 'MAX'), ('U 最小值', 'U', 'MIN'), ('U 最大值', 'U', 'MAX'))
        for text, axis, typ in items:
            op = pie.operator(AlignUV.bl_idname, text=text)
            op.axis = axis
            op.type = typ
        pie.separator()
        box = pie.split()
        column = box.column()
        row = column.row(align=True)
        row.prop(context.scene, 'ho_align_pie_mode', expand=True)
        column.separator()
        if mode == 'VIEW':
            row = column.split(factor=0.2)
            row.label(icon='PIVOT_CURSOR')
            right = row.row(align=True)
            for text, axis in (('水平', 'U'), ('垂直', 'V')):
                op = right.operator(AlignUV.bl_idname, text=text)
                op.axis = axis
                op.type = 'CURSOR'
        else:
            for text, axis in (('U 光标', 'U'), ('V 光标', 'V')):
                op = pie.operator(AlignUV.bl_idname, text=text)
                op.axis = axis
                op.type = 'CURSOR'


ALIGN_PIE_CLASSES = (
    AlignEditMesh,
    CenterEditMesh,
    AlignObjectToEdge,
    AlignObjectToVert,
    Straighten,
    AlignUV,
    HO_MT_align_pie,
    HO_MT_uv_align_pie,
)


def register_props():
    if not hasattr(bpy.types.Scene, 'ho_align_pie_mode'):
        bpy.types.Scene.ho_align_pie_mode = EnumProperty(
            items=(('VIEW', '视图', ''), ('AXES', '坐标轴', '')),
            default='VIEW',
        )


def unregister_props():
    if hasattr(bpy.types.Scene, 'ho_align_pie_mode'):
        del bpy.types.Scene.ho_align_pie_mode
