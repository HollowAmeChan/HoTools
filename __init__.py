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


from . import VertexColorTools, ShapekeyTools, BoneTools, AnimationTools, exIcon, VertexGroupTools,Exporter,NameMapping,UvTools,MeshTools,Checker,Rbf,ModTools,ModifierTools,HoPie
from . import ProjectTools, ObjectTools, CurveTools
from . import OmniNode, HoTab
from .Utils.keymap_utils import find_user_keymap_item
from bpy.props import BoolProperty, FloatProperty

# 内置的绘制快捷键ui的接口
import rna_keymap_ui


def _preference_keymaps():
    return [
        *ProjectTools.preference_keymaps(),
        *ObjectTools.preference_keymaps(),
        *CurveTools.preference_keymaps(),
        *getattr(VertexGroupTools.vertexGroupOperators, 'addon_keymaps', []),
        *MeshTools.preference_keymaps(),
        *HoPie.preference_keymaps(),
        *HoTab.preference_keymaps(),
    ]


def _preference_user_keymaps(context):
    """将已注册的插件默认快捷键解析为可持久化的用户快捷键项。"""
    kc = context.window_manager.keyconfigs.user
    resolved = []
    for addon_keymap, addon_item in _preference_keymaps():
        user_item = find_user_keymap_item(kc, addon_keymap, addon_item)
        if user_item is not None:
            resolved.append(user_item)
    return resolved


def _preference_space_playback_keymaps(context):
    """Return Blender's unmodified Space bindings for animation playback."""
    kc = context.window_manager.keyconfigs.user
    keymap = kc.keymaps.get("Frames")
    if keymap is None:
        return []

    result = []
    for item in keymap.keymap_items:
        if item.idname != "screen.animation_play":
            continue
        if item.type != "SPACE" or item.value != "PRESS":
            continue
        if any((
                item.any,
                item.shift,
                item.ctrl,
                item.alt,
                item.oskey,
                item.hyper,
        )):
            continue
        if item.key_modifier != "NONE":
            continue
        result.append((keymap, item))
    return result


def _draw_space_playback_warning(layout, context):
    """Draw editable Blender playback bindings in the HoMainPie settings."""
    warning = layout.row(align=True)
    warning.alert = True
    warning.label(
        text="禁用原生空格播放以使用",
        icon="ERROR",
    )

    kc = context.window_manager.keyconfigs.user
    for keymap, item in _preference_space_playback_keymaps(context):
        layout.context_pointer_set("keymap", keymap)
        rna_keymap_ui.draw_kmi([], kc, keymap, item, layout, 0)


bl_info = {
    "name": "HoTools",
    "author": "Hollow_ame",
    "version": (3, 0, 0),
    "blender": (4, 1, 0),
    "location": "View3D > Sidebar > HoTools",
    "description": "面向独立模型师、mod作者、动画创作者的巨型工具集。",
    "doc_url": "https://hollowamechan.github.io/HotoolsDoc-Quartz/",
    "support": "COMMUNITY",
    "warning": "",
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
    HoPie.set_pie_enabled('align', self.hoTools_enableAlignPie)


def updateCursorPieState(self, context):
    HoPie.set_pie_enabled('cursor', self.hoTools_enableCursorPie)


def updateSelectionModePieState(self, context):
    HoPie.set_pie_enabled('selection_mode', self.hoTools_enableSelectionModePie)


def updateDeleteMergePieState(self, context):
    HoPie.set_pie_enabled('delete_merge', self.hoTools_enableDeleteMergePie)


def updateMainPieState(self, context):
    HoPie.set_pie_enabled('main', self.hoTools_enableHoMainPie)


def updateArmatureModePieState(self, context):
    HoPie.set_pie_enabled('armature_mode', self.hoTools_enableArmatureModePie)


def builtin_asset_library_path():
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "HoAssets"))


