import bpy
import os
from bpy.types import Operator,Panel

from . import VertexColorTools, ShapekeyTools, FastOperators, BoneTools, AnimationTools, exIcon, VertexGroupTools,Exporter,NameMapping,UvTools,Checker
from bpy.props import BoolProperty, FloatProperty

# 内置的绘制快捷键ui的接口
import rna_keymap_ui


bl_info = {
    "name": "HoTools",
    "author": "Hollow_ame",
    "version": (2, 0, 0),
    "blender": (4, 3, 0),
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


class AddonPreference(bpy.types.AddonPreferences):
    """插件的参数，不随着文件改变而改变"""
    bl_idname = __name__

    hoTools_enableExIcon: BoolProperty(name="开关exicon",
                                       default=False, update=updateExIconState)  # type: ignore
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


cls = [OP_register_asset_library,AddonPreference,]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    
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
    FastOperators.register()
    VertexColorTools.register()
    VertexGroupTools.register()
    ShapekeyTools.register()
    BoneTools.register()
    AnimationTools.register()
    Exporter.register()
    NameMapping.register()
    exIcon.register()
    UvTools.register()
    Checker.register()

    

def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    FastOperators.unregister()
    VertexColorTools.unregister()
    VertexGroupTools.unregister()
    ShapekeyTools.unregister()
    BoneTools.unregister()
    AnimationTools.unregister()
    Exporter.unregister()
    NameMapping.unregister()
    exIcon.unregister()
    UvTools.unregister()
    Checker.unregister()

    
