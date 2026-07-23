"""Bone frame 旧入口的 product-only 兼容门面。

旧 N3 文件直接创建 V0 task、调用旧 solver 并读取 native_context；这些路径
不再属于产品执行合同。产品 frame input、owner 复用、写回和 finite 输出由
公开 BoneCloth/BoneSpring soak 统一验证，本门面只保留旧文件名供外部脚本
过渡调用，完成矩阵迁移后删除。
"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


def run_product_bone_frame_contract():
    return importlib.import_module(
        "test_blender_mc2_bone_product_constraint_soak"
    ).test_bone_product_frame_transform_contract()


def test_bone_frame_product_contract():
    return run_product_bone_frame_contract()


if __name__ == "__main__":
    run_product_bone_frame_contract()
    print("PASS test_bone_frame_product_contract")
