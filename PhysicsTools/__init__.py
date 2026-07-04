import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty

from .physicsOperators import (
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_MeshCollision_CreateBasePoseProxy,
    OP_Hotools_MeshCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
)
from .physicsPanel import (
    PT_Hotools_PhysicsPanel,
    PT_Hotools_Physics_ObjectCollision,
    PT_Hotools_Physics_MeshCollision,
    PT_Hotools_Physics_RigidBody,
    PT_Hotools_Physics_RigidConstraint,
    PT_Hotools_Bone_PhysicsPanel,
    PT_Hotools_Bone_CollisionSubPanel,
)
from .collisionPreview import (
    PT_Hotools_CollisionOverlayPopover,
    COLLISION_OVERLAY_PREVIEW_MODE_ITEMS,
    _ensure_draw_handler,
    _remove_draw_handler,
    draw_collision_overlay_header,
)
from .physicsProperty import PG_Hotools_BoneCollision, PG_Hotools_MeshCollision, PG_Hotools_ObjectCollision, PG_Hotools_RigidBody, PG_Hotools_RigidConstraint
from .physicsUtils import _overlay_show_update


cls = [
    PG_Hotools_BoneCollision,
    PG_Hotools_ObjectCollision,
    PG_Hotools_MeshCollision,
    PG_Hotools_RigidBody,
    PG_Hotools_RigidConstraint,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_CreateBasePoseProxy,
    OP_Hotools_MeshCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_ToggleCollidedByGroup,
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    PT_Hotools_CollisionOverlayPopover,
    # 统一物理面板
    PT_Hotools_PhysicsPanel,
    PT_Hotools_Physics_ObjectCollision,
    PT_Hotools_Physics_MeshCollision,
    PT_Hotools_Physics_RigidBody,
    PT_Hotools_Physics_RigidConstraint,
    # Bone 上下文（含原 Armature 辅助操作）
    PT_Hotools_Bone_PhysicsPanel,
    PT_Hotools_Bone_CollisionSubPanel,
]


def reg_props():
    bpy.types.Bone.hotools_collision = PointerProperty(type=PG_Hotools_BoneCollision)

    bpy.types.Object.hotools_object_collision = PointerProperty(type=PG_Hotools_ObjectCollision)

    bpy.types.Object.hotools_mesh_collision = PointerProperty(type=PG_Hotools_MeshCollision)

    bpy.types.Object.hotools_rigid_body = PointerProperty(type=PG_Hotools_RigidBody)

    bpy.types.Object.hotools_rigid_constraint = PointerProperty(type=PG_Hotools_RigidConstraint)

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
    bpy.types.Scene.ho_collision_overlay_only_visible_bones = BoolProperty(
        name="仅显示可见骨",
        description="仅绘制在当前视图层中有效可见的骨骼碰撞体",
        default=False,
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_collision_overlay_preview_mode = EnumProperty(
        name="预览模式",
        description="切换碰撞预览的查看方式",
        items=COLLISION_OVERLAY_PREVIEW_MODE_ITEMS,
        default="STANDARD",
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_collision_overlay_include_passive_collision = BoolProperty(
        name="额外显示简单碰撞",
        description="在碰撞组交互检查模式下，同时显示被该组命中的简单碰撞体",
        default=False,
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
    del bpy.types.Object.hotools_rigid_constraint
    del bpy.types.Object.hotools_rigid_body
    del bpy.types.Scene.ho_bone_collision_show_roots_section
    del bpy.types.Scene.ho_bone_collision_show_info_section
    del bpy.types.Scene.ho_collision_overlay_show_mesh_vertices
    del bpy.types.Scene.ho_collision_overlay_show_object
    del bpy.types.Scene.ho_collision_overlay_color_mode
    del bpy.types.Scene.ho_collision_overlay_preview_mode
    del bpy.types.Scene.ho_collision_overlay_include_passive_collision
    del bpy.types.Scene.ho_collision_overlay_only_visible_bones
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
