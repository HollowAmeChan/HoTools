"""HoAux panel composition and first-phase maintenance operators."""

from collections import Counter

from bpy.types import Operator

from .collection_registry import assign_all
from .ir.blender_reader import snapshot_armature
from .ir.writer import to_json
from .name_registry import iter_hoaux_bones
from .operations import scope_is_enabled
from .modules import shoulder_volume
from .preview import ShoulderVolumePreview


class OT_HoAuxEnsureCollections(Operator):
    bl_idname = "hoaux.ensure_collections"
    bl_label = "整理 HoAux 集合"
    bl_description = "为当前 HoAux 骨追加模块和过滤集合，不移除已有集合"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        count = assign_all(context.object.data)
        self.report({"INFO"}, f"已整理 {count} 根 HoAux 骨")
        return {"FINISHED"}


class OT_HoAuxCopySourceIR(Operator):
    bl_idname = "hoaux.copy_source_ir"
    bl_label = "复制 HoAux Source IR"
    bl_description = "按当前 Blender 状态生成 Source IR 并复制到剪贴板"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        source_ir = snapshot_armature(context.object)
        context.window_manager.clipboard = to_json(source_ir)
        self.report({"INFO"}, f"已复制 {len(source_ir.resources)} 条资源")
        return {"FINISHED"}


class OT_HoAuxGenerateShoulderVolume(Operator):
    bl_idname = "hoaux.generate_shoulder_volume"
    bl_label = "生成 Shoulder Volume"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        settings = context.scene.hoaux_settings
        ShoulderVolumePreview.clear()
        try:
            parameters = shoulder_volume.parameters_from_settings(settings)
            result = shoulder_volume.generate(
                context.object,
                settings.shoulderBone,
                settings.upperArmBone,
                settings.side,
                parameters,
            )
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        created_count = len(result["bones"]) + int(result["createdDir"])
        self.report({"INFO"}, f"已生成 {created_count} 根 HoAux 骨")
        return {"FINISHED"}


class OT_HoAuxPreviewShoulderVolume(Operator):
    bl_idname = "hoaux.preview_shoulder_volume"
    bl_label = "预览 Shoulder Volume"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        if ShoulderVolumePreview.is_visible():
            ShoulderVolumePreview.clear()
            return {"FINISHED"}
        try:
            ShoulderVolumePreview.show(context)
        except (KeyError, TypeError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (
    OT_HoAuxEnsureCollections,
    OT_HoAuxCopySourceIR,
    OT_HoAuxGenerateShoulderVolume,
    OT_HoAuxPreviewShoulderVolume,
)


def draw_panel(layout, context):
    obj = context.object
    if obj is None or obj.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return

    bones = list(iter_hoaux_bones(obj.data))
    header = layout.row(align=True)
    header.label(text=f"HoAux  {len(bones)}", icon="ARMATURE_DATA")
    header.operator("hoaux.ensure_collections", text="", icon="OUTLINER_COLLECTION")
    header.operator("hoaux.copy_source_ir", text="", icon="COPYDOWN")
    header.operator("hoaux.remove_all", text="", icon="TRASH")

    if bones:
        role_counts = Counter(
            bone.hotools_boneprops.hoAux.roleTag for bone in bones
        )
        row = layout.row(align=True)
        for role in ("DEF", "TRK", "DIR"):
            row.label(text=f"{role} {role_counts.get(role, 0)}")

    if bones:
        grouped = {}
        for bone in bones:
            info = bone.hotools_boneprops.hoAux
            key = (info.pipelineId, info.moduleId)
            grouped.setdefault(key, []).append(bone)
        for (pipeline_id, module_id), group in sorted(grouped.items()):
            box = layout.box()
            row = box.row(align=True)
            row.label(text=f"{pipeline_id or 'UNASSIGNED'} / {module_id or 'UNASSIGNED'}")
            if module_id != "INFRASTRUCTURE":
                toggle = row.operator(
                    "hoaux.toggle_module",
                    text="",
                    icon="HIDE_OFF" if scope_is_enabled(obj, pipeline_id, module_id) else "HIDE_ON",
                )
                toggle.pipeline_id = pipeline_id
                toggle.module_id = module_id
                remove = row.operator("hoaux.remove_module", text="", icon="TRASH")
                remove.pipeline_id = pipeline_id
                remove.module_id = module_id
            for bone in group:
                box.label(text=bone.name, icon="BONE_DATA")

    settings = context.scene.hoaux_settings
    box = layout.box()
    box.label(text="Shoulder Volume")
    box.prop(settings, "side", expand=True)
    box.prop_search(settings, "shoulderBone", obj.data, "bones", text="Shoulder")
    box.prop_search(settings, "upperArmBone", obj.data, "bones", text="UpperArm")
    row = box.row(align=True)
    row.prop(settings, "shoulderTrackLength")
    row.prop(settings, "shoulderDefLength")
    disclosure = box.row(align=True)
    disclosure.prop(
        settings,
        "showShoulderParameters",
        text="Parameters",
        icon="TRIA_DOWN" if settings.showShoulderParameters else "TRIA_RIGHT",
        emboss=False,
    )
    if settings.showShoulderParameters:
        column = box.column(align=True)
        row = column.row(align=True)
        row.prop(settings, "shoulderDirLength")
        row.prop(settings, "shoulderHalfInfluence")
        row = column.row(align=True)
        row.prop(settings, "shoulderResponseAngle")
        row.prop(settings, "shoulderHeadTail")
        row = column.row(align=True)
        row.prop(settings, "shoulderConvexAxis")
        row.prop(settings, "shoulderRollFollow")
        row = column.row(align=True)
        row.prop(settings, "shoulderTwistOffset")
        row.prop(settings, "shoulderStraightThreshold")
        column.prop(settings, "shoulderX0Angle")
        row = column.row(align=True)
        row.prop(settings, "shoulderX1Scale")
        row.prop(settings, "shoulderX0Scale")
        row = column.row(align=True)
        row.prop(settings, "shoulderZ1Scale")
        row.prop(settings, "shoulderZ0Scale")
    row = box.row(align=True)
    row.operator(
        "hoaux.preview_shoulder_volume",
        icon="HIDE_OFF" if ShoulderVolumePreview.is_visible() else "HIDE_ON",
    )
    row.operator("hoaux.generate_shoulder_volume", icon="BONE_DATA")
