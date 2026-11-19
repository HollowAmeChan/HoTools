"""HoTools BS corrective authoring, native drivers, and HoFBX metadata."""
import json
import math
import uuid

import numpy as np

import bpy
import gpu
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList
from mathutils import Euler, Quaternion, Vector
from .bs_math import (
    ANGLE_EPSILON, IDENTITY, euler_xyz_quaternion, normalize_quaternion,
    pose_weight, quaternion_angle,
)

from ..BoneTools.previewUtils import AuxPreviewUtils
from ..Utils.hud import begin_hud, end_hud, draw_hud_lines
from ..Utils.shapekey_utils import read_shape_key_positions

SCHEMA = "hotools.bs-corrective"
VERSION = 5
_DRIVER_MARKER = "hotoolsBscMarker"
_DRIVER_NAMESPACE_FUNCTION = "hotools_bs_rbf"
_RBF_RUNTIME = {}
_RBF_CACHE = {}
_RBF_UI_CACHE = {}
_BASE_POINT = "BASE"


def _update_pose_parameters(self, context):
    """Refresh compiled data only; realtime rotation still comes from drivers."""
    armature = self.id_data
    settings = settings_for(armature)
    rule = _find_pose_rule(settings, self) if settings is not None else None
    _RBF_UI_CACHE.clear()
    BsCorrectivePreview.invalidate()
    if rule is None or not rule.driver_payload:
        return
    try:
        encoded = _encode_rbf_payload(rule, persist=False)
        _RBF_RUNTIME[rule.id] = _decode_rbf_payload(encoded)
        rule.driver_payload = encoded
    except (KeyError, TypeError, ValueError):
        _RBF_RUNTIME.pop(rule.id, None)
        rule.driver_payload = json.dumps({"version": VERSION, "invalid": True})
    _RBF_CACHE.pop(rule.id, None)
    for keys in bpy.data.shape_keys:
        animation = keys.animation_data
        for fc in animation.drivers if animation else ():
            if _owned_driver(fc, armature, {rule.id}):
                fc.driver.expression = fc.driver.expression
                keys.update_tag()
    if context is not None and getattr(context, "view_layer", None) is not None:
        context.view_layer.update()


def _update_enabled(self, context):
    _RBF_UI_CACHE.clear()
    armature = self.id_data
    settings = settings_for(armature)
    if settings is None:
        return
    if not hasattr(self, "rules"):
        # A rule is the master switch for its authored pose rows. Individual
        # pose switches remain available when the rule itself is enabled.
        enabled = bool(self.enabled)
        for point in _authored_points(self):
            if point.enabled != enabled:
                point.enabled = enabled
    _sync_pose_enabled(armature, context=context)


def _update_pose_enabled(self, context):
    armature = self.id_data
    settings = settings_for(armature)
    if settings is None:
        return
    owner = _find_pose_rule(settings, self)
    if owner is not None:
        _set_pose_enabled(armature, owner, self, context=context)


def _update_preview(self, context):
    if self.preview_enabled:
        BsCorrectivePreview.show(context, armature=self.id_data)
    else:
        BsCorrectivePreview.clear()


def _current_local_pose(armature, bone_name):
    pose_bone = armature.pose.bones.get(bone_name) if armature and bone_name else None
    if pose_bone is None:
        raise ValueError(f"测量骨骼不存在：{bone_name}")
    euler = pose_bone.matrix_basis.to_euler("XYZ")
    return (float(euler.x), float(euler.y), float(euler.z))


def _rbf_distance(a, b):
    return quaternion_angle(euler_xyz_quaternion(a), euler_xyz_quaternion(b))


def _authored_points(rule):
    return [point for point in rule.pose_points if point.id != _BASE_POINT]


def _ensure_base_point(rule):
    """Keep the fixed zero sample in the native UIList, never in task data."""
    bases = [i for i, point in enumerate(rule.pose_points) if point.id == _BASE_POINT]
    if not bases:
        point = rule.pose_points.add()
        point.id = _BASE_POINT
        rule.pose_points.move(len(rule.pose_points) - 1, 0)
    elif bases[0] != 0:
        rule.pose_points.move(bases[0], 0)
    point = rule.pose_points[0]
    point.x = point.y = point.z = 0.0
    point.bs_name = ""


class PG_BsCorrectiveInfluenceObject(PropertyGroup):
    """Mesh object included in the rule's authoring scope."""
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object, poll=lambda self, obj: obj.type == "MESH")  # type: ignore


class PG_BsCorrectivePosePoint(PropertyGroup):
    """One authored pose and its generated shape-key name."""
    id: StringProperty(default="")  # type: ignore
    enabled: BoolProperty(name="启用", default=True, update=_update_pose_enabled)  # type: ignore
    bs_name: StringProperty(name="BS 名称", default="_BSC_pose1")  # type: ignore
    weight: FloatProperty(name="权重", default=1.0, min=0.0, max=1.0, subtype="FACTOR", update=_update_pose_parameters)  # type: ignore
    radius: FloatProperty(
        name="影响半径",
        default=math.radians(30.0),
        min=ANGLE_EPSILON,
        max=math.pi,
        subtype="ANGLE",
        description="允许偏离本姿态的最大旋转角；基准侧自动归零，其他修型独立叠加",
        update=_update_pose_parameters,
    )  # type: ignore
    x: FloatProperty(name="X", default=0.0, unit="ROTATION")  # type: ignore
    y: FloatProperty(name="Y", default=0.0, unit="ROTATION")  # type: ignore
    z: FloatProperty(name="Z", default=0.0, unit="ROTATION")  # type: ignore


class PG_BsCorrectiveRule(PropertyGroup):
    id: StringProperty(default="")  # type: ignore
    enabled: BoolProperty(default=True, update=_update_enabled)  # type: ignore
    bone: StringProperty(name="测量骨骼", default="")  # type: ignore
    influence_objects: CollectionProperty(type=PG_BsCorrectiveInfluenceObject)  # type: ignore
    pose_points: CollectionProperty(type=PG_BsCorrectivePosePoint)  # type: ignore
    # Compiled RBF data is serialized with the rule so the runtime namespace
    # can be rebuilt after opening a .blend without using custom properties.
    driver_payload: StringProperty(default="")  # type: ignore
    influence_active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore
    pose_active_index: bpy.props.IntProperty(
        default=0, min=0, update=lambda self, context: AuxPreviewUtils.tag_redraw(),
    )  # type: ignore


class PG_BsCorrectiveSettings(PropertyGroup):
    enabled: BoolProperty(name="启用 BS 修型", default=True, update=_update_enabled)  # type: ignore
    preview_enabled: BoolProperty(name="修型范围预览", default=False, update=_update_preview)  # type: ignore
    rules: CollectionProperty(type=PG_BsCorrectiveRule)  # type: ignore
    active_index: bpy.props.IntProperty(default=0, min=0, update=_update_preview)  # type: ignore


def settings_for(armature):
    return getattr(armature, "hotools_bs_corrective", None)


def _armature_object_poll(_self, obj):
    return obj is not None and obj.type == "ARMATURE"


def _context_armature(context):
    active = getattr(context, "object", None)
    if active is not None and getattr(active, "type", None) == "ARMATURE":
        return active
    scene = getattr(context, "scene", None)
    selected = getattr(scene, "hotools_bs_corrective_view_armature", None) if scene else None
    return selected if selected is not None and getattr(selected, "type", None) == "ARMATURE" else None


def _operator_armature(operator, context):
    name = getattr(operator, "armature_name", "")
    selected = bpy.data.objects.get(name) if name else None
    if selected is not None and getattr(selected, "type", None) == "ARMATURE":
        return selected
    return _context_armature(context)


def _owner_armature(data, context):
    owner = getattr(data, "id_data", None)
    if owner is not None and getattr(owner, "type", None) == "ARMATURE":
        return owner
    return _context_armature(context)


def _find_bone(armature, name):
    return armature.data.bones.get(name) if armature and name else None


def _shape_names(mesh):
    keys = getattr(getattr(mesh, "data", None), "shape_keys", None)
    return [key.name for key in keys.key_blocks] if keys else []


