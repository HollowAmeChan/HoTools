"""Standalone Tab modes pie, adapted from MACHIN3tools' modes pie."""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ._Core import HoPie


_EDITABLE_TYPES = {'MESH', 'ARMATURE', 'CURVE', 'FONT', 'SURFACE', 'META',
                   'LATTICE', 'CURVES', 'GREASEPENCIL'}
_MESH_MODES = (
    ('TEXTURE_PAINT', '纹理绘制', 'TPAINT_HLT'),
    ('WEIGHT_PAINT', '权重绘制', 'WPAINT_HLT'),
    ('VERTEX_PAINT', '顶点绘制', 'VPAINT_HLT'),
    ('SCULPT', '雕刻模式', 'SCULPTMODE_HLT'),
    ('OBJECT', '物体模式', 'OBJECT_DATA'),
    ('EDIT', '编辑模式', 'EDITMODE_HLT'),
)


def _editable_mesh(context):
    obj = context.active_object
    return (obj is not None and obj.type == 'MESH'
            and obj.is_editable and obj.data.is_editable)


def _is_mode_context(context):
    obj = context.active_object
    area_type = getattr(context.area, 'type', None)
    if obj is None or obj.type not in _EDITABLE_TYPES:
        return False
    if area_type == 'IMAGE_EDITOR':
        return _editable_mesh(context) and context.mode in {'OBJECT', 'EDIT_MESH'}
    if area_type != 'VIEW_3D':
        return False
    if obj.type == 'ARMATURE':
        # The existing armature pie owns Tab whenever its own switch is on.
        from . import _Register
        if _Register._armature_mode_pie_enabled:
            return False
    return True


class HO_OT_object_mode_pie(bpy.types.Operator):
    bl_idname = 'ho.object_mode_pie'
    bl_label = '物体模式饼'
    bl_options = {'INTERNAL'}

    pie_menu_name: StringProperty(default='HO_MT_object_mode_pie', options={'SKIP_SAVE'})  # type: ignore

    @classmethod
    def poll(cls, context):
        return _is_mode_context(context)

    def invoke(self, context, event):
        menu_cls = getattr(bpy.types, self.pie_menu_name, None)
        if menu_cls is None:
            return {'CANCELLED'}

        def draw_menu(menu, draw_context):
            menu_cls.draw(menu, draw_context)

        context.window_manager.popup_menu_pie(event, draw_menu, title=menu_cls.bl_label)
        return {'FINISHED'}


class HO_OT_object_mode_mesh_select(bpy.types.Operator):
    bl_idname = 'ho.object_mode_mesh_select'
    bl_label = '网格选择模式'
    bl_description = '进入编辑模式并选择点/边/面；Shift 扩展选择模式，Ctrl 扩展或收缩选区'
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(('VERT', '点', ''), ('EDGE', '边', ''), ('FACE', '面', '')))  # type: ignore
    use_extend: BoolProperty(default=False, options={'SKIP_SAVE'})  # type: ignore
    use_expand: BoolProperty(default=False, options={'SKIP_SAVE'})  # type: ignore

    @classmethod
    def poll(cls, context):
        return _editable_mesh(context) and context.mode in {'OBJECT', 'EDIT_MESH'}

    def invoke(self, context, event):
        self.use_extend = event.shift
        self.use_expand = event.ctrl
        return self.execute(context)

    def execute(self, context):
        if context.mode == 'OBJECT':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(
            type=self.mode, use_extend=self.use_extend, use_expand=self.use_expand)
        # Blender 5.1 returns CANCELLED when the requested mode is already set,
        # even if this operator just entered Edit Mode and needs an undo step.
        return {'FINISHED'}


class HO_OT_object_mode_image(bpy.types.Operator):
    bl_idname = 'ho.object_mode_image'
    bl_label = '图像编辑器模式'
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(('UV', 'UV 编辑', ''), ('PAINT', '绘制', ''),
                             ('MASK', '遮罩', ''), ('VIEW', '查看', '')))  # type: ignore

    @classmethod
    def poll(cls, context):
        return (getattr(context.area, 'type', None) == 'IMAGE_EDITOR'
                and _editable_mesh(context) and context.mode in {'OBJECT', 'EDIT_MESH'})

    def execute(self, context):
        if self.mode == 'UV':
            obj = context.active_object
            if context.mode == 'OBJECT':
                if not obj.data.uv_layers:
                    obj.data.uv_layers.new()
                bpy.ops.object.mode_set(mode='EDIT')
                if not context.tool_settings.use_uv_select_sync:
                    bpy.ops.mesh.select_all(action='SELECT')
        elif context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.space_data.mode = self.mode
        return {'FINISHED'}


