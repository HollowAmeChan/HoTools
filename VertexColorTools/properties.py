import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
)
from bpy.types import PropertyGroup


def update_vertex_color_view_mode(self, context):
    if context is None:
        return
    try:
        if self.view_mode:
            bpy.ops.ho.entervertexcolorview()
        else:
            bpy.ops.ho.quitvertexcolorview()
    except RuntimeError:
        pass


class HO_PG_VertexColorItem(PropertyGroup):
    color: FloatVectorProperty(
        name="VertexColor",
        size=3,
        subtype="COLOR",
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
    )  # type: ignore


class HO_PG_VertexColorSceneSettings(PropertyGroup):
    temp_colors: CollectionProperty(type=HO_PG_VertexColorItem)  # type: ignore
    default_colors: CollectionProperty(type=HO_PG_VertexColorItem)  # type: ignore

    show_base_tools: BoolProperty(default=True)  # type: ignore
    show_template_tools: BoolProperty(default=False)  # type: ignore
    show_utils_tools: BoolProperty(default=False)  # type: ignore

    view_mode: BoolProperty(
        default=False,
        description="使用 Blender 原生顶点色预览",
        update=update_vertex_color_view_mode,
    )  # type: ignore

    paint_color: FloatVectorProperty(
        name="缓存颜色",
        size=3,
        subtype="COLOR",
        default=(1.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
    )  # type: ignore

    default_group_index: IntProperty(default=1, min=0, max=3)  # type: ignore
    choose_same_threshold: FloatProperty(
        name="容差",
        description="选择同顶点色时使用的容差",
        default=0.01,
        min=0.0,
        max=1.0,
    )  # type: ignore


def get_scene_settings(scene):
    return scene.ho_vertex_color_tools


CLASSES = (
    HO_PG_VertexColorItem,
    HO_PG_VertexColorSceneSettings,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ho_vertex_color_tools = PointerProperty(type=HO_PG_VertexColorSceneSettings)


def unregister():
    if hasattr(bpy.types.Scene, "ho_vertex_color_tools"):
        del bpy.types.Scene.ho_vertex_color_tools
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