def _rule_meshes(rule):
    """Return the unique mesh scope owned by a rule."""
    meshes = []
    seen = set()
    for item in rule.influence_objects:
        mesh = item.mesh
        if mesh is None:
            continue
        pointer = mesh.as_pointer()
        if pointer not in seen:
            seen.add(pointer)
            meshes.append(mesh)
    return meshes


def _rule_outputs(rule):
    """Yield each authored pose expanded to every mesh in the rule scope."""
    for point in _authored_points(rule):
        for mesh in _rule_meshes(rule):
            yield point, mesh, point.bs_name.strip()


def _validate_pose_names(settings):
    names = set()
    for rule in settings.rules:
        for point in _authored_points(rule):
            name = (point.bs_name or "").strip()
            if name in names:
                raise ValueError(f"修型姿势 BS 名称重复：{name}")
            names.add(name)


def _validate_rule(armature, rule, require_targets=True):
    if not rule.bone or _find_bone(armature, rule.bone) is None:
        raise ValueError(f"测量骨骼不存在：{rule.bone}")
    points = _authored_points(rule)
    if not points:
        raise ValueError("RBF 至少需要一个姿态控制点")
    point_ids = {point.id for point in points if point.id}
    if len(point_ids) != len(points):
        raise ValueError("控制点 id 为空或重复")
    names = set()
    for point in points:
        name = (point.bs_name or "").strip()
        if not name:
            raise ValueError("姿势 BS 名称不能为空")
        if name in names:
            raise ValueError(f"规则内姿势 BS 名称重复：{name}")
        names.add(name)
        if not math.isfinite(point.weight) or not 0.0 <= point.weight <= 1.0:
            raise ValueError(f"姿势权重必须在 0..1：{name}")
        if not math.isfinite(point.radius) or not 0.0 < point.radius <= math.pi + 1e-6:
            raise ValueError(f"姿势影响半径必须在 0°..180°：{name}")
    meshes = _rule_meshes(rule)
    if not meshes:
        raise ValueError(f"规则缺少影响物体：{rule.bone}")
    if len(meshes) != sum(1 for item in rule.influence_objects if item.mesh):
        raise ValueError("规则影响物体不能重复")
    for mesh in meshes:
        if mesh.type != "MESH":
            raise ValueError("影响物体必须是 Mesh 对象")
        if mesh.data.shape_keys and not mesh.data.shape_keys.use_relative:
            raise ValueError(f"BS 修型仅支持相对形态键：{mesh.name}")
        if require_targets:
            for point in points:
                shape_key = point.bs_name.strip()
                if shape_key not in _shape_names(mesh):
                    raise ValueError(f"找不到形态键：{mesh.name}/{shape_key}")


