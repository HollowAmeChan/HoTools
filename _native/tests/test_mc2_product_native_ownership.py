"""Source-level ownership gates for the MC2 product native path."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NATIVE_SRC = ROOT / "_native" / "src"
MC2_PYTHON = (
    ROOT
    / "OmniNode"
    / "NodeTree"
    / "Function"
    / "physicsWorld"
    / "mc2"
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_whole_domain_self_has_no_v0_owner_dependency() -> None:
    source = _source(NATIVE_SRC / "mc2_whole_domain_self.cpp")
    assert "WholeDomainSelfState" in source
    for forbidden in (
        "mc2_context_internal.hpp",
        "mc2_context_helpers.hpp",
        "Mc2ContextV0",
        "mc2_internal",
    ):
        assert forbidden not in source


def test_frame_orientations_have_no_v0_owner_dependency() -> None:
    source = _source(NATIVE_SRC / "mc2_frame_orientations.cpp")
    for forbidden in (
        "mc2_context_internal.hpp",
        "mc2_context_helpers.hpp",
        "Mc2ContextV0",
        "mc2_internal",
    ):
        assert forbidden not in source


def test_product_topology_uses_only_v1_static_fingerprints() -> None:
    source = _source(MC2_PYTHON / "topology.py")
    assert "mc2_mesh_static_fingerprint_v1" in source
    assert "mc2_bone_static_fingerprint_v1" in source
    assert "static_fingerprint_v0" not in source
