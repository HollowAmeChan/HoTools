"""HoTools BS corrective authoring, native drivers, and HoFBX metadata."""
import json
import re
import uuid

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from .bs_corrective_expression import parse


CHANNELS = (("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""))
SCHEMA = "hotools.bs-corrective"
VERSION = 1


class PG_BsCorrectiveVariable(PropertyGroup):
    name: StringProperty(default="other_x")  # type: ignore
    bone: StringProperty(name="骨骼", default="")  # type: ignore
    channel: EnumProperty(name="通道", items=CHANNELS, default="X")  # type: ignore


class PG_BsCorrectiveTarget(PropertyGroup):
    """One mesh/shape-key output owned by a corrective rule."""
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object)  # type: ignore
    shape_key: StringProperty(name="目标形态键", default="")  # type: ignore


class PG_BsCorrectiveRule(PropertyGroup):
    id: StringProperty(default="")  # type: ignore
    enabled: BoolProperty(default=True)  # type: ignore
    bone: StringProperty(name="测量骨骼", default="")  # type: ignore
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object)  # type: ignore
    shape_key: StringProperty(name="目标形态键", default="")  # type: ignore
    targets: CollectionProperty(type=PG_BsCorrectiveTarget)  # type: ignore
    expression: StringProperty(default="clamp(x / 1.57079632679, 0, 1)")  # type: ignore
    comment: StringProperty(default="")  # type: ignore
    bs_name: StringProperty(name="BS 名称", default="_BSC_pose1")  # type: ignore
    variables: CollectionProperty(type=PG_BsCorrectiveVariable)  # type: ignore
    expanded: BoolProperty(default=True)  # type: ignore


class PG_BsCorrectiveSettings(PropertyGroup):
    enabled: BoolProperty(name="启用 BS 修型", default=True)  # type: ignore
    rules: CollectionProperty(type=PG_BsCorrectiveRule)  # type: ignore
    active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore
    targets_active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore


def settings_for(armature):
    return getattr(armature, "hotools_bs_corrective", None)


def _find_bone(armature, name):
    return armature.data.bones.get(name) if armature and name else None


def _shape_names(mesh):
    keys = getattr(getattr(mesh, "data", None), "shape_keys", None)
    return [key.name for key in keys.key_blocks] if keys else []


def _rule_targets(rule):
    """Return the new target list, migrating the legacy single target in memory."""
    if getattr(rule, "targets", None):
        return list(rule.targets)
    return [rule] if getattr(rule, "mesh", None) is not None else []


def _validate_rule(armature, rule):
    if not rule.bone or _find_bone(armature, rule.bone) is None:
        raise ValueError(f"测量骨骼不存在：{rule.bone}")
    targets = _rule_targets(rule)
    if not targets:
        raise ValueError("至少指定一个目标网格")
    for target in targets:
        if target.mesh is None or target.mesh.type != "MESH":
            raise ValueError("目标网格必须是 Mesh 对象")
        if target.shape_key not in _shape_names(target.mesh):
            raise ValueError(f"找不到形态键：{target.shape_key}")
    names = []
    for variable in rule.variables:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", variable.name or ""):
            raise ValueError(f"变量名无效：{variable.name}")
        if variable.name in names or variable.name in {"x", "y", "z", "pi"}:
            raise ValueError(f"变量名重复或保留：{variable.name}")
        if _find_bone(armature, variable.bone) is None:
            raise ValueError(f"变量骨骼不存在：{variable.bone}")
        names.append(variable.name)
    parse(rule.expression, names)


def build_export_config(armature, fbx_bone_axes="Y_X", measurement_bones=None):
    """Return a JSON-ready config; this is deliberately side-effect free."""
    settings = settings_for(armature)
    if settings is None or not settings.enabled:
        return None
    result = {
        "schema": SCHEMA,
        "version": VERSION,
        "rotationOrder": "XYZ",
        "angleUnit": "radian",
        "rotationSpace": "LOCAL",
        "fbxBoneAxes": fbx_bone_axes,
        "measurement": "source_local_rotation",
        "rules": [],
    }
    for rule in settings.rules:
        _validate_rule(armature, rule)
        if not rule.id:
            rule.id = uuid.uuid4().hex
        # MCH is the export-time stable cache for a source bone whose authored
        # rest rotation is cleared by HoFBX.  The authored rule remains keyed by
        # the source name, while Unity reads the actual exported cache bone.
        measurement_bone = (measurement_bones or {}).get(rule.bone, rule.bone)
        targets = _rule_targets(rule)
        entry = {
            "id": rule.id,
            "enabled": bool(rule.enabled),
            "armatureName": armature.name,
            "bone": rule.bone,
            "measurementBone": measurement_bone,
            "mesh": targets[0].mesh.name,
            "shapeKey": targets[0].shape_key,
            "bsName": rule.bs_name,
            "targets": [{"mesh": target.mesh.name, "shapeKey": target.shape_key} for target in targets],
            "expression": rule.expression,
            "comment": rule.comment,
            "variables": [
                {
                    "name": item.name,
                    "bone": (measurement_bones or {}).get(item.bone, item.bone),
                    "channel": item.channel,
                }
                for item in rule.variables
            ],
        }
        result["rules"].append(entry)
    return result