class HO_OT_object_mode_uv_select(bpy.types.Operator):
    bl_idname = 'ho.object_mode_uv_select'
    bl_label = 'UV 选择模式'
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=(('VERTEX', '点', ''), ('EDGE', '边', ''),
                             ('FACE', '面', ''), ('ISLAND', '岛', '')))  # type: ignore

    @classmethod
    def poll(cls, context):
        return (getattr(context.area, 'type', None) == 'IMAGE_EDITOR'
                and _editable_mesh(context) and context.mode == 'EDIT_MESH')

    def execute(self, context):
        context.space_data.mode = 'UV'
        settings = context.tool_settings
        if self.mode == 'ISLAND' and hasattr(settings, 'use_uv_select_island'):
            settings.use_uv_select_island = True
            return {'FINISHED'}
        if settings.use_uv_select_sync:
            if self.mode == 'ISLAND':
                return {'CANCELLED'}
            bpy.ops.mesh.select_mode(type='VERT' if self.mode == 'VERTEX' else self.mode)
        else:
            settings.uv_select_mode = self.mode
        return {'FINISHED'}


def _mode_button(layout, obj, mode, text, icon):
    layout.operator('object.mode_set', text=text, icon=icon,
                    depress=obj.mode == mode).mode = mode


def _draw_mode_strip(layout, context):
    obj = context.active_object
    modes = _MESH_MODES
    if obj.type == 'MESH' and obj.particle_systems:
        modes = (('PARTICLE_EDIT', '粒子编辑', 'PARTICLEMODE'),) + modes
    elif obj.type == 'CURVES':
        modes = (('SCULPT_CURVES', '雕刻模式', 'SCULPTMODE_HLT'),
                 ('OBJECT', '物体模式', 'OBJECT_DATA'), ('EDIT', '编辑模式', 'EDITMODE_HLT'))
    elif obj.type == 'GREASEPENCIL':
        modes = (('WEIGHT_GREASE_PENCIL', '权重绘制', 'WPAINT_HLT'),
                 ('VERTEX_GREASE_PENCIL', '顶点绘制', 'VPAINT_HLT'),
                 ('PAINT_GREASE_PENCIL', '绘制模式', 'GREASEPENCIL'),
                 ('SCULPT_GREASE_PENCIL', '雕刻模式', 'SCULPTMODE_HLT'),
                 ('OBJECT', '物体模式', 'OBJECT_DATA'), ('EDIT', '编辑模式', 'EDITMODE_HLT'))
    grid = layout.grid_flow(columns=len(modes), even_columns=True, align=True)
    grid.scale_y = 1.5
    for mode, _label, icon in modes:
        _mode_button(grid, obj, mode, '', icon)


def _draw_mesh_options(layout, context):
    if context.mode == 'EDIT_MESH':
        col = layout.column(align=True)
        col.prop(context.space_data.shading, 'show_xray', text='穿透选择', icon='XRAY')
        col.prop(context.tool_settings, 'use_mesh_automerge', text='自动合并')
    elif context.mode in {'PAINT_WEIGHT', 'PAINT_VERTEX', 'PAINT_TEXTURE'}:
        row = layout.row(align=True)
        row.prop(context.active_object.data, 'use_paint_mask', text='面遮罩', icon='FACESEL')
        if context.mode != 'PAINT_TEXTURE':
            row.prop(context.active_object.data, 'use_paint_mask_vertex', text='点遮罩', icon='VERTEXSEL')


