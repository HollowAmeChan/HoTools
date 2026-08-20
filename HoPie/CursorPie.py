from types import SimpleNamespace

import bmesh
import bpy
from bpy.props import BoolProperty
from mathutils import Matrix, Quaternion, Vector

from Utils.mesh_utils import (
    average_locations,
    component_rotation,
    selected_verts,
)
from Utils.transform_utils import (
    compensate_children,
    set_cursor_transform,
    set_obj_origin,
)
from Utils.ui_utils import popup_error

from ._Core import HoPie


class CursorToOrigin(bpy.types.Operator):
    bl_idname = 'ho.cursor_to_origin'
    bl_label = '游标归零'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return self.invoke(context, SimpleNamespace(alt=False, ctrl=False))

    def invoke(self, context, event):
        if event.alt and event.ctrl:
            popup_error(self, 'ALT 和 CTRL 不能同时使用')
            return {'CANCELLED'}
        cursor = context.scene.cursor
        old = cursor.matrix.copy()
        set_cursor_transform(
            cursor,
            old.to_translation() if event.ctrl else Vector(),
            old.to_quaternion() if event.alt else Quaternion(),
        )
        return {'FINISHED'}


class CursorRotationReset(bpy.types.Operator):
    bl_idname = 'ho.cursor_rotation_reset'
    bl_label = '游标旋转重置'
    bl_description = '将3D游标旋转重置为默认方向，保留当前位置'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cursor = context.scene.cursor
        set_cursor_transform(cursor, cursor.location.copy(), Quaternion())
        return {'FINISHED'}


class CursorToSelected(bpy.types.Operator):
    bl_idname = 'ho.cursor_to_selected'
    bl_label = '游标->选中项'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return self.invoke(context, SimpleNamespace(alt=False, ctrl=False))

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            return bool(selected_verts(bmesh.from_edit_mesh(context.active_object.data)))
        return bool(context.selected_objects or context.active_object)

    def invoke(self, context, event):
        if event.alt and event.ctrl:
            popup_error(self, 'ALT 和 CTRL 不能同时使用')
            return {'CANCELLED'}
        cursor = context.scene.cursor
        old = cursor.matrix.copy()
        active = context.active_object
        if context.mode == 'EDIT_MESH':
            bm = bmesh.from_edit_mesh(active.data)
            select_mode = tuple(context.scene.tool_settings.mesh_select_mode)
            if select_mode == (True, False, False):
                verts = selected_verts(bm)
                location = active.matrix_world @ average_locations([v.co for v in verts])
            elif select_mode == (False, True, False):
                edges = [edge for edge in bm.edges if edge.select]
                location = active.matrix_world @ average_locations([(edge.verts[0].co + edge.verts[1].co) * 0.5 for edge in edges])
            else:
                faces = [face for face in bm.faces if face.select]
                location = active.matrix_world @ average_locations([face.calc_center_median_weighted() for face in faces])
            rotation = component_rotation(context, active, bm).to_quaternion()
        else:
            objects = context.selected_objects or [active]
            if len(objects) == 1:
                location = objects[0].matrix_world.translation
            else:
                corners = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
                location = Vector((
                    (min(corner.x for corner in corners) + max(corner.x for corner in corners)) * 0.5,
                    (min(corner.y for corner in corners) + max(corner.y for corner in corners)) * 0.5,
                    (min(corner.z for corner in corners) + max(corner.z for corner in corners)) * 0.5,
                ))
            rotation = active.matrix_world.to_quaternion() if active else old.to_quaternion()
        set_cursor_transform(
            cursor,
            old.to_translation() if event.ctrl else location,
            old.to_quaternion() if event.alt else rotation,
        )
        return {'FINISHED'}


class SelectedToCursor(bpy.types.Operator):
    bl_idname = 'ho.selected_to_cursor'
    bl_label = '选中项->游标'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return self.invoke(context, SimpleNamespace(alt=False, ctrl=False))

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def invoke(self, context, event):
        if event.alt and event.ctrl:
            popup_error(self, 'ALT 和 CTRL 不能同时使用')
            return {'CANCELLED'}
        cursor = context.scene.cursor.matrix
        for obj in context.selected_objects:
            loc, rot, scale = obj.matrix_world.decompose()
            scale_matrix = Matrix.Diagonal((*scale, 1.0))
            if event.alt:
                matrix = Matrix.Translation(cursor.translation) @ rot.to_matrix().to_4x4() @ scale_matrix
            elif event.ctrl:
                matrix = Matrix.Translation(loc) @ cursor.to_3x3().to_4x4() @ scale_matrix
            else:
                matrix = Matrix.Translation(cursor.translation) @ cursor.to_3x3().to_4x4() @ scale_matrix
            if obj.children and context.scene.tool_settings.use_transform_skip_children:
                compensate_children(obj, obj.matrix_world, matrix)
            obj.matrix_world = matrix
        return {'FINISHED'}


