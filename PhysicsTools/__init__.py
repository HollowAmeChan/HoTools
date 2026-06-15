import bpy
from bpy.props import BoolProperty, PointerProperty

from .collisionOperators import (
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_AddSelectedSpringRoots,
    OP_Hotools_BoneCollision_ClearAllSpringRoots,
    OP_Hotools_BoneCollision_GradientRadius,
    OP_Hotools_BoneCollision_SelectSpringRoots,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
)
from .collisionPanel import (
    PT_Hotools_ArmatureCollisionPanel,
    PT_Hotools_BoneCollisionPanel,
    PT_Hotools_ObjectCollisionPanel,
)
from .collisionPreview import _ensure_draw_handler, _remove_draw_handler
from .collisionProperty import PG_Hotools_BoneCollision, PG_Hotools_ObjectCollision
from .collisionUtils import _overlay_show_update


cls = [
    PG_Hotools_BoneCollision,
    PG_Hotools_ObjectCollision,
    OP_Hotools_BoneCollision_AddSelectedSpringRoots,
    OP_Hotools_BoneCollision_ClearAllSpringRoots,
    OP_Hotools_BoneCollision_SelectSpringRoots,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    PT_Hotools_BoneCollisionPanel,
    PT_Hotools_ObjectCollisionPanel,
    PT_Hotools_ArmatureCollisionPanel,
]


def reg_props():
    if hasattr(bpy.types.Bone, "hotools_collision"):
        del bpy.types.Bone.hotools_collision
    bpy.types.Bone.hotools_collision = PointerProperty(type=PG_Hotools_BoneCollision)

    if hasattr(bpy.types.Object, "hotools_object_collision"):
        del bpy.types.Object.hotools_object_collision
    bpy.types.Object.hotools_object_collision = PointerProperty(type=PG_Hotools_ObjectCollision)

    if hasattr(bpy.types.Scene, "ho_bone_collision_show_overlay_section"):
        del bpy.types.Scene.ho_bone_collision_show_overlay_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_overlay_show"):
        del bpy.types.Scene.ho_bone_collision_overlay_show
    bpy.types.Scene.ho_bone_collision_overlay_show = BoolProperty(
        name="显示HoTools碰撞体",
        description="在3D视图叠加层中显示HoTools骨骼碰撞范围和Spring Root标记",
        default=False,
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_bone_collision_show_info_section = BoolProperty(
        name="信息",
        default=True,
    )
    bpy.types.Scene.ho_bone_collision_show_roots_section = BoolProperty(
        name="活动骨碰撞",
        default=True,
    )


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_bone_collision_show_overlay_section"):
        del bpy.types.Scene.ho_bone_collision_show_overlay_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_show_roots_section"):
        del bpy.types.Scene.ho_bone_collision_show_roots_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_show_info_section"):
        del bpy.types.Scene.ho_bone_collision_show_info_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_overlay_show"):
        del bpy.types.Scene.ho_bone_collision_overlay_show
    if hasattr(bpy.types.Object, "hotools_object_collision"):
        del bpy.types.Object.hotools_object_collision
    if hasattr(bpy.types.Bone, "hotools_collision"):
        del bpy.types.Bone.hotools_collision


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    _ensure_draw_handler()


def unregister():
    _remove_draw_handler()
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
