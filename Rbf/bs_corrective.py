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


class PG_BsCorrectiveRule(PropertyGroup):
    id: StringProperty(default="")  # type: ignore
    enabled: BoolProperty(default=True)  # type: ignore
    bone: StringProperty(name="测量骨骼", default="")  # type: ignore
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object)  # type: ignore
    shape_key: StringProperty(name="目标形态键", default="")  # type: ignore
    expression: StringProperty(default="clamp(x / 1.57079632679, 0, 1)")  # type: ignore
    comment: StringProperty(default="")  # type: ignore
    variables: CollectionProperty(type=PG_BsCorrectiveVariable)  # type: ignore


class PG_BsCorrectiveSettings(PropertyGroup):
    enabled: BoolProperty(name="启用 BS 修型", default=True)  # type: ignore
    rules: CollectionProperty(type=PG_BsCorrectiveRule)  # type: ignore
    active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore


def settings_for(armature):
    return getattr(armature, "hotools_bs_corrective", None)


def _find_bone(armature, name):
    return armature.data.bones.get(name) if armature and name else None


def _shape_names(mesh):
    keys = getattr(getattr(mesh, "data", None), "shape_keys", None)
    return [key.name for key in keys.key_blocks] if keys else []


def _validate_rule(armature, rule):
    if not rule.bone or _find_bone(armature, rule.bone) is None:
        raise ValueError(f"测量骨骼不存在：{rule.bone}")
    if rule.mesh is None or rule.mesh.type != "MESH":
        raise ValueError("目标网格必须是 Mesh 对象")
    if rule.shape_key not in _shape_names(rule.mesh):
        raise ValueError(f"找不到形态键：{rule.shape_key}")
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
        result["rules"].append({
            "id": rule.id,
            "enabled": bool(rule.enabled),
            "armatureName": armature.name,
            "bone": rule.bone,
            "measurementBone": measurement_bone,
            "mesh": rule.mesh.name,
            "shapeKey": rule.shape_key,
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
        })
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
        shape_keys = rule.mesh.data.shape_keys
        key = shape_keys.key_blocks.get(rule.shape_key)
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
        if rule.mesh is None or rule.mesh.data.shape_keys is None:
            continue
        key = rule.mesh.data.shape_keys.key_blocks.get(rule.shape_key)
        if key is None or key.id_data.animation_data is None:
            continue
        for fcurve in list(key.id_data.animation_data.drivers):
            if (fcurve.data_path == f'key_blocks["{key.name}"].value' and
                    fcurve.group is not None and fcurve.group.name == "HoToolsBS:" + rule.id):
                key.id_data.driver_remove(fcurve.data_path, fcurve.array_index)
                removed += 1
    return removed


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


def draw_bs_corrective_panel(layout, context):
    """Draw the authoring controls inside the RBF panel's 修型 page."""
    armature = context.object
    if armature is None or armature.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return
    settings = settings_for(armature)
    layout.prop(settings, "enabled")
    row = layout.row(align=True)
    row.operator(OP_BsCorrectiveAdd.bl_idname, icon="ADD")
    row.operator(OP_BsCorrectiveRemove.bl_idname, icon="REMOVE")
    row = layout.row(align=True)
    row.operator(OP_BsCorrectiveGenerateDrivers.bl_idname, icon="DRIVER")
    row.operator(OP_BsCorrectiveRemoveDrivers.bl_idname, icon="X")
    if not settings.rules:
        layout.label(text="暂无规则；导出不会生成 BS 元数据", icon="INFO")
        return
    for index, rule in enumerate(settings.rules):
        box = layout.box()
        box.prop(rule, "enabled", text=f"规则 {index + 1}")
        box.prop_search(rule, "bone", armature.data, "bones", text="测量骨骼")
        box.prop(rule, "mesh", text="目标网格")
        if rule.mesh is not None:
            keys = _shape_names(rule.mesh)
            if keys:
                box.prop_search(rule, "shape_key", rule.mesh.data.shape_keys, "key_blocks", text="目标形态键")
        box.prop(rule, "shape_key", text="形态键名称")
        box.prop(rule, "expression", text="表达式")
        box.prop(rule, "comment", text="注释")


CLASSES = [PG_BsCorrectiveVariable, PG_BsCorrectiveRule, PG_BsCorrectiveSettings,
           OP_BsCorrectiveAdd, OP_BsCorrectiveRemove, OP_BsCorrectiveGenerateDrivers,
           OP_BsCorrectiveRemoveDrivers]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hotools_bs_corrective = PointerProperty(type=PG_BsCorrectiveSettings)


def unregister():
    del bpy.types.Object.hotools_bs_corrective
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
