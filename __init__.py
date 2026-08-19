import bpy
from bpy.types import Operator,Panel

import os  # NOQA: E402
import sys  # NOQA: E402
plugin_dir = os.path.dirname(__file__)
sys.path.append(plugin_dir)
lib_dir = os.path.join(plugin_dir, "_Lib")
sys.path.append(lib_dir)
if sys.version_info[:2] == (3, 13):
    py_lib_dir = os.path.join(lib_dir, "py313")
elif sys.version_info[:2] == (3, 11):
    py_lib_dir = os.path.join(lib_dir, "py311")
else:
    raise RuntimeError(
        "HoTools supports Blender Python 3.11 and 3.13; "
        f"found {sys.version_info.major}.{sys.version_info.minor}"
    )

sys.path.append(py_lib_dir)
sys.path.insert(0, os.path.join(py_lib_dir, "HotoolsPackage"))


from . import VertexColorTools, ShapekeyTools, FastOperators, BoneTools, AnimationTools, exIcon, VertexGroupTools,Exporter,NameMapping,UvTools,MeshTools,Checker,Rbf,ModTools,ModifierTools,HoPie
from . import OmniNode, HoTab
from bpy.props import BoolProperty, FloatProperty

# 内置的绘制快捷键ui的接口
import rna_keymap_ui


def _preference_keymaps():
    return [
        *getattr(FastOperators, 'addon_keymaps', []),
        *getattr(VertexGroupTools.vertexGroupOperators, 'addon_keymaps', []),
        *MeshTools.preference_keymaps(),
        *HoPie.preference_keymaps(),
        *HoTab.preference_keymaps(),
    ]


bl_info = {
    "name": "HoTools",
    "author": "Hollow_ame",
    "version": (3, 0, 0),
    "blender": (4, 5, 0),
    "location": "Hollow",
    "description": "https://space.bilibili.com/60340452",
    "warning": "",
    "wiki_url": "",
    "category": "Mesh",
}


def updateExIconState(self, context):
    """插件参数使用到的更新函数"""
    prefs = context.preferences.addons[__name__].preferences
    if prefs.hoTools_enableExIcon:
        bpy.ops.ho.draw_exicon()
    else:
        bpy.ops.ho.remove_exicon()


def updateOmniNodeFeaturesState(self, context):
    """OmniNode功能使用到的更新函数"""
    prefs = context.preferences.addons[__name__].preferences
    if prefs.hoTools_OmniNodeFeatures_enable:
        OmniNode.register()
    else:
        OmniNode.unregister()


def updateHoTabState(self, context):
    if self.hoTools_enableHoTab:
        HoTab.enable()
    else:
        HoTab.disable()


def updateAlignPieState(self, context):
    HoPie.set_align_pie_enabled(self.hoTools_enableAlignPie)


def updateCursorPieState(self, context):
    HoPie.set_cursor_pie_enabled(self.hoTools_enableCursorPie)


def updateSelectionModePieState(self, context):
    HoPie.set_selection_mode_pie_enabled(self.hoTools_enableSelectionModePie)


def updateDeleteMergePieState(self, context):
    HoPie.set_delete_merge_pie_enabled(self.hoTools_enableDeleteMergePie)


def updateMainPieState(self, context):
    HoPie.set_main_pie_enabled(self.hoTools_enableHoMainPie)


def updateMainPieEditModeOnly(self, context):
    HoPie.set_main_pie_edit_mode_only(self.hoTools_HoMainPieEditModeOnly)


# 插件内置资源路径相关函数
def asset_library_exists(path):
    libs = bpy.context.preferences.filepaths.asset_libraries
    path = os.path.normpath(path)

    for lib in libs:
        if os.path.normpath(lib.path) == path:
            return True
    return False
def register_asset_library(name, path):
    prefs = bpy.context.preferences.filepaths
    libs = prefs.asset_libraries
    path = os.path.normpath(path)
    
    try:
        # Blender 4.x
        libs.new(name=name, directory=path)
    except TypeError:
        # Blender 3.x
        libs.new(name=name, path=path)
    return True

class OP_register_asset_library(Operator):
    bl_idname = "ho.register_asset_library"
    bl_label = "注册内置资源库"
    bl_description = "将Hotools内置资源库注册到Blender资源库中,可在资源浏览器中使用"

    def execute(self, context):
        addon_dir = os.path.dirname(__file__)
        asset_path = os.path.join(addon_dir, "HoAssets")
        if asset_library_exists(asset_path):
            self.report({'INFO'}, "HoAssets已经被注册过了")
            return {'CANCELLED'}

        register_asset_library("HoTools", asset_path)
        self.report({'INFO'}, "HoTools资产库HoAssets已注册")
        return {'FINISHED'}


