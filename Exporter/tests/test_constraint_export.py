"""约束 JSON 映射器的最小示例测试。"""

import sys
from pathlib import Path

addon_path = Path(__file__).parent.parent.parent
if str(addon_path) not in sys.path:
    sys.path.insert(0, str(addon_path))

from Exporter.ConstraintSemantics import FanConstraint, TwistConstraint
from Exporter.UnityConstraintMapper import UnityConstraintMapper


def test_export():
    constraints = [
        FanConstraint(
            bone_name="fan_L_01",
            weight=0.33,
            fan_type="FAN",
            target_bone="pin_L",
        ),
        TwistConstraint(
            bone_name="upper_arm_twist_01.L",
            weight=0.67,
            source_bone="upper_arm.L",
            target_bone="MCH_forearm.L",
        ),
    ]

    json_str = UnityConstraintMapper.export_to_json("TestArmature", constraints)
    print(json_str)


if __name__ == "__main__":
    test_export()
