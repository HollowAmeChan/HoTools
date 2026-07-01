"""
约束导出模块测试 — 模拟数据验证导出流程和 JSON 格式。

运行: 在 Blender 脚本编辑器里执行此文件,查看输出的 JSON 示例。
"""

import sys
from pathlib import Path

# 把 HoTools 路径加入 sys.path,让 import 能找到模块
addon_path = Path(__file__).parent.parent
if str(addon_path) not in sys.path:
    sys.path.insert(0, str(addon_path))

from Exporter.ConstraintSemantics import FanConstraint, TwistChainGroup
from Exporter.UnityConstraintMapper import UnityConstraintMapper


def test_export():
    """模拟约束数据,测试 JSON 导出格式。"""

    # 模拟识别出的语义约束
    constraints = [
        FanConstraint(
            bone_name="fan_L_01",
            weight=0.33,
            fan_type="FAN",
            target_bone="pin_L",
        ),
        FanConstraint(
            bone_name="fan_L_02",
            weight=0.67,
            fan_type="FAN",
            target_bone="pin_L",
        ),
        FanConstraint(
            bone_name="fan_side_spine_01",
            weight=0.5,
            fan_type="FAN_SIDE",
            target_bone="pin_spine_01",
        ),
    ]

    # 模拟识别出的 twist 链
    twist_chains = [
        TwistChainGroup(
            source_bone="upper_arm.L",
            twist_bones=[
                ("upper_arm_twist_01.L", 0.33, "MCH_forearm.L"),
                ("upper_arm_twist_02.L", 0.67, "MCH_forearm.L"),
            ],
        ),
        TwistChainGroup(
            source_bone="forearm.L",
            twist_bones=[
                ("forearm_twist_01.L", 0.5, "MCH_hand.L"),
            ],
        ),
    ]

    # 导出为 JSON
    json_str = UnityConstraintMapper.export_to_json(
        armature_name="TestArmature",
        constraints=constraints,
        twist_chains=twist_chains,
    )

    print("=" * 80)
    print("HoTools Constraint Export - JSON 示例输出")
    print("=" * 80)
    print(json_str)
    print("=" * 80)
    print(f"\n导出统计:")
    print(f"  Fan 约束: {len(constraints)} 个")
    print(f"  Twist 链: {len(twist_chains)} 个")
    print(f"  Twist 骨: {sum(len(c.twist_bones) for c in twist_chains)} 个")
    print(f"  总约束数: {len(constraints) + sum(len(c.twist_bones) for c in twist_chains)} 个")


if __name__ == "__main__":
    test_export()
