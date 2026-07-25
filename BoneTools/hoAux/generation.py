"""HoAux creation, naming, collections, shared bones, and rollback."""

from dataclasses import dataclass

import bpy

from .properties import ensure_rig_id


COLLECTION_KEY_PROP = "hoaux_key"
COLLECTION_RIG_PROP = "hoaux_rig_id"


def iter_hoaux_bones(armature_data):
    for bone in armature_data.bones:
        props = getattr(bone, "hotools_boneprops", None)
        info = getattr(props, "hoAux", None) if props else None
        if info is not None and info.isHoAuxBone:
            yield bone


def find_bone_by_key(armature_data, name_key: str):
    if not name_key:
        return None
    for bone in iter_hoaux_bones(armature_data):
        if bone.hotools_boneprops.hoAux.nameKey == name_key:
            return bone
    return None


def allocate_bone_name(armature_data, preferred_name: str) -> str:
    if armature_data.bones.get(preferred_name) is None:
        return preferred_name
    index = 1
    while armature_data.bones.get(f"{preferred_name}.{index:03d}") is not None:
        index += 1
    return f"{preferred_name}.{index:03d}"


def find_collection(armature_data, collection_key: str):
    collections = getattr(armature_data, "collections_all", armature_data.collections)
    for collection in collections:
        if collection.get(COLLECTION_KEY_PROP) == collection_key:
            return collection
    return None


def ensure_collection(
    armature_data,
    collection_key: str,
    preferred_name: str,
    parent=None,
    *,
    visible_on_create=True,
):
    collection = find_collection(armature_data, collection_key)
    if collection is None:
        collection = armature_data.collections.new(preferred_name)
        collection[COLLECTION_KEY_PROP] = collection_key
        collection[COLLECTION_RIG_PROP] = ensure_rig_id(armature_data)
        collection.is_visible = visible_on_create
    if parent is not None and collection.parent != parent:
        collection.parent = parent
    return collection


def ensure_base_tree(armature_data):
    return {
        "root": ensure_collection(
            armature_data,
            "HOAUX:ROOT",
            "HoAux",
            visible_on_create=True,
        )
    }


def collections_for_bone(armature_data, info):
    root = ensure_base_tree(armature_data)["root"]
    tag = info.roleTag if info.roleTag in {"DEF", "TRK", "DIR"} else "OTHER"
    return [
        ensure_collection(
            armature_data,
            f"HOAUX:TAG:{tag}",
            tag,
            root,
            visible_on_create=tag == "DEF",
        )
    ]


def assign_bone(armature_data, bone):
    info = bone.hotools_boneprops.hoAux
    if not info.isHoAuxBone:
        return []
    assigned = []
    for collection in collections_for_bone(armature_data, info):
        collection.assign(bone)
        assigned.append(collection)
    return assigned


def restore_armature_mode(obj, desired_mode):
    if obj.mode == desired_mode:
        return
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    if desired_mode != "OBJECT":
        bpy.ops.object.mode_set(mode=desired_mode)


class GenerationTransaction:
    def __init__(self, armature_object):
        self.armature_object = armature_object
        self.original_mode = armature_object.mode
        self.created_bones = []
        self.created_constraints = []
        self.created_drivers = []
        self._committed = False

    def track_bone(self, bone_name):
        self.created_bones.append(bone_name)

    def track_constraint(self, owner_name, constraint):
        self.created_constraints.append((owner_name, constraint))

    def track_driver(self, fcurve):
        self.created_drivers.append(fcurve)

    def commit(self):
        self._committed = True

    def rollback(self):
        obj = self.armature_object
        animation_data = obj.animation_data
        if animation_data is not None:
            for fcurve in reversed(self.created_drivers):
                try:
                    animation_data.drivers.remove(fcurve)
                except (ReferenceError, RuntimeError):
                    pass

        for owner_name, constraint in reversed(self.created_constraints):
            pose_bone = obj.pose.bones.get(owner_name)
            if pose_bone is None:
                continue
            try:
                pose_bone.constraints.remove(constraint)
            except (ReferenceError, RuntimeError):
                pass

        if self.created_bones:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            if obj.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                for bone_name in reversed(self.created_bones):
                    edit_bone = obj.data.edit_bones.get(bone_name)
                    if edit_bone is not None:
                        obj.data.edit_bones.remove(edit_bone)
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if not self._committed:
                self.rollback()
        finally:
            self.restore_original_mode()
        return False

    def restore_original_mode(self):
        restore_armature_mode(self.armature_object, self.original_mode)