def _set_transform_variable(driver, name, armature, bone_name, channel):
    variable = driver.variables.new()
    variable.name = name
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = armature
    target.bone_target = bone_name
    target.transform_type = "ROT_" + channel
    target.transform_space = "LOCAL_SPACE"


def generate_native_drivers(armature):
    """Create Blender Transform Channel drivers for all enabled authored rules."""
    settings = settings_for(armature)
    if settings is None or not settings.enabled:
        return 0
    remove_native_drivers(armature)
    generated = 0
    for rule in settings.rules:
        if not rule.enabled:
            continue
        _validate_rule(armature, rule)
        targets = _rule_targets(rule)
        for target_rule in targets:
            shape_keys = target_rule.mesh.data.shape_keys
            key = shape_keys.key_blocks.get(target_rule.shape_key) if shape_keys else None
            if key is None:
                continue
            # Drivers cannot carry ID properties in Blender 4.5; use their group as
            # an ownership marker so refresh/remove never touches authored drivers.
            fcurve = key.driver_add("value")
            animation_data = key.id_data.animation_data_create()
            action = animation_data.action
            if action is None:
                action = bpy.data.actions.new(key.id_data.name + "_HoToolsBS")
                animation_data.action = action
            group_name = "HoToolsBS:" + rule.id
            group = action.groups.get(group_name) or action.groups.new(group_name)
            fcurve.group = group
            driver = fcurve.driver
            driver.type = "SCRIPTED"
            names = [item.name for item in rule.variables]
            driver.expression = parse(rule.expression, names)
            source = rule.bone
            for channel in "XYZ":
                _set_transform_variable(driver, channel.lower(), armature, source, channel)
            for item in rule.variables:
                _set_transform_variable(driver, item.name, armature, item.bone, item.channel)
            generated += 1
    return generated


def remove_native_drivers(armature):
    """Remove only drivers generated by this controller, preserving user drivers."""
    settings = settings_for(armature)
    if settings is None:
        return 0
    removed = 0
    for rule in settings.rules:
        for target in _rule_targets(rule):
            if target.mesh is None or target.mesh.data.shape_keys is None:
                continue
            key = target.mesh.data.shape_keys.key_blocks.get(target.shape_key)
            if key is None or key.id_data.animation_data is None:
                continue
            for fcurve in list(key.id_data.animation_data.drivers):
                if (fcurve.data_path == f'key_blocks["{key.name}"].value' and
                        fcurve.group is not None and fcurve.group.name == "HoToolsBS:" + rule.id):
                    key.id_data.driver_remove(fcurve.data_path, fcurve.array_index)
                    removed += 1
    return removed


def _collect_generated_targets(armature, overwrite=True):
    """Validate reset names and return the target/name pairs to create."""
    settings = settings_for(armature)
    if settings is None:
        return []
    requested = set()
    requested_targets = set()
    targets = []
    for rule in settings.rules:
        name = (rule.bs_name or "").strip()
        if not name:
            raise ValueError("BS 名称不能为空")
        if name in requested:
            raise ValueError(f"规则 BS 名称冲突：{name}")
        requested.add(name)
        for target in _rule_targets(rule):
            if target.mesh is None or target.mesh.type != "MESH":
                raise ValueError("目标网格必须是 Mesh 对象")
            target_id = (target.mesh.as_pointer(), name)
            if target_id in requested_targets:
                raise ValueError(f"目标 BS 重复：{target.mesh.name}/{name}")
            requested_targets.add(target_id)
            targets.append((target, name))
    return targets


