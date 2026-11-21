"""Auxiliary bone systems and their panel/registration boundary."""

import bpy

from . import boneTwist, boneFan, boneFanSingle, boneFanSide, copyRotation
from .panel import draw_overview, draw_constraint_controls, draw_type_panels

_MODULES = (boneTwist, boneFan, boneFanSingle, boneFanSide, copyRotation)


def draw_panel(layout, context):
    draw_overview(layout, context)
    draw_constraint_controls(layout)
    draw_type_panels(layout, context)


def register():
    bpy.types.Scene.ho_aux_overview_expanded = bpy.props.BoolProperty(
        name="辅助骨总览展开",
        default=False,
    )
    bpy.types.Scene.ho_bs_corrective_overview_expanded = bpy.props.BoolProperty(
        name="修型总览展开", default=False,
    )
    for module in _MODULES:
        module.register()


def unregister():
    shutdown_previews()
    for module in reversed(_MODULES):
        module.unregister()
    if hasattr(bpy.types.Scene, "ho_aux_overview_expanded"):
        del bpy.types.Scene.ho_aux_overview_expanded
    if hasattr(bpy.types.Scene, "ho_bs_corrective_overview_expanded"):
        del bpy.types.Scene.ho_bs_corrective_overview_expanded


def shutdown_previews():
    for module in _MODULES:
        preview = next(
            (getattr(module, name, None) for name in (
                "TwistBonePreview", "BoneFanPreview", "BoneFanSinglePreview", "BoneFanSidePreview"
            ) if hasattr(module, name)),
            None,
        )
        if preview is not None:
            preview.shutdown()
