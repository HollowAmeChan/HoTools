"""修改器工具模块。

把常用的修改器堆栈操作、形态键共存提示和批量复制集中到原生修改器面板。
"""

import bpy
from bpy.types import Operator

from ..Checker.objectChecker.define import check_object_shape_keys_with_modifiers
# 复制操作沿用 FastOperators 中已有的注册类，避免改变原有操作 ID。
from ..FastOperators import OP_CopyALL_modifiers_to_selected
from ..ShapekeyTools.operators import OP_applyShowingModifiersKeepShapekeys


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


def _draw_modifier_tools(layout, context):
    obj = context.active_object
    if obj is None:
        return
    layout.use_property_decorate = False
    if not obj.modifiers:
        return

    col = layout.column(align=True)

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
    OP_ApplyAllModifiers,
    OP_DeleteAllModifiers,
    OP_ToggleModifiersViewport,
    OP_ToggleAllModifiersExpanded,
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
