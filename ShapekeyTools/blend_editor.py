"""形态键混合矩阵调试页的界面（左右两个工作区）。

布局：

- 左列：矩阵列表 + 矩阵属性 + 可折叠的「操作物体对象列表」，底部是生成/关闭调试矩阵；
- 右列：坐标点位列表（键名 / 键值 / 控制点位置 / 跳转），以及应用控制与全键归零。

工具都抽到了 ``blend_utils``：功能（权重求值、形态键读写）在 ``blend_func``，
绘制（GPU 图元、文字、坐标映射）在 ``draw_func``。这里只做界面编排。
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Context, Menu, Operator, UIList, UILayout

try:
    from . import blend_debug_store as _store
    from . import blend_overlay as _overlay
    from .blend_utils import blend_func as _func
    from .blend_utils import point_layout as _layout
    from .blend_utils import shapekey_utils as _keys
except ImportError:  # 兼容旧工具直接导入脚本
    import blend_debug_store as _store
    import blend_overlay as _overlay
    from blend_utils import blend_func as _func
    from blend_utils import point_layout as _layout
    from blend_utils import shapekey_utils as _keys


evaluate_item = _func.evaluate_item
invalidate_weight_cache = _func.invalidate_weight_cache


def _active_item(context):
    return _store.active_item(context.scene)


# region 算子


class OP_ShapekeyTools_BlendApplyWeights(Operator):
    bl_idname = "ho.shapekeytools_blend_apply"
    bl_label = "应用控制"
    bl_description = (
        "按当前混合矩阵把权重写进操作物体的形态键（对齐 Unity 混合树的混合逻辑）"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = _active_item(context)
        if item is None:
            self.report({'WARNING'}, "没有选中的调试矩阵")
            return {'CANCELLED'}
        report = _func.apply_weights(context, item)
        if report.total == 0:
            self.report({'WARNING'}, report.summary())
            return {'CANCELLED'}
        if report.failed:
            self.report({'WARNING'}, report.summary())
        else:
            self.report({'INFO'}, report.summary())
        return {'FINISHED'}


class OP_ShapekeyTools_BlendResetCursor(Operator):
    bl_idname = "ho.shapekeytools_blend_reset_cursor"
    bl_label = "控制点归零"
    bl_description = "把控制点（输入坐标）复位到原点 (0, 0)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = _active_item(context)
        if item is None:
            return {'CANCELLED'}
        item.cursor_u = 0.0
        item.cursor_v = 0.0
        _func.invalidate_weight_cache()
        if context.scene.ho_bs_apply_on_cursor:
            _func.apply_weights(context, item)
        return {'FINISHED'}


class OP_ShapekeyTools_BlendClearAllKeys(Operator):
    bl_idname = "ho.shapekeytools_blend_clear_all_keys"
    bl_label = "全键归零"
    bl_description = (
        "把操作物体的全部形态键归零（不只矩阵里的），并把活动键切回基型；"
        "与形态键工具里的「全键归零 + 选中基型」一致"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        item = _active_item(context)
        if item is None:
            return {'CANCELLED'}
        cleared = _func.clear_all_keys(item, context)
        self.report({'INFO'}, f"已归零 {cleared} 个形态键")
        return {'FINISHED'}


class OP_ShapekeyTools_BlendJumpToPoint(Operator):
    bl_idname = "ho.shapekeytools_blend_jump_to_point"
    bl_label = "跳到该控制点"
    bl_description = "把控制点移动到该点位（预览它的权重）"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty(name="下标", default=-1)  # type: ignore

    def execute(self, context):
        item = _active_item(context)
        if item is None:
            return {'CANCELLED'}
        index = self.index if self.index >= 0 else item.point_index
        if not 0 <= index < len(item.points):
            return {'CANCELLED'}
        point = item.points[index]
        item.cursor_u = point.u
        item.cursor_v = point.v
        item.point_index = index
        _func.invalidate_weight_cache()
        if context.scene.ho_bs_apply_on_cursor:
            _func.apply_weights(context, item)
        return {'FINISHED'}


# endregion


# region 列表与菜单


class HO_UL_ShapekeyTools_BlendPoints(UIList):
    """坐标点位列表。每行横排：``键名 - 键值(权重) - 控制点位置 - 跳转``。

    行里不放启用开关，也不放坐标编辑：坐标只在视口里拖方块改，或者选中这一行后在
    下面的「控制点位置」里改。最右侧的取色器图标把控制点跳到该点位。
    """

    # UIList 不会自动从类名生成 bl_idname，template_list 按 idname 查找，必须显式声明。
    bl_idname = "HO_UL_ShapekeyTools_BlendPoints"

    def draw_item(self, context, layout: UILayout, data, item, icon,
                  active_data, active_propname, index):
        item_data = _active_item(context)
        weights, _names = _func.evaluate_item(item_data)
        weight = weights[index] if index < len(weights) else 0.0
        row = layout.row(align=True)
        row.alignment = 'EXPAND'

        # 键名（可手打，也可以用右侧菜单从物体的键里挑）
        row.prop(item, "shape_key", text="")
        pick = row.row(align=True)
        pick.alignment = 'RIGHT'
        pick.menu(HO_MT_ShapekeyTools_BlendPointKey.bl_idname,
                  text="", icon='DOWNARROW_HLT')

        # 键值：当前权重
        value = row.row(align=True)
        value.alignment = 'RIGHT'
        value.ui_units_x = 3.5
        value.label(text=f"{weight:.3f}")

        # 控制点位置：只读显示
        position = row.row(align=True)
        position.alignment = 'RIGHT'
        position.ui_units_x = 8.0
        position.label(text=f"{item.u:.3f}, {item.v:.3f}")

        # 跳到该点位
        jump = row.operator(
            OP_ShapekeyTools_BlendJumpToPoint.bl_idname, text="", icon='EYEDROPPER')
        jump.index = index


class HO_UL_ShapekeyTools_BlendObjects(UIList):
    """操作物体对象列表：标准 UIList，每行只有「删除 × + 物体」。

    行结构刻意做得很素：``[×] [物体] [空白]``。右侧留一小节空白，方便点在这一行上
    （把这一行设为列表的活动行），也不用去点很窄的物体名文字。
    """

    bl_idname = "HO_UL_ShapekeyTools_BlendObjects"

    def draw_item(self, context, layout: UILayout, data, item, icon,
                  active_data, active_propname, index):
        row = layout.row(align=True)
        row.alignment = 'EXPAND'
        missing = _keys.resolve_object(item) is None
        if missing:
            row.alert = True

        remove = row.operator(
            _store.OP_ShapekeyTools_BlendObjectRemove.bl_idname, text="", icon='X')
        remove.index = index
        row.prop(item, "object", text="")
        if missing:
            row.label(text="", icon='ERROR')
        # 右侧留白：这一小节没有任何控件，点它就是点在这一行上
        spacer = row.row(align=True)
        spacer.ui_units_x = 2.0


class HO_MT_ShapekeyTools_BlendPointKey(Menu):
    """坐标点的形态键挑选菜单：列出操作物体与活动物体上的键名。"""

    bl_idname = "HO_MT_ShapekeyTools_BlendPointKey"
    bl_label = "指定形态键"

    def draw(self, context):
        layout = self.layout
        item = _active_item(context)
        if item is None or not item.points:
            layout.label(text="没有坐标点", icon='INFO')
            return
        index = max(0, min(item.point_index, len(item.points) - 1))
        names = _func.candidate_shape_key_names(item, context)
        if not names:
            layout.label(text="物体上没有形态键", icon='INFO')
            return
        for name in names:
            operator = layout.operator(
                _store.OP_ShapekeyTools_BlendPointSetShapeKey.bl_idname,
                text=name,
            )
            operator.index = index
            operator.shape_key = name


# endregion


# region 面板绘制


def _draw_debug_list(layout: UILayout, context: Context) -> None:
    """矩阵列表。"""
    scene = context.scene
    box = layout.box()
    row = box.row(align=True)
    row.template_list(
        "UI_UL_list", "ho_bs_debug_list",
        scene, "ho_bs_debug_items",
        scene, "ho_bs_debug_index",
        rows=6,
    )
    column = row.column(align=True)
    column.operator(
        _store.OP_ShapekeyTools_BlendDebugAdd.bl_idname, text="", icon='ADD')
    column.operator(
        _store.OP_ShapekeyTools_BlendDebugRemove.bl_idname, text="", icon='REMOVE')
    column.operator(
        _store.OP_ShapekeyTools_BlendDebugClear.bl_idname, text="", icon='TRASH')


def _draw_debug_config(layout: UILayout, context: Context) -> None:
    """矩阵属性。"""
    item = _active_item(context)
    if item is None:
        placeholder = layout.box()
        placeholder.label(text="没有调试矩阵", icon='INFO')
        return

    box = layout.box()
    column = box.column(align=True)

    mode_row = column.row(align=True)
    mode_row.prop(item, "mix_mode", text="")

    axis_row = column.row(align=True)
    axis_row.prop(item, "u_name", text="")
    axis_row.prop(item, "v_name", text="")

    cursor_row = column.row(align=True)
    cursor_row.prop(item, "cursor_u", text="")
    cursor_row.prop(item, "cursor_v", text="")
    # 控制点归零：就放在 XY 右侧角落，一个图标
    cursor_row.operator(
        OP_ShapekeyTools_BlendResetCursor.bl_idname, text="", icon='LOOP_BACK')


def _draw_debug_objects(layout: UILayout, context: Context) -> None:
    """可折叠的「操作物体对象列表」：标准 UIList + template_list。

    行内绘制在 :class:`HO_UL_ShapekeyTools_BlendObjects`，滚动/选中/拖动排序由
    Blender 的 ``template_list`` 接管；活动行下标存在场景上（``ho_bs_object_list``）。
    """
    item = _active_item(context)
    if item is None:
        return
    scene = context.scene
    box = layout.box()
    header = box.row(align=True)
    header.prop(
        item,
        "objects_expanded",
        text="",
        icon='TRIA_DOWN' if item.objects_expanded else 'TRIA_RIGHT',
        emboss=False,
    )
    header.label(text=f"操作物体对象列表 ({len(item.objects)})")
    if item.objects:
        valid_count = len(_keys.active_objects(item))
        if valid_count != len(item.objects):
            header.alert = True
            header.label(text=f"失效 {len(item.objects) - valid_count}", icon='ERROR')
            header.alert = False
    if not item.objects_expanded:
        return

    # 注意：绘制回调里**绝对不能写 ID 属性**（Blender 会报
    # “Writing to ID classes in this context is not allowed”）。
    # 行下标只在算子里写；template_list 自己会把越界下标夹回范围。
    row = box.row(align=True)
    row.template_list(
        HO_UL_ShapekeyTools_BlendObjects.__name__, "",
        item, "objects",
        scene, "ho_bs_object_list",
        rows=6,
    )
    column = row.column(align=True)
    column.operator(
        _store.OP_ShapekeyTools_BlendObjectAdd.bl_idname, text="", icon='ADD')
    column.operator(
        _store.OP_ShapekeyTools_BlendObjectRemove.bl_idname, text="", icon='REMOVE')
    column.operator(
        _store.OP_ShapekeyTools_BlendObjectClear.bl_idname, text="", icon='TRASH')

    if not item.objects:
        note = box.row()
        note.enabled = False
        note.label(text="选中网格物体后点 + 快速添加", icon='INFO')


def _draw_points(layout: UILayout, context: Context, item) -> None:
    """坐标点位列表 + 当前点位的坐标编辑。"""
    box = layout.box()
    header = box.row(align=True)
    header.label(text=f"坐标点位 ({len(item.points)})", icon='MESH_GRID')
    duplicates = _layout.duplicate_coordinate_groups(item) if len(item.points) > 1 else []
    if duplicates:
        header.alert = True
        header.label(text=f"重合 {len(duplicates)} 处", icon='ERROR')
        header.alert = False

    row = box.row(align=True)
    row.template_list(
        HO_UL_ShapekeyTools_BlendPoints.__name__, "",
        item, "points",
        item, "point_index",
        rows=8,
    )
    column = row.column(align=True)
    column.operator(
        _store.OP_ShapekeyTools_BlendPointAddActive.bl_idname, text="", icon='ADD')
    column.operator(
        _store.OP_ShapekeyTools_BlendPointRemove.bl_idname, text="", icon='REMOVE')

    if not item.points:
        note = box.row()
        note.enabled = False
        note.label(text="点 + 添加当前活动形态键（自动切到下一个键）", icon='INFO')
        return

    # 当前活动点位的坐标：选中行后在这里改
    index = max(0, min(item.point_index, len(item.points) - 1))
    point = item.points[index]
    edit = box.row(align=True)
    edit.label(text=f"#{index + 1} 控制点位置")
    edit.prop(point, "u", text=item.u_name[:6] or "U")
    edit.prop(point, "v", text=item.v_name[:6] or "V")
    edit.operator(
        OP_ShapekeyTools_BlendJumpToPoint.bl_idname, text="", icon='EYEDROPPER')


def _draw_actions(layout: UILayout, context: Context, item) -> None:
    """应用控制 / 全键归零。"""
    scene = context.scene
    box = layout.box()
    row = box.row(align=True)
    row.scale_y = 1.5
    row.operator(
        OP_ShapekeyTools_BlendApplyWeights.bl_idname,
        text="应用控制",
        icon='CHECKMARK',
    )
    row.operator(
        OP_ShapekeyTools_BlendClearAllKeys.bl_idname,
        text="全键归零",
        icon='X',
    )

    if not _keys.active_objects(item):
        warn = box.row()
        warn.alert = True
        warn.label(text="操作物体对象列表为空", icon='ERROR')

    option = box.row(align=True)
    option.prop(scene, "ho_bs_apply_on_cursor", text="控点立刻更新", toggle=True)
    option.prop(scene, "ho_bs_mute_others", text="关闭其他", toggle=True)


def _draw_debug_actions(layout: UILayout, context: Context) -> None:
    item = _active_item(context)
    if item is None:
        placeholder = layout.box()
        placeholder.label(text="没有调试矩阵", icon='INFO')
        return
    box = layout.box().column(align=True)
    _draw_points(box, context, item)
    _draw_actions(box, context, item)


def _draw_widget_controls(layout: UILayout, context: Context) -> None:
    """生成 / 关闭视口左下角的调试矩阵绘件。"""
    control = layout.box()
    if not _overlay.WIDGET.is_running:
        row = control.row(align=True)
        row.scale_y = 1.4
        row.operator(
            _overlay.OP_ShapekeyTools_BlendWidget.bl_idname,
            text="生成调试矩阵",
            icon='PLAY',
        )
    else:
        row = control.row(align=True)
        row.scale_y = 1.4
        row.alert = True
        row.operator(
            _overlay.OP_ShapekeyTools_BlendWidgetStop.bl_idname,
            text="关闭调试矩阵",
            icon='PAUSE',
        )
        row.alert = False
        note = control.row()
        note.enabled = False
        note.label(text=_overlay.WIDGET.describe(context))


def drawBlendPanel(layout: UILayout, context: Context) -> None:
    """形态键工具 → 混合矩阵页面的总入口。"""
    workspace = layout.split(factor=0.42, align=False)
    left = workspace.column(align=True)
    right = workspace.column(align=True)
    _draw_debug_list(left, context)
    _draw_debug_config(left, context)
    _draw_debug_objects(left, context)
    _draw_debug_actions(right, context)
    _draw_widget_controls(layout.row(align=True), context)


# endregion


def reg_props():
    bpy.types.Scene.ho_bs_debug_list = StringProperty(default="")


def ureg_props():
    del bpy.types.Scene.ho_bs_debug_list


cls = [
    HO_UL_ShapekeyTools_BlendPoints,
    HO_UL_ShapekeyTools_BlendObjects,
    HO_MT_ShapekeyTools_BlendPointKey,
    OP_ShapekeyTools_BlendApplyWeights,
    OP_ShapekeyTools_BlendResetCursor,
    OP_ShapekeyTools_BlendClearAllKeys,
    OP_ShapekeyTools_BlendJumpToPoint,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    ureg_props()
    for item in reversed(cls):
        bpy.utils.unregister_class(item)
    _func.invalidate_weight_cache()


__all__ = (
    "drawBlendPanel",
    "evaluate_item",
    "invalidate_weight_cache",
    "register",
    "unregister",
)
