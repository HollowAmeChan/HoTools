"""HoTools BS corrective authoring, native drivers, and HoFBX metadata."""
import json
import math
import re
import uuid

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from .bs_corrective_expression import parse


CHANNELS = (("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""))
SCHEMA = "hotools.bs-corrective"
VERSION = 1
_DRIVER_CACHE_PREFIX = ".HoToolsBSDriverCache."
_DRIVER_MARKER = "__hotools_bsc"


def _current_local_pose(armature, bone_name):
    pose_bone = armature.pose.bones.get(bone_name) if armature and bone_name else None
    if pose_bone is None:
        raise ValueError(f"测量骨骼不存在：{bone_name}")
    euler = pose_bone.matrix_basis.to_euler("XYZ")
    return (float(euler.x), float(euler.y), float(euler.z))


def _rbf_distance(a, b):
    # Driver expressions use direct local XYZ differences. The authoring and
    # Unity evaluators must share this metric to keep previews deterministic.
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _rbf_kernel(distance, radius):
    safe_radius = max(float(radius), 1e-6)
    return math.exp(-(distance * distance) / (2.0 * safe_radius * safe_radius))


def _solve_linear(matrix, values):
    """Small regularized Gaussian elimination for authored RBF coefficients."""
    size = len(values)
    augmented = [list(matrix[i]) + [float(values[i])] for i in range(size)]
    for pivot in range(size):
        row = max(range(pivot, size), key=lambda index: abs(augmented[index][pivot]))
        if abs(augmented[row][pivot]) < 1e-9:
            raise ValueError("RBF 控制点过近或重复，无法求解")
        augmented[pivot], augmented[row] = augmented[row], augmented[pivot]
        divisor = augmented[pivot][pivot]
        augmented[pivot] = [item / divisor for item in augmented[pivot]]
        for row in range(size):
            if row == pivot:
                continue
            factor = augmented[row][pivot]
            if abs(factor) < 1e-12:
                continue
            augmented[row] = [
                augmented[row][column] - factor * augmented[pivot][column]
                for column in range(size + 1)
            ]
    return [augmented[index][-1] for index in range(size)]


def _rbf_training_points(rule):
    points = [(rule.base_x, rule.base_y, rule.base_z, 0.0)] if rule.rbf_include_base else []
    points.extend((point.x, point.y, point.z, point.weight) for point in rule.pose_points)
    return points


def _rbf_coefficients(rule):
    points = _rbf_training_points(rule)
    if not points:
        raise ValueError("RBF 至少需要一个控制点或基准姿态")
    positions = [item[:3] for item in points]
    for index, position in enumerate(positions):
        if any(_rbf_distance(position, other) < 1e-5 for other in positions[:index]):
            raise ValueError("RBF 控制点过近或重复，无法求解")
    kernel = [[_rbf_kernel(_rbf_distance(a, b), rule.rbf_radius) for b in positions] for a in positions]
    for index in range(len(kernel)):
        kernel[index][index] += 1e-6
    return positions, _solve_linear(kernel, [item[3] for item in points])


def _rbf_kernel_expression(point, radius):
    radius_term = max(float(radius) * float(radius) * 2.0, 1e-8)
    terms = []
    for variable, value in zip("xyz", point):
        constant = f"{float(value):.8g}"
        delta = variable if abs(float(value)) < 1e-10 else f"({variable}-{constant})"
        terms.append(f"{delta}**2")
    return f"exp(-({' + '.join(terms)})/{radius_term:.8g})"


def _rbf_expression(rule):
    positions, coefficients = _rbf_coefficients(rule)
    terms = [f"({coefficient:.8g})*({_rbf_kernel_expression(position, rule.rbf_radius)})"
             for position, coefficient in zip(positions, coefficients)
             if abs(coefficient) > 1e-12]
    # Keep the complete Gaussian sum here.  The generator uses it directly
    # when Blender stores it intact and splits it into ordinary transform
    # drivers when the current RNA field truncates it.
    return "min(max(" + "+".join(terms or ["0"]) + ",0),1)"


class PG_BsCorrectiveVariable(PropertyGroup):
    name: StringProperty(default="other_x")  # type: ignore
    bone: StringProperty(name="骨骼", default="")  # type: ignore
    channel: EnumProperty(name="通道", items=CHANNELS, default="X")  # type: ignore


class PG_BsCorrectiveTarget(PropertyGroup):
    """One mesh/shape-key output owned by a corrective rule."""
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object)  # type: ignore
    shape_key: StringProperty(name="目标形态键", default="")  # type: ignore


class PG_BsCorrectivePosePoint(PropertyGroup):
    """One authored local-rotation sample for an RBF rule."""
    x: FloatProperty(name="X", default=0.0, unit="ROTATION")  # type: ignore
    y: FloatProperty(name="Y", default=0.0, unit="ROTATION")  # type: ignore
    z: FloatProperty(name="Z", default=0.0, unit="ROTATION")  # type: ignore
    weight: FloatProperty(name="权重", default=1.0, min=0.0, max=1.0)  # type: ignore


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
    mode: EnumProperty(name="求值模式", items=(
        ("EXPRESSION", "表达式", "兼容旧版单轴驱动"),
        ("RBF", "RBF 姿态", "使用局部姿态控制点插值"),
    ), default="EXPRESSION")  # type: ignore
    rbf_radius: FloatProperty(name="RBF 半径", default=0.5, min=0.001, max=100.0, unit="ROTATION")  # type: ignore
    rbf_include_base: BoolProperty(name="包含基准姿态", default=True)  # type: ignore
    base_x: FloatProperty(name="基准 X", default=0.0, unit="ROTATION")  # type: ignore
    base_y: FloatProperty(name="基准 Y", default=0.0, unit="ROTATION")  # type: ignore
    base_z: FloatProperty(name="基准 Z", default=0.0, unit="ROTATION")  # type: ignore
    pose_points: CollectionProperty(type=PG_BsCorrectivePosePoint)  # type: ignore
    pose_active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore
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
    if getattr(rule, "mode", "EXPRESSION") == "RBF":
        if not rule.pose_points and not rule.rbf_include_base:
            raise ValueError("RBF 至少需要一个姿态控制点")
        _rbf_coefficients(rule)
        return
    names = []
    for variable in rule.variables:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", variable.name or ""):
            raise ValueError(f"变量名无效：{variable.name}")
        if variable.name in names or variable.name in {"x", "y", "z", "pi", _DRIVER_MARKER}:
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
            "mode": getattr(rule, "mode", "EXPRESSION"),
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
        if getattr(rule, "mode", "EXPRESSION") == "RBF":
            entry.update({
                "rbfRadius": rule.rbf_radius,
                "rbfIncludeBase": bool(rule.rbf_include_base),
                "rbfBase": [rule.base_x, rule.base_y, rule.base_z],
                "rbfPoints": [
                    {"pose": [point.x, point.y, point.z], "weight": point.weight}
                    for point in rule.pose_points
                ],
            })
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


def _set_driver_expression(driver, expression):
    """Assign an expression and reject RNA truncation before it can be saved."""
    driver.expression = expression
    if driver.expression != expression:
        raise RuntimeError(
            "当前 Blender 版本截断了脚本驱动表达式；"
            "该 BS 修型规则无法安全生成驱动器"
        )


def _try_set_driver_expression(driver, expression):
    """Return whether Blender kept the complete expression in its RNA field."""
    driver.expression = expression
    return driver.expression == expression


def _driver_cache_prefix(armature):
    return _DRIVER_CACHE_PREFIX + armature.name + "."


def _remove_driver_cache(armature):
    prefix = _driver_cache_prefix(armature)
    for obj in list(bpy.data.objects):
        if obj is armature or obj.type != "ARMATURE":
            continue
        data_name = obj.data.name if obj.data else ""
        if obj.name.startswith(prefix) or data_name.startswith(prefix):
            bpy.data.objects.remove(obj, do_unlink=True)
    for data in list(bpy.data.armatures):
        if data.users == 0 and data.name.startswith(prefix):
            bpy.data.armatures.remove(data)


def _create_driver_cache(armature, bone_names):
    """Create a hidden, parentless helper armature for split RBF drivers."""
    prefix = _driver_cache_prefix(armature)
    data = bpy.data.armatures.new(prefix + "Data")
    helper = bpy.data.objects.new(prefix + "Object", data)
    collections = list(armature.users_collection)
    if collections:
        collections[0].objects.link(helper)
    elif bpy.context.scene is not None:
        bpy.context.scene.collection.objects.link(helper)

    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_selected = list(bpy.context.selected_objects)
    previous_mode = previous_active.mode if previous_active else "OBJECT"
    if previous_active and previous_mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        for obj in previous_selected:
            obj.select_set(False)
        view_layer.objects.active = helper
        helper.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        for index, name in enumerate(bone_names):
            bone = data.edit_bones.new(name)
            bone.head = (0.0, index * 0.1, 0.0)
            bone.tail = (0.0, index * 0.1 + 0.1, 0.0)
        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        if helper.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        helper.select_set(False)
        for obj in previous_selected:
            if obj and obj.name in view_layer.objects:
                obj.select_set(True)
        view_layer.objects.active = previous_active
        if previous_active and previous_mode != "OBJECT" and previous_active.name in view_layer.objects:
            bpy.ops.object.mode_set(mode=previous_mode)

    helper.hide_viewport = True
    helper.hide_render = True
    helper.hide_select = True
    try:
        helper.hide_set(True)
    except RuntimeError:
        pass
    for pose_bone in helper.pose.bones:
        pose_bone.rotation_mode = "XYZ"
    return helper


def _cache_driver_add(helper, bone_name):
    pose_bone = helper.pose.bones[bone_name]
    fcurve = pose_bone.driver_add("rotation_euler", 0)
    fcurve.driver.type = "SCRIPTED"
    return fcurve.driver


def _set_driver_marker(driver, armature, bone_name):
    """Add a no-op transform variable used to identify generated target drivers."""
    _set_transform_variable(driver, _DRIVER_MARKER, armature, bone_name, "X")


def _marked_expression(expression):
    return f"({expression})+0*{_DRIVER_MARKER}"


def _build_rbf_driver_cache(armature, rules):
    """Split long RBF expressions into short parentless helper-bone drivers."""
    nodes = []
    roots = {}
    for rule in rules:
        positions, coefficients = _rbf_coefficients(rule)
        leaves = []
        for position, coefficient in zip(positions, coefficients):
            if abs(coefficient) <= 1e-12:
                continue
            name = f"BSC_{len(nodes):04d}"
            nodes.append((name, rule, "point", position, coefficient, None))
            leaves.append(name)
        if not leaves:
            name = f"BSC_{len(nodes):04d}"
            nodes.append((name, rule, "constant", None, 0.0, None))
            leaves.append(name)
        while len(leaves) > 1:
            grouped = []
            for start in range(0, len(leaves), 4):
                children = leaves[start:start + 4]
                name = f"BSC_{len(nodes):04d}"
                nodes.append((name, rule, "sum", None, 0.0, children))
                grouped.append(name)
            leaves = grouped
        roots[id(rule)] = leaves[0]

    helper = _create_driver_cache(armature, [node[0] for node in nodes])
    for name, rule, kind, position, coefficient, children in nodes:
        driver = _cache_driver_add(helper, name)
        if kind == "point":
            _set_driver_expression(
                driver,
                f"({coefficient:.8g})*({_rbf_kernel_expression(position, rule.rbf_radius)})",
            )
            for channel in "XYZ":
                _set_transform_variable(driver, channel.lower(), armature, rule.bone, channel)
        elif kind == "constant":
            _set_driver_expression(driver, "0")
        else:
            names = [f"v{index}" for index in range(len(children))]
            _set_driver_expression(driver, "+".join(names))
            for variable_name, child in zip(names, children):
                _set_transform_variable(driver, variable_name, helper, child, "X")
    return helper, roots


def _shape_key_driver_add(key):
    fcurve = key.driver_add("value")
    fcurve.driver.type = "SCRIPTED"
    return fcurve.driver


def _shape_key_driver_remove(key):
    key.id_data.driver_remove(f'key_blocks["{key.name}"].value', 0)


def generate_native_drivers(armature):
    """Create Blender Transform Channel drivers for all enabled authored rules."""
    settings = settings_for(armature)
    if settings is None or not settings.enabled:
        return 0
    remove_native_drivers(armature)
    generated = 0
    long_rules = []
    long_targets = []
    try:
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
                # Use a no-op transform variable as the ownership marker; driver
                # FCurves are not reliably attached to Action groups in Blender 4.5.
                driver = _shape_key_driver_add(key)
                _set_driver_marker(driver, armature, rule.bone)
                if getattr(rule, "mode", "EXPRESSION") == "RBF":
                    expression = _marked_expression(_rbf_expression(rule))
                    if not _try_set_driver_expression(driver, expression):
                        _shape_key_driver_remove(key)
                        if not any(item is rule for item in long_rules):
                            long_rules.append(rule)
                        long_targets.append((key, rule))
                        continue
                    for channel in "XYZ":
                        _set_transform_variable(driver, channel.lower(), armature, rule.bone, channel)
                else:
                    names = [item.name for item in rule.variables]
                    _set_driver_expression(driver, _marked_expression(parse(rule.expression, names)))
                    source = rule.bone
                    for channel in "XYZ":
                        _set_transform_variable(driver, channel.lower(), armature, source, channel)
                    for item in rule.variables:
                        _set_transform_variable(driver, item.name, armature, item.bone, item.channel)
                generated += 1
        if long_rules:
            helper, roots = _build_rbf_driver_cache(armature, long_rules)
            for key, rule in long_targets:
                driver = _shape_key_driver_add(key)
                _set_driver_marker(driver, armature, rule.bone)
                _set_driver_expression(driver, _marked_expression("min(max(value,0),1)"))
                _set_transform_variable(driver, "value", helper, roots[id(rule)], "X")
                generated += 1
    except Exception:
        # Do not leave a truncated or half-generated driver graph behind.
        remove_native_drivers(armature)
        raise
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
                        (any(variable.name == _DRIVER_MARKER for variable in fcurve.driver.variables) or
                         fcurve.group is not None and fcurve.group.name == "HoToolsBS:" + rule.id)):
                    key.id_data.driver_remove(fcurve.data_path, fcurve.array_index)
                    removed += 1
    _remove_driver_cache(armature)
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