@dataclass(frozen=True)
class SharedDirectionSpec:
    parent_name: str
    source_name: str
    head: object
    tail: object
    roll_reference: object
    owner_space: str = "LOCAL"
    target_space: str = "LOCAL"
    mix_mode: str = "REPLACE"
    influence: float = 0.5


def _close_vector(actual, expected, tolerance):
    return (actual - expected).length <= tolerance


def find_shared_direction(armature_data, shared_key):
    if not shared_key:
        return None
    matches = [
        bone
        for bone in iter_hoaux_bones(armature_data)
        if bone.hotools_boneprops.hoAux.roleTag == "DIR"
        and bone.hotools_boneprops.hoAux.sharedKey == shared_key
    ]
    if len(matches) > 1:
        names = ", ".join(bone.name for bone in matches)
        raise ValueError(f"共享 DIR 键 {shared_key} 存在多个实例：{names}")
    return matches[0] if matches else None


def validate_shared_direction(armature_object, bone, spec, *, tolerance=1e-5):
    errors = []
    if bone.parent is None or bone.parent.name != spec.parent_name:
        errors.append(f"parent={bone.parent.name if bone.parent else '<none>'}")
    if not _close_vector(bone.head_local, spec.head, tolerance):
        errors.append("head")
    if not _close_vector(bone.tail_local, spec.tail, tolerance):
        errors.append("tail")
    direction = (bone.tail_local - bone.head_local).normalized()
    actual_roll = bone.matrix_local.to_3x3().col[2]
    expected_roll = spec.roll_reference - direction * spec.roll_reference.dot(direction)
    if expected_roll.length <= tolerance:
        errors.append("rollReferenceDegenerate")
    elif actual_roll.normalized().dot(expected_roll.normalized()) < 1.0 - tolerance:
        errors.append("roll")

    pose_bone = armature_object.pose.bones.get(bone.name)
    constraints = [] if pose_bone is None else [
        constraint
        for constraint in pose_bone.constraints
        if constraint.type == "COPY_ROTATION"
        and getattr(constraint, "target", None) == armature_object
        and getattr(constraint, "subtarget", "") == spec.source_name
    ]
    if len(constraints) != 1:
        errors.append(f"copyRotationCount={len(constraints)}")
    else:
        constraint = constraints[0]
        for field_name, expected in (
            ("owner_space", spec.owner_space),
            ("target_space", spec.target_space),
            ("mix_mode", spec.mix_mode),
        ):
            actual = getattr(constraint, field_name)
            if actual != expected:
                errors.append(f"{field_name}={actual}")
        if abs(constraint.influence - spec.influence) > tolerance:
            errors.append(f"influence={constraint.influence:.6g}")

    if errors:
        raise ValueError(
            f"共享 DIR {bone.name} 与请求签名不一致：{', '.join(errors)}"
        )
    return bone


def create_edit_bone(edit_bones, plan, actual_name):
    bone = edit_bones.new(actual_name)
    bone.head = plan.head
    bone.tail = plan.tail
    bone.parent = edit_bones.get(plan.parent_name)
    bone.use_connect = False
    bone.align_roll(plan.roll_reference)
    return bone


def write_bone_metadata(
    bone,
    *,
    rig_id,
    pipeline_id,
    module_id,
    module_type,
    generation_id,
    role_tag,
    part,
    function,
    marker,
    side,
    name_key,
    shared_key="",
):
    info = bone.hotools_boneprops.hoAux
    info.isHoAuxBone = True
    info.rigId = rig_id
    info.pipelineId = pipeline_id
    info.moduleId = module_id
    info.moduleType = module_type
    info.roleTag = role_tag
    info.part = part
    info.function = function
    info.marker = marker
    info.side = side
    info.generationId = generation_id
    info.sharedKey = shared_key
    info.nameKey = name_key
    bone.use_deform = role_tag == "DEF"