def build_export_config(armature, fbx_bone_axes="Y_X", measurement_bones=None):
    """Return a JSON-ready config; this is deliberately side-effect free."""
    settings = settings_for(armature)
    if settings is None or not settings.enabled:
        return None
    result = {
        "schema": SCHEMA,
        "version": VERSION,
        "poseSpace": "LOCAL",
        "rotationRepresentation": "quaternion-xyzw",
        "angleUnit": "radian",
        "kernel": "smoothstep-compact",
        "evaluation": "independent",
        "distanceMetric": "quaternion-angle",
        "neutralMode": "triangle-smoothstep",
        "fbxBoneAxes": fbx_bone_axes,
        "measurement": "source_local_rotation",
        "rules": [],
    }
    outputs = set()
    _validate_pose_names(settings)
    for rule in settings.rules:
        _validate_rule(armature, rule)
        _compile_rbf(rule)
        for _, mesh, shape_key in _rule_outputs(rule):
            output = (mesh.data.as_pointer(), shape_key)
            if rule.enabled and output in outputs:
                raise ValueError(f"目标形态键重复：{mesh.name}/{shape_key}")
            if rule.enabled:
                outputs.add(output)
        if not rule.id:
            rule.id = uuid.uuid4().hex
        # MCH is the export-time stable cache for a source bone whose authored
        # rest rotation is cleared by HoFBX.  The authored rule remains keyed by
        # the source name, while Unity reads the actual exported cache bone.
        measurement_bone = (measurement_bones or {}).get(rule.bone, rule.bone)
        entry = {
            "id": rule.id,
            "enabled": bool(rule.enabled),
            "armatureName": armature.name,
            "bone": rule.bone,
            "measurementBone": measurement_bone,
            "influenceObjects": [item.mesh.name for item in rule.influence_objects if item.mesh],
            # The task-shaped records are generated at the export boundary;
            # authoring stores only one output name on each pose.
            "tasks": [
                {
                    "id": point.id,
                    "bsName": point.bs_name.strip(),
                    "pointId": point.id,
                    "enabled": bool(rule.enabled and point.enabled),
                    "weight": float(point.weight),
                    "targets": [
                        {"mesh": mesh.name, "shapeKey": point.bs_name.strip()}
                        for mesh in _rule_meshes(rule)
                    ],
                }
                for point in _authored_points(rule)
            ],
            "rbf": {
                "includeBase": True,
                "basePose": list(IDENTITY),
                "controlPoints": [
                    {"id": point.id, "pose": list(euler_xyz_quaternion((point.x, point.y, point.z))),
                     "radius": float(point.radius)}
                    for point in _authored_points(rule)
                ],
            },
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
    target.rotation_mode = "XYZ"


def _set_driver_expression(driver, expression):
    """Assign an expression and reject RNA truncation before it can be saved."""
    driver.expression = expression
    if driver.expression != expression:
        raise RuntimeError(
            "当前 Blender 版本截断了脚本驱动表达式；"
            "该 BS 修型规则无法安全生成驱动器"
        )


def _encode_rbf_payload(rule, persist=True):
    """Serialize compiled RBF data into a normal RNA StringProperty."""
    poses, indices, radii, weights, _ = _compile_rbf(rule)
    payload = {
        "version": VERSION,
        "poses": poses,
        "ids": list(indices),
        "radii": radii,
        "weights": weights,
    }
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    if persist:
        rule.driver_payload = encoded
    return encoded


def _compile_rbf(rule):
    """Compile independent poses in O(N), without interpolation coefficients."""
    points = _authored_points(rule)
    return _compiled_poses(
        [euler_xyz_quaternion((p.x, p.y, p.z)) for p in points],
        [p.id for p in points], [float(p.radius) for p in points], [float(p.weight) for p in points],
    )


def _compiled_poses(poses, ids, radii, weights):
    count = len(poses)
    if not count or any(len(values) != count for values in (ids, radii, weights)):
        raise ValueError("修型驱动数据为空或长度不一致")
    if any(not isinstance(pose_id, str) or not pose_id for pose_id in ids) or len(set(ids)) != count:
        raise ValueError("修型姿态 id 为空或重复")
    poses = tuple(normalize_quaternion(pose) for pose in poses)
    radii, weights = tuple(float(v) for v in radii), tuple(float(v) for v in weights)
    if any(not math.isfinite(v) or not 0.0 < v <= math.pi + 1e-6 for v in radii):
        raise ValueError("姿态影响半径必须为有限正数且不超过 180°")
    if any(not math.isfinite(v) or not 0.0 <= v <= 1.0 for v in weights):
        raise ValueError("姿态权重必须在 0..1")
    neutral_angles = tuple(quaternion_angle(pose, IDENTITY) for pose in poses)
    if any(angle < ANGLE_EPSILON for angle in neutral_angles):
        raise ValueError("修型姿态不能与基准姿态相同")
    return poses, {pose_id: index for index, pose_id in enumerate(ids)}, radii, weights, neutral_angles


def _decode_rbf_payload(encoded):
    payload = json.loads(encoded)
    if payload.get("version") != VERSION:
        raise ValueError("修型驱动数据版本不匹配，请刷新驱动")
    return _compiled_poses(payload["poses"], payload["ids"], payload["radii"], payload["weights"])


def _evaluate_rbf_outputs(item, current):
    poses, _, radii, weights, neutral_angles = item
    quaternion = euler_xyz_quaternion(current)
    neutral = quaternion_angle(quaternion, IDENTITY)
    return tuple(pose_weight(quaternion, pose, radius, weight, c, neutral)
                 for pose, radius, weight, c in zip(poses, radii, weights, neutral_angles))


def _driver_namespace_rbf(rule_id, pose_id, x, y, z):
    """Evaluate one serialized rule output from Blender's driver namespace."""
    rule_id = str(rule_id)
    pose_id = str(pose_id)
    item = _RBF_RUNTIME.get(rule_id)
    if item is None:
        return 0.0
    index = item[1].get(pose_id)
    if index is None:
        return 0.0
    current = (float(x), float(y), float(z))
    if not (math.isfinite(current[0]) and math.isfinite(current[1]) and math.isfinite(current[2])):
        return 0.0
    cached = _RBF_CACHE.get(rule_id)
    if cached is not None and cached[0] == current:
        return float(cached[1][index])
    outputs = _evaluate_rbf_outputs(item, current)
    _RBF_CACHE[rule_id] = (current, outputs)
    return float(outputs[index])


def _rebuild_driver_namespace():
    """Rebuild runtime rule data from serialized armature settings."""
    _RBF_RUNTIME.clear()
    _RBF_CACHE.clear()
    _RBF_UI_CACHE.clear()
    for armature in bpy.data.objects:
        if armature.type != "ARMATURE":
            continue
        settings = settings_for(armature)
        if settings is None:
            continue
        for rule in settings.rules:
            _ensure_base_point(rule)
            if not rule.id or not rule.driver_payload:
                continue
            try:
                _RBF_RUNTIME[rule.id] = _decode_rbf_payload(rule.driver_payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                # Invalid rules are reported by normal driver generation/validation.
                continue


def _register_driver_namespace(rebuild=True):
    bpy.app.driver_namespace[_DRIVER_NAMESPACE_FUNCTION] = _driver_namespace_rbf
    # Add-on registration runs under Blender's restricted startup context,
    # where bpy.data has no collections yet. The load handler rebuilds it once
    # the .blend data is available.
    if rebuild and getattr(bpy.data, "objects", None) is not None:
        _rebuild_driver_namespace()


def _unregister_driver_namespace():
    if bpy.app.driver_namespace.get(_DRIVER_NAMESPACE_FUNCTION) is _driver_namespace_rbf:
        bpy.app.driver_namespace.pop(_DRIVER_NAMESPACE_FUNCTION, None)
    _RBF_RUNTIME.clear()
    _RBF_CACHE.clear()
    _RBF_UI_CACHE.clear()


@persistent
def _restore_driver_namespace(_):
    _register_driver_namespace()


def _set_driver_marker(driver, armature, bone_name):
    """The X input doubles as the ownership marker, avoiding a fourth fetch."""
    _set_transform_variable(driver, _DRIVER_MARKER, armature, bone_name, "X")


def _rbf_namespace_expression(rule, point):
    if not rule.id:
        rule.id = uuid.uuid4().hex
    # The rule id is persisted in the controller; only the function itself
    # must be restored into bpy.app.driver_namespace after opening a file.
    return f'{_DRIVER_NAMESPACE_FUNCTION}({json.dumps(rule.id)},{json.dumps(point.id)},{_DRIVER_MARKER},y,z)'


def _shape_key_driver_add(key):
    fcurve = key.driver_add("value")
    fcurve.driver.type = "SCRIPTED"
    return fcurve.driver


def _selected_rules(armature, rule_indices=None):
    settings = settings_for(armature)
    selected = set(rule_indices) if rule_indices is not None else None
    return [(i, rule) for i, rule in enumerate(settings.rules)
            if selected is None or i in selected] if settings else []


def _owned_driver(fcurve, armature, rule_ids):
    return (any(variable.name == _DRIVER_MARKER and variable.targets[0].id == armature
                for variable in fcurve.driver.variables)
            and any(json.dumps(rule_id) in fcurve.driver.expression for rule_id in rule_ids))


def _driver_owns_pose(fcurve, point_id):
    return json.dumps(point_id) in fcurve.driver.expression


def _find_pose_rule(settings, point):
    point_pointer = point.as_pointer()
    for rule in settings.rules:
        if any(candidate.as_pointer() == point_pointer for candidate in rule.pose_points):
            return rule
    return None


def _set_shape_key_enabled(key, enabled):
    key.mute = not enabled
    if not enabled:
        key.value = 0.0


def _set_pose_enabled(armature, rule, point, context=None, update=True):
    """Synchronize one pose's authored enabled state to all target keys/drivers."""
    settings = settings_for(armature)
    if settings is None or point.id == _BASE_POINT:
        return
    enabled = bool(settings.enabled and rule.enabled and point.enabled)
    names = point.bs_name.strip()
    for mesh in _rule_meshes(rule):
        shape_keys = mesh.data.shape_keys
        key = shape_keys.key_blocks.get(names) if shape_keys else None
        if key is not None:
            _set_shape_key_enabled(key, enabled)
            shape_keys.update_tag()
    for keys in bpy.data.shape_keys:
        animation = keys.animation_data
        for fcurve in list(animation.drivers) if animation else []:
            if not (_owned_driver(fcurve, armature, {rule.id}) and _driver_owns_pose(fcurve, point.id)):
                continue
            fcurve.mute = not enabled
            try:
                key = keys.path_resolve(fcurve.data_path.rsplit(".", 1)[0])
                _set_shape_key_enabled(key, enabled)
            except (AttributeError, KeyError, RuntimeError, ValueError):
                # A stale driver path can survive an edited shape-key list.
                pass
        keys.update_tag()
    if update and context is not None and getattr(context, "view_layer", None) is not None:
        context.view_layer.update()


def _sync_pose_enabled(armature, rule_indices=None, context=None):
    settings = settings_for(armature)
    if settings is None:
        return
    for _, rule in _selected_rules(armature, rule_indices):
        for point in _authored_points(rule):
            _set_pose_enabled(armature, rule, point, update=False)
    if context is not None and getattr(context, "view_layer", None) is not None:
        context.view_layer.update()

def generate_native_drivers(armature, rule_indices=None, warnings=None):
    """Refresh drivers best-effort, optionally collecting per-target warnings.

    A malformed rule or missing shape key must not prevent unrelated rules and
    targets from being refreshed. Existing drivers for a skipped rule remain
    untouched; valid targets are rebuilt independently.
    """
    settings = settings_for(armature)
    if settings is None:
        return 0
    warnings = warnings if warnings is not None else []
    _sync_pose_enabled(armature, rule_indices)
    selected = _selected_rules(armature, rule_indices)
    prepared = {}
    valid_indices = []
    for index, rule in selected:
        try:
            _validate_rule(armature, rule, require_targets=False)
            if not rule.id:
                rule.id = uuid.uuid4().hex
            encoded = _encode_rbf_payload(rule, persist=False)
            prepared[rule.id] = encoded, _decode_rbf_payload(encoded)
            valid_indices.append(index)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            warnings.append(f"规则「{rule.bone or '未指定骨骼'}」跳过：{exc}")

    if not valid_indices:
        return 0

    # Detect output conflicts without making one bad target abort the batch.
    owners = {}
    for index, rule in enumerate(settings.rules):
        if not rule.enabled:
            continue
        for _, mesh, shape_key in _rule_outputs(rule):
            owners.setdefault((mesh.data.as_pointer(), shape_key), []).append(index)

    remove_native_drivers(armature, valid_indices)
    _register_driver_namespace(rebuild=False)
    generated = 0
    try:
        for index, rule in selected:
            if index not in valid_indices:
                continue
            rule.driver_payload, _RBF_RUNTIME[rule.id] = prepared[rule.id]
            _RBF_CACHE.pop(rule.id, None)
            for point, mesh, shape_key in _rule_outputs(rule):
                target_id = (mesh.data.as_pointer(), shape_key)
                if len(owners.get(target_id, ())) > 1:
                    warnings.append(f"目标形态键冲突，跳过：{mesh.name}/{shape_key}")
                    continue
                shape_keys = mesh.data.shape_keys
                key = shape_keys.key_blocks.get(shape_key) if shape_keys else None
                if key is None:
                    warnings.append(f"找不到形态键，跳过：{mesh.name}/{shape_key}")
                    continue
                animation = key.id_data.animation_data
                foreign = any(
                    fcurve.data_path == key.path_from_id("value") and
                    not _owned_driver(fcurve, armature, {rule.id})
                    for fcurve in (animation.drivers if animation else [])
                )
                if foreign:
                    warnings.append(f"目标已有其他驱动器，跳过：{mesh.name}/{shape_key}")
                    continue
                try:
                    # Use the X transform variable as the ownership marker;
                    # FCurves are not reliably attached to Action groups.
                    driver = _shape_key_driver_add(key)
                    _set_driver_marker(driver, armature, rule.bone)
                    expression = _rbf_namespace_expression(rule, point)
                    _set_driver_expression(driver, expression)
                    for channel in "YZ":
                        _set_transform_variable(driver, channel.lower(), armature, rule.bone, channel)
                    generated += 1
                except Exception as exc:
                    try:
                        key.id_data.driver_remove(key.path_from_id("value"), 0)
                    except (AttributeError, RuntimeError, ValueError):
                        pass
                    warnings.append(f"驱动生成失败，跳过：{mesh.name}/{shape_key}（{exc}）")
        _sync_pose_enabled(armature, valid_indices)
    except Exception:
        # A fatal graph error should still remove only this controller's
        # generated drivers; per-target validation errors are handled above.
        remove_native_drivers(armature, valid_indices)
        raise
    return generated

def remove_native_drivers(armature, rule_indices=None):
    """Remove only drivers generated by this controller, preserving user drivers."""
    settings = settings_for(armature)
    if settings is None:
        return 0
    removed = 0
    rule_ids = {rule.id for _, rule in _selected_rules(armature, rule_indices) if rule.id}
    # Search by ownership, not by the current mesh scope: editing a rule must
    # not strand an old generated driver.
    for keys in bpy.data.shape_keys:
        animation = keys.animation_data
        for fcurve in list(animation.drivers) if animation else []:
            if _owned_driver(fcurve, armature, rule_ids):
                keys.driver_remove(fcurve.data_path, fcurve.array_index)
                removed += 1
    for rule_id in rule_ids:
        _RBF_RUNTIME.pop(rule_id, None)
        _RBF_CACHE.pop(rule_id, None)
    for _, rule in _selected_rules(armature, rule_indices):
        rule.driver_payload = ""
    return removed


def _collect_generated_targets(armature, rule_indices=None):
    """Validate reset names and return the rule pose/name pairs to create."""
    settings = settings_for(armature)
    if settings is None:
        return []
    requested_targets = set()
    targets = []
    selected = set(rule_indices) if rule_indices is not None else None
    untouched_outputs = {
        (mesh.data.as_pointer(), shape_key)
        for index, other in enumerate(settings.rules)
        if selected is not None and index not in selected
        for _, mesh, shape_key in _rule_outputs(other)
    }
    for rule_index, rule in enumerate(settings.rules):
        if selected is not None and rule_index not in selected:
            continue
        meshes = _rule_meshes(rule)
        if not meshes:
            raise ValueError(f"规则缺少影响物体：{rule.bone}")
        for point in _authored_points(rule):
            name = (point.bs_name or "").strip()
            if not name:
                raise ValueError("BS 名称不能为空")
            for mesh in meshes:
                if mesh is None or mesh.type != "MESH":
                    raise ValueError("目标网格必须是 Mesh 对象")
                if mesh.data.shape_keys and not mesh.data.shape_keys.use_relative:
                    raise ValueError(f"BS 修型仅支持相对形态键：{mesh.name}")
                target_id = (mesh.data.as_pointer(), name)
                if target_id in untouched_outputs:
                    raise ValueError(f"目标形态键已被其他规则使用：{mesh.name}/{name}")
                if target_id in requested_targets:
                    raise ValueError(f"目标 BS 重复：{mesh.name}/{name}")
                requested_targets.add(target_id)
                existing = mesh.data.shape_keys.key_blocks.get(name) if mesh.data.shape_keys else None
                if existing is not None:
                    if existing == mesh.data.shape_keys.reference_key:
                        raise ValueError(f"不能覆盖基准形态键：{mesh.name}/{name}")
                targets.append((point, mesh, name))
    return targets


def _shape_key_is_empty(key, reference_cache=None):
    """Only exact zero deltas are empty; even tiny authored offsets are kept."""
    relative = key.relative_key
    if relative is None or relative == key or len(key.data) != len(relative.data):
        return False
    cache = reference_cache if reference_cache is not None else {}
    relative_id = relative.as_pointer()
    if relative_id not in cache:
        cache[relative_id] = read_shape_key_positions(relative)
    coordinates = read_shape_key_positions(key)
    return bool(np.isfinite(coordinates).all() and np.array_equal(coordinates, cache[relative_id]))


def _remove_shape_key_drivers(key):
    animation = key.id_data.animation_data
    for fcurve in list(animation.drivers) if animation else []:
        if fcurve.data_path == key.path_from_id("value"):
            key.id_data.driver_remove(fcurve.data_path, fcurve.array_index)


def _prepare_generated_shape_keys(targets, overwrite=False, overwrite_targets=None):
    """Reset empty/approved keys, retaining all other sculpted coordinates."""
    overwrite_targets = set(overwrite_targets or ())
    reference_cache = {}
    # Classify before modifying any relative-key coordinates in this batch.
    prepared = []
    for _, mesh, name in targets:
        shape_keys = mesh.data.shape_keys
        existing = shape_keys.key_blocks.get(name) if shape_keys else None
        reset_geometry = existing is not None and (
            overwrite or (mesh.data.as_pointer(), name) in overwrite_targets
            or _shape_key_is_empty(existing, reference_cache)
        )
        prepared.append((mesh, name, existing, reset_geometry))
    for mesh, name, existing, reset_geometry in prepared:
        if mesh.data.shape_keys is None:
            mesh.shape_key_add(name="Basis", from_mix=False)
        if existing is None:
            mesh.shape_key_add(name=name, from_mix=False)
        else:
            # Reset always refreshes these configured outputs, including keys
            # whose sculpt is kept. Unrelated shape-key drivers stay untouched.
            _remove_shape_key_drivers(existing)
            if reset_geometry:
                # Preserve key identity, references from other keys and topology.
                basis = mesh.data.shape_keys.reference_key
                existing.data.foreach_set("co", read_shape_key_positions(basis).ravel())
                existing.relative_key = basis
                existing.mute = False
    return len(targets)


class HO_UL_BsCorrectiveRule(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        select = row.row(align=True)
        select.enabled = bool(item.bone)
        operator = select.operator("hotools.bs_corrective_select_bone", text="", icon="RESTRICT_SELECT_OFF")
        operator.index = index
        owner = _owner_armature(data, context)
        if owner is not None:
            operator.armature_name = owner.name
        armature = _owner_armature(data, context)
        if armature is not None:
            row.prop_search(item, "bone", armature.data, "bones", text="")
        else:
            row.prop(item, "bone", text="")
        rotation = _display_bone_rotation(item, armature)
        row.label(text=f"{rotation}" if rotation else "--")



class HO_UL_BsCorrectiveInfluence(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "mesh", text="", emboss=False)


class HO_UL_BsCorrectivePoint(UIList):
    def draw_item(self, context, layout:bpy.types.UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.id == _BASE_POINT:
            preview = row.row(align=False)
            preview.enabled = bool(data.bone)
            operator = preview.operator("hotools.bs_corrective_pose", text="基准姿态", icon="MOD_ARMATURE")
            operator.index = index
            owner = _owner_armature(data, context)
            if owner is not None:
                operator.armature_name = owner.name
        else:
            row.prop(item, "enabled", text="")
            preview = row.row(align=False)
            preview.enabled = bool(data.bone)
            operator = preview.operator("hotools.bs_corrective_pose", text="", icon="OUTLINER_OB_ARMATURE")
            operator.index = index
            owner = _owner_armature(data, context)
            if owner is not None:
                operator.armature_name = owner.name
            row.prop(item, "bs_name", text="", emboss=False)
            row.label(text=f"{math.degrees(item.x):.1f}° / {math.degrees(item.y):.1f}° / {math.degrees(item.z):.1f}°")
            row.prop(item, "radius", text="")
            weight = _display_rbf_weight(data, item, _owner_armature(data, context))
            row.label(text=f"RBF {weight:.3f}" if weight is not None else "RBF --")
            row.prop(item, "weight", text="")



def _display_rbf_weight(rule, point, armature):
    """Return the current driver-space weight without making UI drawing fail."""
    if point.id == _BASE_POINT or armature is None or not rule.bone:
        return 0.0 if point.id == _BASE_POINT else None
    try:
        current = _current_local_pose(armature, rule.bone)
    except (AttributeError, ValueError, RuntimeError):
        return None
    signature = (
        rule.as_pointer(),
        rule.id,
        bool(rule.enabled),
        tuple((p.id, float(p.x), float(p.y), float(p.z)) for p in _authored_points(rule)),
        tuple((p.id, float(p.radius), float(p.weight), bool(p.enabled)) for p in _authored_points(rule)),
        current,
    )
    cache_key = (armature.as_pointer(), signature)
    cached = _RBF_UI_CACHE.get(cache_key)
    if cached is None:
        try:
            item = (_RBF_RUNTIME.get(rule.id) or _decode_rbf_payload(rule.driver_payload)
                    if rule.driver_payload else _compile_rbf(rule))
            values = _evaluate_rbf_outputs(item, current)
            settings = settings_for(armature)
            if not rule.enabled or settings is None or not settings.enabled:
                values = tuple(0.0 for _ in values)
            cached = {pose_id: float(values[index]) for pose_id, index in item[1].items()}
        except (KeyError, TypeError, ValueError, RuntimeError):
            cached = {}
        if len(_RBF_UI_CACHE) > 128:
            _RBF_UI_CACHE.clear()
        _RBF_UI_CACHE[cache_key] = cached
    return cached.get(point.id) if point.enabled else 0.0


def _display_bone_rotation(rule, armature):
    if armature is None or not rule.bone:
        return None
    try:
        pose = _current_local_pose(armature, rule.bone)
    except (AttributeError, ValueError, RuntimeError):
        return None
    return " / ".join(f"{math.degrees(value):.1f}°" for value in pose)


class BsCorrectivePreview:
    """3D range preview for the active corrective rule."""

    _handler_3d = None
    _handler_2d = None
    _armature_name = ""
    _slice_cache = {}

    @classmethod
    def invalidate(cls):
        cls._slice_cache.clear()
        AuxPreviewUtils.tag_redraw()

    @classmethod
    def show(cls, context, armature=None):
        armature = armature if armature is not None else getattr(context, "object", None)
        settings = settings_for(armature) if armature is not None else None
        if armature is None or armature.type != "ARMATURE" or settings is None:
            cls.clear()
            return
        cls._armature_name = armature.name
        AuxPreviewUtils.ensure_handlers(cls, cls._draw_3d, cls._draw_2d)
        AuxPreviewUtils.tag_redraw()

    @classmethod
    def clear(cls):
        cls._armature_name = ""
        cls._slice_cache.clear()
        AuxPreviewUtils.remove_handlers(cls)
        AuxPreviewUtils.tag_redraw()

    @classmethod
    def shutdown(cls):
        cls.clear()

    @staticmethod
    def _color(weight, enabled, authored_weight=1.0):
        authored = max(0.0, min(1.0, float(authored_weight)))
        if not enabled:
            return (0.20 + authored * 0.16, 0.22 + authored * 0.16, 0.30 + authored * 0.18,
                    0.24 + authored * 0.18)
        value = max(0.0, min(1.0, float(weight)))
        # Current RBF influence shifts blue toward orange; authored weight keeps
        # low-current points visible and independently changes their opacity.
        return (
            0.18 + 0.82 * value,
            0.62 - 0.34 * value,
            1.00 - 0.82 * value,
            0.18 + 0.48 * value + 0.28 * authored,
        )

    @classmethod
    def _pose_slices(cls, point):
        """Two swing arcs plus a small twist arc for the selected pose only."""
        key = (point.x, point.y, point.z, point.radius, point.weight)
        if key in cls._slice_cache:
            return cls._slice_cache[key]
        pose = Euler((point.x, point.y, point.z), "XYZ").to_quaternion()
        normalized = normalize_quaternion((pose.x, pose.y, pose.z, pose.w))
        groups = [[] for _ in range(8)]
        c = quaternion_angle(normalized, IDENTITY)
        if c < ANGLE_EPSILON:
            return groups
        for axis in ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)):
            arc = []
            for i in range(65):
                angle = point.radius * (2.0 * i / 64 - 1.0)
                rotation = pose @ Quaternion(axis, angle)
                q = normalize_quaternion((rotation.x, rotation.y, rotation.z, rotation.w))
                value = pose_weight(q, normalized, point.radius, point.weight, c)
                arc.append((rotation @ Vector((0.0, 1.0, 0.0)), value))
            for (a, wa), (b, wb) in zip(arc, arc[1:]):
                groups[min(7, int((wa + wb) * 0.5 / max(point.weight, 1e-9) * 7))].extend((a, b))
        # A local-Y twist leaves the bone direction unchanged. Draw it as a
        # small separate arc around the pose tip rather than pretending it is swing.
        arc = []
        for i in range(65):
            angle = point.radius * (2.0 * i / 64 - 1.0)
            rotation = pose @ Quaternion((0.0, 1.0, 0.0), angle)
            q = normalize_quaternion((rotation.x, rotation.y, rotation.z, rotation.w))
            value = pose_weight(q, normalized, point.radius, point.weight, c)
            arc.append((pose @ Vector((0.22 * math.sin(angle), 1.2, 0.22 * math.cos(angle))), value))
        for (a, wa), (b, wb) in zip(arc, arc[1:]):
            groups[min(7, int((wa + wb) * 0.5 / max(point.weight, 1e-9) * 7))].extend((a, b))
        if len(cls._slice_cache) > 64:
            cls._slice_cache.clear()
        cls._slice_cache[key] = groups
        return groups

    @classmethod
    def _draw_3d(cls):
        if not cls._armature_name:
            return
        armature = bpy.data.objects.get(cls._armature_name)
        settings = settings_for(armature)
        if armature is None or settings is None or not settings.preview_enabled:
            return
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)] if settings.rules else None
        if rule is None or not rule.enabled or not rule.bone:
            return
        bone = armature.pose.bones.get(rule.bone)
        if bone is None:
            return

        head = armature.matrix_world @ bone.head
        tail = armature.matrix_world @ bone.tail
        length = max((tail - head).length, 0.05)
        # Display uses rotations only; non-uniform scale must not distort the
        # angular guides into ellipses or shear them as the bone moves.
        frame = (armature.matrix_world.to_quaternion() @ bone.matrix.to_quaternion()
                 @ bone.matrix_basis.to_quaternion().inverted()).to_matrix()
        actual_direction = AuxPreviewUtils.safe_normalized_vector(tail - head)

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        gpu.state.line_width_set(2.0)
        try:
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            actual_lines = [tuple(head), tuple(tail)]
            AuxPreviewUtils.draw_lines(shader, actual_lines, (0.95, 0.95, 0.95, 0.9))
            if actual_direction is not None:
                AuxPreviewUtils.draw_points(shader, [tuple(head)], (1.0, 0.75, 0.15, 1.0), size=9.0)

            authored = _authored_points(rule)
            selected_point = rule.pose_points[min(rule.pose_active_index, len(rule.pose_points) - 1)] if rule.pose_points else None
            # Keep the selected halo on top when pose markers overlap.
            authored.sort(key=lambda point: selected_point is not None and selected_point.id == point.id)
            for point in authored:
                try:
                    weight = _display_rbf_weight(rule, point, armature)
                    if weight is None:
                        weight = 0.0
                    authored_weight = max(0.0, min(1.0, float(point.weight)))
                    pose_rotation = Euler((point.x, point.y, point.z), "XYZ").to_matrix()
                    ghost_rotation = frame @ pose_rotation
                    direction = ghost_rotation @ Vector((0.0, 1.0, 0.0))
                    enabled = bool(settings.enabled and rule.enabled and point.enabled)
                    color = cls._color(weight, enabled, authored_weight)
                    selected = selected_point is not None and selected_point.id == point.id
                    if selected:
                        gpu.state.line_width_set(2.5)
                        for level, vertices in enumerate(cls._pose_slices(point)):
                            lines = [tuple(head + frame @ vertex * length * 1.05) for vertex in vertices]
                            alpha = 0.18 + 0.72 * level / 7
                            AuxPreviewUtils.draw_lines(shader, lines, (0.30 + 0.70 * level / 7, 0.72, 1.0 - 0.65 * level / 7, alpha))
                        lines = [tuple(head), tuple(head + direction.normalized() * length * 1.35)]
                        gpu.state.line_width_set(3.5)
                        AuxPreviewUtils.draw_lines(shader, lines, (1.0, 0.82, 0.24, 1.0))
                        # Selection has its own gold halo, separate from the
                        # inner marker's blue-to-orange live output color.
                        AuxPreviewUtils.draw_points(
                            shader, [tuple(head + direction.normalized() * length * 1.35)],
                            (1.0, 0.82, 0.24, 1.0), size=17.0,
                        )
                    else:
                        color = (*color[:3], max(color[3], 0.85 if enabled else 0.60))
                    marker_size = 10.0 if selected else 9.0 + 3.0 * min(max(weight, 0.0), 1.0)
                    if not selected:
                        # A dark rim keeps idle poses readable on light meshes.
                        AuxPreviewUtils.draw_points(
                            shader, [tuple(head + direction.normalized() * length * 1.35)],
                            (0.035, 0.045, 0.065, 0.95), size=marker_size + 4.0,
                        )
                    AuxPreviewUtils.draw_points(
                        shader,
                        [tuple(head + direction.normalized() * length * 1.35)],
                        color,
                        size=marker_size,
                    )
                except (AttributeError, ValueError, RuntimeError, IndexError, TypeError):
                    continue
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")

    @classmethod
    def _draw_2d(cls):
        armature = bpy.data.objects.get(cls._armature_name) if cls._armature_name else None
        settings = settings_for(armature)
        if armature is None or settings is None or not settings.rules:
            return
        rule = settings.rules[min(settings.active_index, len(settings.rules) - 1)]
        if not settings.preview_enabled:
            return
        lines = [("BS 修型范围预览  ", rule.bone or "未指定骨骼")]
        lines.append(("范围显示  ", "金色为选中项 · 摆动弧 / 扭转弧"))
        try:
            current = euler_xyz_quaternion(_current_local_pose(armature, rule.bone))
        except (ValueError, RuntimeError, AttributeError):
            return
        selected = rule.pose_points[min(rule.pose_active_index, len(rule.pose_points) - 1)] if rule.pose_points else None
        for point in [selected] if selected is not None and selected.id != _BASE_POINT else ():
            weight = _display_rbf_weight(rule, point, armature)
            state = "启用" if point.enabled and (weight or 0.0) > 0.001 else "待命"
            lines.append(
                (f"▶ {point.bs_name}  ",
                 f"{state}  偏离 {math.degrees(quaternion_angle(current, euler_xyz_quaternion((point.x, point.y, point.z)))):.1f}°"
                 f" / {math.degrees(point.radius):.1f}°  "
                 f"目标 {point.weight:.2f}  当前 RBF {(weight or 0.0):.3f}")
            )
        font_id = 0
        begin_hud(font_id, size=14, shadow=True)
        draw_hud_lines(font_id, 20.0, 42.0, lines, line_height=20)
        end_hud(font_id, shadow=True)


