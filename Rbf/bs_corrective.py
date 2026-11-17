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
_RBF_UI_CACHE = {}
_BASE_POINT = "BASE"
def _update_enabled(self, context):
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
    point.bs_name = ""


class PG_BsCorrectiveInfluenceObject(PropertyGroup):
    """Mesh object included in the rule's authoring scope."""
    mesh: PointerProperty(name="目标网格", type=bpy.types.Object, poll=lambda self, obj: obj.type == "MESH")  # type: ignore


class PG_BsCorrectivePosePoint(PropertyGroup):
    """One authored pose and its generated shape-key name."""
    id: StringProperty(default="")  # type: ignore
    enabled: BoolProperty(name="启用", default=True, update=_update_pose_enabled)  # type: ignore
    bs_name: StringProperty(name="BS 名称", default="_BSC_pose1")  # type: ignore
    weight: FloatProperty(name="权重", default=1.0, min=0.0, max=1.0, subtype="FACTOR")  # type: ignore
    x: FloatProperty(name="X", default=0.0, unit="ROTATION")  # type: ignore
    y: FloatProperty(name="Y", default=0.0, unit="ROTATION")  # type: ignore
    z: FloatProperty(name="Z", default=0.0, unit="ROTATION")  # type: ignore


class PG_BsCorrectiveRule(PropertyGroup):
    id: StringProperty(default="")  # type: ignore
    enabled: BoolProperty(default=True, update=_update_enabled)  # type: ignore
    bone: StringProperty(name="测量骨骼", default="")  # type: ignore
    influence_objects: CollectionProperty(type=PG_BsCorrectiveInfluenceObject)  # type: ignore
    pose_points: CollectionProperty(type=PG_BsCorrectivePosePoint)  # type: ignore
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
    pose_active_index: bpy.props.IntProperty(default=0, min=0)  # type: ignore


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
    positions, pose_ids, matrix = _compile_rbf(rule)
    payload = {
        "radius": float(rule.rbf_radius),
        "positions": positions.tolist(),
        "coefficients": {pose_id: matrix[:, index].tolist() for index, pose_id in enumerate(pose_ids)},
    }
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    if persist:
        rule.driver_payload = encoded
    return encoded


def _compile_rbf(rule):
    """Factor the shared kernel once, solving all pose channels together."""
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
    values = np.zeros((len(positions), len(points)), dtype=np.float64)
    indices = {point.id: i + 1 for i, point in enumerate(points)}
    for column, point in enumerate(points):
        if point.id not in indices:
            raise ValueError("姿势引用了不存在的控制点")
        values[indices[point.id], column] = float(point.weight)
    try:
        coefficients = np.linalg.solve(kernel, values)
    except np.linalg.LinAlgError as exc:
        raise ValueError("RBF 控制点无法求解") from exc
    return positions, tuple(point.id for point in points), coefficients


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
    return positions, {pose_id: index for index, pose_id in enumerate(coefficients)}, matrix, 1.0 / (2 * radius * radius)


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


def _validate_outputs(armature, rule_indices=None):
    """Reject conflicting outputs and foreign drivers before touching the graph."""
    settings = settings_for(armature)
    if settings is not None:
        _validate_pose_names(settings)
    requested = set()
    for _, rule in _selected_rules(armature):
        if not rule.enabled:
            continue
        for _, mesh, shape_key in _rule_outputs(rule):
            key = (mesh.data.as_pointer(), shape_key)
            if key in requested:
                raise ValueError(f"目标形态键被多个规则重复使用：{mesh.name}/{shape_key}")
            requested.add(key)
    for _, rule in _selected_rules(armature, rule_indices):
        if not rule.enabled:
            continue
        _validate_rule(armature, rule)
        for _, mesh, shape_key in _rule_outputs(rule):
            key = mesh.data.shape_keys.key_blocks[shape_key]
            animation = key.id_data.animation_data
            for fcurve in animation.drivers if animation else []:
                if fcurve.data_path == key.path_from_id("value") and not _owned_driver(fcurve, armature, {rule.id}):
                    raise ValueError(f"目标已有其他驱动器：{mesh.name}/{shape_key}")


def generate_native_drivers(armature, rule_indices=None):
    """Create Blender drivers and resync every pose's enabled state."""
    settings = settings_for(armature)
    if settings is None:
        return 0
    _sync_pose_enabled(armature, rule_indices)
    if not settings.enabled:
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
            for point, mesh, shape_key in _rule_outputs(rule):
                shape_keys = mesh.data.shape_keys
                key = shape_keys.key_blocks.get(shape_key) if shape_keys else None
                if key is None:
                    continue
                # Use the X transform variable as the ownership marker; driver
                # FCurves are not reliably attached to Action groups in Blender 4.5.
                driver = _shape_key_driver_add(key)
                _set_driver_marker(driver, armature, rule.bone)
                expression = _rbf_namespace_expression(rule, point)
                _set_driver_expression(driver, expression)
                for channel in "YZ":
                    _set_transform_variable(driver, channel.lower(), armature, rule.bone, channel)
                generated += 1
        _sync_pose_enabled(armature, rule_indices)
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


