"""Explicit copyR ownership; never manufactures matching bones or weights."""

import math

from RigConstraints.blender import metadata
from .properties import OWNER_SPACES, TARGET_SPACES

GENERATOR_ID = "hotools.aux.copy_r"
AUX_TYPE = "COPY_R"
CONSTRAINT_NAME = "HoTools_COPY_R_CopyRotation"
_FIELDS = ("target", "subtarget", "owner_space", "target_space", "mix_mode", "influence",
           "use_x", "use_y", "use_z", "invert_x", "invert_y", "invert_z", "mute")


def _owners(armature, owner_names):
    if armature is None or armature.type != "ARMATURE":
        raise ValueError("copyR 需要当前骨架")
    if armature.mode == "EDIT":
        raise ValueError("请先完成编辑骨骼，再创建 copyR")
    names = list(dict.fromkeys(owner_names))
    if not names:
        raise ValueError("请选择需要跟随的受约束骨")
    result = []
    for name in names:
        owner = armature.pose.bones.get(name)
        if owner is None:
            raise ValueError("受约束骨不存在：" + str(name))
        props = getattr(owner.bone, "hotools_boneprops", None)
        if props is None or not hasattr(props, "constraintGroups") or not hasattr(props, "auxBone"):
            raise ValueError("请启用 HoTools 骨骼属性及约束语义登记")
        aux = props.auxBone
        if aux.isAuxBone and aux.auxType not in {"NONE", AUX_TYPE}:
            raise ValueError(owner.name + " 已属于其他辅助骨类型：" + aux.auxType)
        result.append(owner)
    return result


def _registered(owner):
    groups = metadata.iter_groups(owner.bone, pose_bone=owner)
    foreign = [group for group in groups if group["generatorId"] != GENERATOR_ID]
    if foreign:
        raise ValueError(owner.name + " 已有其他用途登记，不覆盖")
    own = [group for group in groups if group["generatorId"] == GENERATOR_ID]
    if not own:
        aux = owner.bone.hotools_boneprops.auxBone
        if aux.isAuxBone and aux.auxType == AUX_TYPE:
            raise ValueError(owner.name + " 的 copyR 登记缺失；请先清除损坏身份")
        return None
    if len(own) != 1 or own[0]["semanticType"] != "COPY_ROTATION" or own[0]["semanticVersion"] != 1:
        raise ValueError(owner.name + " 的 copyR 语义登记不完整")
    members = own[0]["members"]
    if len(members) != 1 or members[0]["constraintType"] != "COPY_ROTATION" or members[0]["role"] != "rotation":
        raise ValueError(owner.name + " 的 copyR 成员登记不完整")
    constraint = owner.constraints.get(members[0]["constraintName"])
    if constraint is None or constraint.type != "COPY_ROTATION":
        raise ValueError(owner.name + " 的 copyR 约束缺失或类型不匹配；不会接管手工约束")
    return constraint


class CopyRotationCore:
    AUX_TYPE = AUX_TYPE
    GENERATOR_ID = GENERATOR_ID
    CONSTRAINT_NAME = CONSTRAINT_NAME

    @staticmethod
    def configure(armature, owner_names, target_bone_name, *, influence=1.0,
                  target_space="LOCAL_OWNER_ORIENT", owner_space="LOCAL"):
        """Create/update an explicitly owned copyR on every named existing bone.

        All selected owners are preflighted before the first mutation. Registered
        constraints are reused; names alone never grant ownership. Rest matrices,
        hierarchy, bone count and vertex groups are not authoring outputs here.
        """
        owners = _owners(armature, owner_names)
        if not isinstance(target_bone_name, str) or not target_bone_name or armature.pose.bones.get(target_bone_name) is None:
            raise ValueError("请选择同骨架中存在的目标骨")
        if target_space not in {row[0] for row in TARGET_SPACES} or owner_space not in {row[0] for row in OWNER_SPACES}:
            raise ValueError("copyR 空间设置无效")
        if isinstance(influence, bool) or not isinstance(influence, (int, float)) or not math.isfinite(influence) or not 0 <= influence <= 1:
            raise ValueError("跟随强度必须在 0 到 1 之间")
        target = armature.pose.bones[target_bone_name]
        prepared = []
        for owner in owners:
            if owner == target or owner.bone in target.bone.parent_recursive:
                raise ValueError(owner.name + " 不能跟随自身或自身子骨，以免形成依赖循环")
            constraint = _registered(owner)
            if constraint is None and owner.constraints.get(CONSTRAINT_NAME) is not None:
                raise ValueError(owner.name + " 已有同名手工约束 " + CONSTRAINT_NAME + "；请先改名")
            prepared.append((owner, constraint))

        changes = []
        try:
            for owner, existing in prepared:
                aux = owner.bone.hotools_boneprops.auxBone
                previous_aux = (aux.isAuxBone, aux.auxType, [ref.name for ref in aux.sourceBones], [ref.name for ref in aux.constraintNames])
                constraint = existing if existing is not None else owner.constraints.new("COPY_ROTATION")
                old_fields = {name: getattr(constraint, name) for name in _FIELDS} if existing is not None else None
                changes.append((owner, constraint, old_fields, previous_aux))
                if existing is None:
                    constraint.name = CONSTRAINT_NAME
                constraint.target = armature
                constraint.subtarget = target_bone_name
                constraint.owner_space = owner_space
                constraint.target_space = target_space
                constraint.mix_mode = "REPLACE"
                constraint.influence = float(influence)
                constraint.use_x = constraint.use_y = constraint.use_z = True
                constraint.invert_x = constraint.invert_y = constraint.invert_z = False
                constraint.mute = False
                aux.isAuxBone = True
                aux.auxType = AUX_TYPE
                aux.sourceBones.clear()
                aux.sourceBones.add().name = target_bone_name
                aux.constraintNames.clear()
                aux.constraintNames.add().name = constraint.name
                metadata.register_group(owner, "COPY_ROTATION", [constraint], generator_id=GENERATOR_ID,
                                        roles=["rotation"], owns_bone=False)
        except Exception:
            for owner, constraint, old_fields, previous_aux in reversed(changes):
                if old_fields is None:
                    owner.constraints.remove(constraint)
                    metadata.unregister_group(owner.bone, "COPY_ROTATION", generator_id=GENERATOR_ID)
                else:
                    for name, value in old_fields.items():
                        setattr(constraint, name, value)
                aux = owner.bone.hotools_boneprops.auxBone
                aux.isAuxBone, aux.auxType = previous_aux[:2]
                aux.sourceBones.clear()
                aux.constraintNames.clear()
                for name in previous_aux[2]:
                    aux.sourceBones.add().name = name
                for name in previous_aux[3]:
                    aux.constraintNames.add().name = name
            raise
        return [constraint for _owner, constraint, _fields, _aux in changes]

    @staticmethod
    def remove(armature, owner_names):
        """Remove this generator's constraint/declaration, retaining every bone."""
        owners = _owners(armature, owner_names)
        prepared = [(owner, _registered(owner)) for owner in owners]
        count = 0
        for owner, constraint in prepared:
            if constraint is None:
                continue
            owner.constraints.remove(constraint)
            metadata.unregister_group(owner.bone, "COPY_ROTATION", generator_id=GENERATOR_ID)
            aux = owner.bone.hotools_boneprops.auxBone
            aux.isAuxBone = False
            aux.auxType = "NONE"
            aux.sourceBones.clear()
            aux.constraintNames.clear()
            count += 1
        return count