def _active_rule(context):
    return _active_rule_for_armature(getattr(context, "object", None))


def _active_rule_for_armature(armature):
    settings = settings_for(armature) if armature else None
    return settings.rules[min(settings.active_index, len(settings.rules) - 1)] if settings and settings.rules else None


def _next_bs_name(settings):
    used = {
        point.bs_name.strip()
        for rule in settings.rules
        for point in _authored_points(rule)
        if point.bs_name.strip()
    }
    index = 1
    while f"_BSC_pose{index}" in used:
        index += 1
    return f"_BSC_pose{index}"


def _add_point(armature, rule, pose):
    if _rbf_distance(pose, (0.0, 0.0, 0.0)) < ANGLE_EPSILON:
        raise ValueError("修型姿态不能与基准姿态相同")
    _ensure_base_point(rule)
    point = rule.pose_points.add()
    point.id = uuid.uuid4().hex
    point.x, point.y, point.z = pose
    point.radius = math.radians(30.0)
    point.bs_name = ""
    point.bs_name = _next_bs_name(settings_for(armature))
    rule.pose_active_index = len(rule.pose_points) - 1
    return point


class _ArmatureOperator:
    @classmethod
    def poll(cls, context):
        return _context_armature(context) is not None


class OP_BsCorrectiveSelectBone(_ArmatureOperator, Operator):
    bl_idname = "hotools.bs_corrective_select_bone"
    bl_label = "选择规则骨骼"
    bl_description = "选择并激活这条规则的参考骨骼；物体模式下进入姿态模式，Shift 点击加选"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1, min=-1) # type: ignore
    extend: BoolProperty(default=False, options={"SKIP_SAVE"}) # type: ignore
    armature_name: StringProperty(default="", options={"SKIP_SAVE"})  # type: ignore

    def invoke(self, context, event):
        self.extend = bool(event.shift)
        return self.execute(context)

    def execute(self, context):
        from ..Utils.bone_selection import select_bones

        armature = _operator_armature(self, context)
        settings = settings_for(armature)
        if settings is None or not 0 <= self.index < len(settings.rules):
            return {"CANCELLED"}
        rule = settings.rules[self.index]
        bones = armature.data.edit_bones if armature.mode == "EDIT" else armature.data.bones
        bone = bones.get(rule.bone)
        if bone is None:
            self.report({"WARNING"}, f"参考骨骼不存在：{rule.bone or '未指定'}")
            return {"CANCELLED"}
        context.view_layer.objects.active = armature
        armature.select_set(True)
        if armature.mode == "OBJECT":
            bpy.ops.object.mode_set(mode="POSE")
        bone.hide = False
        bone.hide_select = False
        select_bones(armature, [rule.bone], extend=self.extend)
        settings.active_index = self.index
        return {"FINISHED"}


