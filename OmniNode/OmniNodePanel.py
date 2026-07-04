import bpy
from bpy.props import BoolProperty
from bpy.types import Panel

from .NodeTree.OmniNodeOperator import (
    LayerRunning,
    OmniTreeBindMount,
    OmniTreeClearCompileCache,
    OmniTreeClearMount,
    OmniTreeCreate,
    OmniTreeCreateMount,
    OmniTreeClearRuntimeCache,
    OmniTreeCompile,
    OmniTreeDestroy,
    OmniTreeOpen,
    OmniTreeRunCompiled,
    _should_alert_compile_button,
    _tree_has_compile_cache,
    iter_omni_mount_objects,
    omni_mount_owner_for_tree,
    omni_object_root_tree,
)


def _is_omni_tree(tree):
    return tree is not None and getattr(tree, "bl_idname", None) == "OmniNodeTree"


def _tree_name_key(tree):
    return str(getattr(tree, "name_full", "") or getattr(tree, "name", ""))


def _iter_omni_trees():
    trees = [tree for tree in bpy.data.node_groups if _is_omni_tree(tree)]
    return sorted(trees, key=lambda tree: _tree_name_key(tree).casefold())


def _compiled_status_icon(tree):
    try:
        if _tree_has_compile_cache(tree):
            return "CHECKMARK"
    except Exception:
        pass
    return "RADIOBUT_OFF"


def _tree_operator(layout, op_idname, tree_name, *, text="", icon="NONE"):
    op = layout.operator(op_idname, text=text, icon=icon)
    op.tree_name = tree_name
    return op


def _active_empty(context):
    obj = getattr(context, "object", None)
    return obj if obj is not None and getattr(obj, "type", None) == 'EMPTY' else None


