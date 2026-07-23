"""Panel composition for auxiliary bone tools."""

from .. import boneProperty


def draw_overview(layout, context):
    scene = context.scene
    obj = context.object
    if obj is None or obj.type != "ARMATURE":
        return
    box = layout.box()
    expanded = scene.ho_aux_overview_expanded
    header = box.row(align=True)
    header.prop(scene, "ho_aux_overview_expanded", text="", icon="TRIA_DOWN" if expanded else "TRIA_RIGHT", emboss=False)
    header.label(text="辅助骨总览", icon="BONE_DATA")
    if expanded:
        boneProperty.draw_aux_overview(box, context)


def draw_constraint_controls(layout):
    row = layout.row(align=True)
    row.operator("ho.disable_aux_bone_constraints", text="禁用辅助骨约束")
    row.operator("ho.enable_aux_bone_constraints", text="启用辅助骨约束")


def draw_type_panels(layout, context):
    from . import boneTwist, boneFan, boneFanSingle, boneFanSide
    for module in (boneTwist, boneFan, boneFanSingle, boneFanSide):
        module.draw_panel(layout, context)