class OP_BsCorrectiveListEdit(_ArmatureOperator, Operator):
    """Native list controls for rules, influence meshes and authored poses."""
    bl_idname = "hotools.bs_corrective_list_edit"
    bl_label = "编辑修型列表"
    bl_options = {"REGISTER", "UNDO"}
    kind: bpy.props.EnumProperty(items=[(x, x, "") for x in ("RULES", "OBJECTS", "POINTS")]) # type: ignore
    action: bpy.props.EnumProperty(items=[(x, x, "") for x in ("ADD", "REMOVE", "CLEAR", "UP", "DOWN", "ENABLE", "DISABLE")]) # type: ignore
    index: bpy.props.IntProperty(default=-1) # type: ignore
    armature_name: StringProperty(default="", options={"SKIP_SAVE"})  # type: ignore

    @classmethod
    def description(cls, context, properties):
        kind = {"RULES": "规则", "OBJECTS": "影响物体", "POINTS": "修型姿势"}.get(properties.kind, "条目")
        if properties.action == "ADD" and properties.kind == "POINTS":
            return "记录参考骨骼的当前局部姿态并创建修型姿势"
        action = {"ADD": "添加", "REMOVE": "删除活动", "CLEAR": "清空全部", "UP": "上移活动", "DOWN": "下移活动",
                  "ENABLE": "启用全部", "DISABLE": "禁用全部"}.get(properties.action, "编辑")
        return action + kind

    def execute(self, context):
        armature = _operator_armature(self, context)
        settings = settings_for(armature)
        rule = _active_rule_for_armature(armature)
        if self.kind != "RULES" and rule is None:
            return {"CANCELLED"}
        collection, owner, index_property = {
            "RULES": (settings.rules, settings, "active_index"),
            "OBJECTS": (rule.influence_objects, rule, "influence_active_index") if rule else (None, None, ""),
            "POINTS": (rule.pose_points, rule, "pose_active_index") if rule else (None, None, ""),
        }[self.kind]
        index = self.index if self.index >= 0 else getattr(owner, index_property, max(0, len(collection) - 1))
        try:
            if self.action in {"ENABLE", "DISABLE"}:
                for item in settings.rules:
                    item.enabled = self.action == "ENABLE"
                return {"FINISHED"}
            if self.action == "ADD":
                if self.kind == "RULES":
                    item = collection.add()
                    item.id = uuid.uuid4().hex
                    bone = (
                        context.active_pose_bone or context.active_bone
                        if getattr(context, "object", None) is armature else None
                    )
                    if bone:
                        item.bone = bone.name
                    _ensure_base_point(item)
                elif self.kind == "POINTS":
                    _add_point(armature, rule, _current_local_pose(armature, rule.bone))
                    return {"FINISHED"}
                else:
                    collection.add()
                if owner:
                    setattr(owner, index_property, len(collection) - 1)
                return {"FINISHED"}
            if not collection:
                return {"CANCELLED"}
            if self.action in {"UP", "DOWN"}:
                target = index + (-1 if self.action == "UP" else 1)
                minimum = 1 if self.kind == "POINTS" else 0
                if not minimum <= index < len(collection) or not minimum <= target < len(collection):
                    return {"CANCELLED"}
                collection.move(index, target)
                if owner:
                    setattr(owner, index_property, target)
                return {"FINISHED"}
            if self.kind == "POINTS" and self.action == "REMOVE" and index == 0:
                self.report({"INFO"}, "基准姿态固定为零，不能删除")
                return {"CANCELLED"}
            if not 0 <= index < len(collection):
                return {"CANCELLED"}
            if self.kind in {"RULES", "POINTS"}:
                remove_native_drivers(armature, None if self.kind == "RULES" and self.action == "CLEAR" else [settings.active_index])
            if self.kind == "POINTS":
                if self.action == "CLEAR":
                    rule.pose_points.clear()
                    _ensure_base_point(rule)
                else:
                    for i, item in enumerate(rule.pose_points):
                        if item.id == collection[index].id:
                            rule.pose_points.remove(i)
                            break
                rule.driver_payload = ""
                rule.pose_active_index = min(index, max(0, len(rule.pose_points) - 1))
            else:
                if self.action == "CLEAR":
                    collection.clear()
                else:
                    collection.remove(index)
                if owner:
                    setattr(owner, index_property, min(index, max(0, len(collection) - 1)))
            return {"FINISHED"}
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class OP_BsCorrectivePose(_ArmatureOperator, Operator):
    bl_idname = "hotools.bs_corrective_pose"
    bl_label = "预览修型姿势"
    bl_description = "预览该修型姿势；只修改参考骨骼的局部旋转"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1, min=-1) # type: ignore
    armature_name: StringProperty(default="", options={"SKIP_SAVE"})  # type: ignore

    def execute(self, context):
        armature = _operator_armature(self, context)
        rule = _active_rule_for_armature(armature)
        if rule is None or not rule.pose_points:
            return {"CANCELLED"}
        index = self.index if self.index >= 0 else min(rule.pose_active_index, len(rule.pose_points) - 1)
        if not 0 <= index < len(rule.pose_points):
            return {"CANCELLED"}
        point = rule.pose_points[index]
        bone = armature.pose.bones.get(rule.bone)
        if bone is None:
            self.report({"ERROR"}, "请先指定参考骨骼")
            return {"CANCELLED"}
        from mathutils import Euler
        rotation = Euler((point.x, point.y, point.z), "XYZ")
        if bone.rotation_mode == "QUATERNION":
            bone.rotation_quaternion = rotation.to_quaternion()
        elif bone.rotation_mode == "AXIS_ANGLE":
            axis, angle = rotation.to_quaternion().to_axis_angle()
            bone.rotation_axis_angle = (angle, *axis)
        else:
            bone.rotation_euler = rotation.to_quaternion().to_euler(bone.rotation_mode)
        rule.pose_active_index = index
        context.view_layer.update()
        return {"FINISHED"}