def _draw_module_box(layout, prefs, expanded_prop, title, switch_prop=None, draw_content=None):
    box = layout.box()
    header = box.row(align=True)
    if switch_prop:
        header.prop(prefs, switch_prop, text='')
    header.prop(
        prefs,
        expanded_prop,
        text='',
        icon='TRIA_DOWN' if getattr(prefs, expanded_prop) else 'TRIA_RIGHT',
        emboss=False,
    )
    header.label(text=title)
    if getattr(prefs, expanded_prop):
        content = box.column(align=True)
        if draw_content:
            draw_content(content)
        else:
            placeholder = content.row()
            placeholder.enabled = False
            placeholder.label(text='暂无')
    return box


class AddonPreference(bpy.types.AddonPreferences):
    """插件的参数，不随着文件改变而改变"""
    bl_idname = __name__

    hoTools_enableExIcon: BoolProperty(name="开关exicon",
                                       default=False, update=updateExIconState)  # type: ignore
    hoTools_OmniNodeFeatures_enable: BoolProperty(name="OmniNode",
                                          default=False,update=updateOmniNodeFeaturesState)  # type: ignore
    hoTools_enableHoTab: BoolProperty(name="HoTab", default=True, update=updateHoTabState)  # type: ignore
    hoTools_enableAlignPie: BoolProperty(name="对齐饼菜单", default=False, update=updateAlignPieState)  # type: ignore
    hoTools_enableCursorPie: BoolProperty(name="光标与原点饼菜单", default=False, update=updateCursorPieState)  # type: ignore
    hoTools_enableSelectionModePie: BoolProperty(name="选择模式饼菜单", default=True, update=updateSelectionModePieState)  # type: ignore
    hoTools_enableDeleteMergePie: BoolProperty(name="删除与合并饼菜单", default=True, update=updateDeleteMergePieState)  # type: ignore
    hoTools_enableHoMainPie: BoolProperty(name="Ho大饼", default=True, update=updateMainPieState)  # type: ignore
    hoTools_HoMainPieEditModeOnly: BoolProperty(name="仅编辑模式",description="开启时仅在编辑网格模式响应空格；关闭后在三维视图的其他模式也响应",default=False,update=updateMainPieEditModeOnly,)  # type: ignore
    hoTools_ui_exicon_expanded: BoolProperty(name='展开 ExIcon', default=False)  # type: ignore
    hoTools_ui_omninode_expanded: BoolProperty(name='展开 OmniNode', default=False)  # type: ignore
    hoTools_ui_hotab_expanded: BoolProperty(name='展开 HoTab', default=False)  # type: ignore
    hoTools_ui_hopie_expanded: BoolProperty(name='展开 HoPie', default=False)  # type: ignore
    hoTools_ui_keymaps_expanded: BoolProperty(name='展开快捷键', default=True)  # type: ignore

    hoTools_ExIconSize: FloatProperty(name="图标大小", default=0.5)  # type: ignore
    hoTools_ExiconAlpha: FloatProperty(
        name="图标不透明度", default=0.5, min=0.0, max=1.0)  # type: ignore

    def _draw_legacy_preferences(self, context):
        layout: bpy.types.UILayout = self.layout
        row = layout.row(align=True)
        row.alert = True
        row.operator("ho.register_asset_library", text="注册内置资源库")
        row.alert = False
        row = layout.row(align=True)
        row.prop(self, "hoTools_enableExIcon")
        row.prop(self, "hoTools_ExIconSize")
        row.prop(self, "hoTools_ExiconAlpha")
        row = layout.row(align=True)
        row.prop(self, "hoTools_OmniNodeFeatures_enable")
        row = layout.row(align=True)
        row.prop(self, "hoTools_enableAlignPie")
        row.prop(self, "hoTools_enableCursorPie")

        # 获取 KeyMap
        wm = context.window_manager
        kc = wm.keyconfigs.user  # 使用用户配置
        km = kc.keymaps.get("Window")

        if km:
            col = layout.column()
            for kmi in km.keymap_items:
                if kmi.idname == FastOperators.OP_select_inside_face_loop.bl_idname:
                    col.context_pointer_set("keymap", km)
                    rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)
                if kmi.idname == FastOperators.OP_AddSelectSideRingLoops.bl_idname:
                    col.context_pointer_set("keymap", km)
                    rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)
                if kmi.idname == FastOperators.OP_RemoveSelectSideRingLoops.bl_idname:
                    col.context_pointer_set("keymap", km)
                    rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)
                if kmi.idname == "ho.vertexgrouptools_switch_vg_bycursor":
                    col.context_pointer_set("keymap", km)
                    rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)

        if _preference_keymaps():
            col = layout.column()
            for km, kmi in _preference_keymaps():
                col.context_pointer_set("keymap", km)
                rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        wm = context.window_manager
        kc = wm.keyconfigs.user

        intro = layout.box()
        intro.label(text='HoTools 模块设置')
        row = intro.row(align=True)
        row.alert = True
        row.operator('ho.register_asset_library', text='注册内置资源库')

        def draw_exicon(content):
            row = content.row(align=True)
            row.prop(self, 'hoTools_ExIconSize')
            row.prop(self, 'hoTools_ExiconAlpha')

        def draw_hopie(content):
            def draw_indented(box, draw_content):
                split = box.split(factor=0.08, align=True)
                split.column()
                draw_content(split.column(align=True))

            def draw_align_mode(column):
                column.prop(
                    context.scene,
                    'ho_align_pie_mode',
                    text='模式',
                    expand=True,
                )

            def draw_empty_slot(box):
                row = box.row()
                row.scale_y = 0.35
                row.label(text='')

            align_box = content.box()
            row = align_box.row(align=True)
            row.prop(self, 'hoTools_enableAlignPie', text='')
            row.label(text='对齐饼')
            draw_indented(align_box, draw_align_mode)

            cursor_box = content.box()
            row = cursor_box.row(align=True)
            row.prop(self, 'hoTools_enableCursorPie', text='')
            row.label(text='光标与原点饼')
            draw_empty_slot(cursor_box)

            selection_box = content.box()
            row = selection_box.row(align=True)
            row.prop(self, 'hoTools_enableSelectionModePie', text='')
            row.label(text='选择模式饼')
            draw_empty_slot(selection_box)

            delete_merge_box = content.box()
            row = delete_merge_box.row(align=True)
            row.prop(self, 'hoTools_enableDeleteMergePie', text='')
            row.label(text='删除/合并饼')
            draw_empty_slot(delete_merge_box)

            main_pie_box = content.box()
            row = main_pie_box.row(align=True)
            row.prop(self, 'hoTools_enableHoMainPie', text='')
            row.label(text='Ho大饼）')
            option_row = main_pie_box.row(align=True)
            option_row.prop(self, 'hoTools_HoMainPieEditModeOnly')
            draw_empty_slot(main_pie_box)

        _draw_module_box(layout, self, 'hoTools_ui_exicon_expanded', 'ExIcon', 'hoTools_enableExIcon', draw_exicon)
        _draw_module_box(layout, self, 'hoTools_ui_omninode_expanded', 'OmniNode', 'hoTools_OmniNodeFeatures_enable')
        _draw_module_box(layout, self, 'hoTools_ui_hotab_expanded', 'HoTab', 'hoTools_enableHoTab')
        _draw_module_box(layout, self, 'hoTools_ui_hopie_expanded', 'HoPie', draw_content=draw_hopie)

        def draw_keymaps(content):
            for keymap, keymap_item in _preference_keymaps():
                content.context_pointer_set('keymap', keymap)
                rna_keymap_ui.draw_kmi([], kc, keymap, keymap_item, content, 0)

        if _preference_keymaps():
            _draw_module_box(layout, self, 'hoTools_ui_keymaps_expanded', '快捷键', draw_content=draw_keymaps)