def add_copy_rotation(
    owner,
    target_object,
    target_bone,
    transaction,
    *,
    name="HoAux Copy Rotation",
    owner_space="LOCAL",
    target_space="LOCAL_OWNER_ORIENT",
    mix_mode="REPLACE",
    influence=1.0,
):
    constraint = owner.constraints.new("COPY_ROTATION")
    constraint.name = name
    constraint.target = target_object
    constraint.subtarget = target_bone
    constraint.owner_space = owner_space
    constraint.target_space = target_space
    constraint.mix_mode = mix_mode
    constraint.influence = influence
    transaction.track_constraint(owner.name, constraint)
    return constraint


def add_copy_location(
    owner,
    target_object,
    target_bone,
    transaction,
    *,
    name="HoAux Copy Location",
    owner_space="WORLD",
    target_space="WORLD",
    head_tail=1.0,
    influence=0.0,
):
    constraint = owner.constraints.new("COPY_LOCATION")
    constraint.name = name
    constraint.target = target_object
    constraint.subtarget = target_bone
    constraint.owner_space = owner_space
    constraint.target_space = target_space
    constraint.head_tail = head_tail
    constraint.influence = influence
    transaction.track_constraint(owner.name, constraint)
    return constraint


def add_stretch_to(
    owner,
    target_object,
    target_bone,
    transaction,
    *,
    name="HoAux Stretch To",
    owner_space="WORLD",
    target_space="WORLD",
    head_tail=0.0,
    rest_length=0.0,
    influence=1.0,
    volume="NO_VOLUME",
    keep_axis="SWING_Y",
    bulge=1.0,
    use_bulge_min=False,
    use_bulge_max=False,
    bulge_min=1.0,
    bulge_max=1.0,
    bulge_smooth=0.0,
):
    constraint = owner.constraints.new("STRETCH_TO")
    constraint.name = name
    constraint.target = target_object
    constraint.subtarget = target_bone
    constraint.owner_space = owner_space
    constraint.target_space = target_space
    constraint.head_tail = head_tail
    constraint.rest_length = rest_length
    constraint.influence = influence
    constraint.volume = volume
    constraint.keep_axis = keep_axis
    constraint.bulge = bulge
    constraint.use_bulge_min = use_bulge_min
    constraint.use_bulge_max = use_bulge_max
    constraint.bulge_min = bulge_min
    constraint.bulge_max = bulge_max
    constraint.bulge_smooth = bulge_smooth
    transaction.track_constraint(owner.name, constraint)
    return constraint


def response_expression(full_response_angle_degrees):
    scale = 360.0 / full_response_angle_degrees
    return f"abs(asin(var)*{scale:.9g}/pi)"


def signed_response_expression(
    full_response_angle_degrees,
    *,
    sign=1.0,
    multiplier=1.0,
):
    scale = 360.0 / full_response_angle_degrees
    scale *= sign * multiplier
    return f"clamp(asin(var)*{scale:.9g}/pi)"


def delayed_response_expression(
    full_response_angle_degrees,
    *,
    onset=0.5,
):
    base = response_expression(full_response_angle_degrees)
    multiplier = 1.0 / (1.0 - onset)
    return f"clamp({base}-{onset:.9g})*{multiplier:.9g}"


def add_transform_driver(
    driven_owner,
    driven_property,
    armature_object,
    source_bone,
    transform_type,
    expression,
    transaction,
    *,
    transform_space="LOCAL_SPACE",
    rotation_mode="QUATERNION",
):
    fcurve = driven_owner.driver_add(driven_property)
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    driver.expression = expression
    variable = driver.variables.new()
    variable.name = "var"
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = armature_object
    target.bone_target = source_bone
    target.transform_type = transform_type
    target.transform_space = transform_space
    target.rotation_mode = rotation_mode
    transaction.track_driver(fcurve)
    return fcurve
