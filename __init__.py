import bpy
from bpy.types import Operator,Panel

import os  # NOQA: E402
import sys  # NOQA: E402
"""
bl安装插件时无法识别到内部写为模块的文件夹(仅安装阶段，安装完毕后使用正常),
需要单独添加模块的路径才能找到
"""
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


from . import VertexColorTools, ShapekeyTools, FastOperators, BoneTools, AnimationTools, exIcon, VertexGroupTools,Exporter,NameMapping,UvTools,MeshTools,Checker,Rbf,ModTools,HoPie
from . import OmniNode
from bpy.props import BoolProperty, FloatProperty

# 内置的绘制快捷键ui的接口
import rna_keymap_ui


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


def updateAlignPieState(self, context):
    HoPie.set_align_pie_enabled(self.hoTools_enableAlignPie)


def updateCursorPieState(self, context):
    HoPie.set_cursor_pie_enabled(self.hoTools_enableCursorPie)


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


def _draw_module_box(layout, prefs, expanded_prop, title, icon='PLUGIN', switch_prop=None, draw_content=None):
    box = layout.box()
    header = box.row(align=True)
    header.prop(
        prefs,
        expanded_prop,
        text='',
        icon='TRIA_DOWN' if getattr(prefs, expanded_prop) else 'TRIA_RIGHT',
        emboss=False,
    )
    header.label(text=title, icon=icon)
    if switch_prop:
        header.prop(prefs, switch_prop, text='启用', toggle=True)
    if getattr(prefs, expanded_prop):
        content = box.column(align=True)
        if draw_content:
            draw_content(content)
        else:
            placeholder = content.row()
            placeholder.enabled = False
            placeholder.label(text='暂无偏好参数，保留扩展位置')
    return box


class AddonPreference(bpy.types.AddonPreferences):
    """插件的参数，不随着文件改变而改变"""
    bl_idname = __name__

    hoTools_enableExIcon: BoolProperty(name="开关exicon",
                                       default=False, update=updateExIconState)  # type: ignore
    hoTools_OmniNodeFeatures_enable: BoolProperty(name="OmniNode",
                                          default=False,update=updateOmniNodeFeaturesState)  # type: ignore
    hoTools_enableAlignPie: BoolProperty(name="对齐饼菜单", default=False, update=updateAlignPieState)  # type: ignore
    hoTools_enableCursorPie: BoolProperty(name="光标与原点饼菜单", default=False, update=updateCursorPieState)  # type: ignore
    hoTools_cursorShowToGrid: BoolProperty(name="光标饼菜单显示网格操作", default=False)  # type: ignore
    hoTools_ui_exicon_expanded: BoolProperty(name='展开 ExIcon', default=True)  # type: ignore
    hoTools_ui_omninode_expanded: BoolProperty(name='展开 OmniNode', default=False)  # type: ignore
    hoTools_ui_hopie_expanded: BoolProperty(name='展开 HoPie', default=True)  # type: ignore
    hoTools_ui_keymaps_expanded: BoolProperty(name='展开快捷键', default=False)  # type: ignore

    hoTools_ExIconSize: FloatProperty(name="图标大小", default=0.5)  # type: ignore
    hoTools_ExiconAlpha: FloatProperty(
        name="图标不透明度", default=0.5, min=0.0, max=1.0)  # type: ignore

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        row = layout.row(align=True)
        row.alert = True
        row.operator("ho.register_asset_library", text="注册内置资源库")
        row.alert = False
        row = layout.row(align=True)
        row.prop(self, "hoTools_enableExIcon", toggle=True)
        row.prop(self, "hoTools_ExIconSize")
        row.prop(self, "hoTools_ExiconAlpha")
        row = layout.row(align=True)
        row.prop(self, "hoTools_OmniNodeFeatures_enable", toggle=True)
        row = layout.row(align=True)
        row.prop(self, "hoTools_enableAlignPie", toggle=True)
        row.prop(self, "hoTools_enableCursorPie", toggle=True)
        row.prop(self, "hoTools_cursorShowToGrid", toggle=True)

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

        if MeshTools.addon_keymaps or HoPie.preference_keymaps():
            col = layout.column()
            for km, kmi in [*MeshTools.addon_keymaps, *HoPie.preference_keymaps()]:
                col.context_pointer_set("keymap", km)
                rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        wm = context.window_manager
        kc = wm.keyconfigs.user

        intro = layout.box()
        intro.label(text='HoTools 模块设置', icon='PREFERENCES')
        row = intro.row(align=True)
        row.alert = True
        row.operator('ho.register_asset_library', text='注册内置资源库', icon='ASSET_MANAGER')

        def draw_exicon(content):
            row = content.row(align=True)
            row.prop(self, 'hoTools_ExIconSize')
            row.prop(self, 'hoTools_ExiconAlpha')

        def draw_hopie(content):
            row = content.row(align=True)
            row.prop(self, 'hoTools_enableAlignPie', text='对齐饼菜单', toggle=True)
            row.prop(self, 'hoTools_enableCursorPie', text='光标与原点饼菜单', toggle=True)
            content.prop(self, 'hoTools_cursorShowToGrid', text='显示网格操作')

        _draw_module_box(layout, self, 'hoTools_ui_exicon_expanded', 'ExIcon', 'IMAGE_DATA', 'hoTools_enableExIcon', draw_exicon)
        _draw_module_box(layout, self, 'hoTools_ui_omninode_expanded', 'OmniNode', 'NODETREE', 'hoTools_OmniNodeFeatures_enable')
        _draw_module_box(layout, self, 'hoTools_ui_hopie_expanded', 'HoPie', 'MESH_CIRCLE', draw_content=draw_hopie)

        def draw_keymaps(content):
            for keymap, keymap_item in [*MeshTools.addon_keymaps, *HoPie.preference_keymaps()]:
                content.context_pointer_set('keymap', keymap)
                rna_keymap_ui.draw_kmi([], kc, keymap, keymap_item, content, 0)

        if MeshTools.addon_keymaps or HoPie.preference_keymaps():
            _draw_module_box(layout, self, 'hoTools_ui_keymaps_expanded', '快捷键', 'KEYINGSET', draw_content=draw_keymaps)


cls = [OP_register_asset_library,AddonPreference,]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    
    FastOperators.register()
    VertexColorTools.register()
    VertexGroupTools.register()
    ShapekeyTools.register()
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

    prefs = bpy.context.preferences.addons[__name__].preferences
    if prefs.hoTools_enableAlignPie:
        HoPie.set_align_pie_enabled(True)
    if prefs.hoTools_enableCursorPie:
        HoPie.set_cursor_pie_enabled(True)
    if prefs.hoTools_OmniNodeFeatures_enable:
        OmniNode.register()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

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
    
