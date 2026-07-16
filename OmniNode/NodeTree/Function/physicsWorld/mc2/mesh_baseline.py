"""Pure MeshCloth baseline builder for the final-proxy MC2 N0 contract.

The algorithm follows MagicaCloth2 2.18.1 ``CreateMeshBaseLine()``,
``CreateBaseLinePose()``, and ``CreateVertexRootAndDepth()``. Unity native hash
enumeration is not a stable public ordering contract, so equal-cost choices and
sibling output use the lowest final-proxy vertex index as the canonical tie
break. No Blender data or evaluated frame pose enters this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .static_data import (
    MC2BaselineStaticSpec,
    MC2ProxyStaticSpec,
    make_mc2_baseline_static_spec,
    make_mc2_proxy_static_spec,
)


MC2_VERTEX_FIXED = 0x01
MC2_VERTEX_MOVE = 0x02
MC2_VERTEX_ZERO_DISTANCE = 0x20
MC2_VERTEX_TRIANGLE = 0x80
MC2_BASELINE_INCLUDE_LINE = 0x01


@dataclass(frozen=True)
class MC2MeshBaselineBuildResult:
    final_proxy: MC2ProxyStaticSpec
    baseline: MC2BaselineStaticSpec
    tie_break: str = "lowest_vertex_index"

    def __post_init__(self) -> None:
        if self.final_proxy.setup_type != "mesh_cloth":
            raise ValueError("Mesh baseline result requires a mesh_cloth proxy")
        if self.baseline.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("baseline must reference the finalized proxy signature")
        if self.tie_break != "lowest_vertex_index":
            raise ValueError("unsupported Mesh baseline tie break")


def _replace_proxy_attributes(
    proxy: MC2ProxyStaticSpec,
    attributes: tuple[int, ...],
) -> MC2ProxyStaticSpec:
    if attributes == proxy.vertex_attributes:
        return proxy
    return make_mc2_proxy_static_spec(
        task_id=proxy.task_id,
        setup_type=proxy.setup_type,
        vertex_identities=proxy.vertex_identities,
        local_positions=proxy.local_positions,
        local_normals=proxy.local_normals,
        local_tangents=proxy.local_tangents,
        uvs=proxy.uvs,
        vertex_attributes=attributes,
        edges=proxy.edges,
        triangles=proxy.triangles,
    )


def _build_native_baseline(proxy: MC2ProxyStaticSpec) -> dict:
    count = proxy.vertex_count
    attributes = np.ascontiguousarray(proxy.vertex_attributes, dtype=np.uint8)
    parents = np.empty(count, dtype=np.int32)
    child_ranges = np.empty((count, 2), dtype=np.int32)
    child_data = np.empty(count, dtype=np.int32)
    baseline_flags = np.empty(count, dtype=np.uint8)
    baseline_ranges = np.empty((count, 2), dtype=np.int32)
    baseline_data = np.empty(count, dtype=np.int32)
    roots = np.empty(count, dtype=np.int32)
    depths = np.empty(count, dtype=np.float64)
    local_positions = np.empty((count, 3), dtype=np.float64)
    local_rotations = np.empty((count, 4), dtype=np.float64)
    from .native import native_module

    counts = native_module().mc2_build_mesh_baseline_derived_v0(
        np.ascontiguousarray(proxy.local_positions, dtype=np.float64),
        np.ascontiguousarray(proxy.local_normals, dtype=np.float64),
        np.ascontiguousarray(proxy.local_tangents, dtype=np.float64),
        attributes,
        np.ascontiguousarray(proxy.edges, dtype=np.int32).reshape((-1, 2)),
        parents,
        child_ranges,
        child_data,
        baseline_flags,
        baseline_ranges,
        baseline_data,
        roots,
        depths,
        local_positions,
        local_rotations,
    )
    child_count = int(counts["child_count"])
    baseline_count = int(counts["baseline_count"])
    baseline_data_count = int(counts["baseline_data_count"])
    return {
        "attributes": tuple(int(value) for value in attributes),
        "parents": tuple(int(value) for value in parents),
        "child_ranges": tuple(tuple(int(value) for value in row) for row in child_ranges),
        "child_data": tuple(int(value) for value in child_data[:child_count]),
        "baseline_flags": tuple(int(value) for value in baseline_flags[:baseline_count]),
        "baseline_ranges": tuple(
            tuple(int(value) for value in row)
            for row in baseline_ranges[:baseline_count]
        ),
        "baseline_data": tuple(int(value) for value in baseline_data[:baseline_data_count]),
        "roots": tuple(int(value) for value in roots),
        "depths": tuple(float(value) for value in depths),
        "local_positions": tuple(
            tuple(float(value) for value in row) for row in local_positions
        ),
        "local_rotations": tuple(
            tuple(float(value) for value in row) for row in local_rotations
        ),
    }


def _build_native_baseline_pose_depth(
    proxy: MC2ProxyStaticSpec,
    parents: tuple[int, ...],
    baseline_data: tuple[int, ...],
) -> dict:
    count = proxy.vertex_count
    attributes = np.ascontiguousarray(proxy.vertex_attributes, dtype=np.uint8)
    roots = np.empty(count, dtype=np.int32)
    depths = np.empty(count, dtype=np.float64)
    local_positions = np.empty((count, 3), dtype=np.float64)
    local_rotations = np.empty((count, 4), dtype=np.float64)
    from .native import native_module

    native_module().mc2_build_baseline_pose_depth_derived_v0(
        np.ascontiguousarray(proxy.local_positions, dtype=np.float64),
        np.ascontiguousarray(proxy.local_normals, dtype=np.float64),
        np.ascontiguousarray(proxy.local_tangents, dtype=np.float64),
        attributes,
        np.ascontiguousarray(parents, dtype=np.int32),
        np.ascontiguousarray(baseline_data, dtype=np.int32),
        roots,
        depths,
        local_positions,
        local_rotations,
    )
    return {
        "attributes": tuple(int(value) for value in attributes),
        "roots": tuple(int(value) for value in roots),
        "depths": tuple(float(value) for value in depths),
        "local_positions": tuple(
            tuple(float(value) for value in row) for row in local_positions
        ),
        "local_rotations": tuple(
            tuple(float(value) for value in row) for row in local_rotations
        ),
    }


def build_mc2_mesh_baseline(proxy: MC2ProxyStaticSpec) -> MC2MeshBaselineBuildResult:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    if proxy.setup_type != "mesh_cloth":
        raise ValueError("Mesh baseline builder only accepts mesh_cloth")

    derived = _build_native_baseline(proxy)
    final_proxy = _replace_proxy_attributes(proxy, derived["attributes"])
    baseline = make_mc2_baseline_static_spec(
        proxy_signature=final_proxy.proxy_signature,
        vertex_count=final_proxy.vertex_count,
        parent_indices=derived["parents"],
        child_ranges=derived["child_ranges"],
        child_data=derived["child_data"],
        baseline_flags=derived["baseline_flags"],
        baseline_ranges=derived["baseline_ranges"],
        baseline_data=derived["baseline_data"],
        root_indices=derived["roots"],
        depths=derived["depths"],
        vertex_local_positions=derived["local_positions"],
        vertex_local_rotations=derived["local_rotations"],
    )
    return MC2MeshBaselineBuildResult(final_proxy=final_proxy, baseline=baseline)


__all__ = [
    "MC2_BASELINE_INCLUDE_LINE",
    "MC2_VERTEX_FIXED",
    "MC2_VERTEX_MOVE",
    "MC2_VERTEX_TRIANGLE",
    "MC2_VERTEX_ZERO_DISTANCE",
    "MC2MeshBaselineBuildResult",
    "build_mc2_mesh_baseline",
]
