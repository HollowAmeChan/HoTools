"""修改器工具模块。

把常用的修改器堆栈操作、形态键共存提示和批量复制集中到原生修改器面板。
"""

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty

from ..Checker.objectChecker.define import check_object_shape_keys_with_modifiers
from ..ShapekeyTools.operators import (
    OP_applyShowingModifiersKeepShapekeys,
    OP_ForceRemoveAll,
)


_QUICK_MODIFIER_ITEMS = (
    ("SUBSURF_SIMPLE", "纯细分", "简单细分，不产生平滑形变"),
    ("SUBSURF", "细分", "Catmull-Clark 细分"),
    ("SOLIDIFY", "实体化", "为表面添加厚度"),
    ("MIRROR", "镜像", "沿 X 轴镜像"),
    ("TRIANGULATE", "三角化", "把面转换为三角面"),
    ("BOOLEAN", "布尔", "添加布尔修改器"),
    ("SHRINKWRAP", "缩裹", "把网格顶点缩裹到目标表面"),
    ("DATA_TRANSFER", "传递", "添加数据传递修改器"),
)

_QUICK_MODIFIER_SPECS = {
    "SUBSURF_SIMPLE": ("SUBSURF", "纯细分", "MOD_SUBSURF"),
    "SUBSURF": ("SUBSURF", "细分", "MOD_SUBSURF"),
    "SOLIDIFY": ("SOLIDIFY", "实体化", "MOD_SOLIDIFY"),
    "MIRROR": ("MIRROR", "镜像", "MOD_MIRROR"),
    "TRIANGULATE": ("TRIANGULATE", "三角化", "MOD_TRIANGULATE"),
    "BOOLEAN": ("BOOLEAN", "布尔", "MOD_BOOLEAN"),
    "SHRINKWRAP": ("SHRINKWRAP", "缩裹", "MOD_SHRINKWRAP"),
    "DATA_TRANSFER": ("DATA_TRANSFER", "传递", "MOD_DATA_TRANSFER"),
}


# 这些修改器只改变顶点位置，不改变拓扑；其余可见修改器按非形变修改器提示。
_DEFORM_ONLY_MODIFIER_TYPES = frozenset({
    "ARMATURE",
    "CAST",
    "CORRECTIVE_SMOOTH",
    "CURVE",
    "DISPLACE",
    "HOOK",
    "LAPLACIANDEFORM",
    "LATTICE",
    "MESH_DEFORM",
    "SHRINKWRAP",
    "SIMPLE_DEFORM",
    "SMOOTH",
    "SMOOTH_CORRECTIVE",
    "SURFACE_DEFORM",
    "WARP",
    "WAVE",
})


