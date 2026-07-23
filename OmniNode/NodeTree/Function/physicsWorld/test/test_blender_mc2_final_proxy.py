"""Mesh final-proxy 旧入口的 product-only 兼容门面。"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
MC2_TEST_ROOT = os.path.normpath(os.path.join(TEST_ROOT, "..", "mc2", "test"))
for path in (TEST_ROOT, MC2_TEST_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)


def run_product_mesh_final_proxy_contract() -> None:
    pure_tests = importlib.import_module("test_mesh_final_proxy")
    pure_tests.test_final_proxy_matches_tier_a_oracle_fixtures()
    product_tests = importlib.import_module("test_blender_mc2_mesh_product_static")
    product_tests.test_mesh_product_static_contract()
    print("PASS test_mesh_final_proxy_product_contract")


def test_mesh_final_proxy_product_contract() -> None:
    run_product_mesh_final_proxy_contract()


if __name__ == "__main__":
    run_product_mesh_final_proxy_contract()
