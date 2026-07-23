"""MC2 统一 product debug 验收入口。

旧的 debug_draw 脚本仍保留作迁移审计证据；这个入口只执行 product
owner 的冻结快照和独立 debug 契约，避免重新引入 V0 slot/context。
"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
MC2_TEST_ROOT = os.path.join(
    os.path.dirname(TEST_ROOT), "mc2", "test"
)
for path in (TEST_ROOT, MC2_TEST_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)


def _run_product_debug_contracts():
    product_slot = importlib.import_module("test_product_slot")
    owner = importlib.import_module("test_domain_owner")
    product_frame = importlib.import_module("test_product_frame")
    product_slot.test_slot_native_executes_complete_compiled_frame()
    owner.test_owner_exposes_explicit_product_debug_state()
    product_frame.test_product_frame_compiles_two_partition_pose_and_metadata()


def test_mc2_product_debug_acceptance():
    _run_product_debug_contracts()


if __name__ == "__main__":
    _run_product_debug_contracts()
    print("PASS test_mc2_product_debug_acceptance")
