"""Physics World Blender UI 生命周期。"""

import bpy

from ..blender_registry import register_blender_property_domain, unregister_blender_property_domain
from .collision_preview import (
    PT_Hotools_CollisionOverlayPopover,
    _ensure_draw_handler,
    _remove_draw_handler,
    draw_collision_overlay_header,
)
from .operators import (
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_MeshCollision_CreateBasePoseProxy,
    OP_Hotools_MeshCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
    OP_Hotools_RigidBody_SetCollisionGroup,
    OP_Hotools_RigidBody_ToggleCollidesWithGroup,
)
from .panels import (
    PT_Hotools_Bone_CollisionSubPanel,
    PT_Hotools_Bone_PhysicsPanel,
    PT_Hotools_Physics_MeshCollision,
    PT_Hotools_Physics_ObjectCollision,
    PT_Hotools_Physics_RigidBody,
    PT_Hotools_Physics_RigidConstraint,
    PT_Hotools_PhysicsPanel,
)
from .properties import PHYSICS_UI_BLENDER_PROPERTIES


PHYSICS_UI_CLASSES = (
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_ObjectCollision_SetPrimaryGroup,
    OP_Hotools_RigidBody_SetCollisionGroup,
    OP_Hotools_RigidBody_ToggleCollidesWithGroup,
    OP_Hotools_MeshCollision_CreateBasePoseProxy,
    OP_Hotools_MeshCollision_SetPrimaryGroup,
    OP_Hotools_MeshCollision_ToggleCollidedByGroup,
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    PT_Hotools_CollisionOverlayPopover,
    PT_Hotools_PhysicsPanel,
    PT_Hotools_Physics_ObjectCollision,
    PT_Hotools_Physics_MeshCollision,
    PT_Hotools_Physics_RigidBody,
    PT_Hotools_Physics_RigidConstraint,
    PT_Hotools_Bone_PhysicsPanel,
    PT_Hotools_Bone_CollisionSubPanel,
)

_REGISTERED = False


def register() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    registered_classes = []
    try:
        for cls in PHYSICS_UI_CLASSES:
            bpy.utils.register_class(cls)
            registered_classes.append(cls)
        register_blender_property_domain(
            "physics_ui",
            PHYSICS_UI_BLENDER_PROPERTIES,
            dependencies=("collision", "rigid", "mesh_cloth"),
        )
        _ensure_draw_handler()
        bpy.types.VIEW3D_HT_header.append(draw_collision_overlay_header)
    except Exception:
        unregister_blender_property_domain("physics_ui", force=True)
        _remove_draw_handler()
        for cls in reversed(registered_classes):
            bpy.utils.unregister_class(cls)
        raise
    _REGISTERED = True


def unregister() -> None:
    global _REGISTERED
    if not _REGISTERED:
        return
    try:
        bpy.types.VIEW3D_HT_header.remove(draw_collision_overlay_header)
    except Exception:
        pass
    _remove_draw_handler()
    unregister_blender_property_domain("physics_ui", force=True)
    for cls in reversed(PHYSICS_UI_CLASSES):
        bpy.utils.unregister_class(cls)
    _REGISTERED = False


__all__ = ["PHYSICS_UI_BLENDER_PROPERTIES", "PHYSICS_UI_CLASSES", "register", "unregister"]
