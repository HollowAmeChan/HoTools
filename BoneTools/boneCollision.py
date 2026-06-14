import bpy
from bpy.types import Panel, PropertyGroup
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty


class PG_Hotools_BoneCollision(PropertyGroup):
    collision_type: EnumProperty(
        name="碰撞体",
        description="这根骨骼携带的物理碰撞体类型；当前只负责持久化与编辑",
        items=[
            ("NONE", "无", "不作为物理碰撞体"),
            ("SPHERE", "球体", "以骨骼局部偏移为中心的球形碰撞体"),
            ("CAPSULE", "胶囊", "沿骨骼局部Y轴延伸的胶囊碰撞体"),
        ],
        default="NONE",
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="碰撞体半径，使用Blender单位",
        default=0.05,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    length: FloatProperty(
        name="长度",
        description="胶囊中段长度，球体类型会忽略这个参数",
        default=0.2,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    offset: FloatVectorProperty(
        name="中心偏移",
        description="碰撞体中心相对骨骼局部空间的偏移",
        size=3,
        subtype="XYZ",
        default=(0.0, 0.0, 0.0),
    )  # type: ignore


def _active_collision_props(context):
    bone = context.active_bone
    if bone is None:
        return None
    return getattr(bone, "hotools_collision", None)


class PT_Hotools_BoneCollisionPanel(Panel):
    bl_idname = "BONE_PT_Hotools_BoneCollisionPanel"
    bl_label = "HoTools碰撞体"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.mode == "POSE" and _active_collision_props(context) is not None

    def draw(self, context):
        props = _active_collision_props(context)
        layout = self.layout

        layout.prop(props, "collision_type", text="类型")
        if props.collision_type == "NONE":
            return

        col = layout.column(align=True)
        col.prop(props, "radius")
        if props.collision_type == "CAPSULE":
            col.prop(props, "length")
        col.prop(props, "offset")


cls = [
    PG_Hotools_BoneCollision,
    PT_Hotools_BoneCollisionPanel,
]


def reg_props():
    if hasattr(bpy.types.Bone, "hotools_collision"):
        del bpy.types.Bone.hotools_collision
    bpy.types.Bone.hotools_collision = PointerProperty(type=PG_Hotools_BoneCollision)


def ureg_props():
    if hasattr(bpy.types.Bone, "hotools_collision"):
        del bpy.types.Bone.hotools_collision


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