def _selected_component_matrix(context, active):
    bm = bmesh.from_edit_mesh(active.data)
    select_mode = tuple(context.scene.tool_settings.mesh_select_mode)
    if select_mode == (True, False, False):
        verts = selected_verts(bm)
        location = active.matrix_world @ average_locations([v.co for v in verts])
    elif select_mode == (False, True, False):
        edges = [edge for edge in bm.edges if edge.select]
        location = active.matrix_world @ average_locations([(edge.verts[0].co + edge.verts[1].co) * 0.5 for edge in edges])
    else:
        faces = [face for face in bm.faces if face.select]
        location = active.matrix_world @ average_locations([face.calc_center_median_weighted() for face in faces])
    return Matrix.Translation(location) @ component_rotation(context, active, bm)


class OriginToActive(bpy.types.Operator):
    bl_idname = 'ho.origin_to_active'
    bl_label = '原点->活动项'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return self.invoke(context, SimpleNamespace(alt=False, ctrl=False))

    @classmethod
    def poll(cls, context):
        if not context.active_object:
            return False
        if context.mode == 'OBJECT':
            return bool([obj for obj in context.selected_objects if obj != context.active_object and obj.type not in {'EMPTY', 'FONT'}])
        return context.mode == 'EDIT_MESH' and bool(selected_verts(bmesh.from_edit_mesh(context.active_object.data)))

    def invoke(self, context, event):
        if event.alt and event.ctrl:
            popup_error(self, 'ALT 和 CTRL 不能同时使用')
            return {'CANCELLED'}
        active = context.active_object
        if context.mode == 'EDIT_MESH':
            old = active.matrix_world.copy()
            old_loc, old_rot, old_scale = old.decompose()
            component = _selected_component_matrix(context, active)
            component_loc, component_rot, _ = component.decompose()
            if event.alt:
                matrix = Matrix.Translation(component_loc) @ old_rot.to_matrix().to_4x4() @ Matrix.Diagonal((*old_scale, 1.0))
            elif event.ctrl:
                matrix = Matrix.Translation(old_loc) @ component_rot.to_matrix().to_4x4() @ Matrix.Diagonal((*old_scale, 1.0))
            else:
                matrix = Matrix.Translation(component_loc) @ component_rot.to_matrix().to_4x4() @ Matrix.Diagonal((*old_scale, 1.0))
            set_obj_origin(active, matrix, bmesh.from_edit_mesh(active.data))
            return {'FINISHED'}
        target = active.matrix_world
        active_loc, active_rot, _ = target.decompose()
        for obj in [item for item in context.selected_objects if item != active and item.type not in {'EMPTY', 'FONT'}]:
            loc, rot, scale = obj.matrix_world.decompose()
            scale_matrix = Matrix.Diagonal((*scale, 1.0))
            if event.alt:
                matrix = Matrix.Translation(active_loc) @ rot.to_matrix().to_4x4() @ scale_matrix
            elif event.ctrl:
                matrix = Matrix.Translation(loc) @ active_rot.to_matrix().to_4x4() @ scale_matrix
            else:
                matrix = target.copy()
            set_obj_origin(obj, matrix)
        return {'FINISHED'}


class OriginToCursor(bpy.types.Operator):
    bl_idname = 'ho.origin_to_cursor'
    bl_label = '原点->游标'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return self.invoke(context, SimpleNamespace(alt=False, ctrl=False))

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' or bool([obj for obj in context.selected_objects if obj.type not in {'EMPTY', 'FONT'}])

    def invoke(self, context, event):
        if event.alt and event.ctrl:
            popup_error(self, 'ALT 和 CTRL 不能同时使用')
            return {'CANCELLED'}
        cursor = context.scene.cursor.matrix
        if context.mode == 'EDIT_MESH':
            active = context.active_object
            old = active.matrix_world
            loc, rot, scale = old.decompose()
            scale_matrix = Matrix.Diagonal((*scale, 1.0))
            if event.alt:
                matrix = Matrix.Translation(cursor.translation) @ rot.to_matrix().to_4x4() @ scale_matrix
            elif event.ctrl:
                matrix = Matrix.Translation(loc) @ cursor.to_3x3().to_4x4() @ scale_matrix
            else:
                matrix = cursor.copy()
            set_obj_origin(active, matrix, bmesh.from_edit_mesh(active.data))
        else:
            for obj in context.selected_objects:
                loc, rot, scale = obj.matrix_world.decompose()
                scale_matrix = Matrix.Diagonal((*scale, 1.0))
                if event.alt:
                    matrix = Matrix.Translation(cursor.translation) @ rot.to_matrix().to_4x4() @ scale_matrix
                elif event.ctrl:
                    matrix = Matrix.Translation(loc) @ cursor.to_3x3().to_4x4() @ scale_matrix
                else:
                    matrix = cursor.copy()
                set_obj_origin(obj, matrix)
        return {'FINISHED'}


