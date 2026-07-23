"""旧 mixed-output 名称的 product-only 过渡门面。

完整执行已经迁移到 `test_blender_mc2_product_mixed_output_soak.py` 和
`test_blender_mc2_product_center_controls_soak.py`；本文件只保留旧符号，
待剩余独立断言登记后删除。
"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


def _product_mixed():
    return importlib.import_module(
        "test_blender_mc2_product_mixed_output_soak"
    ).test_three_setup_product_mixed_output_900_frame_deterministic_soak()


def _product_center(symbol: str):
    return getattr(
        importlib.import_module("test_blender_mc2_product_center_controls_soak"),
        symbol,
    )()


def center_world_controls():
    return _product_center("center_world_controls")


def center_local_controls():
    return _product_center("center_local_controls")


def center_depth_controls():
    return _product_center("center_depth_controls")


def center_anchor_controls():
    return _product_center("center_anchor_controls")


def main():
    _product_mixed()
    center_world_controls()
    center_local_controls()
    center_depth_controls()
    center_anchor_controls()
    print("PASS product-only mixed-output compatibility facade")


if __name__ == "__main__":
    main()
