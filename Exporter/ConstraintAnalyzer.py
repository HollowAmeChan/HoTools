"""
约束语义识别器 — 从 Blender armature 的 pose bone constraints 中提取语义约束。

识别规则:
1. 只识别约束到当前骨架内部骨的约束(target 是同一骨架);跨骨架约束全部过滤。
2. 按约束名前缀 HoTools_<AUX>_<KIND> 识别辅助骨约束类型(依赖 BoneUtils 命名规范)。
3. Twist 链聚合:同源骨的多个 twist 骨识别为一个 TwistChainGroup。
4. 通用约束当前不导出,接口预留。
"""

import bpy
from .ConstraintSemantics import (
    SemanticConstraint,
    FanConstraint,
    TwistConstraint,
    TwistChainGroup,
    GenericConstraint,
)


class ConstraintAnalyzer:
    """约束语义识别器。"""

    # HoTools 辅助骨约束的统一前缀,与 BoneUtils.AUX_CONSTRAINT_PREFIX 对齐
    AUX_PREFIX = "HoTools"

    @staticmethod
    def analyze(armature: bpy.types.Object) -> tuple[list[SemanticConstraint], list[TwistChainGroup]]:
        """分析骨架内所有约束,返回 (语义约束列表, twist链分组列表)。

        只返回约束到骨架内部骨的约束;跨骨架约束被过滤。Twist 约束单独聚合成链。
        """
        if armature.type != "ARMATURE":
            return [], []

        constraints_list = []
        twist_map = {}  # {源骨名: [(twist骨名, weight), ...]}

        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                # 过滤:只要约束到当前骨架内部骨的约束
                if not ConstraintAnalyzer._is_internal_constraint(constraint, armature):
                    continue

                semantic = ConstraintAnalyzer._identify_constraint(
                    pose_bone.name, constraint, armature
                )
                if semantic is None:
                    continue

                # Twist 约束单独聚合成链
                if isinstance(semantic, TwistConstraint):
                    source = semantic.source_bone
                    if source not in twist_map:
                        twist_map[source] = []
                    # 目标骨用约束真正的 subtarget（通常是权重来源骨的子关节骨，如手骨），
                    # 而非权重来源骨自身；source_bone（权重来源）在此恰好用作链分组的键。
                    twist_map[source].append(
                        (semantic.bone_name, semantic.weight, semantic.target_bone)
                    )
                else:
                    constraints_list.append(semantic)

        # 把 twist_map 转成 TwistChainGroup 列表
        twist_chains = [
            TwistChainGroup(source_bone=src, twist_bones=bones)
            for src, bones in twist_map.items()
        ]

        return constraints_list, twist_chains

    @staticmethod
    def _is_internal_constraint(constraint, armature: bpy.types.Object) -> bool:
        """约束是否指向当前骨架内部骨(target 是同一骨架,subtarget 非空)。"""
        if not hasattr(constraint, "target") or constraint.target is None:
            return False
        if constraint.target != armature:
            return False
        if not hasattr(constraint, "subtarget") or not constraint.subtarget:
            return False
        return True

    @staticmethod
    def _identify_constraint(
        bone_name: str, constraint, armature: bpy.types.Object
    ) -> SemanticConstraint | None:
        """识别单个约束的语义。返回 None 表示不支持/不导出。"""
        # 按约束名前缀识别 HoTools 辅助骨约束
        if constraint.name.startswith(ConstraintAnalyzer.AUX_PREFIX + "_"):
            return ConstraintAnalyzer._identify_aux_constraint(bone_name, constraint, armature)

        # 通用约束当前不导出,接口预留
        # return ConstraintAnalyzer._identify_generic_constraint(bone_name, constraint)
        return None

    @staticmethod
    def _identify_aux_constraint(
        bone_name: str, constraint, armature: bpy.types.Object
    ) -> SemanticConstraint | None:
        """识别 HoTools 辅助骨约束(名字格式 HoTools_<AUX>_<KIND>)。"""
        parts = constraint.name.split("_")
        if len(parts) < 3:
            return None  # 格式不对,跳过

        # parts: ["HoTools", <AUX>, <KIND>, ...]
        aux_type = parts[1]
        kind = parts[2]

        weight = getattr(constraint, "influence", 1.0)
        target_bone = constraint.subtarget

        # Fan 系列约束:HoTools_FAN_CopyRotation / HoTools_FAN_SINGLE_CopyRotation / HoTools_FAN_SIDE_CopyRotation
        if aux_type in ("FAN", "FAN_SINGLE", "FAN_SIDE") and kind == "CopyRotation":
            if constraint.type != "COPY_ROTATION":
                return None
            return FanConstraint(
                bone_name=bone_name,
                weight=weight,
                fan_type=aux_type,
                target_bone=target_bone,
            )

        # Twist 约束:HoTools_TWIST_CopyRotation(主约束) 或 HoTools_TWIST_StretchTo(辅助,抑制翻转)
        # 只识别 CopyRotation,StretchTo 不单独导出(Unity 端用锁 Y 轴代替)
        if aux_type == "TWIST" and kind == "CopyRotation":
            if constraint.type != "COPY_ROTATION":
                return None
            # 权重来源骨(辅助骨权重从这根骨拆分而来)从 auxBone.sourceBones 读取,
            # 同一来源的 twist 骨聚合为一条链
            source_bone = ConstraintAnalyzer._get_twist_source_bone(bone_name, armature)
            if source_bone is None:
                return None
            # 约束的实际目标 = COPY_ROTATION 的 subtarget(如 hand.L,主骨的子关节骨),
            # twist 骨真正拷贝的是它的旋转;Unity 端约束必须指向这个骨,而非权重来源骨。
            return TwistConstraint(
                bone_name=bone_name,
                weight=weight,
                source_bone=source_bone,
                target_bone=target_bone,
            )

        return None

    @staticmethod
    def _get_twist_source_bone(twist_bone_name: str, armature: bpy.types.Object) -> str | None:
        """从 twist 骨的 auxBone.sourceBones 读取权重来源骨名(第一个)。

        sourceBones 记录该辅助骨的蒙皮权重从哪根骨拆分而来(拆分/合并时保证权重 sum 不变)。
        """
        bone = armature.data.bones.get(twist_bone_name)
        if bone is None:
            return None
        props = getattr(bone, "hotools_boneprops", None)
        if props is None:
            return None
        aux = getattr(props, "auxBone", None)
        if aux is None or not aux.isAuxBone:
            return None
        if not aux.sourceBones:
            return None
        return aux.sourceBones[0].name

    @staticmethod
    def _identify_generic_constraint(bone_name: str, constraint) -> GenericConstraint | None:
        """识别通用约束(非 HoTools 辅助骨约束)。当前版本不导出,接口预留。"""
        # 后续扩展:解析 COPY_LOCATION / COPY_ROTATION / COPY_SCALE 等,保留完整参数
        return None