class OriginToBottomBounds(bpy.types.Operator):
    bl_idname = 'ho.origin_to_bottom_bounds'
    bl_label = '原点->底部'
    bl_options = {'REGISTER', 'UNDO'}
    evaluated: BoolProperty(name='使用求值后的包围盒', default=False) # type: ignore

    def draw(self, context):
        self.layout.prop(self, 'evaluated', toggle=True)

    def execute(self, context):
        depsgraph = context.evaluated_depsgraph_get() if self.evaluated else None
        for obj in [item for item in context.selected_objects if item.type == 'MESH']:
            source = obj.evaluated_get(depsgraph) if depsgraph else obj
            local_corners = [Vector(corner) for corner in source.bound_box]
            min_z = min(corner.z for corner in local_corners)
            bottom = [corner for corner in local_corners if abs(corner.z - min_z) < 1e-6]
            center = obj.matrix_world @ average_locations(bottom)
            _, rotation, scale = obj.matrix_world.decompose()
            matrix = Matrix.Translation(center) @ rotation.to_matrix().to_4x4() @ Matrix.Diagonal((*scale, 1.0))
            set_obj_origin(obj, matrix)
        return {'FINISHED'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool([obj for obj in context.selected_objects if obj.type == 'MESH'])

    def invoke(self, context, event):
        self.evaluated = event.alt
        return self.execute(context)


class HO_MT_cursor_pie(bpy.types.Menu):
    bl_label = '饼: 游标与原点'
    bl_idname = 'HO_MT_cursor_pie'

    def draw(self, context):
        pie = HoPie.from_pie_layout(self.layout.menu_pie(), context)

        if context.mode == 'EDIT_MESH':
            selection = tuple(context.scene.tool_settings.mesh_select_mode)
            label = '顶点' if selection == (True, False, False) else '边' if selection == (False, True, False) else '面' if selection == (False, False, True) else '选中项'
            pie.operator(CursorToSelected.bl_idname, text=f'游标->{label}', icon='PIVOT_CURSOR')
        else:
            pie.operator(CursorToSelected.bl_idname, text='游标->选中项', icon='PIVOT_CURSOR')

        if context.mode == 'OBJECT':
            pie.operator(SelectedToCursor.bl_idname, text='选中项->游标', icon='RESTRICT_SELECT_OFF')
        else:
            pie.operator('view3d.snap_selected_to_cursor', text='选中项->游标', icon='RESTRICT_SELECT_OFF').use_offset = False

        if context.mode in {'OBJECT', 'EDIT_MESH'}:
            box = pie.split()
            column = box.column(align=True)
            row = column.split(factor=0.25)
            row.separator()
            row.label(text='对象原点')
            column.scale_x = 1.1
            if context.mode == 'OBJECT':
                row = column.split(factor=0.5, align=True)
                row.scale_y = 1.5
                row.operator('object.origin_set', text='原点->几何体', icon='MESH_DATA').type = 'ORIGIN_GEOMETRY'
                row.operator(OriginToCursor.bl_idname, text='原点->游标', icon='LAYER_ACTIVE')
                row = column.split(factor=0.5, align=True)
                row.scale_y = 1.5
                row.operator(OriginToActive.bl_idname, text='原点->活动项', icon='TRANSFORM_ORIGINS')
                row.operator(OriginToBottomBounds.bl_idname, text='原点->底部', icon='AXIS_TOP')
            else:
                if selection in {(True, False, False), (False, True, False), (False, False, True)}:
                    row = column.row(align=True)
                    row.scale_y = 1.5
                    icon = 'VERTEXSEL' if label == '顶点' else 'EDGESEL' if label == '边' else 'FACESEL'
                    row.operator(OriginToActive.bl_idname, text=f'原点->{label}', icon=icon)
                    row.operator(OriginToCursor.bl_idname, text='原点->游标', icon='LAYER_ACTIVE')
                else:
                    row = column.split(factor=0.25, align=True)
                    row.scale_y = 1.5
                    row.separator()
                    row.operator(OriginToCursor.bl_idname, text='原点->游标', icon='LAYER_ACTIVE')
        else:
            pie.separator()

        # HyperCursor is intentionally not a HoTools dependency, but its slot
        # remains separated so the remaining items keep M3's radial positions.
        pie.separator()
        pie.operator(CursorToOrigin.bl_idname, icon='PIVOT_CURSOR')
        pie.operator('view3d.snap_selected_to_cursor', text='选中项->游标（偏移）', icon='RESTRICT_SELECT_OFF').use_offset = True
        pie.operator(CursorRotationReset.bl_idname, icon='FILE_REFRESH')


CURSOR_PIE_CLASSES = (
    CursorToOrigin,
    CursorRotationReset,
    CursorToSelected,
    SelectedToCursor,
    OriginToActive,
    OriginToCursor,
    OriginToBottomBounds,
    HO_MT_cursor_pie,
)