def _prepare_generated_shape_keys(armature, overwrite=True):
    """Create each rule's named output key before attaching native drivers."""
    targets = _collect_generated_targets(armature, overwrite)
    for target, name in targets:
        shape_keys = target.mesh.data.shape_keys
        existing = shape_keys.key_blocks.get(name) if shape_keys else None
        if existing is not None:
            if not overwrite:
                raise ValueError(f"已存在形态键：{target.mesh.name}/{name}")
            if existing.name == "Basis":
                raise ValueError(f"不能覆盖 Basis 形态键：{target.mesh.name}")
    for target, name in targets:
        shape_keys = target.mesh.data.shape_keys
        existing = shape_keys.key_blocks.get(name) if shape_keys else None
        if existing is not None:
            shape_keys.key_blocks.remove(existing)
        if target.mesh.data.shape_keys is None:
            target.mesh.shape_key_add(name="Basis", from_mix=False)
        target.mesh.shape_key_add(name=name, from_mix=False)
        target.shape_key = name
    return len(targets)


class OP_BsCorrectiveAdd(Operator):
    bl_idname = "hotools.bs_corrective_add"
    bl_label = "添加 BS 修型规则"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context):
        settings = settings_for(context.object)
        rule = settings.rules.add()
        rule.id = uuid.uuid4().hex
        used = {item.bs_name for item in settings.rules[:-1] if item.bs_name}
        index = 1
        while f"_BSC_pose{index}" in used:
            index += 1
        rule.bs_name = f"_BSC_pose{index}"
        settings.active_index = len(settings.rules) - 1
        return {"FINISHED"}


class OP_BsCorrectiveRemove(Operator):
    bl_idname = "hotools.bs_corrective_remove"
    bl_label = "删除 BS 修型规则"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = settings_for(context.object) if context.object else None
        return settings is not None and len(settings.rules) > 0

    def execute(self, context):
        settings = settings_for(context.object)
        index = min(settings.active_index, len(settings.rules) - 1)
        settings.rules.remove(index)
        settings.active_index = max(0, index - 1)
        return {"FINISHED"}


class OP_BsCorrectiveClearRules(Operator):
    bl_idname = "hotools.bs_corrective_clear_rules"
    bl_label = "清空规则"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = settings_for(context.object) if context.object else None
        return settings is not None and len(settings.rules) > 0

    def execute(self, context):
        settings_for(context.object).rules.clear()
        settings_for(context.object).active_index = 0
        return {"FINISHED"}


class OP_BsCorrectiveToggleRule(Operator):
    bl_idname = "hotools.bs_corrective_toggle_rule"
    bl_label = "启用/禁用规则"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=0, min=0)  # type: ignore

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or self.index >= len(settings.rules):
            return {"CANCELLED"}
        settings.rules[self.index].enabled = not settings.rules[self.index].enabled
        settings.active_index = self.index
        return {"FINISHED"}


class OP_BsCorrectiveMoveRule(Operator):
    bl_idname = "hotools.bs_corrective_move_rule"
    bl_label = "移动规则"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=0, min=0)  # type: ignore
    direction: bpy.props.IntProperty(default=1)  # type: ignore

    def execute(self, context):
        settings = settings_for(context.object)
        target = self.index + self.direction
        if settings is None or self.index >= len(settings.rules) or not 0 <= target < len(settings.rules):
            return {"CANCELLED"}
        settings.rules.move(self.index, target)
        settings.active_index = target
        return {"FINISHED"}


class OP_BsCorrectiveToggleExpanded(Operator):
    bl_idname = "hotools.bs_corrective_toggle_expanded"
    bl_label = "折叠/展开规则"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=0, min=0)  # type: ignore

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or self.index >= len(settings.rules):
            return {"CANCELLED"}
        settings.rules[self.index].expanded = not settings.rules[self.index].expanded
        settings.active_index = self.index
        return {"FINISHED"}


class OP_BsCorrectiveAddTarget(Operator):
    bl_idname = "hotools.bs_corrective_add_target"
    bl_label = "添加目标"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or not settings.rules:
            return {"CANCELLED"}
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        targets = _rule_targets(rule)
        if not rule.targets and targets:
            legacy = rule.targets.add()
            legacy.mesh, legacy.shape_key = targets[0].mesh, targets[0].shape_key
        rule.targets.add()
        settings.targets_active_index = len(rule.targets) - 1
        return {"FINISHED"}