class _BatchRuleOperator(_ArmatureOperator):
    # Shift always opens a confirmation dialog with an explicit all-rules checkbox.
    def invoke(self, context, event):
        self.all_rules = bool(event.shift)
        if self.all_rules:
            return context.window_manager.invoke_props_dialog(self, width=360)
        return self.execute(context)

    def draw(self, context):
        self.layout.prop(self, "all_rules")

    def indices(self, context):
        armature = _operator_armature(self, context)
        settings = settings_for(armature)
        return None if self.all_rules else [settings.active_index]


class OP_BsCorrectiveGenerateDrivers(_BatchRuleOperator, Operator):
    bl_idname = "hotools.bs_corrective_generate_drivers"
    bl_label = "刷新驱动"
    bl_description = "只更新已有目标形态键的驱动器；Shift 点击确认批量处理全部规则"
    bl_options = {"REGISTER", "UNDO"}
    all_rules: BoolProperty(name="处理全部规则", default=False) # type: ignore
    armature_name: StringProperty(default="", options={"SKIP_SAVE"})  # type: ignore

    def execute(self, context):
        armature = _operator_armature(self, context)
        warnings = []
        try:
            count = generate_native_drivers(armature, self.indices(context), warnings)
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for warning in warnings[:8]:
            self.report({"WARNING"}, warning)
        if len(warnings) > 8:
            self.report({"WARNING"}, f"另有 {len(warnings) - 8} 条刷新警告，详见控制台")
        self.report({"INFO"}, f"已刷新 {count} 条 BS 驱动器")
        return {"FINISHED"}