def _collect_generated_targets(armature, overwrite=True, rule_indices=None):
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
                    if not overwrite:
                        animation = existing.id_data.animation_data
                        for fcurve in animation.drivers if animation else []:
                            if fcurve.data_path == existing.path_from_id("value") and not _owned_driver(fcurve, armature, {rule.id}):
                                raise ValueError(f"目标已有其他驱动器：{mesh.name}/{name}")
                targets.append((point, mesh, name))
    return targets


def _remove_shape_key_drivers(key):
    animation = key.id_data.animation_data
    for fcurve in list(animation.drivers) if animation else []:
        if fcurve.data_path == key.path_from_id("value"):
            key.id_data.driver_remove(fcurve.data_path, fcurve.array_index)


def _prepare_generated_shape_keys(armature, overwrite=True, rule_indices=None):
    """Create each rule's named output key before attaching native drivers."""
    targets = _collect_generated_targets(armature, overwrite, rule_indices)
    for point, mesh, name in targets:
        shape_keys = mesh.data.shape_keys
        existing = shape_keys.key_blocks.get(name) if shape_keys else None
        if mesh.data.shape_keys is None:
            mesh.shape_key_add(name="Basis", from_mix=False)
        if existing is None:
            mesh.shape_key_add(name=name, from_mix=False)
        elif overwrite:
            # Preserve key identity, relative-key references and topology.
            _remove_shape_key_drivers(existing)
            basis = mesh.data.shape_keys.reference_key
            coordinates = np.empty(len(basis.data) * 3, dtype=np.float32)
            basis.data.foreach_get("co", coordinates)
            existing.data.foreach_set("co", coordinates)
            existing.relative_key = basis
            existing.mute = False
    return len(targets)


class HO_UL_BsCorrectiveRule(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        select = row.row(align=True)
        select.enabled = bool(item.bone)
        select.operator("hotools.bs_corrective_select_bone", text="", icon="RESTRICT_SELECT_OFF").index = index
        armature = context.object if context.object and context.object.type == "ARMATURE" else None
        if armature is not None:
            row.prop_search(item, "bone", armature.data, "bones", text="")
        else:
            row.prop(item, "bone", text="")
        row.prop(item, "rbf_radius", text="")
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
            preview.operator("hotools.bs_corrective_pose", text="基准姿态", icon="MOD_ARMATURE").index = index
        else:
            row.prop(item, "enabled", text="")
            preview = row.row(align=False)
            preview.enabled = bool(data.bone)
            preview.operator("hotools.bs_corrective_pose", text="", icon="OUTLINER_OB_ARMATURE").index = index
            row.prop(item, "bs_name", text="", emboss=False)
            row.label(text=f"{math.degrees(item.x):.1f}° / {math.degrees(item.y):.1f}° / {math.degrees(item.z):.1f}°")
            weight = _display_rbf_weight(data, item, context.object)
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
        tuple((p.id, float(p.x), float(p.y), float(p.z)) for p in _authored_points(rule)),
        float(rule.rbf_radius),
        current,
    )
    cache_key = (armature.as_pointer(), signature)
    cached = _RBF_UI_CACHE.get(cache_key)
    if cached is None:
        item = _RBF_RUNTIME.get(rule.id)
        try:
            if item is None:
                item = _decode_rbf_payload(_encode_rbf_payload(rule, persist=False))
            values = _evaluate_rbf_outputs(item, current)
            cached = {pose_id: float(values[index]) for pose_id, index in item[1].items()}
        except (KeyError, TypeError, ValueError, RuntimeError, np.linalg.LinAlgError):
            cached = {}
        if len(_RBF_UI_CACHE) > 128:
            _RBF_UI_CACHE.clear()
        _RBF_UI_CACHE[cache_key] = cached
    return cached.get(point.id)


def _display_bone_rotation(rule, armature):
    if armature is None or not rule.bone:
        return None
    try:
        pose = _current_local_pose(armature, rule.bone)
    except (AttributeError, ValueError, RuntimeError):
        return None
    return " / ".join(f"{math.degrees(value):.1f}°" for value in pose)


