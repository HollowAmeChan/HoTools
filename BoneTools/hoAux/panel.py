"""HoAux panel composition and first-phase maintenance operators."""

from collections import Counter

from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from .ir.blender_reader import snapshot_armature
from .ir.writer import to_json
from .name_registry import iter_hoaux_bones
from .operations import scope_bones, scope_is_enabled
from .module_registry import definitions, get_definition
from .transaction import restore_armature_mode


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


class OT_HoAuxGenerateModule(Operator):
    bl_idname = "hoaux.generate_module"
    bl_label = "生成 HoAux 模块"
    bl_options = {"REGISTER", "UNDO"}

    module_type: StringProperty(default="")  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature_object = context.object
        original_mode = armature_object.mode
        try:
            definition = get_definition(self.module_type)
            settings = definition.settings(context.scene)
            settings.preview_enabled = False
            result = definition.generate_from_context(context)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            restore_armature_mode(armature_object, original_mode)
        created_count = len(result["bones"]) + result.get(
            "createdDirCount", int(result["createdDir"])
        )
        self.report({"INFO"}, f"已生成 {created_count} 根 HoAux 骨")
        return {"FINISHED"}


def _group_key(pipeline_id, module_id):
    return f"{pipeline_id}||{module_id}"


def _group_expanded(armature_data, key):
    state = armature_data.hoaux_group_states.get(key)
    return False if state is None else state.expanded


def _selected_bone_names(armature_object):
    if armature_object.mode == "EDIT":
        return {
            bone.name for bone in armature_object.data.edit_bones if bone.select
        }
    return {bone.name for bone in armature_object.data.bones if bone.select}


def _select_bones(armature_object, names, extend):
    names = [name for name in names if name]
    if armature_object.mode == "EDIT":
        bones = armature_object.data.edit_bones
        if not extend:
            for bone in bones:
                bone.select = bone.select_head = bone.select_tail = False
        last = None
        for name in names:
            bone = bones.get(name)
            if bone is not None:
                bone.select = bone.select_head = bone.select_tail = True
                last = bone
        if last is not None:
            bones.active = last
        return

    bones = armature_object.data.bones
    if not extend:
        for bone in bones:
            bone.select = False
    last = None
    for name in names:
        bone = bones.get(name)
        if bone is not None:
            bone.select = True
            last = bone
    if last is not None:
        bones.active = last


class OT_HoAuxGroupToggle(Operator):
    bl_idname = "hoaux.group_toggle"
    bl_label = "展开或折叠 HoAux 模块"
    bl_options = {"REGISTER"}

    key: StringProperty(default="")  # type: ignore

    def execute(self, context):
        states = context.object.data.hoaux_group_states
        state = states.get(self.key)
        if state is None:
            state = states.add()
            state.name = self.key
            state.expanded = True
        else:
            state.expanded = not state.expanded
        return {"FINISHED"}


class OT_HoAuxGroupSelect(Operator):
    bl_idname = "hoaux.group_select"
    bl_label = "选择 HoAux 模块骨骼"
    bl_description = "选择该模块的全部 HoAux 骨；Shift = 加选"
    bl_options = {"REGISTER", "UNDO"}

    pipeline_id: StringProperty(default="")  # type: ignore
    module_id: StringProperty(default="")  # type: ignore
    extend: BoolProperty(default=False)  # type: ignore

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        names = [
            bone.name
            for bone in scope_bones(
                context.object.data, self.pipeline_id, self.module_id
            )
        ]
        _select_bones(context.object, names, self.extend)
        return {"FINISHED"}


class OT_HoAuxBoneSelect(Operator):
    bl_idname = "hoaux.bone_select"
    bl_label = "选择 HoAux 骨"
    bl_description = "选择该 HoAux 骨；Shift = 加选"
    bl_options = {"REGISTER", "UNDO"}

    bone: StringProperty(default="")  # type: ignore
    extend: BoolProperty(default=False)  # type: ignore

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        _select_bones(context.object, [self.bone], self.extend)
        return {"FINISHED"}


CLASSES = (
    OT_HoAuxCopySourceIR,
    OT_HoAuxGenerateModule,
    OT_HoAuxGroupToggle,
    OT_HoAuxGroupSelect,
    OT_HoAuxBoneSelect,
)


def draw_panel(layout, context):
    obj = context.object
    if obj is None or obj.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return

    bones = list(iter_hoaux_bones(obj.data))
    overview = layout.box()
    expanded = context.scene.hoaux_overview_expanded
    header = overview.row(align=True)
    header.prop(
        context.scene,
        "hoaux_overview_expanded",
        text="",
        icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text="HoAux总览", icon="BONE_DATA")
    actions = header.row(align=True)
    actions.alignment = "RIGHT"
    actions.label(text=f"×{len(bones)}")
    actions.operator("hoaux.copy_source_ir", text="", icon="COPYDOWN")
    actions.operator("hoaux.remove_all", text="", icon="TRASH")

    if expanded and bones:
        role_counts = Counter(
            bone.hotools_boneprops.hoAux.roleTag for bone in bones
        )
        row = overview.row(align=True)
        for role in ("DEF", "TRK", "DIR"):
            row.label(text=f"{role} {role_counts.get(role, 0)}")

        grouped = {}
        for bone in bones:
            info = bone.hotools_boneprops.hoAux
            key = (info.pipelineId, info.moduleId)
            grouped.setdefault(key, []).append(bone)
        for (pipeline_id, module_id), group in sorted(grouped.items()):
            box = overview.box()
            key = _group_key(pipeline_id, module_id)
            group_expanded = _group_expanded(obj.data, key)
            group_names = {bone.name for bone in group}
            selected = _selected_bone_names(obj)
            row = box.row(align=True)
            row.alert = bool(group_names & selected)
            toggle = row.operator(
                "hoaux.group_toggle",
                text="",
                icon="TRIA_DOWN" if group_expanded else "TRIA_RIGHT",
                emboss=False,
            )
            toggle.key = key
            select = row.operator(
                "hoaux.group_select",
                text=f"{pipeline_id or '未分配'} / {module_id or '未分配'}",
                emboss=False,
            )
            select.pipeline_id = pipeline_id
            select.module_id = module_id
            controls = row.row(align=True)
            controls.alignment = "RIGHT"
            controls.label(text=f"×{len(group)}")
            if module_id != "INFRASTRUCTURE":
                enabled = scope_is_enabled(obj, pipeline_id, module_id)
                constraint_toggle = controls.operator(
                    "hoaux.toggle_module",
                    text="",
                    icon="CON_TRACKTO" if enabled else "TRACKING_CLEAR_FORWARDS",
                    depress=enabled,
                )
                constraint_toggle.pipeline_id = pipeline_id
                constraint_toggle.module_id = module_id
                remove = controls.operator("hoaux.remove_module", text="", icon="TRASH")
                remove.pipeline_id = pipeline_id
                remove.module_id = module_id
            if group_expanded:
                for bone in sorted(group, key=lambda item: item.name):
                    bone_row = box.row(align=True)
                    bone_row.alert = bone.name in selected
                    pick = bone_row.operator(
                        "hoaux.bone_select",
                        text=bone.name,
                        icon="BONE_DATA",
                        emboss=False,
                    )
                    pick.bone = bone.name

    for definition in definitions():
        definition.draw_panel(layout, context)