def reset_correctives(armature, overwrite=False, rule_indices=None, overwrite_targets=None, warnings=None):
    # Preflight the whole batch (including the solver) before removing anything.
    settings = settings_for(armature)
    if settings is not None:
        _validate_pose_names(settings)
    selected = _selected_rules(armature, rule_indices)
    for _, rule in selected:
        _validate_rule(armature, rule, require_targets=False)
        _compile_rbf(rule)
    targets = _collect_generated_targets(armature, rule_indices)
    _prepare_generated_shape_keys(targets, overwrite, overwrite_targets)
    return generate_native_drivers(armature, rule_indices, warnings)


class PG_BsCorrectiveResetTarget(PropertyGroup):
    """Transient per-key choices belonging only to the reset dialog."""
    # Operator properties cannot contain data-block pointers, even nested in a
    # collection. Mesh names resolve again when confirming or redoing the reset.
    mesh_name: StringProperty()  # type: ignore
    mesh_data_name: StringProperty()  # type: ignore
    key_name: StringProperty()  # type: ignore
    is_empty: BoolProperty()  # type: ignore
    overwrite: BoolProperty(
        name="覆盖",
        description="勾选后清空这个形态键的修型顶点；未勾选时保留顶点，仍刷新驱动器",
        default=False,
    )  # type: ignore