def _active_rule(context):
    settings = settings_for(context.object) if context.object else None
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
    if any(_rbf_distance(pose, point) < 1e-5 for point in _rule_points(rule)):
        raise ValueError("当前姿态已存在；请先摆出新的局部旋转姿态")
    _ensure_base_point(rule)
    point = rule.pose_points.add()
    point.id = uuid.uuid4().hex
    point.x, point.y, point.z = pose
    point.bs_name = ""
    point.bs_name = _next_bs_name(settings_for(armature))
    rule.pose_active_index = len(rule.pose_points) - 1
    return point


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
    """Native list controls for rules, influence meshes and authored poses."""
    bl_idname = "hotools.bs_corrective_list_edit"
    bl_label = "编辑修型列表"
    bl_options = {"REGISTER", "UNDO"}
    kind: bpy.props.EnumProperty(items=[(x, x, "") for x in ("RULES", "OBJECTS", "POINTS")]) # type: ignore
    action: bpy.props.EnumProperty(items=[(x, x, "") for x in ("ADD", "REMOVE", "CLEAR", "UP", "DOWN", "ENABLE", "DISABLE")]) # type: ignore
    index: bpy.props.IntProperty(default=-1) # type: ignore

    @classmethod
    def description(cls, context, properties):
        kind = {"RULES": "规则", "OBJECTS": "影响物体", "POINTS": "修型姿势"}.get(properties.kind, "条目")
        if properties.action == "ADD" and properties.kind == "POINTS":
            return "记录参考骨骼的当前局部姿态并创建修型姿势"
        action = {"ADD": "添加", "REMOVE": "删除活动", "CLEAR": "清空全部", "UP": "上移活动", "DOWN": "下移活动",
                  "ENABLE": "启用全部", "DISABLE": "禁用全部"}.get(properties.action, "编辑")
        return action + kind

    def execute(self, context):
        armature = context.object
        settings = settings_for(armature)
        rule = _active_rule(context)
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
                    bone = context.active_pose_bone or context.active_bone
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
        if self.all_rules or self.bl_idname == "hotools.bs_corrective_reset":
            return context.window_manager.invoke_props_dialog(self, width=360)
        return self.execute(context)

    def draw(self, context):
        self.layout.prop(self, "all_rules")
        if self.bl_idname == "hotools.bs_corrective_reset":
            self.layout.prop(self, "overwrite_existing")
            self.layout.label(text="按规则影响物体生成同名姿势 BS。", icon="INFO")
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
    settings = settings_for(armature)
    if settings is not None:
        _validate_pose_names(settings)
    selected = _selected_rules(armature, rule_indices)
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
    bl_description = "按规则影响物体生成姿势 BS 并添加驱动器；可选择覆盖已有 BS；Shift 点击批量执行"
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


def _list_button(layout, kind, action, icon, index=-1):
    operator = layout.operator(OP_BsCorrectiveListEdit.bl_idname, text="", icon=icon)
    operator.kind, operator.action, operator.index = kind, action, index
    return operator


def _draw_list(layout, list_type, owner, collection, active, kind, rows=4):
    row = layout.row()
    row.template_list(list_type.__name__, kind, owner, collection, owner, active, rows=rows)
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


def draw_bs_corrective_header(layout, context):
    """Keep the shared enable switch accessible in collapsed overview headers."""
    armature = context.object
    if armature is not None and armature.type == "ARMATURE":
        settings = settings_for(armature)
        if settings is not None:
            layout.prop(settings, "enabled", text="")


def draw_bs_corrective_menu(layout, context):
    """One native three-list controller shared by Armature Properties and N-panel."""
    armature = context.object
    if armature is None or armature.type != "ARMATURE":
        layout.label(text="请选择骨架", icon="INFO")
        return
    settings = settings_for(armature)
    rule = _active_rule(context)
    actions = layout.row(align=True)
    actions.enabled = rule is not None
    actions.operator(OP_BsCorrectiveReset.bl_idname, text="重置规则", icon="FILE_REFRESH")
    actions.operator(OP_BsCorrectiveGenerateDrivers.bl_idname, text="刷新驱动", icon="DRIVER")
    top = layout.split(factor=0.72)
    left, right = top.column(), top.column()
    _draw_list(left, HO_UL_BsCorrectiveRule, settings, "rules", "active_index", "RULES", rows=7)
    if rule is None:
        right.label(text="添加规则后，摆姿态并添加修型姿势。", icon="INFO")
        return
    _draw_list(right, HO_UL_BsCorrectiveInfluence, rule, "influence_objects", "influence_active_index", "OBJECTS", rows=7)
    _draw_list(layout, HO_UL_BsCorrectivePoint, rule, "pose_points", "pose_active_index", "POINTS")


def draw_bs_corrective_panel(layout, context):
    header, body = layout.panel("hotools_bs_corrective_overview", default_closed=False)
    draw_bs_corrective_header(header, context)
    header.label(text="修型总览", icon="SHAPEKEY_DATA")
    if body is not None:
        draw_bs_corrective_menu(body, context)


CLASSES = [
    PG_BsCorrectiveInfluenceObject, PG_BsCorrectivePosePoint,
    PG_BsCorrectiveRule, PG_BsCorrectiveSettings,
    HO_UL_BsCorrectiveRule, HO_UL_BsCorrectiveInfluence, HO_UL_BsCorrectivePoint,
    OP_BsCorrectiveSelectBone, OP_BsCorrectiveListEdit, OP_BsCorrectivePose, OP_BsCorrectiveGenerateDrivers,
    OP_BsCorrectiveReset,
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
