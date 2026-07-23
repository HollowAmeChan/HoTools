"""Mesh base-pose 旧入口的 product-only 兼容门面。"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


def run_product_base_pose_contract() -> None:
    product = importlib.import_module("test_blender_mc2_mesh_product_base_pose")
    product.test_mesh_product_base_pose_contract()
    print("PASS test_base_pose_product_contract")


def test_base_pose_product_contract() -> None:
    run_product_base_pose_contract()


def main() -> None:
    run_product_base_pose_contract()


if __name__ == "__main__":
    main()