# 插件内置资源路径相关函数
def asset_library_entry(path):
    libs = bpy.context.preferences.filepaths.asset_libraries
    path = os.path.normpath(path)

    for lib in libs:
        if os.path.normpath(lib.path) == path:
            return lib
    return None


def asset_library_exists(path):
    return asset_library_entry(path) is not None


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


def unregister_asset_library(path):
    lib = asset_library_entry(path)
    if lib is None:
        return False
    bpy.context.preferences.filepaths.asset_libraries.remove(lib)
    return True


class OP_register_asset_library(Operator):
    bl_idname = "ho.register_asset_library"
    bl_label = "注册内置资源库"
    bl_description = "将Hotools内置资源库注册到Blender资源库中,可在资源浏览器中使用"

    def execute(self, context):
        asset_path = builtin_asset_library_path()
        if asset_library_exists(asset_path):
            self.report({'INFO'}, "HoAssets已经被注册过了")
            return {'CANCELLED'}

        register_asset_library("HoTools", asset_path)
        self.report({'INFO'}, "HoTools资产库HoAssets已注册")
        return {'FINISHED'}


class OP_unregister_asset_library(Operator):
    bl_idname = "ho.unregister_asset_library"
    bl_label = "注销内置资源库"
    bl_description = "从 Blender 资源库列表中移除 HoTools 内置资源库"

    def execute(self, context):
        if not unregister_asset_library(builtin_asset_library_path()):
            self.report({'INFO'}, "HoAssets 尚未注册")
            return {'CANCELLED'}
        self.report({'INFO'}, "HoTools 资产库 HoAssets 已注销")
        return {'FINISHED'}