class OP_BsCorrectiveRemoveTarget(Operator):
    bl_idname = "hotools.bs_corrective_remove_target"
    bl_label = "删除目标"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1, min=-1)  # type: ignore

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or not settings.rules:
            return {"CANCELLED"}
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        if not rule.targets:
            rule.mesh = None; rule.shape_key = ""
            return {"FINISHED"}
        index = self.index if self.index >= 0 else min(settings.targets_active_index, len(rule.targets) - 1)
        if index < 0 or index >= len(rule.targets):
            return {"CANCELLED"}
        rule.targets.remove(index)
        if not rule.targets:
            rule.mesh = None
            rule.shape_key = ""
        settings.targets_active_index = max(0, index - 1)
        return {"FINISHED"}


class OP_BsCorrectiveClearTargets(Operator):
    bl_idname = "hotools.bs_corrective_clear_targets"
    bl_label = "清空目标"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or not settings.rules:
            return {"CANCELLED"}
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        rule.targets.clear()
        rule.mesh = None; rule.shape_key = ""
        settings.targets_active_index = 0
        return {"FINISHED"}


class OP_BsCorrectiveMoveTarget(Operator):
    bl_idname = "hotools.bs_corrective_move_target"
    bl_label = "移动目标"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=0, min=0)  # type: ignore
    direction: bpy.props.IntProperty(default=1)  # type: ignore

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or not settings.rules:
            return {"CANCELLED"}
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        index = self.index
        target = index + self.direction
        if not 0 <= index < len(rule.targets) or not 0 <= target < len(rule.targets):
            return {"CANCELLED"}
        rule.targets.move(index, target)
        settings.targets_active_index = target
        return {"FINISHED"}


class OP_BsCorrectiveGenerateDrivers(Operator):
    bl_idname = "hotools.bs_corrective_generate_drivers"
    bl_label = "生成 Blender 驱动器"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context):
        try:
            count = generate_native_drivers(context.object)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已生成 {count} 条 Blender BS 驱动器")
        return {"FINISHED"}


class OP_BsCorrectiveReset(Operator):
    bl_idname = "hotools.bs_corrective_reset"
    bl_label = "重置并生成 BS"
    bl_options = {"REGISTER", "UNDO"}
    overwrite_existing: BoolProperty(name="覆盖同名形态键", default=True)  # type: ignore

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            # Preflight before removing drivers so a rejected reset is side-effect free.
            _collect_generated_targets(context.object, self.overwrite_existing)
            # Remove drivers while rules still point at their previous keys. This
            # prevents stale HoTools drivers when a reset changes the BS name.
            remove_native_drivers(context.object)
            _prepare_generated_shape_keys(context.object, self.overwrite_existing)
            count = generate_native_drivers(context.object)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已重置并生成 {count} 条 Blender BS 驱动器")
        return {"FINISHED"}


class OP_BsCorrectiveRemoveDrivers(Operator):
    bl_idname = "hotools.bs_corrective_remove_drivers"
    bl_label = "移除本工具驱动器"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context):
        count = remove_native_drivers(context.object)
        self.report({"INFO"}, f"已移除 {count} 条本工具 Blender 驱动器")
        return {"FINISHED"}


