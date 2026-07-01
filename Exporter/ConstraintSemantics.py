"""
HoTools 约束语义定义 — 从 Blender 约束抽象出的语义对象。

识别器(ConstraintAnalyzer)把 Blender pose bone constraints 转成这些语义对象,
映射器(UnityConstraintMapper)再把语义对象转成 Unity JSON。这一层解耦让我们能
先识别"这是什么约束",再决定"Unity 端怎么做"。
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SemanticConstraint:
    """约束语义基类,所有具体语义约束继承它。"""
    bone_name: str  # 约束所在骨的名字
    weight: float  # 约束影响权重(Blender 的 influence)


@dataclass
class FanConstraint(SemanticConstraint):
    """Fan/FanSingle/FanSide 辅助骨约束语义。

    Blender 实现:fan 骨上一个 COPY_ROTATION,世界空间复制 pin 骨旋转,influence 按
    扇形位置梯度分配。Unity 映射:世界→世界 RotationConstraint,权重直接用 weight。
    """
    fan_type: Literal["FAN", "FAN_SINGLE", "FAN_SIDE"] = "FAN"
    target_bone: str = ""


@dataclass
class TwistConstraint(SemanticConstraint):
    """Twist 辅助骨约束语义。

    Blender 实现:twist 骨上 COPY_ROTATION(local→localOwnerOrient) + STRETCH_TO(抑制翻转)。
    Unity 映射:退化为单 RotationConstraint,世界→世界,锁 Y 轴(只传 twist 分量)。
    """
    source_bone: str = ""


@dataclass
class TwistChainGroup:
    """Twist 链分组 — 同一源骨的多个 twist 骨聚合在一起,Unity 端可优化为多源约束。

    识别器把同源 twist 骨聚合成这个对象;映射器可选:逐个导出单约束,或导出一个
    多源 RotationConstraint。当前方案:逐个导出(Unity 原生支持)。
    """
    source_bone: str = ""
    twist_bones: list[tuple[str, float]] = field(default_factory=list)  # [(twist骨名, weight), ...]


@dataclass
class GenericConstraint(SemanticConstraint):
    """通用约束语义 — 不属于 HoTools 辅助骨约束的其他约束。

    当前版本暂不导出,接口预留。后续可扩展支持手动添加的 COPY_LOCATION / COPY_ROTATION
    等通用约束,完整保留空间参数、轴向、混合模式。
    """
    constraint_type: str = ""
    target_bone: str = ""
    # 后续扩展字段:owner_space, target_space, mix_mode, axes, offset, invert, ...
