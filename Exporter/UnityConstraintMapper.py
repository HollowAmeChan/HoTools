"""
Unity 约束映射器 — 把语义约束对象转成 Unity 可用的 JSON 格式。

映射规则(当前版本):
1. Fan 约束 → 世界→世界 RotationConstraint,全轴,权重直接映射
2. Twist 链 → 逐个 twist 骨导出为独立 RotationConstraint,世界→世界,锁 Y 轴
3. 通用约束当前不导出,占位返回空

Unity JSON 格式定义见本文件顶部多行注释。
"""

"""
HoTools Bone Constraint Export Format for Unity (v1.0)

设计原则:
1. 所有约束默认世界空间 → 世界空间,配合 HoTools FBX 导出的清除旋转功能。
2. 语义化约束(twist/fan)先识别再映射,而非直接导出 Blender 约束。
3. 空间参数、轴向、混合模式完整保留,Unity 端可精确复现。

根对象:
{
  "version": "1.0",              // 格式版本
  "exportTime": "ISO8601字符串",  // 导出时间戳
  "armatureName": "骨架名",       // 源骨架名称
  "bones": [                      // 骨骼约束列表
    {
      "boneName": "骨名",
      "constraints": [             // 该骨上的约束列表
        // ── Fan 约束 ──
        {
          "type": "Rotation",
          "semantic": "fan",               // HoTools 语义标记
          "fanType": "FAN" | "FAN_SINGLE" | "FAN_SIDE",
          "targetPath": "pin骨名",
          "weight": 0.0~1.0,
          "space": {"source": "world", "target": "world"},
          "axes": {"x": true, "y": true, "z": true}
        },

        // ── Twist 约束(单骨,已退化) ──
        {
          "type": "Rotation",
          "semantic": "twist",
          "sourceBone": "主骨名",           // twist 链的源骨
          "targetPath": "主骨名",           // 约束目标(与源骨相同)
          "weight": 0.0~1.0,
          "space": {"source": "world", "target": "world"},
          "axes": {"x": true, "y": false, "z": true}  // 锁 Y 轴,只传 twist 分量
        }
      ]
    }
  ]
}

Unity 端处理建议:
- semantic="fan": 世界空间 RotationConstraint,全轴
- semantic="twist": 世界空间 RotationConstraint,锁 Y 轴(axes.y=false)
  多个同源 twist 骨可合并为一个多源 RotationConstraint,或逐个独立约束
"""

import json
from datetime import datetime
from .ConstraintSemantics import (
    SemanticConstraint,
    FanConstraint,
    TwistConstraint,
    TwistChainGroup,
    GenericConstraint,
)


class UnityConstraintMapper:
    """Unity 约束映射器。"""

    VERSION = "1.0"

    @staticmethod
    def export_to_dict(
        armature_name: str,
        constraints: list[SemanticConstraint],
        twist_chains: list[TwistChainGroup],
    ) -> dict:
        """把语义约束列表转成 Unity JSON 字典结构。"""
        # 按骨名分组约束
        bones_map = {}  # {骨名: [约束字典列表]}

        # Fan 等普通约束
        for sem in constraints:
            bone_name = sem.bone_name
            if bone_name not in bones_map:
                bones_map[bone_name] = []
            constraint_dict = UnityConstraintMapper._map_constraint(sem)
            if constraint_dict is not None:
                bones_map[bone_name].append(constraint_dict)

        # Twist 链:逐个 twist 骨导出为独立约束
        for chain in twist_chains:
            for twist_bone_name, weight, target_bone in chain.twist_bones:
                if twist_bone_name not in bones_map:
                    bones_map[twist_bone_name] = []
                bones_map[twist_bone_name].append(
                    UnityConstraintMapper._map_twist_constraint(
                        twist_bone_name, chain.source_bone, weight, target_bone
                    )
                )

        # 构造最终 JSON 结构
        bones_list = [
            {"boneName": bone_name, "constraints": constraints_list}
            for bone_name, constraints_list in sorted(bones_map.items())
        ]

        return {
            "version": UnityConstraintMapper.VERSION,
            "exportTime": datetime.utcnow().isoformat() + "Z",
            "armatureName": armature_name,
            "bones": bones_list,
        }

    @staticmethod
    def export_to_json(
        armature_name: str,
        constraints: list[SemanticConstraint],
        twist_chains: list[TwistChainGroup],
    ) -> str:
        """导出为 JSON 字符串(格式化,缩进2空格)。"""
        data = UnityConstraintMapper.export_to_dict(armature_name, constraints, twist_chains)
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def _map_constraint(sem: SemanticConstraint) -> dict | None:
        """映射单个语义约束为 Unity JSON 字典。返回 None 表示不导出。"""
        if isinstance(sem, FanConstraint):
            return {
                "type": "Rotation",
                "semantic": "fan",
                "fanType": sem.fan_type,
                "targetPath": sem.target_bone,
                "weight": sem.weight,
                "space": {"source": "world", "target": "world"},
                "axes": {"x": True, "y": True, "z": True},
            }

        if isinstance(sem, GenericConstraint):
            # 通用约束当前不导出,接口预留
            return None

        return None

    @staticmethod
    def _map_twist_constraint(
        twist_bone_name: str, source_bone: str, weight: float, target_bone: str
    ) -> dict:
        """映射 Twist 约束为 Unity JSON 字典。

        退化方案:单个 RotationConstraint,世界→世界,锁 Y 轴(只传 twist 分量)。

        - sourceBone: twist 骨的权重来源骨(如 lower_arm.L,辅助骨权重从它拆分而来),仅作信息标记。
        - targetPath: 约束真正指向的骨(如 hand.L),即 Blender COPY_ROTATION 的 subtarget。
          twist 跟随的是手骨的旋转,而非权重来源骨自身。
        """
        return {
            "type": "Rotation",
            "semantic": "twist",
            "sourceBone": source_bone,
            "targetPath": target_bone,
            "weight": weight,
            "space": {"source": "world", "target": "world"},
            "axes": {"x": True, "y": False, "z": True},  # 锁 Y 轴
        }