def _draw_asset_library_controls(layout):
    registered = asset_library_exists(builtin_asset_library_path())
    status = layout.row(align=True)
    if not registered:
        status.alert = True
        status.label(text=("点击注册以使用内置资产->"))
        status.operator('ho.register_asset_library', text='注册内置资源库')
        status.alert = False
    if registered:
        status.operator('ho.unregister_asset_library', text='注销内置资源库')


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
    hoTools_enableAlignPie: BoolProperty(name="对齐饼菜单", default=True, update=updateAlignPieState)  # type: ignore
    hoTools_enableCursorPie: BoolProperty(name="光标与原点饼菜单", default=True, update=updateCursorPieState)  # type: ignore
    hoTools_enableSelectionModePie: BoolProperty(name="选择模式饼菜单", default=True, update=updateSelectionModePieState)  # type: ignore
    hoTools_enableDeleteMergePie: BoolProperty(name="删除与合并饼菜单", default=True, update=updateDeleteMergePieState)  # type: ignore
    hoTools_enableHoMainPie: BoolProperty(name="Ho大饼", default=True, update=updateMainPieState)  # type: ignore
    hoTools_enableArmatureModePie: BoolProperty(name="骨架模式饼", default=True, update=updateArmatureModePieState)  # type: ignore
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
        _draw_asset_library_controls(layout)
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
                if kmi.idname == "ho.vertexgrouptools_switch_vg_bycursor":
                    col.context_pointer_set("keymap", km)
                    rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)

        user_keymaps = _preference_user_keymaps(context)
        if user_keymaps:
            col = layout.column()
            for keymap, keymap_item in user_keymaps:
                col.context_pointer_set("keymap", keymap)
                rna_keymap_ui.draw_kmi([], kc, keymap, keymap_item, col, 0)

    def draw(self, context):
        layout: bpy.types.UILayout = self.layout
        wm = context.window_manager
        kc = wm.keyconfigs.user

        columns = layout.split(factor=0.3, align=False)
        left = columns.column(align=True)
        right = columns.column(align=True)

        intro = left.box()
        intro.label(text='HoTools 模块设置')
        _draw_asset_library_controls(intro)

        def draw_exicon(content):
            row = content.row(align=True)
            row.prop(self, 'hoTools_ExIconSize')
            row.prop(self, 'hoTools_ExiconAlpha')

        def draw_hopie(content):
            has_details = hasattr(context.scene, 'ho_align_pie_mode')
            if has_details:
                split = content.split(factor=0.3, align=False)
                controls = split.column(align=True)
                details = split.column(align=True)
            else:
                controls = content
                details = None

            def draw_toggle(prop_name, label):
                row = controls.row(align=True)
                row.prop(self, prop_name, text=label, toggle=True)

            draw_toggle('hoTools_enableAlignPie', '对齐饼')
            draw_toggle('hoTools_enableCursorPie', '光标与原点饼')
            draw_toggle('hoTools_enableSelectionModePie', '选择模式饼')
            draw_toggle('hoTools_enableDeleteMergePie', '删除/合并饼')
            draw_toggle('hoTools_enableHoMainPie', 'Ho大饼')
            draw_toggle('hoTools_enableArmatureModePie', '骨架模式饼')

            if details is not None:
                settings_column = details
            else:
                settings_column = controls

            if self.hoTools_enableHoMainPie:
                settings = settings_column.box()
                settings.label(text='Ho大饼设置')
                _draw_space_playback_warning(settings, context)

            if details is not None:
                if self.hoTools_enableAlignPie:
                    settings = details.box()
                    settings.label(text='对齐饼设置')
                    settings.prop(
                        context.scene,
                        'ho_align_pie_mode',
                        text='模式',
                        expand=True,
                    )

        _draw_module_box(left, self, 'hoTools_ui_exicon_expanded', 'ExIcon', 'hoTools_enableExIcon', draw_exicon)
        _draw_module_box(left, self, 'hoTools_ui_omninode_expanded', 'OmniNode', 'hoTools_OmniNodeFeatures_enable')
        _draw_module_box(left, self, 'hoTools_ui_hotab_expanded', 'HoTab', 'hoTools_enableHoTab')
        _draw_module_box(left, self, 'hoTools_ui_hopie_expanded', 'HoPie', draw_content=draw_hopie)

        user_keymaps = _preference_user_keymaps(context)

        def draw_keymaps(content):
            for keymap, keymap_item in user_keymaps:
                content.context_pointer_set('keymap', keymap)
                rna_keymap_ui.draw_kmi([], kc, keymap, keymap_item, content, 0)

        if user_keymaps:
            _draw_module_box(right, self, 'hoTools_ui_keymaps_expanded', '快捷键', draw_content=draw_keymaps)


cls = [OP_register_asset_library, OP_unregister_asset_library, AddonPreference,]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    
    ProjectTools.register()
    ObjectTools.register()
    MeshTools.register()
    CurveTools.register()
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
    Checker.register()
    Rbf.register()
    ModTools.register()
    HoPie.register()
    HoTab.register()

    prefs = bpy.context.preferences.addons[__name__].preferences
    HoPie.set_pie_enabled('align', prefs.hoTools_enableAlignPie)
    HoPie.set_pie_enabled('cursor', prefs.hoTools_enableCursorPie)
    HoPie.set_pie_enabled('selection_mode', prefs.hoTools_enableSelectionModePie)
    HoPie.set_pie_enabled('delete_merge', prefs.hoTools_enableDeleteMergePie)
    HoPie.set_pie_enabled('main', prefs.hoTools_enableHoMainPie)
    HoPie.set_pie_enabled('armature_mode', prefs.hoTools_enableArmatureModePie)
    if prefs.hoTools_OmniNodeFeatures_enable:
        OmniNode.register()
    if prefs.hoTools_enableHoTab:
        HoTab.enable()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    ModifierTools.unregister()
    CurveTools.unregister()
    MeshTools.unregister()
    ObjectTools.unregister()
    ProjectTools.unregister()
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
    HoPie.unregister()
    Checker.unregister()
    Rbf.unregister()
    OmniNode.unregister()
    ModTools.unregister()
    HoTab.unregister()
    
