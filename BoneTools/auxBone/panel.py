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
    """Read-only BS corrective audit alongside the auxiliary-bone overview."""
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
    settings = getattr(obj, "hotools_bs_corrective", None)
    rules = getattr(settings, "rules", None) if settings is not None else None
    if settings is None or not settings.enabled:
        box.label(text="BS 修型中控未启用", icon="INFO")
        return
    if not rules:
        box.label(text="暂无修型规则", icon="INFO")
        return
    box.label(text=f"共 {len(rules)} 条规则")
    for index, rule in enumerate(rules):
        row = box.row(align=True)
        row.enabled = bool(rule.enabled)
        target = f" → {rule.mesh.name}/{rule.shape_key or '（未指定形态键）'}" if rule.mesh else ""
        row.label(text=f"{index + 1}. {rule.bone or '（未指定骨骼）'}{target}", icon="SHAPEKEY_DATA")
        detail = box.column(align=True)
        detail.enabled = bool(rule.enabled)
        detail.label(text=f"表达式：{rule.expression or '（空）'}")
        if rule.variables:
            detail.label(text="变量：" + ", ".join(
                f"{item.name}={item.bone}.{item.channel}" for item in rule.variables
            ))
        if rule.comment:
            detail.label(text=f"注释：{rule.comment}")


def draw_constraint_controls(layout):
    row = layout.row(align=True)
    row.operator("ho.disable_aux_bone_constraints", text="禁用辅助骨约束")
    row.operator("ho.enable_aux_bone_constraints", text="启用辅助骨约束")


def draw_type_panels(layout, context):
    from . import boneTwist, boneFan, boneFanSingle, boneFanSide
    for module in (boneTwist, boneFan, boneFanSingle, boneFanSide):
        module.draw_panel(layout, context)