class OP_CopyALL_modifiers_to_selected(Operator):
    """Copy every modifier from the active object to the other selected objects."""

    bl_idname = "ho.copyall_modifiers_to_selected"
    bl_label = "复制全部修改器到所选"
    bl_description = "按顺序复制全部修改器到所选物体"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        active_obj = context.active_object
        selected_objs = context.selected_objects

        if not active_obj:
            self.report({"ERROR"}, "没有活动物体")
            return {"CANCELLED"}
        if len(selected_objs) < 2:
            self.report({"ERROR"}, "需要选择至少两个物体（源物体+目标物体）")
            return {"CANCELLED"}

        modifiers = active_obj.modifiers
        if not modifiers:
            self.report({"INFO"}, "活动物体没有修改器")
            return {"FINISHED"}

        try:
            for modifier in modifiers:
                bpy.ops.object.modifier_copy_to_selected(modifier=modifier.name)
        except RuntimeError as error:
            self.report({"ERROR"}, f"复制失败: {error}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"成功复制 {len(modifiers)} 个修改器")
        return {"FINISHED"}


def _has_visible_non_deform_modifier(obj) -> bool:
    """检查网格是否同时有形态键和显示中的非形变修改器。"""
    if not check_object_shape_keys_with_modifiers(obj):
        return False
    shape_keys = getattr(getattr(obj, "data", None), "shape_keys", None)
    if shape_keys is None or len(shape_keys.key_blocks) <= 1:
        return False
    return any(
        bool(getattr(modifier, "show_viewport", True))
        and modifier.type not in _DEFORM_ONLY_MODIFIER_TYPES
        for modifier in obj.modifiers
    )


class OP_AddQuickModifier(Operator):
    """快速添加并配置一个常用修改器。"""

    bl_idname = "ho.modifier_add_quick"
    bl_label = "添加修改器"
    bl_description = "添加一个常用修改器到活动物体"
    bl_options = {"REGISTER", "UNDO"}

    modifier_type: EnumProperty(
        name="修改器类型",
        items=_QUICK_MODIFIER_ITEMS,
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and hasattr(obj, "modifiers")

    def execute(self, context):
        obj = context.active_object
        spec = _QUICK_MODIFIER_SPECS.get(self.modifier_type)
        if obj is None or spec is None:
            self.report({"ERROR"}, "无法添加修改器")
            return {"CANCELLED"}

        modifier_type, modifier_name, _icon = spec
        try:
            modifier = obj.modifiers.new(name=modifier_name, type=modifier_type)
            if modifier_type == "SUBSURF":
                modifier.levels = 2
                modifier.render_levels = 2
                if self.modifier_type == "SUBSURF_SIMPLE":
                    modifier.subdivision_type = "SIMPLE"
        except Exception as error:
            self.report({"ERROR"}, f"添加{modifier_name}失败：{error}")
            return {"CANCELLED"}

        modifier.show_expanded = True
        self.report({"INFO"}, f"已添加{modifier_name}修改器")
        return {"FINISHED"}


class OP_ApplyAllModifiers(Operator):
    """应用所有所选物体的修改器。"""

    bl_idname = "ho.modifier_apply_all"
    bl_label = "应用全部修改器"
    bl_description = "应用所有所选物体的修改器"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = tuple(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "没有选择物体，未应用修改器")
            return {"CANCELLED"}

        failed_objects = []
        applied_count = 0
        for obj in selected_objects:
            for modifier in tuple(obj.modifiers):
                try:
                    with context.temp_override(object=obj, modifier=modifier):
                        bpy.ops.object.modifier_apply(modifier=modifier.name)
                    applied_count += 1
                except Exception:
                    failed_objects.append(obj.name)

        if failed_objects:
            names = ", ".join(dict.fromkeys(failed_objects))
            self.report({"WARNING"}, f"部分修改器应用失败：{names}")
        else:
            self.report({"INFO"}, f"已应用 {applied_count} 个修改器")
        return {"FINISHED"}


class OP_DeleteAllModifiers(Operator):
    """删除所有所选物体的修改器。"""

    bl_idname = "ho.modifier_delete_all"
    bl_label = "删除全部修改器"
    bl_description = "删除所有所选物体的修改器"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        selected_objects = tuple(context.selected_objects)
        if not selected_objects:
            self.report({"INFO"}, "没有选择物体，未删除修改器")
            return {"CANCELLED"}

        deleted_count = sum(len(obj.modifiers) for obj in selected_objects)
        for obj in selected_objects:
            for modifier in tuple(obj.modifiers):
                obj.modifiers.remove(modifier)
        self.report({"INFO"}, f"已删除 {deleted_count} 个修改器")
        return {"FINISHED"}


class OP_ToggleModifiersViewport(Operator):
    """切换所选物体的修改器视图显示。"""

    bl_idname = "ho.modifier_toggle_viewport"
    bl_label = "切换视图显示"
    bl_description = "显示或隐藏所选物体的修改器"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        modifiers = [
            modifier
            for obj in context.selected_objects
            for modifier in obj.modifiers
            if modifier.type != "COLLISION"
        ]
        if not modifiers:
            self.report({"INFO"}, "没有可切换显示的修改器")
            return {"CANCELLED"}

        show_viewport = not any(modifier.show_viewport for modifier in modifiers)
        for modifier in modifiers:
            modifier.show_viewport = show_viewport
        self.report({"INFO"}, "已显示修改器" if show_viewport else "已隐藏修改器")
        return {"FINISHED"}


class OP_ToggleAllModifiersExpanded(Operator):
    """展开或折叠活动物体的修改器堆栈。"""

    bl_idname = "ho.modifier_toggle_expanded"
    bl_label = "展开/折叠堆栈"
    bl_description = "展开或折叠活动物体的修改器堆栈"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        modifiers = tuple(context.active_object.modifiers)
        if not modifiers:
            self.report({"INFO"}, "活动物体没有修改器")
            return {"CANCELLED"}

        collapse = sum(1 if modifier.show_expanded else -1 for modifier in modifiers) > 0
        for modifier in modifiers:
            modifier.show_expanded = not collapse
        return {"FINISHED"}


def _draw_shape_key_warning(layout, obj):
    if not _has_visible_non_deform_modifier(obj):
        return
    row = layout.row(align=True)
    row.alert = True
    row.label(text="形态键与非形变修改器共存", icon="ERROR")
    row.alert = False
    row.operator(
        OP_applyShowingModifiersKeepShapekeys.bl_idname,
        text="保持形态键应用",
        icon="MODIFIER",
    )
    row.operator(
        OP_ForceRemoveAll.bl_idname,
        text="",
        icon="TRASH",
    )


def _draw_quick_modifier_buttons(layout):
    """绘制两排四列的常用修改器按钮。"""
    box = layout.box()
    col = box.column(align=True)
    col.scale_y = 2
    # 展开到 HoPie 时，row(align=True) 在 Blender 的嵌套布局中可能吞掉一列。
    # 固定四列网格同时保持按钮无缝对齐，普通修改器面板也使用同一套布局。
    grid = col.grid_flow(
        row_major=True,
        columns=4,
        even_columns=True,
        even_rows=True,
        align=True,
    )
    for modifier_id, label, _description in _QUICK_MODIFIER_ITEMS:
        icon = _QUICK_MODIFIER_SPECS[modifier_id][2]
        operator = grid.operator(OP_AddQuickModifier.bl_idname, text=label, icon=icon)
        operator.modifier_type = modifier_id


def _draw_modifier_tools(layout, context):
    obj = context.active_object
    layout.use_property_decorate = False
    col = layout.column(align=True)

    _draw_quick_modifier_buttons(col)

    if obj is None:
        return
    
    if obj.modifiers:
        row = col.row(align=True)
        row.operator(OP_ApplyAllModifiers.bl_idname,text="应用全部", icon="IMPORT")
        row.operator(OP_DeleteAllModifiers.bl_idname,text="删除全部", icon="X")
        row = col.row(align=True)
        row.operator(OP_ToggleModifiersViewport.bl_idname,text="切换显示", icon="RESTRICT_VIEW_OFF")
        row.operator(OP_ToggleAllModifiersExpanded.bl_idname, text="展开/折叠", icon="FULLSCREEN_ENTER")

    _draw_shape_key_warning(col, obj)
    if len(context.selected_objects) >= 2:
        col.operator(
            OP_CopyALL_modifiers_to_selected.bl_idname,
            text="复制全部到所选",
            icon="COPYDOWN",
        )


def draw_in_DATA_PT_modifiers(self, context):
    """在原生修改器面板顶部绘制工具按钮。"""
    _draw_modifier_tools(self.layout, context)


def draw_in_VIEW3D_MT_object_apply(self, context):
    """在物体应用菜单中加入批量应用修改器。"""
    obj = context.active_object
    if obj is None or not obj.modifiers:
        return
    self.layout.operator(
        OP_ApplyAllModifiers.bl_idname,
        text="应用全部修改器",
        icon="IMPORT",
    )


_CLASSES = (
    OP_AddQuickModifier,
    OP_ApplyAllModifiers,
    OP_DeleteAllModifiers,
    OP_ToggleModifiersViewport,
    OP_ToggleAllModifiersExpanded,
    OP_CopyALL_modifiers_to_selected,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.DATA_PT_modifiers.prepend(draw_in_DATA_PT_modifiers)
    bpy.types.VIEW3D_MT_object_apply.append(draw_in_VIEW3D_MT_object_apply)


def unregister():
    try:
        bpy.types.VIEW3D_MT_object_apply.remove(draw_in_VIEW3D_MT_object_apply)
    except Exception:
        pass
    try:
        bpy.types.DATA_PT_modifiers.remove(draw_in_DATA_PT_modifiers)
    except Exception:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


__all__ = ["register", "unregister"]
