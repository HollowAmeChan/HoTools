"""HoTools 导出器使用的约束语义中间对象。"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class SemanticConstraint:
    """约束语义基类。"""

    bone_name: str
    weight: float


@dataclass
class ParentConstraint(SemanticConstraint):
    """Blender CHILD_OF 映射到 Unity ParentConstraint。"""

    target_bone: str = ""


@dataclass
class FanConstraint(SemanticConstraint):
    """Fan/FanSingle/FanSide 辅助骨旋转约束。"""

    fan_type: Literal["FAN", "FAN_SINGLE", "FAN_SIDE"] = "FAN"
    target_bone: str = ""


@dataclass
class TwistConstraint(SemanticConstraint):
    """Twist 辅助骨约束，直接携带权重来源骨和目标骨。"""

    source_bone: str = ""
    target_bone: str = ""


@dataclass
class GenericConstraint(SemanticConstraint):
    """尚未映射到 Unity 的通用约束占位。"""

    constraint_type: str = ""
    target_bone: str = ""
