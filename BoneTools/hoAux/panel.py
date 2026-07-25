"""HoAux panel composition and first-phase maintenance operators."""

from collections import Counter
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from .ir.blender_reader import snapshot_armature
from .ir.codec import to_json
from .generation import iter_hoaux_bones, restore_armature_mode
from .operations import scope_bones, scope_is_enabled
from .module_base import (
    definitions,
    get_definition,
    role_name_sets,
    whole_arm_pipeline_definitions,
)
from Utils.bone_selection import select_bones, selected_bone_names


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


def _pipeline_role_names(context):
    root = context.scene.hoaux_settings
    return (
        root.shoulderBone,
        root.upperArmBone,
        root.lowerArmBone,
        root.handBone,
    )


def _pipeline_sides(context):
    return tuple(
        side
        for _names, side in role_name_sets(
            context, *_pipeline_role_names(context)
        )
    )


def _module_generated_sides(armature_data, module_type):
    return {
        bone.hotools_boneprops.hoAux.side
        for bone in iter_hoaux_bones(armature_data)
        if bone.hotools_boneprops.hoAux.moduleType == module_type
    }


class OT_HoAuxGeneratePipeline(Operator):
    bl_idname = "hoaux.generate_pipeline"
    bl_label = "生成整臂流水线"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        from .operations import remove_scope

        armature_object = context.object
        original_mode = armature_object.mode
        generated_types = []
        sides = set()
        missing = []
        created_count = 0
        try:
            sides = set(_pipeline_sides(context))
            for definition in whole_arm_pipeline_definitions():
                present = _module_generated_sides(
                    armature_object.data, definition.type_id
                )
                relevant = present & sides
                if relevant == sides:
                    continue
                if relevant:
                    detail = ", ".join(sorted(relevant))
                    raise ValueError(
                        f"{definition.label} 仅存在部分侧别：{detail}"
                    )
                missing.append(definition)

            for definition in missing:
                definition.build_preview_scene(context)

            root = context.scene.hoaux_settings
            root.pipelinePreviewEnabled = False
            for definition in definitions():
                definition.settings(context.scene).preview_enabled = False

            for definition in missing:
                result = definition.generate_from_context(context)
                generated_types.append(definition.type_id)
                created_count += len(result["bones"]) + result.get(
                    "createdDirCount", int(result["createdDir"])
                )
        except (ValueError, RuntimeError) as exc:
            for module_type in reversed(generated_types):
                for side in sides:
                    remove_scope(
                        armature_object,
                        f"ARM.{side}",
                        f"{module_type}.{side}",
                    )
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            restore_armature_mode(armature_object, original_mode)

        if missing:
            self.report(
                {"INFO"},
                f"已生成 {len(missing)} 段流水线，新增 {created_count} 根 HoAux 骨",
            )
        else:
            self.report({"INFO"}, "整臂流水线已经完整")
        return {"FINISHED"}


class OT_HoAuxRemovePipeline(Operator):
    bl_idname = "hoaux.remove_pipeline"
    bl_label = "删除整臂流水线"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        from .operations import HoAuxRemovalBlockedError, remove_scope

        armature_object = context.object
        original_mode = armature_object.mode
        pipeline_ids = sorted(
            {
                bone.hotools_boneprops.hoAux.pipelineId
                for bone in iter_hoaux_bones(armature_object.data)
                if bone.hotools_boneprops.hoAux.pipelineId.startswith("ARM.")
            }
        )
        removed_count = 0
        try:
            for pipeline_id in pipeline_ids:
                removed_count += remove_scope(
                    armature_object, pipeline_id=pipeline_id
                )["bones"]
        except HoAuxRemovalBlockedError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            restore_armature_mode(armature_object, original_mode)
        self.report({"INFO"}, f"已删除 {removed_count} 根整臂 HoAux 骨")
        return {"FINISHED"}


def _group_key(pipeline_id, module_id):
    return f"{pipeline_id}||{module_id}"


def _group_expanded(armature_data, key):
    state = armature_data.hoaux_group_states.get(key)
    return False if state is None else state.expanded


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
        select_bones(context.object, names, extend=self.extend)
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
        select_bones(context.object, [self.bone], extend=self.extend)
        return {"FINISHED"}


CLASSES = (
    OT_HoAuxCopySourceIR,
    OT_HoAuxGenerateModule,
    OT_HoAuxGeneratePipeline,
    OT_HoAuxRemovePipeline,
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
            selected = set(selected_bone_names(context, obj))
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

    root = context.scene.hoaux_settings
    pipeline = layout.box()
    pipeline_header = pipeline.row(align=True)
    pipeline_header.prop(
        root,
        "pipelineExpanded",
        text="",
        icon="TRIA_DOWN" if root.pipelineExpanded else "TRIA_RIGHT",
        emboss=False,
    )
    pipeline_header.label(text="整臂流水线", icon="ARMATURE_DATA")
    pipeline_header.operator("hoaux.generate_pipeline", text="生成全部", icon="PLAY")
    pipeline_preview = pipeline_header.row(align=True)
    pipeline_preview.alert = root.pipelinePreviewEnabled
    pipeline_preview.prop(
        root,
        "pipelinePreviewEnabled",
        text="",
        icon="HIDE_OFF" if root.pipelinePreviewEnabled else "HIDE_ON",
    )
    pipeline_header.operator("hoaux.remove_pipeline", text="", icon="TRASH")
    if root.pipelineExpanded:
        roles = pipeline.column(align=True)
        for property_name, label in (
            ("shoulderBone", "肩骨"),
            ("upperArmBone", "大臂骨"),
            ("lowerArmBone", "小臂骨"),
            ("handBone", "手骨"),
        ):
            roles.prop_search(root, property_name, obj.data, "bones", text=label)
        roles.prop(root, "processSymmetry")
        module_types = {
            bone.hotools_boneprops.hoAux.moduleType for bone in bones
        }
        for definition in whole_arm_pipeline_definitions():
            row = pipeline.row(align=True)
            row.label(
                text=definition.label,
                icon=(
                    "CHECKMARK"
                    if definition.type_id in module_types
                    else "RADIOBUT_OFF"
                ),
            )

    for definition in definitions():
        definition.draw_panel(layout, context)