def _draw_image_pie(pie, context):
    settings = context.tool_settings
    if context.mode == 'OBJECT':
        for slot, mode, text, icon in (
                (pie.left, 'UV', 'UV 编辑', 'GROUP_UVS'),
                (pie.right, 'PAINT', '绘制', 'TPAINT_HLT'),
                (pie.bottom, 'MASK', '遮罩', 'MOD_MASK'),
                (pie.top, 'VIEW', '查看', 'FILE_IMAGE')):
            slot.operator('ho.object_mode_image', text=text, icon=icon).mode = mode
    else:
        for slot, mode, icon in ((pie.left, 'VERTEX', 'VERTEXSEL'),
                                 (pie.right, 'FACE', 'FACESEL'),
                                 (pie.bottom, 'EDGE', 'EDGESEL')):
            slot.operator('ho.object_mode_uv_select', text={'VERTEX': '点', 'FACE': '面', 'EDGE': '边'}[mode], icon=icon).mode = mode
        _mode_button(pie.top, context.active_object, 'OBJECT', '物体模式', 'OBJECT_DATA')
        pie.top_left.toggle_prop(settings, 'use_uv_select_sync', '同步选择', icon='UV_SYNC_SELECT')
        if hasattr(settings, 'use_uv_select_island'):
            pie.top_right.toggle_prop(settings, 'use_uv_select_island', '岛', icon='UV_ISLANDSEL')
        elif not settings.use_uv_select_sync:
            pie.top_right.operator('ho.object_mode_uv_select', text='岛', icon='UV_ISLANDSEL').mode = 'ISLAND'


class HO_MT_object_mode_pie(bpy.types.Menu):
    bl_idname = 'HO_MT_object_mode_pie'
    bl_label = '物体模式饼'

    @classmethod
    def poll(cls, context):
        return _is_mode_context(context)

    def draw(self, context):
        pie = HoPie.from_pie_layout(self.layout.menu_pie(), context)
        obj = context.active_object
        if context.area.type == 'IMAGE_EDITOR':
            _draw_image_pie(pie, context)
        elif not obj.is_editable or not obj.data.is_editable:
            pie.top.operator('object.make_local', text='转为本地数据', icon='LIBRARY_DATA_DIRECT').type = 'SELECT_OBDATA'
        else:
            if obj.type == 'MESH' and context.mode in {'OBJECT', 'EDIT_MESH'}:
                for slot, mode, label, index, icon in (
                        (pie.left, 'VERT', '点', 0, 'VERTEXSEL'),
                        (pie.right, 'FACE', '面', 2, 'FACESEL'),
                        (pie.bottom, 'EDGE', '边', 1, 'EDGESEL')):
                    slot.operator('ho.object_mode_mesh_select', text=label, icon=icon,
                                  depress=obj.mode == 'EDIT' and context.tool_settings.mesh_select_mode[index]).mode = mode
            else:
                _mode_button(pie.bottom, obj, 'EDIT', '编辑模式', 'EDITMODE_HLT')
                if obj.type == 'ARMATURE':
                    _mode_button(pie.right, obj, 'POSE', '姿态模式', 'POSE_HLT')
                elif obj.type == 'CURVES':
                    _mode_button(pie.right, obj, 'SCULPT_CURVES', '雕刻模式', 'SCULPTMODE_HLT')
                elif obj.type == 'GREASEPENCIL':
                    _mode_button(pie.left, obj, 'PAINT_GREASE_PENCIL', '绘制模式', 'GREASEPENCIL')
                    _mode_button(pie.right, obj, 'SCULPT_GREASE_PENCIL', '雕刻模式', 'SCULPTMODE_HLT')
            mode, label, icon = (('EDIT', '编辑模式', 'EDITMODE_HLT') if obj.mode == 'OBJECT'
                                 else ('OBJECT', '物体模式', 'OBJECT_DATA'))
            _mode_button(pie.top, obj, mode, label, icon)
            if obj.type in {'MESH', 'CURVES', 'GREASEPENCIL'}:
                pie.top_left.expand(_draw_mode_strip)
            if obj.type == 'MESH':
                pie.bottom_right.expand(_draw_mesh_options)
            elif obj.type in {'SURFACE', 'META'}:
                pie.bottom_right.prop(context.space_data.shading, 'show_xray', text='穿透选择', icon='XRAY')
            elif obj.type == 'CURVES' and obj.mode in {'EDIT', 'SCULPT_CURVES'}:
                pie.bottom_right.prop(obj.data, 'selection_domain', text='选择域', expand=True)
        pie.finish()


OBJECT_MODE_PIE_CLASSES = (
    HO_OT_object_mode_mesh_select,
    HO_OT_object_mode_image,
    HO_OT_object_mode_uv_select,
    HO_OT_object_mode_pie,
    HO_MT_object_mode_pie,
)
