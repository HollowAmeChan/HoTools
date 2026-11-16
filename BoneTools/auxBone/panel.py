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


def draw_bs_overview(layout, context):
    """Shared BS corrective authoring menu alongside the auxiliary-bone overview."""
    scene = context.scene
    obj = context.object
    if obj is None or obj.type != "ARMATURE":
        return
    box = layout.box()
    expanded = scene.ho_bs_corrective_overview_expanded
    header = box.row(align=True)
    header.prop(scene, "ho_bs_corrective_overview_expanded", text="", emboss=False,
                icon="TRIA_DOWN" if expanded else "TRIA_RIGHT")
    header.label(text="修型总览", icon="SHAPEKEY_DATA")
    if not expanded:
        return
    from ...Rbf.bs_corrective import draw_bs_corrective_menu
    draw_bs_corrective_menu(box, context)


def draw_constraint_controls(layout):
    row = layout.row(align=True)
    row.operator("ho.disable_aux_bone_constraints", text="禁用辅助骨约束")
    row.operator("ho.enable_aux_bone_constraints", text="启用辅助骨约束")


def draw_type_panels(layout, context):
    from . import boneTwist, boneFan, boneFanSingle, boneFanSide
    for module in (boneTwist, boneFan, boneFanSingle, boneFanSide):
        module.draw_panel(layout, context)

