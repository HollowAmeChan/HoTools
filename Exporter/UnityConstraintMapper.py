"""把 Blender 约束语义映射成 HoUnityTools 可读的 JSON。"""

import json
from datetime import datetime, timezone

from .ConstraintSemantics import (
    SemanticConstraint,
    FanConstraint,
    TwistConstraint,
    GenericConstraint,
    ParentConstraint,
)


class UnityConstraintMapper:
    """Unity 约束 JSON 映射器。"""

    VERSION = "1.0"

    @staticmethod
    def _copy_rotation_constraint(
        target_bone: str,
        weight: float,
        axes: dict | None = None,
    ) -> dict:
        return {
            "type": "Rotation",
            "targetPath": target_bone,
            "weight": weight,
            "space": {"source": "world", "target": "world"},
            "axes": axes or {"x": True, "y": True, "z": True},
        }

    @staticmethod
    def _map_fan_constraint(sem: FanConstraint) -> dict:
        # Fan 的 Blender 多空间/多方案差异无法由当前契约表达；这里明确
        # 退化为世界到世界的全轴 RotationConstraint。
        return {
            **UnityConstraintMapper._copy_rotation_constraint(
                sem.target_bone,
                sem.weight,
            ),
            "semantic": "fan",
            "subType": sem.fan_type,
        }

    @staticmethod
    def _map_twist_constraint(sem: TwistConstraint) -> dict:
        # Twist 不是完整复制 Blender 约束：当前 Unity 语义退化为单骨、
        # 世界到世界、只约束 Y 轴的 RotationConstraint。sourceBone 只保留
        # 蒙皮权重拆分的来源信息，不作为 Unity source。
        return {
            **UnityConstraintMapper._copy_rotation_constraint(
                sem.target_bone,
                sem.weight,
                {"x": False, "y": True, "z": False},
            ),
            "semantic": "twist",
            "sourceBone": sem.source_bone,
        }

    @staticmethod
    def _map_parent_constraint(sem: ParentConstraint) -> dict:
        return {
            "type": "Child",
            "semantic": "parent",
            "targetPath": sem.target_bone,
            "weight": sem.weight,
            "space": {"source": "world", "target": "world"},
            "maintainOffset": True,
        }

    @staticmethod
    def export_to_dict(
        armature_name: str,
        constraints: list[SemanticConstraint],
    ) -> dict:
        """把语义约束逐条映射为 Unity JSON 字典。"""
        bones_map: dict[str, list[dict]] = {}
        for semantic in constraints:
            mapped = UnityConstraintMapper._map_constraint(semantic)
            if mapped is None:
                continue
            bones_map.setdefault(semantic.bone_name, []).append(mapped)

        return {
            "version": UnityConstraintMapper.VERSION,
            "exportTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "armatureName": armature_name,
            "bones": [
                {"boneName": bone_name, "constraints": values}
                for bone_name, values in sorted(bones_map.items())
            ],
        }

    @staticmethod
    def export_to_json(
        armature_name: str,
        constraints: list[SemanticConstraint],
    ) -> str:
        data = UnityConstraintMapper.export_to_dict(armature_name, constraints)
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def _map_constraint(semantic: SemanticConstraint) -> dict | None:
        if isinstance(semantic, FanConstraint):
            return UnityConstraintMapper._map_fan_constraint(semantic)
        if isinstance(semantic, TwistConstraint):
            return UnityConstraintMapper._map_twist_constraint(semantic)
        if isinstance(semantic, ParentConstraint):
            return UnityConstraintMapper._map_parent_constraint(semantic)
        if isinstance(semantic, GenericConstraint):
            return None
        return None
