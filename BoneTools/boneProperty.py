import bpy
from bpy.types import Panel, PropertyGroup
from bpy.props import (
    BoolProperty,
    PointerProperty,
    StringProperty,
)


class PG_Hotools_BoneProps(PropertyGroup):
    keepRotation: BoolProperty(
        name="保留旋转",
        description="在使用hotools fbx导出时,如果这段骨骼不保留旋转,将会自动将骨骼竖直，注意会导致这段骨骼后续的叶骨添加错误",
        default=True,
    )  # type: ignore
    endBone: BoolProperty(
        name="叶骨",
        description="Hotools是否将骨骼标记为叶骨",
        default=False,
    )  # type: ignore
    humanoidMapping: StringProperty(
        name="Humanoid映射",
        description="定义此骨对应Unity-Humannoid标准骨",
        default="",
    )  # type: ignore


class PT_Hotools_PosebonePanel(Panel):
    bl_idname = "BONE_PT_Hotools_PoseBonePanel"
    bl_label = "HoTools骨骼"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.mode == "POSE" and context.active_bone is not None

    def draw(self, context):
        bone = context.active_bone
        layout = self.layout
        props = bone.hotools_boneprops
        layout.prop(props, "keepRotation", toggle=False)
        layout.prop(props, "endBone", toggle=False)
        layout.prop(props, "humanoidMapping", toggle=False)


cls = [
    PG_Hotools_BoneProps,
    PT_Hotools_PosebonePanel,
]


def reg_props():
    if hasattr(bpy.types.Bone, "hotools_boneprops"):
        del bpy.types.Bone.hotools_boneprops
    bpy.types.Bone.hotools_boneprops = PointerProperty(type=PG_Hotools_BoneProps)


def ureg_props():
    if hasattr(bpy.types.Bone, "hotools_boneprops"):
        del bpy.types.Bone.hotools_boneprops


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