def draw_bs_corrective_menu(layout, context):
    """Shared two-pane authoring menu used by Properties and the N-panel."""
    armature = context.object
    if armature is None or armature.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return
    settings = settings_for(armature)
    row = layout.row(align=True)
    row.operator(OP_BsCorrectiveReset.bl_idname, text="重置", icon="FILE_REFRESH")
    row.operator(OP_BsCorrectiveGenerateDrivers.bl_idname, text="刷新驱动器", icon="FILE_REFRESH")
    row.operator(OP_BsCorrectiveRemoveDrivers.bl_idname, text="移除驱动器", icon="X")
    if not settings.rules:
        layout.label(text="暂无规则；导出不会生成 BS 元数据", icon="INFO")
        return
    split = layout.split(factor=0.30)
    left, right = split.column(), split.column()
    controls = left.column(align=True)
    controls.operator(OP_BsCorrectiveAdd.bl_idname, icon="ADD", text="添加")
    controls.operator(OP_BsCorrectiveRemove.bl_idname, icon="REMOVE", text="删除")
    controls.operator(OP_BsCorrectiveClearRules.bl_idname, icon="TRASH", text="清空")
    left.separator()
    for index, rule in enumerate(settings.rules):
        row = left.row(align=True)
        row.alert = index == settings.active_index
        fold = row.operator(OP_BsCorrectiveToggleExpanded.bl_idname, text="",
                            icon="TRIA_DOWN" if rule.expanded else "TRIA_RIGHT")
        fold.index = index
        toggle = row.operator(OP_BsCorrectiveToggleRule.bl_idname, text="", icon="CHECKMARK" if rule.enabled else "X")
        toggle.index = index
        pick = row.operator("hotools.bs_corrective_select_rule", text=f"{index + 1}. {rule.bone or '未指定骨骼'}", emboss=False)
        pick.index = index
        up = row.operator(OP_BsCorrectiveMoveRule.bl_idname, text="", icon="TRIA_UP")
        up.index, up.direction = index, -1
        down = row.operator(OP_BsCorrectiveMoveRule.bl_idname, text="", icon="TRIA_DOWN")
        down.index, down.direction = index, 1
    if not settings.rules:
        left.label(text="暂无规则", icon="INFO")
        return
    rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
    detail = right.box()
    detail.prop(rule, "expanded", text="", icon="TRIA_DOWN" if rule.expanded else "TRIA_RIGHT", emboss=False)
    if not rule.expanded:
        detail.label(text=f"规则 {settings.active_index + 1} 已折叠")
        return
    detail.prop(rule, "enabled", text="启用规则")
    detail.prop_search(rule, "bone", armature.data, "bones", text="测量骨骼")
    detail.prop(rule, "expression", text="表达式")
    detail.prop(rule, "comment", text="注释")
    detail.prop(rule, "bs_name", text="BS 名称")
    target_box = detail.box()
    header = target_box.row(align=True)
    header.label(text="目标形态键", icon="SHAPEKEY_DATA")
    header.operator(OP_BsCorrectiveAddTarget.bl_idname, text="", icon="ADD")
    header.operator(OP_BsCorrectiveRemoveTarget.bl_idname, text="", icon="REMOVE")
    header.operator(OP_BsCorrectiveClearTargets.bl_idname, text="", icon="TRASH")
    target_items = list(rule.targets) if rule.targets else []
    if not target_items and rule.mesh is not None:
        target_items = [rule]
    for target_index, target in enumerate(target_items):
        row = target_box.row(align=True)
        row.prop(target, "mesh", text="")
        if target.mesh is not None and target.mesh.data.shape_keys:
            row.prop_search(target, "shape_key", target.mesh.data.shape_keys, "key_blocks", text="")
        else:
            row.prop(target, "shape_key", text="")
        if rule.targets:
            remove = row.operator(OP_BsCorrectiveRemoveTarget.bl_idname, text="", icon="X")
            remove.index = target_index
            up = row.operator(OP_BsCorrectiveMoveTarget.bl_idname, text="", icon="TRIA_UP")
            up.index, up.direction = target_index, -1
            down = row.operator(OP_BsCorrectiveMoveTarget.bl_idname, text="", icon="TRIA_DOWN")
            down.index, down.direction = target_index, 1
    var_box = detail.box()
    var_box.label(text="附加骨骼变量")
    for variable in rule.variables:
        row = var_box.row(align=True)
        row.prop(variable, "name", text="")
        row.prop_search(variable, "bone", armature.data, "bones", text="")
        row.prop(variable, "channel", text="")


def draw_bs_corrective_panel(layout, context):
    draw_bs_corrective_menu(layout, context)


class OP_BsCorrectiveSelectRule(Operator):
    bl_idname = "hotools.bs_corrective_select_rule"
    bl_label = "选择规则"
    index: bpy.props.IntProperty(default=0, min=0)  # type: ignore

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is not None and self.index < len(settings.rules):
            settings.active_index = self.index
        return {"FINISHED"}


CLASSES = [PG_BsCorrectiveVariable, PG_BsCorrectiveTarget, PG_BsCorrectiveRule, PG_BsCorrectiveSettings,
           OP_BsCorrectiveAdd, OP_BsCorrectiveRemove, OP_BsCorrectiveClearRules,
           OP_BsCorrectiveToggleRule, OP_BsCorrectiveMoveRule, OP_BsCorrectiveToggleExpanded,
           OP_BsCorrectiveSelectRule,
           OP_BsCorrectiveAddTarget, OP_BsCorrectiveRemoveTarget, OP_BsCorrectiveClearTargets,
           OP_BsCorrectiveMoveTarget, OP_BsCorrectiveGenerateDrivers, OP_BsCorrectiveReset,
           OP_BsCorrectiveRemoveDrivers]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hotools_bs_corrective = PointerProperty(type=PG_BsCorrectiveSettings)


def unregister():
    del bpy.types.Object.hotools_bs_corrective
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