class HO_PT_omni_node_panel(Panel):
    bl_idname = "VIEW3D_PT_ho_omni_node_panel"
    bl_label = "OmniNode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_tree_controls(self, layout, context, tree, show_advanced):
        tree_name = _tree_name_key(tree)
        should_alert_compile = _should_alert_compile_button(tree)
        execution_enabled = bool(getattr(tree, "is_execution_enabled", True))

        top = layout.row(align=True)
        name_col = top.row(align=True)
        name_col.scale_x = 1.6
        open_op = name_col.operator(OmniTreeOpen.bl_idname, text=tree.name, icon="NODETREE", emboss=False)
        open_op.tree_name = tree_name

        status_col = top.row(align=True)
        status_col.alignment = 'RIGHT'
        status_col.label(text="", icon=_compiled_status_icon(tree))

        enable_col = top.row(align=True)
        enable_col.scale_x = 0.9
        enable_col.prop(tree, "is_execution_enabled", text="", toggle=True, icon="CHECKMARK", icon_only=True)

        frame_col = top.row(align=True)
        frame_col.scale_x = 0.8
        frame_col.enabled = execution_enabled
        frame_col.prop(tree, "is_frame_run_enabled", text="帧运行", toggle=True, icon="TIME")

        run_row = layout.row(align=True)
        run_row.scale_y = 1.15
        compile_run = run_row.row(align=True)
        compile_run.enabled = execution_enabled
        compile_run.alert = should_alert_compile and execution_enabled
        _tree_operator(compile_run, LayerRunning.bl_idname, tree_name, text="编译运行", icon="FILE_REFRESH")

        compile_button = run_row.row(align=True)
        compile_button.alert = should_alert_compile
        _tree_operator(compile_button, OmniTreeCompile.bl_idname, tree_name, text="编译", icon="FILE_TICK")

        clear_runtime = run_row.row(align=True)
        clear_runtime.enabled = execution_enabled
        _tree_operator(clear_runtime, OmniTreeClearRuntimeCache.bl_idname, tree_name, text="清缓存", icon="X")

        if not show_advanced:
            return

        sub = layout.row(align=True)
        sub.scale_y = 1.1
        sub.enabled = execution_enabled
        _tree_operator(sub, OmniTreeRunCompiled.bl_idname, tree_name, text="运行", icon="PLAY")
        _tree_operator(sub, OmniTreeClearCompileCache.bl_idname, tree_name, text="清编译", icon="TRASH")

        danger = sub.row(align=True)
        danger.alert = True
        danger.operator_context = 'INVOKE_DEFAULT'
        _tree_operator(danger, OmniTreeDestroy.bl_idname, tree_name, text="销毁树", icon="TRASH")

        bind = layout.row(align=True)
        bind.enabled = _active_empty(context) is not None
        op = bind.operator(OmniTreeBindMount.bl_idname, text="绑定选中空物体", icon="EMPTY_AXIS")
        op.tree_name = tree_name

    def draw_tree_row(self, layout, context, tree, show_advanced):
        box = layout.box()
        box.scale_y = 1.05
        self.draw_tree_controls(box.column(align=True), context, tree, show_advanced)

    def draw_mount_row(self, layout, context, obj, tree, show_advanced):
        owner = omni_mount_owner_for_tree(tree, context.scene)
        is_duplicate = owner is not None and owner != obj

        box = layout.box()
        box.scale_y = 1.05
        col = box.column(align=True)

        mount_row = col.row(align=True)
        mount_row.label(text=obj.name, icon="EMPTY_AXIS")
        mount_row.prop(obj, "ho_omni_root_tree", text="")

        if is_duplicate:
            warn = col.row(align=True)
            warn.alert = True
            warn.label(text=f"重复挂载已忽略；有效挂载是 {owner.name}", icon="ERROR")
            return

        self.draw_tree_controls(col, context, tree, show_advanced)

    def draw_active_empty_tools(self, layout, context):
        obj = _active_empty(context)
        if obj is None:
            return

        box = layout.box()
        col = box.column(align=True)
        col.label(text=f"选中空物体: {obj.name}", icon="EMPTY_AXIS")
        col.prop(obj, "ho_omni_root_tree", text="")

        tree = omni_object_root_tree(obj)
        if tree is not None:
            row = col.row(align=True)
            op = row.operator(OmniTreeOpen.bl_idname, text="打开树", icon="NODETREE")
            op.tree_name = _tree_name_key(tree)
            row.operator(OmniTreeClearMount.bl_idname, text="清空挂载", icon="X")

    def draw_mounts(self, layout, context, show_advanced):
        mounts = iter_omni_mount_objects(context.scene)
        if not mounts:
            return False

        for obj in mounts:
            tree = omni_object_root_tree(obj)
            if tree is None:
                continue
            self.draw_mount_row(layout, context, obj, tree, show_advanced)
        return True

    def draw_legacy_trees(self, layout, context, show_advanced):
        trees = _iter_omni_trees()
        if not trees:
            layout.label(text="场景中没有 OmniNodeTree", icon="INFO")
            return

        for tree in trees:
            self.draw_tree_row(layout, context, tree, show_advanced)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        show_advanced = bool(getattr(scene, "ho_omni_panel_show_advanced", False))

        header = layout.row(align=True)
        header.label(text="OmniNode 挂载")
        header.operator(OmniTreeCreateMount.bl_idname, text="", icon="ADD")
        header.prop(scene, "ho_omni_panel_show_advanced", text="高级", toggle=True)

        self.draw_active_empty_tools(layout, context)

        has_mounts = self.draw_mounts(layout, context, show_advanced)
        if not has_mounts:
            layout.label(text="场景中没有 OmniNode 挂载空物体", icon="INFO")
            self.draw_legacy_trees(layout, context, show_advanced)
            return

        if not show_advanced:
            return

        layout.separator()
        all_trees_header = layout.row(align=True)
        all_trees_header.label(text="全部 OmniNodeTree")
        all_trees_header.operator(OmniTreeCreate.bl_idname, text="", icon="ADD")
        self.draw_legacy_trees(layout, context, show_advanced)


classes = [
    HO_PT_omni_node_panel,
]


def register_props():
    if not hasattr(bpy.types.Scene, "ho_omni_panel_show_advanced"):
        bpy.types.Scene.ho_omni_panel_show_advanced = BoolProperty(
            name="高级",
            description="显示 OmniNode 管理的高级操作",
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