cls = [OP_register_asset_library,AddonPreference,]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    
    FastOperators.register()
    VertexColorTools.register()
    VertexGroupTools.register()
    ShapekeyTools.register()
    ModifierTools.register()
    from .OmniNode.PhysicsWorld.blender import register as register_physics_world
    register_physics_world()
    BoneTools.register()
    AnimationTools.register()
    Exporter.register()
    NameMapping.register()
    exIcon.register()
    UvTools.register()
    MeshTools.register()
    Checker.register()
    Rbf.register()
    ModTools.register()
    HoPie.register()
    HoTab.register()

    prefs = bpy.context.preferences.addons[__name__].preferences
    HoPie.set_align_pie_enabled(prefs.hoTools_enableAlignPie)
    HoPie.set_cursor_pie_enabled(prefs.hoTools_enableCursorPie)
    HoPie.set_selection_mode_pie_enabled(prefs.hoTools_enableSelectionModePie)
    HoPie.set_delete_merge_pie_enabled(prefs.hoTools_enableDeleteMergePie)
    HoPie.set_main_pie_edit_mode_only(prefs.hoTools_HoMainPieEditModeOnly)
    HoPie.set_main_pie_enabled(prefs.hoTools_enableHoMainPie)
    if prefs.hoTools_OmniNodeFeatures_enable:
        OmniNode.register()
    if prefs.hoTools_enableHoTab:
        HoTab.enable()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    ModifierTools.unregister()
    FastOperators.unregister()
    VertexColorTools.unregister()
    VertexGroupTools.unregister()
    ShapekeyTools.unregister()
    BoneTools.unregister()
    from .OmniNode.PhysicsWorld.blender import unregister as unregister_physics_world
    unregister_physics_world()
    AnimationTools.unregister()
    Exporter.unregister()
    NameMapping.unregister()
    exIcon.unregister()
    UvTools.unregister()
    MeshTools.unregister()
    HoPie.unregister()
    Checker.unregister()
    Rbf.unregister()
    OmniNode.unregister()
    ModTools.unregister()
    HoTab.unregister()
    
