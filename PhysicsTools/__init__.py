import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty

from .collisionOperators import (
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_AddSelectedSpringRoots,
    OP_Hotools_BoneCollision_ClearAllSpringRoots,
    OP_Hotools_BoneCollision_GradientRadius,
    OP_Hotools_BoneCollision_SelectSpringRoots,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_MeshCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
)
from .collisionPanel import (
    PT_Hotools_ArmatureCollisionPanel,
    PT_Hotools_BoneCollisionPanel,
    PT_Hotools_MeshCollisionPanel,
    PT_Hotools_ObjectCollisionPanel,
)
from .collisionPreview import (
    PT_Hotools_CollisionOverlayPopover,
    _ensure_draw_handler,
    _remove_draw_handler,
    draw_collision_overlay_header,
)
from .collisionProperty import PG_Hotools_BoneCollision, PG_Hotools_MeshCollision, PG_Hotools_ObjectCollision
from .collisionUtils import _overlay_show_update


cls = [
    PG_Hotools_BoneCollision,
    PG_Hotools_ObjectCollision,
    PG_Hotools_MeshCollision,
    OP_Hotools_BoneCollision_AddSelectedSpringRoots,
    OP_Hotools_BoneCollision_ClearAllSpringRoots,
    OP_Hotools_BoneCollision_SelectSpringRoots,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_ToggleCollidedByGroup,
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    PT_Hotools_BoneCollisionPanel,
    PT_Hotools_ObjectCollisionPanel,
    PT_Hotools_MeshCollisionPanel,
    PT_Hotools_ArmatureCollisionPanel,
    PT_Hotools_CollisionOverlayPopover,
]


def reg_props():
    bpy.types.Bone.hotools_collision = PointerProperty(type=PG_Hotools_BoneCollision)

    bpy.types.Object.hotools_object_collision = PointerProperty(type=PG_Hotools_ObjectCollision)

    bpy.types.Object.hotools_mesh_collision = PointerProperty(type=PG_Hotools_MeshCollision)

    bpy.types.Scene.ho_collision_overlay_show = BoolProperty(
        name="HoTools碰撞预览",
        description="在3D视图中显示HoTools碰撞预览叠加层",
        default=False,
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_collision_overlay_show_bone = BoolProperty(
        name="骨骼碰撞体",
        default=True,
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_collision_overlay_color_mode = EnumProperty(
        name="颜色模式",
        description="切换碰撞叠加层的颜色含义",
        items=[
            ("GROUP", "主碰撞组", "按主碰撞组显示颜色"),
            ("PIN", "Pin状态", "按是否固定显示颜色"),
        ],
        default="GROUP",
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_collision_overlay_show_object = BoolProperty(
        name="物体碰撞体",
        default=True,
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_collision_overlay_show_mesh_vertices = BoolProperty(
        name="网格逐顶点球",
        description="显示网格XPBD逐顶点碰撞球；复杂网格上会增加视图绘制开销",
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
    del bpy.types.Scene.ho_bone_collision_show_roots_section
    del bpy.types.Scene.ho_bone_collision_show_info_section
    del bpy.types.Scene.ho_collision_overlay_show_mesh_vertices
    del bpy.types.Scene.ho_collision_overlay_show_object
    del bpy.types.Scene.ho_collision_overlay_color_mode
    del bpy.types.Scene.ho_collision_overlay_show_bone
    del bpy.types.Scene.ho_collision_overlay_show
    del bpy.types.Object.hotools_object_collision
    del bpy.types.Object.hotools_mesh_collision
    del bpy.types.Bone.hotools_collision


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    _ensure_draw_handler()
    bpy.types.VIEW3D_HT_header.append(draw_collision_overlay_header)


def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_collision_overlay_header)
    _remove_draw_handler()
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
