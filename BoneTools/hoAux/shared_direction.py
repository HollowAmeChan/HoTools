"""Shared DIR lookup for HoAux module generation."""

from dataclasses import dataclass

from .name_registry import iter_hoaux_bones


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


def validate_shared_direction(
    armature_object,
    bone,
    spec,
    *,
    tolerance=1e-5,
):
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
        detail = ", ".join(errors)
        raise ValueError(
            f"共享 DIR {bone.name} 与请求签名不一致：{detail}"
        )
    return bone
