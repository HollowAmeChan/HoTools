import bpy
from bpy.props import BoolProperty
from bpy.types import Panel

from .NodeTree.OmniNodeOperator import (
    LayerRunning,
    OmniTreeClearCompileCache,
    OmniTreeClearRuntimeCache,
    OmniTreeCompile,
    OmniTreeDestroy,
    OmniTreeRunCompiled,
    _should_alert_compile_button,
)


def _is_omni_tree(tree):
    return tree is not None and getattr(tree, "bl_idname", None) == "OmniNodeTree"


def _tree_name_key(tree):
    return str(getattr(tree, "name_full", "") or getattr(tree, "name", ""))


def _iter_omni_trees():
    trees = [tree for tree in bpy.data.node_groups if _is_omni_tree(tree)]
    return sorted(trees, key=lambda tree: _tree_name_key(tree).lower())


def _compiled_status_icon(tree):
    try:
        if tree.compile_cache_status_label() == "已缓存":
            return "CHECKMARK"
    except Exception:
        pass
    return "RADIOBUT_OFF"


def _tree_operator(layout, op_idname, tree_name, *, text="", icon="NONE"):
    op = layout.operator(op_idname, text=text, icon=icon)
    op.tree_name = tree_name
    return op


class HO_PT_omni_node_panel(Panel):
    bl_idname = "VIEW3D_PT_ho_omni_node_panel"
    bl_label = "OmniNode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_tree_row(self, layout, tree, show_advanced):
        tree_name = _tree_name_key(tree)
        should_alert_compile = _should_alert_compile_button(tree)
        status = "状态未知"
        try:
            status = tree.compile_cache_status_label()
        except Exception:
            pass

        box = layout.box()
        box.scale_y = 1.05
        col = box.column(align=True)

        top = col.row(align=True)
        name_col = top.row(align=True)
        name_col.scale_x = 1.6
        name_col.label(text=tree.name, icon="NODETREE")

        status_col = top.row(align=True)
        status_col.alignment = 'RIGHT'
        status_col.label(text="", icon=_compiled_status_icon(tree))

        frame_col = top.row(align=True)
        frame_col.scale_x = 0.8
        frame_col.prop(tree, "is_frame_run_enabled", text="帧运行", toggle=True, icon="TIME")

        if not show_advanced:
            run_row = col.row(align=True)
            run_row.scale_y = 1.25
            compile_run = run_row.row(align=True)
            compile_run.alert = should_alert_compile
            _tree_operator(
                compile_run,
                LayerRunning.bl_idname,
                tree_name,
                text="编译运行",
                icon="FILE_REFRESH",
            )
            _tree_operator(compile_run, OmniTreeClearRuntimeCache.bl_idname, tree_name, text="清缓存", icon="X")
            return

        op_row = col.row(align=True)
        op_row.scale_y = 1.15
        compile_run = op_row.row(align=True)
        compile_run.alert = should_alert_compile
        _tree_operator(compile_run, LayerRunning.bl_idname, tree_name, text="编译运行", icon="FILE_REFRESH")
        compile_button = op_row.row(align=True)
        compile_button.alert = should_alert_compile
        _tree_operator(compile_button, OmniTreeCompile.bl_idname, tree_name, text="编译", icon="FILE_TICK")
        _tree_operator(op_row, OmniTreeClearRuntimeCache.bl_idname, tree_name, text="清缓存", icon="X")

        sub = col.row(align=True)
        sub.scale_y = 1.15
        _tree_operator(sub, OmniTreeRunCompiled.bl_idname, tree_name, text="运行", icon="PLAY")
        _tree_operator(sub, OmniTreeClearRuntimeCache.bl_idname, tree_name, text="清缓存", icon="X")
        _tree_operator(sub, OmniTreeClearCompileCache.bl_idname, tree_name, text="清编译", icon="TRASH")
        danger = sub.row(align=True)
        danger.alert = True
        danger.operator_context = 'INVOKE_DEFAULT'
        _tree_operator(danger, OmniTreeDestroy.bl_idname, tree_name, text="销毁树", icon="TRASH")

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        show_advanced = bool(getattr(scene, "ho_omni_panel_show_advanced", False))

        header = layout.row(align=True)
        header.label(text="OmniNode 树")
        header.prop(scene, "ho_omni_panel_show_advanced", text="高级", toggle=True)

        trees = _iter_omni_trees()
        if not trees:
            layout.label(text="没有 OmniNodeTree", icon="INFO")
            return

        for tree in trees:
            self.draw_tree_row(layout, tree, show_advanced)


classes = [HO_PT_omni_node_panel]


def register_props():
    if not hasattr(bpy.types.Scene, "ho_omni_panel_show_advanced"):
        bpy.types.Scene.ho_omni_panel_show_advanced = BoolProperty(
            name="高级",
            description="显示 OmniNode 批量管理的高级操作",
            default=False,
        )


def unregister_props():
    if hasattr(bpy.types.Scene, "ho_omni_panel_show_advanced"):
        del bpy.types.Scene.ho_omni_panel_show_advanced


def register():
    register_props()
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    unregister_props()
