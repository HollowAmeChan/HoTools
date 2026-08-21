import bpy
from bpy.props import StringProperty

from ._Core import HoPie


def _is_armature_view(context):
    return (
        getattr(getattr(context, 'area', None), 'type', None) == 'VIEW_3D'
        and getattr(getattr(context, 'active_object', None), 'type', None) == 'ARMATURE'
    )


class HO_OT_armature_mode_pie(bpy.types.Operator):
    bl_idname = 'ho.armature_mode_pie'
    bl_label = '饼:骨架模式'
    bl_options = {'INTERNAL'}

    pie_menu_name: StringProperty(default='HO_MT_armature_mode_pie', options={'SKIP_SAVE'}) # type: ignore

    @classmethod
    def poll(cls, context):
        return _is_armature_view(context)

    def invoke(self, context, event):
        menu_cls = getattr(bpy.types, self.pie_menu_name, None)
        draw = getattr(menu_cls, 'draw', None)
        if draw is None:
            return {'CANCELLED'}

        def draw_menu(menu, draw_context):
            draw(menu, draw_context)

        try:
            context.window_manager.popup_menu_pie(
                event,
                draw_menu,
                title=getattr(menu_cls, 'bl_label', self.pie_menu_name),
            )
        except (AttributeError, RuntimeError, TypeError):
            return {'CANCELLED'}
        return {'FINISHED'}


def _mode_operator(pie, mode, text, icon):
    operator = pie.operator('object.mode_set', text=text, icon=icon)
    operator.mode = mode
    return operator


class HO_MT_armature_mode_pie(bpy.types.Menu):
    bl_idname = 'HO_MT_armature_mode_pie'
    bl_label = '饼:骨架模式'

    @classmethod
    def poll(cls, context):
        area = getattr(context, 'area', None)
        active = getattr(context, 'active_object', None)
        return (
            getattr(area, 'type', None) == 'VIEW_3D'
            and getattr(active, 'type', None) == 'ARMATURE'
        )

    def draw(self, context):
        pie = HoPie.from_pie_layout(self.layout.menu_pie(), context)
        mode = getattr(context, 'mode', 'OBJECT')
        if mode == 'OBJECT':
            _mode_operator(pie.top, 'POSE', '姿态模式', 'POSE_HLT')
            _mode_operator(pie.bottom, 'EDIT', '编辑模式', 'EDITMODE_HLT')
        elif mode == 'POSE':
            _mode_operator(pie.top, 'OBJECT', '物体模式', 'OBJECT_DATA')
            _mode_operator(pie.bottom, 'EDIT', '编辑模式', 'EDITMODE_HLT')
        else:
            _mode_operator(pie.top, 'OBJECT', '物体模式', 'OBJECT_DATA')
            _mode_operator(pie.bottom, 'POSE', '姿态模式', 'POSE_HLT')
        pie.finish()


ARMATURE_MODE_PIE_CLASSES = (HO_OT_armature_mode_pie, HO_MT_armature_mode_pie)
ARMATURE_MOD_PIE_CLASSES = ARMATURE_MODE_PIE_CLASSES
