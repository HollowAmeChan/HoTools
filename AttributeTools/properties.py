import bpy
from bpy.props import StringProperty
from bpy.types import PropertyGroup


class HO_PG_AttributeToolsSettings(PropertyGroup):
    smoothnormal_attribute_name: StringProperty(
        name="属性名",
        description="写入对象空间平滑法线的 Face Corner 属性名",
        default="smoothnormalOS",
    )  # type: ignore


def get_scene_settings(scene):
    return scene.ho_attribute_tools


CLASSES = (HO_PG_AttributeToolsSettings,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ho_attribute_tools = bpy.props.PointerProperty(
        type=HO_PG_AttributeToolsSettings,
    )


def unregister():
    if hasattr(bpy.types.Scene, "ho_attribute_tools"):
        del bpy.types.Scene.ho_attribute_tools
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