class HO_UL_BsCorrectiveResetTarget(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        toggle = row.row(align=True)
        toggle.enabled = not item.is_empty
        toggle.prop(item, "overwrite", text="")
        row.label(text=item.mesh_name, icon="MESH_DATA")
        row.label(text=item.key_name, icon="SHAPEKEY_DATA")
        row.label(text="空键 · 自动重置" if item.is_empty else "有修型")


class OP_BsCorrectiveReset(_BatchRuleOperator, Operator):
    bl_idname = "hotools.bs_corrective_reset"
    bl_label = "重置规则"
    bl_description = "创建缺失 BS、自动重置空键，逐项确认是否覆盖已有修型，并刷新全部目标驱动器；Shift 点击批量执行"
    bl_options = {"REGISTER", "UNDO"}
    all_rules: BoolProperty(name="处理全部规则", default=False) # type: ignore
    existing_keys: CollectionProperty(type=PG_BsCorrectiveResetTarget, options={"SKIP_SAVE"})  # type: ignore
    existing_active_index: bpy.props.IntProperty(default=0, min=0, options={"SKIP_SAVE"})  # type: ignore
    missing_count: bpy.props.IntProperty(default=0, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore
    scanned_all_rules: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore
    scan_error: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})  # type: ignore
    armature_name: StringProperty(default="", options={"SKIP_SAVE"})  # type: ignore

    def _scan_existing_keys(self, context):
        previous = {
            (item.mesh_data_name, item.key_name): bool(item.overwrite)
            for item in self.existing_keys if not item.is_empty
        }
        self.existing_keys.clear()
        self.missing_count = 0
        self.scanned_all_rules = self.all_rules
        self.scan_error = ""
        armature = _operator_armature(self, context)
        try:
            targets = _collect_generated_targets(armature, self.indices(context))
        except (ValueError, RuntimeError) as exc:
            self.scan_error = str(exc)
            return
        reference_cache = {}
        for _, mesh, name in targets:
            keys = mesh.data.shape_keys
            key = keys.key_blocks.get(name) if keys else None
            if key is None:
                self.missing_count += 1
                continue
            item = self.existing_keys.add()
            item.mesh_name, item.mesh_data_name, item.key_name = mesh.name, mesh.data.name, name
            item.is_empty = _shape_key_is_empty(key, reference_cache)
            item.overwrite = item.is_empty or previous.get((mesh.data.name, name), False)
        self.existing_active_index = min(self.existing_active_index, max(0, len(self.existing_keys) - 1))

    def invoke(self, context, event):
        self.all_rules = bool(event.shift)
        # Never inherit destructive selections from the previous invocation.
        self.existing_keys.clear()
        self._scan_existing_keys(context)
        return context.window_manager.invoke_props_dialog(self, width=620)

    def check(self, context):
        if self.scanned_all_rules != self.all_rules:
            self._scan_existing_keys(context)
            return True
        return False

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "all_rules")
        if self.scan_error:
            layout.label(text=self.scan_error, icon="ERROR")
            return
        empty_count = sum(item.is_empty for item in self.existing_keys)
        layout.label(
            text=f"新建 {self.missing_count} 个 · 空键自动重置 {empty_count} 个 · "
                 f"已有修型 {len(self.existing_keys) - empty_count} 个",
            icon="INFO",
        )
        if self.existing_keys:
            layout.label(text="勾选覆盖的键将清空修型；已有修型默认保留。")
            layout.template_list(
                HO_UL_BsCorrectiveResetTarget.__name__, "", self, "existing_keys",
                self, "existing_active_index", rows=min(8, max(3, len(self.existing_keys))),
            )
        layout.label(text="所有目标驱动器都会刷新，与是否覆盖修型无关。", icon="DRIVER")

    def execute(self, context):
        armature = _operator_armature(self, context)
        overwrite_targets = {
            (mesh.as_pointer(), item.key_name)
            for item in self.existing_keys
            if item.overwrite and not item.is_empty
            and (mesh := bpy.data.meshes.get(item.mesh_data_name)) is not None
        }
        warnings = []
        try:
            count = reset_correctives(
                armature, rule_indices=self.indices(context),
                overwrite_targets=overwrite_targets, warnings=warnings,
            )
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for warning in warnings[:8]:
            self.report({"WARNING"}, warning)
        if len(warnings) > 8:
            self.report({"WARNING"}, f"另有 {len(warnings) - 8} 条刷新警告")
        self.report({"INFO"}, f"已处理形态键并刷新 {count} 条 BS 驱动器")
        return {"FINISHED"}


def _list_button(layout, kind, action, icon, index=-1, armature=None):
    operator = layout.operator(OP_BsCorrectiveListEdit.bl_idname, text="", icon=icon)
    operator.kind, operator.action, operator.index = kind, action, index
    if armature is not None:
        operator.armature_name = armature.name
    return operator


def _draw_list(layout, list_type, owner, collection, active, kind, rows=4, armature=None):
    row = layout.row()
    row.template_list(list_type.__name__, kind, owner, collection, owner, active, rows=rows)
    buttons = row.column(align=True)
    _list_button(buttons, kind, "ADD", "ADD", armature=armature)
    _list_button(buttons, kind, "REMOVE", "REMOVE", armature=armature)
    _list_button(buttons, kind, "CLEAR", "TRASH", armature=armature)
    if kind == "RULES":
        buttons.separator()
        _list_button(buttons, kind, "ENABLE", "CHECKBOX_HLT", armature=armature)
        _list_button(buttons, kind, "DISABLE", "CHECKBOX_DEHLT", armature=armature)
    buttons.separator()
    _list_button(buttons, kind, "UP", "TRIA_UP", armature=armature)
    _list_button(buttons, kind, "DOWN", "TRIA_DOWN", armature=armature)


def draw_bs_corrective_header(layout, context, armature=None):
    """Keep the shared enable switch accessible in collapsed overview headers."""
    armature = armature if armature is not None else context.object
    if armature is not None and armature.type == "ARMATURE":
        settings = settings_for(armature)
        if settings is not None:
            layout.prop(settings, "enabled", text="")


def draw_bs_corrective_menu(layout:bpy.types.UILayout, context, armature=None):
    """One native three-list controller shared by Armature Properties and N-panel."""
    armature = armature if armature is not None else context.object
    if armature is None or armature.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return
    settings = settings_for(armature)
    rule = _active_rule_for_armature(armature)
    actions = layout.row(align=True)
    actions.operator_context = "INVOKE_DEFAULT"
    actions.enabled = rule is not None
    eye = actions.row(align=True)
    if settings.preview_enabled:
        eye.alert = True
    eye.prop(
        settings,
        "preview_enabled",
        text="",
        icon="HIDE_OFF" if settings.preview_enabled else "HIDE_ON",
        emboss=False,
    )
    eye.alert = False

    reset = actions.operator(OP_BsCorrectiveReset.bl_idname, text="重置规则", icon="FILE_REFRESH")
    reset.armature_name = armature.name
    refresh = actions.operator(OP_BsCorrectiveGenerateDrivers.bl_idname, text="刷新驱动", icon="DRIVER")
    refresh.armature_name = armature.name
    top = layout.split(factor=0.72)
    left, right = top.column(), top.column()
    _draw_list(left, HO_UL_BsCorrectiveRule, settings, "rules", "active_index", "RULES", rows=7, armature=armature)
    if rule is None:
        right.label(text="添加规则后，摆姿态并添加修型姿势。", icon="INFO")
        return
    _draw_list(right, HO_UL_BsCorrectiveInfluence, rule, "influence_objects", "influence_active_index", "OBJECTS", rows=7, armature=armature)
    _draw_list(layout, HO_UL_BsCorrectivePoint, rule, "pose_points", "pose_active_index", "POINTS", armature=armature)


def draw_bs_corrective_npanel(layout, context):
    """Draw the RBF N-panel against an explicitly selected armature object."""
    armature = getattr(context.scene, "hotools_bs_corrective_view_armature", None)
    header, body = layout.panel("hotools_bs_corrective_npanel", default_closed=False)
    draw_bs_corrective_header(header, context, armature=armature)
    header.label(text="修型总览", icon="SHAPEKEY_DATA")
    selector = header.row(align=True)
    selector.label(text="查看骨架")
    selector.prop(context.scene, "hotools_bs_corrective_view_armature", text="", icon="ARMATURE_DATA")
    if body is not None:
        if armature is None or getattr(armature, "type", None) != "ARMATURE":
            body.label(text="请选择骨架", icon="INFO")
            return
        draw_bs_corrective_menu(body, context, armature=armature)


def draw_bs_corrective_panel(layout, context):
    header, body = layout.panel("hotools_bs_corrective_overview", default_closed=False)
    draw_bs_corrective_header(header, context)
    header.label(text="修型总览", icon="SHAPEKEY_DATA")
    if body is not None:
        draw_bs_corrective_menu(body, context)


CLASSES = [
    PG_BsCorrectiveInfluenceObject, PG_BsCorrectivePosePoint,
    PG_BsCorrectiveRule, PG_BsCorrectiveSettings, PG_BsCorrectiveResetTarget,
    HO_UL_BsCorrectiveRule, HO_UL_BsCorrectiveInfluence, HO_UL_BsCorrectivePoint,
    HO_UL_BsCorrectiveResetTarget,
    OP_BsCorrectiveSelectBone, OP_BsCorrectiveListEdit, OP_BsCorrectivePose, OP_BsCorrectiveGenerateDrivers,
    OP_BsCorrectiveReset,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hotools_bs_corrective = PointerProperty(type=PG_BsCorrectiveSettings)
    bpy.types.Scene.hotools_bs_corrective_view_armature = PointerProperty(
        name="查看骨架", type=bpy.types.Object, poll=_armature_object_poll
    )
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _restore_driver_namespace not in handlers:
            handlers.append(_restore_driver_namespace)
    _register_driver_namespace(rebuild=False)


def unregister():
    BsCorrectivePreview.shutdown()
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _restore_driver_namespace in handlers:
            handlers.remove(_restore_driver_namespace)
    _unregister_driver_namespace()
    if hasattr(bpy.types.Object, "hotools_bs_corrective"):
        del bpy.types.Object.hotools_bs_corrective
    if hasattr(bpy.types.Scene, "hotools_bs_corrective_view_armature"):
        del bpy.types.Scene.hotools_bs_corrective_view_armature
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
