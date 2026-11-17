"""HoTools BS corrective authoring, native drivers, and HoFBX metadata."""
import json
import math
import uuid

import numpy as np

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

SCHEMA = "hotools.bs-corrective"
VERSION = 3
_DRIVER_MARKER = "hotoolsBscMarker"
_DRIVER_NAMESPACE_FUNCTION = "hotools_bs_rbf"
_RBF_RUNTIME = {}
_RBF_CACHE = {}
_BASE_POINT = "BASE"
_SYNCING_SELECTION = False


def _sync_point_selection(rule, context):
    global _SYNCING_SELECTION
    if _SYNCING_SELECTION or not rule.pose_points:
        return
    point = rule.pose_points[min(rule.pose_active_index, len(rule.pose_points) - 1)]
    if point.id == _BASE_POINT:
        _SYNCING_SELECTION = True
        try:
            rule.task_active_index = -1
        finally:
            _SYNCING_SELECTION = False
        return
    for index, task in enumerate(rule.tasks):
        if task.point_id == point.id:
            _SYNCING_SELECTION = True
            try:
                rule.task_active_index = index
            finally:
                _SYNCING_SELECTION = False
            break


def _sync_task_selection(rule, context):
    global _SYNCING_SELECTION
    if _SYNCING_SELECTION or not rule.tasks or rule.task_active_index < 0:
        return
    task = rule.tasks[min(rule.task_active_index, len(rule.tasks) - 1)]
    for index, point in enumerate(rule.pose_points):
        if point.id == task.point_id:
            _SYNCING_SELECTION = True
            try:
                rule.pose_active_index = index
            finally:
                _SYNCING_SELECTION = False
            break


def _update_enabled(self, context):
    armature = self.id_data
    settings = settings_for(armature)
    if settings is None:
        return
    for rule in settings.rules:
        for keys in bpy.data.shape_keys:
            animation = keys.animation_data
            for fcurve in animation.drivers if animation else []:
                if _owned_driver(fcurve, armature, {rule.id}):
                    fcurve.mute = not (settings.enabled and rule.enabled)
                    if fcurve.mute:
                        keys.path_resolve(fcurve.data_path.rsplit(".", 1)[0]).value = 0.0
            keys.update_tag()


def _current_local_pose(armature, bone_name):
    pose_bone = armature.pose.bones.get(bone_name) if armature and bone_name else None
    if pose_bone is None:
        raise ValueError(f"测量骨骼不存在：{bone_name}")
    euler = pose_bone.matrix_basis.to_euler("XYZ")
    return (float(euler.x), float(euler.y), float(euler.z))


def _rbf_distance(a, b):
    # Euler angles wrap at +/-pi. Keep Blender and Unity on the same metric so
    # a pose near 179 degrees is close to one near -179 degrees.
    return math.sqrt(sum(_shortest_angle(a[i] - b[i]) ** 2 for i in range(3)))


def _shortest_angle(value):
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _rule_points(rule):
    """Return the implicit zero pose followed by authored control points."""
    return [(0.0, 0.0, 0.0)] + [(point.x, point.y, point.z) for point in _authored_points(rule)]


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
    point.task_id = ""


class PG_BsCorrectiveInfluenceObject(PropertyGroup):
    """Mesh object included in the rule's authoring scope."""
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object, poll=lambda self, obj: obj.type == "MESH")  # type: ignore


class PG_BsCorrectiveTaskTarget(PropertyGroup):
    """One mesh/shape-key output owned by a corrective task."""
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object, poll=lambda self, obj: obj.type == "MESH")  # type: ignore
    shape_key: StringProperty(name="目标形态键", default="")  # type: ignore


class PG_BsCorrectivePosePoint(PropertyGroup):
    """One authored local-rotation sample for an RBF rule."""
    id: StringProperty(default="")  # type: ignore
    x: FloatProperty(name="X", default=0.0, unit="ROTATION")  # type: ignore
    y: FloatProperty(name="Y", default=0.0, unit="ROTATION")  # type: ignore
    z: FloatProperty(name="Z", default=0.0, unit="ROTATION")  # type: ignore
    task_id: StringProperty(name="修型任务", default="")  # type: ignore


class PG_BsCorrectiveTask(PropertyGroup):
    """An output channel linked to exactly one RBF pose point."""
    id: StringProperty(default="")  # type: ignore
    bs_name: StringProperty(name="BS 名称", default="_BSC_pose1")  # type: ignore
    point_id: StringProperty(name="控制点", default="")  # type: ignore
    targets: CollectionProperty(type=PG_BsCorrectiveTaskTarget)  # type: ignore