class OP_BsCorrectiveAddPosePoint(Operator):
    bl_idname = "hotools.bs_corrective_add_pose_point"
    bl_label = "添加 RBF 控制点"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or not settings.rules:
            return {"CANCELLED"}
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        point = rule.pose_points.add()
        point.x, point.y, point.z = _current_local_pose(context.object, rule.bone)
        rule.mode = "RBF"
        rule.pose_active_index = len(rule.pose_points) - 1
        return {"FINISHED"}


class OP_BsCorrectiveCaptureBase(Operator):
    bl_idname = "hotools.bs_corrective_capture_base"
    bl_label = "捕获当前基准姿态"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or not settings.rules:
            return {"CANCELLED"}
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        rule.base_x, rule.base_y, rule.base_z = _current_local_pose(context.object, rule.bone)
        rule.mode = "RBF"
        return {"FINISHED"}


class OP_BsCorrectiveRemovePosePoint(Operator):
    bl_idname = "hotools.bs_corrective_remove_pose_point"
    bl_label = "删除 RBF 控制点"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1, min=-1)  # type: ignore

    def execute(self, context):
        settings = settings_for(context.object)
        if settings is None or not settings.rules:
            return {"CANCELLED"}
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        index = self.index if self.index >= 0 else min(rule.pose_active_index, len(rule.pose_points) - 1)
        if index < 0 or index >= len(rule.pose_points):
            return {"CANCELLED"}
        rule.pose_points.remove(index)
        rule.pose_active_index = max(0, index - 1)
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
    detail.prop(rule, "comment", text="注释")
    detail.prop(rule, "bs_name", text="BS 名称")
    detail.prop(rule, "mode", text="求值模式")
    if rule.mode == "RBF":
        rbf_box = detail.box()
        rbf_box.prop(rule, "rbf_radius")
        rbf_box.prop(rule, "rbf_include_base")
        row = rbf_box.row(align=True)
        row.operator(OP_BsCorrectiveCaptureBase.bl_idname, text="捕获基准姿态", icon="SNAP_ON")
        row.operator(OP_BsCorrectiveAddPosePoint.bl_idname, text="添加当前姿态", icon="ADD")
        for point_index, point in enumerate(rule.pose_points):
            row = rbf_box.row(align=True)
            row.label(text=f"点 {point_index + 1}")
            row.prop(point, "x", text="X")
            row.prop(point, "y", text="Y")
            row.prop(point, "z", text="Z")
            row.prop(point, "weight", text="权重")
            remove = row.operator(OP_BsCorrectiveRemovePosePoint.bl_idname, text="", icon="X")
            remove.index = point_index
    else:
        detail.prop(rule, "expression", text="表达式")
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
    if rule.mode != "RBF":
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


CLASSES = [PG_BsCorrectiveVariable, PG_BsCorrectiveTarget, PG_BsCorrectivePosePoint,
           PG_BsCorrectiveRule, PG_BsCorrectiveSettings,
           OP_BsCorrectiveAdd, OP_BsCorrectiveRemove, OP_BsCorrectiveClearRules,
           OP_BsCorrectiveToggleRule, OP_BsCorrectiveMoveRule, OP_BsCorrectiveToggleExpanded,
           OP_BsCorrectiveSelectRule,
           OP_BsCorrectiveAddTarget, OP_BsCorrectiveRemoveTarget, OP_BsCorrectiveClearTargets,
           OP_BsCorrectiveMoveTarget, OP_BsCorrectiveAddPosePoint, OP_BsCorrectiveCaptureBase,
           OP_BsCorrectiveRemovePosePoint, OP_BsCorrectiveGenerateDrivers, OP_BsCorrectiveReset,
           OP_BsCorrectiveRemoveDrivers]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hotools_bs_corrective = PointerProperty(type=PG_BsCorrectiveSettings)


def unregister():
    del bpy.types.Object.hotools_bs_corrective
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
