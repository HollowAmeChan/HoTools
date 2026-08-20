import bpy

from ._Core import HoPie


def _tool_operator(pie, text, tool_id, icon):
    operator = pie.operator('wm.tool_set_by_id', text=text, icon=icon)
    operator.name = tool_id


class HO_MT_selection_mode_pie(bpy.types.Menu):
    bl_idname = 'HO_MT_selection_mode_pie'
    bl_label = '饼:选择模式'

    def draw(self, context):
        pie = HoPie.from_pie_layout(self.layout.menu_pie(), context)
        _tool_operator(pie, '标注', 'builtin.annotate', 'GREASEPENCIL')
        _tool_operator(pie, '刷选', 'builtin.select_circle', 'MESH_CIRCLE')
        pie.separator()
        _tool_operator(pie, '框选', 'builtin.select_box', 'MESH_PLANE')
        _tool_operator(pie, '套索', 'builtin.select_lasso', 'CURVE_DATA')
        _tool_operator(pie, '点选', 'builtin.select', 'RESTRICT_SELECT_OFF')
        _tool_operator(pie, '标注橡皮', 'builtin.annotate_eraser', 'REMOVE')
        pie.separator()
        pie.separator()
        pie.separator()


SELECTION_MODE_PIE_CLASSES = (HO_MT_selection_mode_pie,)