class PG_BsCorrectiveRule(PropertyGroup):
    id: StringProperty(default="")  # type: ignore
    enabled: BoolProperty(default=True, update=_update_enabled)  # type: ignore
    bone: StringProperty(name="测量骨骼", default="")  # type: ignore
    influence_objects: CollectionProperty(type=PG_BsCorrectiveInfluenceObject)  # type: ignore
    pose_points: CollectionProperty(type=PG_BsCorrectivePosePoint)  # type: ignore
    tasks: CollectionProperty(type=PG_BsCorrectiveTask)  # type: ignore
    comment: StringProperty(default="")  # type: ignore
    rbf_radius: FloatProperty(
        name="RBF 半径",
        default=math.radians(30.0),
        min=0.001,
        max=100.0,
        subtype="ANGLE",
    )  # type: ignore
    # Compiled RBF data is serialized with the rule so the runtime namespace
    # can be rebuilt after opening a .blend without using custom properties.
    driver_payload: StringProperty(default="")  # type: ignore
    influence_active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore
    pose_active_index: bpy.props.IntProperty(default=0, min=0, update=_sync_point_selection)  # type: ignore
    task_active_index: bpy.props.IntProperty(default=-1, min=-1, update=_sync_task_selection)  # type: ignore


class PG_BsCorrectiveSettings(PropertyGroup):
    enabled: BoolProperty(name="启用 BS 修型", default=True, update=_update_enabled)  # type: ignore
    rules: CollectionProperty(type=PG_BsCorrectiveRule)  # type: ignore
    active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore


def settings_for(armature):
    return getattr(armature, "hotools_bs_corrective", None)


def _find_bone(armature, name):
    return armature.data.bones.get(name) if armature and name else None


def _shape_names(mesh):
    keys = getattr(getattr(mesh, "data", None), "shape_keys", None)
    return [key.name for key in keys.key_blocks] if keys else []


def _task_for_point(rule, point_id):
    for task in rule.tasks:
        if task.point_id == point_id:
            return task
    return None


def _point_for_task(rule, task):
    for point in rule.pose_points:
        if point.id == task.point_id:
            return point
    return None


def _rule_outputs(rule):
    for task in rule.tasks:
        point = _point_for_task(rule, task)
        if point is None:
            continue
        for target in task.targets:
            yield task, point, target


def _validate_rule(armature, rule, require_targets=True):
    if not rule.bone or _find_bone(armature, rule.bone) is None:
        raise ValueError(f"测量骨骼不存在：{rule.bone}")
    points = _authored_points(rule)
    if not points:
        raise ValueError("RBF 至少需要一个姿态控制点")
    point_ids = {point.id for point in points if point.id}
    if len(point_ids) != len(points):
        raise ValueError("控制点 id 为空或重复")
    task_ids = {task.id for task in rule.tasks if task.id}
    if len(task_ids) != len(rule.tasks):
        raise ValueError("修型任务 id 为空或重复")
    used_points = set()
    for task in rule.tasks:
        if not task.bs_name.strip():
            raise ValueError("修型任务 BS 名称不能为空")
        point = _point_for_task(rule, task)
        if point is None or point.id == _BASE_POINT or task.point_id in used_points or point.task_id != task.id:
            raise ValueError("每个修型任务必须唯一链接一个控制点")
        used_points.add(task.point_id)
        if require_targets and not task.targets:
            raise ValueError(f"修型任务缺少目标：{task.bs_name}")
        for target in task.targets if require_targets else []:
            if target.mesh is None or target.mesh.type != "MESH":
                raise ValueError("目标网格必须是 Mesh 对象")
            if target.shape_key not in _shape_names(target.mesh):
                raise ValueError(f"找不到形态键：{target.shape_key}")
            if not target.mesh.data.shape_keys.use_relative:
                raise ValueError(f"BS 修型仅支持相对形态键：{target.mesh.name}")
    if used_points != point_ids:
        raise ValueError("每个控制点必须对应一个修型任务")
    if not math.isfinite(rule.rbf_radius) or rule.rbf_radius <= 0:
        raise ValueError("RBF 半径必须为正数")


