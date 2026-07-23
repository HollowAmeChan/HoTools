"""Bone 约束验收的过渡门面。

旧文件名仍被能力矩阵引用，但实现已经全部转发到 product-only runner。
这里不再创建 V0 task，也不读取 native_context；完成矩阵迁移后可直接删除本文件。
"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


def _product_constraint():
    return importlib.import_module(
        "test_blender_mc2_bone_product_constraint_soak"
    ).test_bone_product_constraints_900_frame_deterministic_soak()


def _product_angle_motion():
    return importlib.import_module(
        "test_blender_mc2_bone_product_angle_motion"
    ).test_bone_product_angle_motion_numeric_boundaries()


def _product_collision():
    return importlib.import_module(
        "test_blender_mc2_bone_product_collision_soak"
    ).test_bone_product_collision_filter_response_deterministic()


def _product_friction():
    return importlib.import_module(
        "test_blender_mc2_bone_product_collision_soak"
    ).test_bone_product_friction_ordered_response()


def bone_angle_constraints():
    return _product_constraint()


def bone_gravity_axes_falloff():
    return _product_constraint()


def bone_rotation_output_controls():
    return _product_constraint()


def bone_angle_restoration_attenuation():
    return _product_angle_motion()


def bone_angle_restoration_falloff():
    return _product_angle_motion()


def bone_angle_limit():
    return _product_angle_motion()


def bone_motion_constraints():
    return _product_angle_motion()


def bone_distance_tether():
    return _product_constraint()


def bone_triangle_bending():
    return _product_constraint()


def bone_external_collision():
    return _product_collision()


def bone_friction_response():
    return _product_friction()


def bone_self_collision():
    return _product_constraint()


def main():
    bone_angle_constraints()
    print("PASS Bone product constraint compatibility facade")


if __name__ == "__main__":
    main()
