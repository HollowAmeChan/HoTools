"""Bone static 旧入口的 product-only 兼容门面。

静态拓扑、分区 collector、fragment cache 和 Blender writeback 断言已经归属
MC2 product 测试。本文件只保留旧脚本名，供外部验收脚本过渡调用；不再创建
V0 task，也不读取旧 owner、native_context 或隐藏 slot 字段。
"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
MC2_TEST_ROOT = os.path.normpath(
    os.path.join(TEST_ROOT, "..", "mc2", "test")
)
for path in (TEST_ROOT, MC2_TEST_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)


def run_product_bone_static_contract() -> None:
    static_tests = importlib.import_module("test_bone_product_static")
    for name in (
        "test_product_task_builds_multi_chain_topology_and_static_bundle",
        "test_product_task_rejects_sources_from_multiple_armatures",
        "test_product_partition_capture_matches_task_topology_without_task_creation",
        "test_bone_spring_partition_uses_the_same_domain_owner",
        "test_same_armature_bone_cloth_partitions_compile_into_one_domain",
        "test_bone_product_collection_and_fragment_cache_are_transactional",
        "test_bone_product_slots_reuse_owner_and_allow_explicit_collectors",
    ):
        getattr(static_tests, name)()

    # Importing the Blender product runner executes its multi-partition,
    # multi-request, BoneSpring and writeback contracts.
    importlib.import_module("test_blender_mc2_bone_product")
    print("PASS test_blender_mc2_bone_static_product_contract")


def test_bone_static_product_contract() -> None:
    run_product_bone_static_contract()


if __name__ == "__main__":
    run_product_bone_static_contract()
