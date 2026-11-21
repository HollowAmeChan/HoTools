"""Small authoring settings for the ordinary copyR tool."""

from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import PropertyGroup

OWNER_SPACES = (
    ("LOCAL", "局部空间", "相对于自身静置姿态，排除父骨运动"),
    ("WORLD", "世界空间", "使用完整世界朝向"),
    ("POSE", "姿态空间", "在骨架物体空间求值"),
    ("LOCAL_WITH_PARENT", "局部含父级", "局部空间并包含父骨链运动"),
)
TARGET_SPACES = (("LOCAL_OWNER_ORIENT", "局部空间（所有者方向）", "补偿目标与受约束骨的静置轴差异"),) + OWNER_SPACES


class PG_Hotools_CopyRSettings(PropertyGroup):
    ui_expanded: BoolProperty(name="copyR 设置", default=False)
    target_bone: StringProperty(name="目标骨", description="所选受约束骨跟随的同骨架目标骨", default="")
    influence: FloatProperty(name="跟随强度", default=1.0, min=0.0, max=1.0)
    target_space: EnumProperty(name="目标空间", items=TARGET_SPACES, default="LOCAL_OWNER_ORIENT")
    owner_space: EnumProperty(name="自身空间", items=OWNER_SPACES, default="LOCAL")
