"""HoAux panel composition and first-phase maintenance operators."""

from collections import Counter

from bpy.types import Operator

from .collection_registry import assign_all
from .ir.blender_reader import snapshot_armature
from .ir.writer import to_json
from .name_registry import iter_hoaux_bones
from .operations import scope_is_enabled


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


CLASSES = (OT_HoAuxEnsureCollections, OT_HoAuxCopySourceIR)


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

    if not bones:
        return

    role_counts = Counter(
        bone.hotools_boneprops.hoAux.roleTag for bone in bones
    )
    row = layout.row(align=True)
    for role in ("DEF", "TRK", "DIR"):
        row.label(text=f"{role} {role_counts.get(role, 0)}")

    grouped = {}
    for bone in bones:
        info = bone.hotools_boneprops.hoAux
        key = (info.pipelineId, info.moduleId)
        grouped.setdefault(key, []).append(bone)
    for (pipeline_id, module_id), group in sorted(grouped.items()):
        box = layout.box()
        row = box.row(align=True)
        row.label(text=f"{pipeline_id or 'UNASSIGNED'} / {module_id or 'UNASSIGNED'}")
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
            info = bone.hotools_boneprops.hoAux
            box.label(text=bone.name, icon="BONE_DATA")
