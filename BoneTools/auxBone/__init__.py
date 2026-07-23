"""Auxiliary bone systems and their panel/registration boundary."""

from . import boneTwist, boneFan, boneFanSingle, boneFanSide
from .panel import draw_overview, draw_constraint_controls, draw_type_panels

_MODULES = (boneTwist, boneFan, boneFanSingle, boneFanSide)


def draw_panel(layout, context):
    draw_overview(layout, context)
    draw_constraint_controls(layout)
    draw_type_panels(layout, context)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    shutdown_previews()
    for module in reversed(_MODULES):
        module.unregister()


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
