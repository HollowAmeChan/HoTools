"""Ordinary Aux panel entry matching the twist/fan disclosure layout."""


def draw_panel(layout, context):
    settings = context.scene.ho_copyr_settings
    box = layout.box()
    header = box.row(align=True)
    header.prop(settings, "ui_expanded", text="", icon="TRIA_DOWN" if settings.ui_expanded else "TRIA_RIGHT", emboss=False)
    header.label(text="copyR 旋转跟随")
    header.operator("ho.copyr_generate", text="创建／更新")
    if not settings.ui_expanded:
        return
    armature = context.active_object
    if armature is None or armature.type != "ARMATURE":
        box.label(text="请选择骨架中的受约束骨", icon="INFO")
        return
    box.label(text="所选骨为受约束骨，目标由下方指定")
    box.prop_search(settings, "target_bone", armature.data, "bones", text="目标骨")
    box.prop(settings, "influence")
    box.prop(settings, "target_space")
    box.prop(settings, "owner_space")
    box.label(text="替换旋转 · XYZ 全轴")
    box.operator("ho.copyr_remove", text="移除 copyR（保留原骨）", icon="X")