def build_export_config(armature, fbx_bone_axes="Y_X", measurement_bones=None):
    """Return a JSON-ready config; this is deliberately side-effect free."""
    settings = settings_for(armature)
    if settings is None or not settings.enabled:
        return None
    result = {
        "schema": SCHEMA,
        "version": VERSION,
        "poseSpace": "LOCAL",
        "rotationOrder": "XYZ",
        "angleUnit": "radian",
        "kernel": "gaussian",
        "fbxBoneAxes": fbx_bone_axes,
        "measurement": "source_local_rotation",
        "rules": [],
    }
    names, outputs = set(), set()
    for rule in settings.rules:
        _validate_rule(armature, rule)
        _compile_rbf(rule)
        for task in rule.tasks:
            if task.bs_name in names:
                raise ValueError(f"修型任务 BS 名称重复：{task.bs_name}")
            names.add(task.bs_name)
            for target in task.targets:
                output = (target.mesh.data.as_pointer(), target.shape_key)
                if rule.enabled and output in outputs:
                    raise ValueError(f"目标形态键重复：{target.mesh.name}/{target.shape_key}")
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
            "tasks": [
                {
                    "id": task.id,
                    "bsName": task.bs_name,
                    "pointId": task.point_id,
                    "targets": [
                        {"mesh": target.mesh.name, "shapeKey": target.shape_key}
                        for target in task.targets
                    ],
                }
                for task in rule.tasks
            ],
            "comment": rule.comment,
            "rbf": {
                "radius": rule.rbf_radius,
                "includeBase": True,
                "basePose": [0.0, 0.0, 0.0],
                "controlPoints": [
                    {"id": point.id, "pose": [point.x, point.y, point.z]}
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
    positions, task_ids, matrix = _compile_rbf(rule)
    payload = {
        "radius": float(rule.rbf_radius),
        "positions": positions.tolist(),
        "coefficients": {task_id: matrix[:, index].tolist() for index, task_id in enumerate(task_ids)},
    }
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    if persist:
        rule.driver_payload = encoded
    return encoded


def _compile_rbf(rule):
    """Factor the shared kernel once, solving all task channels together."""
    points = _authored_points(rule)
    positions = np.asarray(_rule_points(rule), dtype=np.float64)
    if not np.isfinite(positions).all() or not math.isfinite(rule.rbf_radius) or rule.rbf_radius <= 0:
        raise ValueError("RBF 输入必须为有限数值，半径必须大于零")
    delta = (positions[:, None, :] - positions[None, :, :] + math.pi) % (2 * math.pi) - math.pi
    distance_squared = np.einsum("ijk,ijk->ij", delta, delta)
    if np.any(distance_squared[np.triu_indices(len(positions), 1)] < 1e-10):
        raise ValueError("RBF 控制点过近或重复，无法求解")
    kernel = np.exp(-distance_squared / (2.0 * rule.rbf_radius ** 2))
    kernel.flat[::len(positions) + 1] += 1e-6
    values = np.zeros((len(positions), len(rule.tasks)), dtype=np.float64)
    indices = {point.id: i + 1 for i, point in enumerate(points)}
    for column, task in enumerate(rule.tasks):
        if task.point_id not in indices:
            raise ValueError("修型任务引用了不存在的控制点")
        values[indices[task.point_id], column] = 1.0
    try:
        coefficients = np.linalg.solve(kernel, values)
    except np.linalg.LinAlgError as exc:
        raise ValueError("RBF 控制点无法求解") from exc
    return positions, tuple(task.id for task in rule.tasks), coefficients


def _decode_rbf_payload(encoded):
    payload = json.loads(encoded)
    positions = payload["positions"]
    coefficients = payload["coefficients"]
    if not positions or not coefficients:
        raise ValueError("RBF 驱动数据为空或长度不一致")
    if any(len(position) != 3 for position in positions):
        raise ValueError("RBF 驱动姿态必须包含 XYZ 三个值")
    if any(len(values) != len(positions) for values in coefficients.values()):
        raise ValueError("RBF 系数与控制点数量不一致")
    positions = np.asarray(positions, dtype=np.float64)
    matrix = np.ascontiguousarray(list(coefficients.values()), dtype=np.float64)
    radius = float(payload["radius"])
    if not np.isfinite(positions).all() or not np.isfinite(matrix).all() or not math.isfinite(radius) or radius <= 0:
        raise ValueError("RBF 驱动数据必须为有限数值，半径必须大于零")
    if matrix.size < 64:
        positions = tuple(tuple(float(value) for value in row) for row in positions)
        matrix = tuple(tuple(float(value) for value in row) for row in matrix)
    return positions, {task_id: index for index, task_id in enumerate(coefficients)}, matrix, 1.0 / (2 * radius * radius)


def _evaluate_rbf_outputs(item, current):
    positions, _, coefficients, radius_term = item
    # Recompute the Gaussian vector only once for ALL output channels. Small
    # rules avoid NumPy setup; larger rules use its bundled vectorized path.
    if isinstance(coefficients, tuple):
        x, y, z = current
        kernels = []
        for px, py, pz in positions:
            dx, dy, dz = _shortest_angle(x - px), _shortest_angle(y - py), _shortest_angle(z - pz)
            kernels.append(math.exp(-(dx * dx + dy * dy + dz * dz) * radius_term))
        return tuple(min(max(sum(c * k for c, k in zip(row, kernels)), 0.0), 1.0) for row in coefficients)
    delta = (np.asarray(current) - positions + math.pi) % (2 * math.pi) - math.pi
    kernels = np.exp(-np.einsum("ij,ij->i", delta, delta) * radius_term)
    return tuple(np.clip(coefficients @ kernels, 0.0, 1.0))


def _driver_namespace_rbf(rule_id, task_id, x, y, z):
    """Evaluate one serialized rule from Blender's driver namespace."""
    rule_id = str(rule_id)
    task_id = str(task_id)
    item = _RBF_RUNTIME.get(rule_id)
    if item is None:
        return 0.0
    index = item[1].get(task_id)
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


@persistent
def _restore_driver_namespace(_):
    _register_driver_namespace()


def _set_driver_marker(driver, armature, bone_name):
    """The X input doubles as the ownership marker, avoiding a fourth fetch."""
    _set_transform_variable(driver, _DRIVER_MARKER, armature, bone_name, "X")


def _rbf_namespace_expression(rule, task):
    if not rule.id:
        rule.id = uuid.uuid4().hex
    # The rule id is persisted in the controller; only the function itself
    # must be restored into bpy.app.driver_namespace after opening a file.
    return f'{_DRIVER_NAMESPACE_FUNCTION}({json.dumps(rule.id)},{json.dumps(task.id)},{_DRIVER_MARKER},y,z)'


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


def _validate_outputs(armature, rule_indices=None):
    """Reject conflicting outputs and foreign drivers before touching the graph."""
    requested = set()
    for _, rule in _selected_rules(armature):
        if not rule.enabled:
            continue
        for _, _, target in _rule_outputs(rule):
            if target.mesh:
                key = (target.mesh.data.as_pointer(), target.shape_key)
                if key in requested:
                    raise ValueError(f"目标形态键被多个任务重复使用：{target.mesh.name}/{target.shape_key}")
                requested.add(key)
    for _, rule in _selected_rules(armature, rule_indices):
        if not rule.enabled:
            continue
        _validate_rule(armature, rule)
        for _, _, target in _rule_outputs(rule):
            key = target.mesh.data.shape_keys.key_blocks[target.shape_key]
            animation = key.id_data.animation_data
            for fcurve in animation.drivers if animation else []:
                if fcurve.data_path == key.path_from_id("value") and not _owned_driver(fcurve, armature, {rule.id}):
                    raise ValueError(f"目标已有其他驱动器：{target.mesh.name}/{target.shape_key}")


def generate_native_drivers(armature, rule_indices=None):
    """Create Blender drivers for enabled rules, caching one RBF result per pose."""
    settings = settings_for(armature)
    if settings is None or not settings.enabled:
        return 0
    _validate_outputs(armature, rule_indices)
    prepared = {}
    for _, rule in _selected_rules(armature, rule_indices):
        if rule.enabled:
            if not rule.id:
                rule.id = uuid.uuid4().hex
            encoded = _encode_rbf_payload(rule, persist=False)
            prepared[rule.id] = encoded, _decode_rbf_payload(encoded)
    remove_native_drivers(armature, rule_indices)
    _register_driver_namespace(rebuild=False)
    generated = 0
    try:
        for _, rule in _selected_rules(armature, rule_indices):
            if not rule.enabled:
                continue
            rule.driver_payload, _RBF_RUNTIME[rule.id] = prepared[rule.id]
            _RBF_CACHE.pop(rule.id, None)
            for task, _, target_rule in _rule_outputs(rule):
                shape_keys = target_rule.mesh.data.shape_keys
                key = shape_keys.key_blocks.get(target_rule.shape_key) if shape_keys else None
                if key is None:
                    continue
                # Use the X transform variable as the ownership marker; driver
                # FCurves are not reliably attached to Action groups in Blender 4.5.
                driver = _shape_key_driver_add(key)
                _set_driver_marker(driver, armature, rule.bone)
                expression = _rbf_namespace_expression(rule, task)
                _set_driver_expression(driver, expression)
                for channel in "YZ":
                    _set_transform_variable(driver, channel.lower(), armature, rule.bone, channel)
                generated += 1
    except Exception:
        # Do not leave a truncated or half-generated driver graph behind.
        remove_native_drivers(armature, rule_indices)
        raise
    return generated


def remove_native_drivers(armature, rule_indices=None):
    """Remove only drivers generated by this controller, preserving user drivers."""
    settings = settings_for(armature)
    if settings is None:
        return 0
    removed = 0
    rule_ids = {rule.id for _, rule in _selected_rules(armature, rule_indices) if rule.id}
    # Search by ownership, not by the current targets: editing a target or
    # deleting a task must not strand the old generated driver.
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


def _collect_generated_targets(armature, overwrite=True, rule_indices=None):
    """Validate reset names and return the target/name pairs to create."""
    settings = settings_for(armature)
    if settings is None:
        return []
    requested = set()
    requested_targets = set()
    targets = []
    selected = set(rule_indices) if rule_indices is not None else None
    untouched_outputs = {
        (target.mesh.data.as_pointer(), target.shape_key)
        for index, other in enumerate(settings.rules)
        if selected is not None and index not in selected
        for _, _, target in _rule_outputs(other) if target.mesh
    }
    for rule_index, rule in enumerate(settings.rules):
        if selected is not None and rule_index not in selected:
            continue
        for task in rule.tasks:
            name = (task.bs_name or "").strip()
            if not name:
                raise ValueError("BS 名称不能为空")
            if name in requested:
                raise ValueError(f"规则 BS 名称冲突：{name}")
            requested.add(name)
            meshes = ([item.mesh for item in rule.influence_objects] or
                      list(dict.fromkeys(target.mesh for target in task.targets)))
            if not meshes:
                raise ValueError(f"规则缺少影响物体：{rule.bone}")
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
                    animation = existing.id_data.animation_data
                    for fcurve in animation.drivers if animation else []:
                        if fcurve.data_path == existing.path_from_id("value") and not _owned_driver(fcurve, armature, {rule.id}):
                            raise ValueError(f"目标已有其他驱动器：{mesh.name}/{name}")
                targets.append((task, mesh, name))
    return targets


def _prepare_generated_shape_keys(armature, overwrite=True, rule_indices=None):
    """Create each rule's named output key before attaching native drivers."""
    targets = _collect_generated_targets(armature, overwrite, rule_indices)
    cleared = set()
    for task, mesh, name in targets:
        if task.as_pointer() not in cleared:
            task.targets.clear()
            cleared.add(task.as_pointer())
        shape_keys = mesh.data.shape_keys
        existing = shape_keys.key_blocks.get(name) if shape_keys else None
        if mesh.data.shape_keys is None:
            mesh.shape_key_add(name="Basis", from_mix=False)
        if existing is None:
            mesh.shape_key_add(name=name, from_mix=False)
        elif overwrite:
            # Preserve key identity, relative-key references and topology.
            basis = mesh.data.shape_keys.reference_key
            coordinates = np.empty(len(basis.data) * 3, dtype=np.float32)
            basis.data.foreach_get("co", coordinates)
            existing.data.foreach_set("co", coordinates)
            existing.relative_key = basis
            existing.mute = False
        target = task.targets.add()
        target.mesh = mesh
        target.shape_key = name
    return len(targets)


class HO_UL_BsCorrectiveRule(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=f"{index + 1}. {item.bone or '未指定骨骼'}", icon="BONE_DATA")
        row.label(text=str(len(item.tasks)))
        select = row.row(align=True)
        select.enabled = bool(item.bone)
        select.operator("hotools.bs_corrective_select_bone", text="", icon="RESTRICT_SELECT_OFF").index = index


class HO_UL_BsCorrectiveInfluence(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "mesh", text="", emboss=False)


class HO_UL_BsCorrectivePoint(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.id == _BASE_POINT:
            row.label(text="0. 基准姿态 · 0° / 0° / 0°", icon="LOCKED")
        else:
            task = _task_for_point(data, item.id)
            row.label(text=f"{index}. {task.bs_name if task else '未关联任务'}", icon="KEY_HLT")
        preview = row.row(align=True)
        preview.enabled = bool(data.bone)
        preview.operator("hotools.bs_corrective_pose", text="", icon="HIDE_OFF").index = index


class HO_UL_BsCorrectiveTask(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        point_index = next((i for i, point in enumerate(data.pose_points) if point.id == item.point_id), -1)
        row.label(text=f"点 {point_index}", icon="KEY_HLT")
        row.prop(item, "bs_name", text="", emboss=False)
        row.label(text=f"{len(item.targets)} 目标")


def _active_rule(context):
    settings = settings_for(context.object) if context.object else None
    return settings.rules[min(settings.active_index, len(settings.rules) - 1)] if settings and settings.rules else None


def _active_task(rule):
    return rule.tasks[rule.task_active_index] if rule and 0 <= rule.task_active_index < len(rule.tasks) else None


def _next_bs_name(settings):
    used = {task.bs_name for rule in settings.rules for task in rule.tasks}
    index = 1
    while f"_BSC_pose{index}" in used:
        index += 1
    return f"_BSC_pose{index}"


def _add_point(armature, rule, pose):
    if any(_rbf_distance(pose, point) < 1e-5 for point in _rule_points(rule)):
        raise ValueError("当前姿态已存在；请先摆出新的局部旋转姿态")
    _ensure_base_point(rule)
    point = rule.pose_points.add()
    point.id = uuid.uuid4().hex
    point.x, point.y, point.z = pose
    name = _next_bs_name(settings_for(armature))
    task = rule.tasks.add()
    task.id = uuid.uuid4().hex
    task.point_id = point.id
    task.bs_name = name
    point.task_id = task.id
    for item in rule.influence_objects:
        if item.mesh:
            target = task.targets.add()
            target.mesh, target.shape_key = item.mesh, task.bs_name
    rule.pose_active_index = len(rule.pose_points) - 1
    rule.task_active_index = len(rule.tasks) - 1
    return point, task


class _ArmatureOperator:
    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "ARMATURE"


class OP_BsCorrectiveSelectBone(_ArmatureOperator, Operator):
    bl_idname = "hotools.bs_corrective_select_bone"
    bl_label = "选择规则骨骼"
    bl_description = "选择并激活这条规则的参考骨骼；物体模式下进入姿态模式，Shift 点击加选"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1, min=-1) # type: ignore
    extend: BoolProperty(default=False, options={"SKIP_SAVE"}) # type: ignore

    def invoke(self, context, event):
        self.extend = bool(event.shift)
        return self.execute(context)

    def execute(self, context):
        from ..Utils.bone_selection import select_bones

        armature = context.object
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
    """Native list controls; removing data also releases its generated drivers."""
    bl_idname = "hotools.bs_corrective_list_edit"
    bl_label = "编辑修型列表"
    bl_options = {"REGISTER", "UNDO"}
    kind: bpy.props.EnumProperty(items=[(x, x, "") for x in ("RULES", "OBJECTS", "POINTS", "TASKS", "TARGETS")]) # type: ignore
    action: bpy.props.EnumProperty(items=[(x, x, "") for x in ("ADD", "REMOVE", "CLEAR", "UP", "DOWN", "ENABLE", "DISABLE")]) # type: ignore
    index: bpy.props.IntProperty(default=-1) # type: ignore

    @classmethod
    def description(cls, context, properties):
        kind = {"RULES": "规则", "OBJECTS": "影响物体", "POINTS": "控制点及对应任务",
                "TASKS": "修型任务及对应控制点", "TARGETS": "任务目标"}.get(properties.kind, "条目")
        if properties.action == "ADD" and properties.kind in {"POINTS", "TASKS"}:
            return "记录参考骨骼的当前局部姿态，并创建一一对应的控制点和修型任务"
        action = {"ADD": "添加", "REMOVE": "删除活动", "CLEAR": "清空全部", "UP": "上移活动", "DOWN": "下移活动",
                  "ENABLE": "启用全部", "DISABLE": "禁用全部"}.get(properties.action, "编辑")
        return action + kind

    def execute(self, context):
        armature = context.object
        settings = settings_for(armature)
        rule = _active_rule(context)
        task = _active_task(rule)
        if self.kind != "RULES" and rule is None or self.kind == "TARGETS" and task is None:
            return {"CANCELLED"}
        collection, owner, index_property = {
            "RULES": (settings.rules, settings, "active_index"),
            "OBJECTS": (rule.influence_objects, rule, "influence_active_index") if rule else (None, None, ""),
            "POINTS": (rule.pose_points, rule, "pose_active_index") if rule else (None, None, ""),
            "TASKS": (rule.tasks, rule, "task_active_index") if rule else (None, None, ""),
            "TARGETS": (task.targets, None, "") if task else (None, None, ""),
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
                    bone = context.active_pose_bone or context.active_bone
                    if bone:
                        item.bone = bone.name
                    _ensure_base_point(item)
                elif self.kind in {"POINTS", "TASKS"}:
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
            if self.kind in {"RULES", "POINTS", "TASKS", "TARGETS"}:
                remove_native_drivers(armature, None if self.kind == "RULES" and self.action == "CLEAR" else [settings.active_index])
            if self.kind in {"POINTS", "TASKS"}:
                if self.action == "CLEAR":
                    rule.tasks.clear()
                    rule.pose_points.clear()
                    _ensure_base_point(rule)
                else:
                    point_id = collection[index].id if self.kind == "POINTS" else collection[index].point_id
                    for i, item in enumerate(rule.tasks):
                        if item.point_id == point_id:
                            rule.tasks.remove(i)
                            break
                    for i, item in enumerate(rule.pose_points):
                        if item.id == point_id:
                            rule.pose_points.remove(i)
                            break
                rule.driver_payload = ""
                rule.pose_active_index = min(index, max(0, len(rule.pose_points) - 1))
                rule.task_active_index = min(rule.task_active_index, max(0, len(rule.tasks) - 1))
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
    bl_label = "控制点姿态"
    bl_description = "预览该控制点姿态并定位对应修型任务；只修改参考骨骼的局部旋转"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1, min=-1) # type: ignore
    capture: BoolProperty(default=False) # type: ignore

    def execute(self, context):
        rule = _active_rule(context)
        if rule is None or not rule.pose_points:
            return {"CANCELLED"}
        index = self.index if self.index >= 0 else min(rule.pose_active_index, len(rule.pose_points) - 1)
        if not 0 <= index < len(rule.pose_points):
            return {"CANCELLED"}
        point = rule.pose_points[index]
        bone = context.object.pose.bones.get(rule.bone)
        if bone is None:
            self.report({"ERROR"}, "请先指定参考骨骼")
            return {"CANCELLED"}
        if self.capture:
            if point.id == _BASE_POINT:
                return {"CANCELLED"}
            pose = _current_local_pose(context.object, rule.bone)
            if any(_rbf_distance(pose, (item.x, item.y, item.z)) < 1e-5
                   for item in rule.pose_points if item.id != point.id):
                self.report({"ERROR"}, "当前姿态与已有控制点重复")
                return {"CANCELLED"}
            point.x, point.y, point.z = pose
        else:
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
        if not self.capture:
            context.view_layer.update()
        return {"FINISHED"}


class _BatchRuleOperator(_ArmatureOperator):
    # Shift always opens a confirmation dialog with an explicit all-rules checkbox.
    def invoke(self, context, event):
        self.all_rules = bool(event.shift)
        if self.all_rules or self.bl_idname == "hotools.bs_corrective_reset":
            return context.window_manager.invoke_props_dialog(self, width=360)
        return self.execute(context)

    def draw(self, context):
        self.layout.prop(self, "all_rules")
        if self.bl_idname == "hotools.bs_corrective_reset":
            self.layout.prop(self, "overwrite_existing")
            self.layout.label(text="按影响物体重建任务目标，并生成同名 BS。", icon="INFO")
            self.layout.label(text="关闭覆盖将保留已有 BS 的修型数据。")

    def indices(self, context):
        return None if self.all_rules else [settings_for(context.object).active_index]


class OP_BsCorrectiveGenerateDrivers(_BatchRuleOperator, Operator):
    bl_idname = "hotools.bs_corrective_generate_drivers"
    bl_label = "刷新驱动"
    bl_description = "只更新已有目标形态键的驱动器；Shift 点击确认批量处理全部规则"
    bl_options = {"REGISTER", "UNDO"}
    all_rules: BoolProperty(name="处理全部规则", default=False) # type: ignore

    def execute(self, context):
        try:
            count = generate_native_drivers(context.object, self.indices(context))
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已刷新 {count} 条 BS 驱动器")
        return {"FINISHED"}


def reset_correctives(armature, overwrite=True, rule_indices=None):
    # Preflight the whole batch (including the solver) before removing anything.
    selected = _selected_rules(armature, rule_indices)
    names = set()
    for _, rule in _selected_rules(armature):
        for task in rule.tasks:
            name = task.bs_name.strip()
            if not name or name in names:
                raise ValueError(f"修型任务 BS 名称为空或重复：{name}")
            names.add(name)
    for _, rule in selected:
        _validate_rule(armature, rule, require_targets=False)
        _compile_rbf(rule)
    _collect_generated_targets(armature, overwrite, rule_indices)
    remove_native_drivers(armature, rule_indices)
    _prepare_generated_shape_keys(armature, overwrite, rule_indices)
    return generate_native_drivers(armature, rule_indices)


class OP_BsCorrectiveReset(_BatchRuleOperator, Operator):
    bl_idname = "hotools.bs_corrective_reset"
    bl_label = "重置规则"
    bl_description = "按影响物体生成任务 BS 并添加驱动器；可选择覆盖已有 BS；Shift 点击批量执行"
    bl_options = {"REGISTER", "UNDO"}
    all_rules: BoolProperty(name="处理全部规则", default=False) # type: ignore
    overwrite_existing: BoolProperty(name="覆盖同名形态键", default=True) # type: ignore

    def execute(self, context):
        try:
            count = reset_correctives(context.object, self.overwrite_existing, self.indices(context))
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已重置规则并生成 {count} 条 BS 驱动器")
        return {"FINISHED"}


class OP_BsCorrectiveRemoveDrivers(_BatchRuleOperator, Operator):
    bl_idname = "hotools.bs_corrective_remove_drivers"
    bl_label = "移除驱动"
    bl_description = "移除活动规则生成的驱动器；Shift 点击确认批量处理全部规则"
    bl_options = {"REGISTER", "UNDO"}
    all_rules: BoolProperty(name="处理全部规则", default=False) # type: ignore

    def execute(self, context):
        count = remove_native_drivers(context.object, self.indices(context))
        self.report({"INFO"}, f"已移除 {count} 条 BS 驱动器")
        return {"FINISHED"}


class OP_BsCorrectiveClearControls(_BatchRuleOperator, Operator):
    bl_idname = "hotools.bs_corrective_clear_controls"
    bl_label = "删除控件"
    bl_description = "删除活动规则的控制点、任务及其驱动器，保留已生成的 BS；Shift 点击确认批量执行"
    bl_options = {"REGISTER", "UNDO"}
    all_rules: BoolProperty(name="处理全部规则", default=False) # type: ignore

    def execute(self, context):
        armature = context.object
        remove_native_drivers(armature, self.indices(context))
        for _, rule in _selected_rules(armature, self.indices(context)):
            rule.pose_points.clear()
            rule.tasks.clear()
            rule.driver_payload = ""
            _ensure_base_point(rule)
            rule.pose_active_index = rule.task_active_index = 0
        return {"FINISHED"}


def _list_button(layout, kind, action, icon, index=-1):
    operator = layout.operator(OP_BsCorrectiveListEdit.bl_idname, text="", icon=icon)
    operator.kind, operator.action, operator.index = kind, action, index
    return operator


def _draw_list(layout, title, list_type, owner, collection, active, kind, rows=4):
    layout.label(text=title)
    row = layout.row()
    buttons = row.column(align=True)
    _list_button(buttons, kind, "ADD", "ADD")
    _list_button(buttons, kind, "REMOVE", "REMOVE")
    _list_button(buttons, kind, "CLEAR", "TRASH")
    if kind == "RULES":
        buttons.separator()
        _list_button(buttons, kind, "ENABLE", "CHECKBOX_HLT")
        _list_button(buttons, kind, "DISABLE", "CHECKBOX_DEHLT")
    buttons.separator()
    _list_button(buttons, kind, "UP", "TRIA_UP")
    _list_button(buttons, kind, "DOWN", "TRIA_DOWN")
    row.template_list(list_type.__name__, kind, owner, collection, owner, active, rows=rows)


def draw_bs_corrective_header(layout, context):
    """Keep the shared enable switch accessible in collapsed overview headers."""
    armature = context.object
    if armature is not None and armature.type == "ARMATURE":
        settings = settings_for(armature)
        if settings is not None:
            layout.prop(settings, "enabled", text="")


def draw_bs_corrective_menu(layout, context):
    """One native four-list controller shared by Armature Properties and N-panel."""
    armature = context.object
    if armature is None or armature.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return
    settings = settings_for(armature)
    top = layout.split(factor=0.5)
    left, right = top.column(), top.column()
    _draw_list(left, "规则", HO_UL_BsCorrectiveRule, settings, "rules", "active_index", "RULES")
    rule = _active_rule(context)
    if rule is None:
        right.label(text="添加规则后，摆姿态并添加控制点。", icon="INFO")
        return
    _draw_list(right, "控制点 → 修型任务", HO_UL_BsCorrectivePoint, rule, "pose_points", "pose_active_index", "POINTS")
    bottom = layout.split(factor=0.5)
    left, right = bottom.column(), bottom.column()
    _draw_list(left, "影响物体", HO_UL_BsCorrectiveInfluence, rule, "influence_objects", "influence_active_index", "OBJECTS")
    _draw_list(right, "修型任务", HO_UL_BsCorrectiveTask, rule, "tasks", "task_active_index", "TASKS")
    detail = layout.box()
    detail.label(text=f"活动规则 · {settings.active_index + 1}", icon="BONE_DATA")
    detail.prop_search(rule, "bone", armature.data, "bones", text="参考骨骼")
    detail.prop(rule, "rbf_radius", text="影响半径")
    detail.prop(rule, "comment", text="注释")
    if rule.pose_points:
        point = rule.pose_points[min(rule.pose_active_index, len(rule.pose_points) - 1)]
        row = detail.row(align=True)
        values = row.row(align=True)
        values.enabled = point.id != _BASE_POINT
        for axis in "xyz":
            values.prop(point, axis, text=axis.upper())
    task = _active_task(rule)
    if task:
        detail.separator()
        detail.prop(task, "bs_name", text="生成 BS 名称")
        header = detail.row(align=True)
        header.label(text="活动任务目标 · 物体 / 形态键")
        _list_button(header, "TARGETS", "ADD", "ADD")
        _list_button(header, "TARGETS", "CLEAR", "TRASH")
        for index, target in enumerate(task.targets):
            row = detail.row(align=True)
            row.prop(target, "mesh", text="")
            keys = target.mesh.data.shape_keys if target.mesh and target.mesh.type == "MESH" else None
            if keys:
                row.prop_search(target, "shape_key", keys, "key_blocks", text="")
            else:
                row.prop(target, "shape_key", text="")
            _list_button(row, "TARGETS", "REMOVE", "X", index)
            _list_button(row, "TARGETS", "UP", "TRIA_UP", index)
            _list_button(row, "TARGETS", "DOWN", "TRIA_DOWN", index)
    row = detail.row(align=True)
    row.operator(OP_BsCorrectiveReset.bl_idname, text="重置规则", icon="FILE_REFRESH")
    row.operator(OP_BsCorrectiveGenerateDrivers.bl_idname, text="刷新驱动", icon="DRIVER")
    row = detail.row(align=True)
    row.operator(OP_BsCorrectiveRemoveDrivers.bl_idname, text="移除驱动", icon="X")
    row.operator(OP_BsCorrectiveClearControls.bl_idname, text="删除控件", icon="TRASH")
    detail.label(text="Shift 点击操作按钮：确认后处理全部规则", icon="INFO")


def draw_bs_corrective_panel(layout, context):
    header, body = layout.panel("hotools_bs_corrective_overview", default_closed=False)
    draw_bs_corrective_header(header, context)
    header.label(text="修型总览", icon="SHAPEKEY_DATA")
    if body is not None:
        draw_bs_corrective_menu(body, context)


CLASSES = [
    PG_BsCorrectiveInfluenceObject, PG_BsCorrectiveTaskTarget, PG_BsCorrectivePosePoint,
    PG_BsCorrectiveTask, PG_BsCorrectiveRule, PG_BsCorrectiveSettings,
    HO_UL_BsCorrectiveRule, HO_UL_BsCorrectiveInfluence, HO_UL_BsCorrectivePoint, HO_UL_BsCorrectiveTask,
    OP_BsCorrectiveSelectBone, OP_BsCorrectiveListEdit, OP_BsCorrectivePose, OP_BsCorrectiveGenerateDrivers,
    OP_BsCorrectiveReset, OP_BsCorrectiveRemoveDrivers, OP_BsCorrectiveClearControls,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hotools_bs_corrective = PointerProperty(type=PG_BsCorrectiveSettings)
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _restore_driver_namespace not in handlers:
            handlers.append(_restore_driver_namespace)
    _register_driver_namespace(rebuild=False)


def unregister():
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _restore_driver_namespace in handlers:
            handlers.remove(_restore_driver_namespace)
    _unregister_driver_namespace()
    if hasattr(bpy.types.Object, "hotools_bs_corrective"):
        del bpy.types.Object.hotools_bs_corrective
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
