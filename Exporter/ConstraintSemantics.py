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
    Unity 映射:退化为单 RotationConstraint,世界→世界,只冻结/约束 Y 轴。
    Blender 导出端直接写 axes={x:false,y:true,z:false},Unity 导入端只按 JSON 设置 rotationAxis。

    - source_bone: 该辅助骨的**权重来源骨**(如 lower_arm.L)。twist 骨的蒙皮权重是
      从这根骨上拆分出来的,拆分/合并时要保证权重 sum 不变。同一权重来源的 twist 骨
      被聚合为同一条链(链分组只是它作为分组键的副作用,非其定义)。
    - target_bone: COPY_ROTATION 真正拷贝旋转的目标骨(如 hand.L,即主骨的子关节骨)。
      这才是 Unity 端约束应指向的骨——手腕滚动带动小臂扭转,twist 跟的是手骨。
    """
    source_bone: str = ""
    target_bone: str = ""


@dataclass
class TwistChainGroup:
    """Twist 链分组 — 同一权重来源骨的多个 twist 骨聚合在一起,Unity 端可优化为多源约束。

    源骨(source_bone)指辅助骨的权重来源骨:这些 twist 骨的蒙皮权重都从它拆分而来,
    拆分/合并时保证权重 sum 不变;同一权重来源的 twist 骨天然属于同一条链,故以它为分组键。
    识别器把同源 twist 骨聚合成这个对象;映射器可选:逐个导出单约束,或导出一个
    多源 RotationConstraint。当前方案:逐个导出(Unity 原生支持)。
    """
    source_bone: str = ""
    # [(twist骨名, weight, target骨名), ...]；target 为 COPY_ROTATION 真正拷贝旋转的目标骨
    twist_bones: list[tuple[str, float, str]] = field(default_factory=list)


@dataclass
class GenericConstraint(SemanticConstraint):
    """通用约束语义 — 不属于 HoTools 辅助骨约束的其他约束。

    当前版本暂不导出,接口预留。后续可扩展支持手动添加的 COPY_LOCATION / COPY_ROTATION
    等通用约束,完整保留空间参数、轴向、混合模式。
    """
    constraint_type: str = ""
    target_bone: str = ""
    # 后续扩展字段:owner_space, target_space, mix_mode, axes, offset, invert, ...
