"""从 Blender 骨架约束提取 HoTools 导出语义。"""

import bpy

from .ConstraintSemantics import (
    SemanticConstraint,
    FanConstraint,
    TwistConstraint,
    GenericConstraint,
    ParentConstraint,
)


class ConstraintAnalyzer:
    """识别同一骨架内部的 Parent、Fan 和 Twist 约束。"""

    AUX_PREFIX = "HoTools"

    @staticmethod
    def analyze(armature: bpy.types.Object) -> list[SemanticConstraint]:
        """返回可导出的语义约束列表，不再引入无运行时用途的中间分组。"""
        if armature.type != "ARMATURE":
            return []

        constraints_list = []
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                if not ConstraintAnalyzer._is_internal_constraint(constraint, armature):
                    continue

                semantic = ConstraintAnalyzer._identify_constraint(
                    pose_bone.name,
                    constraint,
                    armature,
                )
                if semantic is not None:
                    constraints_list.append(semantic)

        return constraints_list

    @staticmethod
    def _is_internal_constraint(constraint, armature: bpy.types.Object) -> bool:
        """只导出 target 指向当前骨架且 subtarget 非空的约束。"""
        if getattr(constraint, "target", None) != armature:
            return False
        return bool(getattr(constraint, "subtarget", ""))

    @staticmethod
    def _identify_constraint(
        bone_name: str,
        constraint,
        armature: bpy.types.Object,
    ) -> SemanticConstraint | None:
        if constraint.type == "CHILD_OF":
            return ParentConstraint(
                bone_name=bone_name,
                weight=getattr(constraint, "influence", 1.0),
                target_bone=constraint.subtarget,
            )

        if constraint.name.startswith(ConstraintAnalyzer.AUX_PREFIX + "_"):
            return ConstraintAnalyzer._identify_aux_constraint(
                bone_name,
                constraint,
                armature,
            )

        return None

    @staticmethod
    def _identify_aux_constraint(
        bone_name: str,
        constraint,
        armature: bpy.types.Object,
    ) -> SemanticConstraint | None:
        aux_type, kind = ConstraintAnalyzer._parse_aux_constraint_name(constraint.name)
        if aux_type is None or kind is None:
            return None

        weight = getattr(constraint, "influence", 1.0)
        target_bone = constraint.subtarget

        if aux_type in ("FAN", "FAN_SINGLE", "FAN_SIDE") and kind == "CopyRotation":
            if constraint.type != "COPY_ROTATION":
                return None
            return FanConstraint(
                bone_name=bone_name,
                weight=weight,
                fan_type=aux_type,
                target_bone=target_bone,
            )

        if aux_type == "TWIST" and kind == "CopyRotation":
            if constraint.type != "COPY_ROTATION":
                return None
            source_bone = ConstraintAnalyzer._get_twist_source_bone(
                bone_name,
                armature,
            )
            if source_bone is None:
                return None
            return TwistConstraint(
                bone_name=bone_name,
                weight=weight,
                source_bone=source_bone,
                target_bone=target_bone,
            )

        return None

    @staticmethod
    def _parse_aux_constraint_name(name: str) -> tuple[str | None, str | None]:
        """解析 HoTools_<AUX_TYPE>_<KIND> 约束名。"""
        prefix = ConstraintAnalyzer.AUX_PREFIX + "_"
        if not name.startswith(prefix):
            return None, None
        aux_type, separator, kind = name[len(prefix):].rpartition("_")
        if not separator or not aux_type or not kind:
            return None, None
        return aux_type, kind

    @staticmethod
    def _get_twist_source_bone(
        twist_bone_name: str,
        armature: bpy.types.Object,
    ) -> str | None:
        bone = armature.data.bones.get(twist_bone_name)
        if bone is None:
            return None
        props = getattr(bone, "hotools_boneprops", None)
        aux = getattr(props, "auxBone", None) if props else None
        if aux is None or not aux.isAuxBone or not aux.sourceBones:
            return None
        return aux.sourceBones[0].name

    @staticmethod
    def _identify_generic_constraint(
        bone_name: str,
        constraint,
    ) -> GenericConstraint | None:
        """通用 COPY_* 约束的未来扩展入口。"""
        return None
