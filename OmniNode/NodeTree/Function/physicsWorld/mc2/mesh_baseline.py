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
    mc2_baseline_content_signature,
)


MC2_VERTEX_FIXED = 0x01
MC2_VERTEX_MOVE = 0x02
MC2_VERTEX_ZERO_DISTANCE = 0x20
MC2_VERTEX_TRIANGLE = 0x80
MC2_BASELINE_INCLUDE_LINE = 0x01


@dataclass(frozen=True)
class MC2MeshBaselineBuildResult:
    final_proxy: object
    baseline: MC2BaselineStaticSpec | MC2MeshBaselineNativeData | MC2MeshBaselineMetadata
    tie_break: str = "lowest_vertex_index"

    def __post_init__(self) -> None:
        if self.final_proxy.setup_type != "mesh_cloth":
            raise ValueError("Mesh baseline result requires a mesh_cloth proxy")
        if self.baseline.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("baseline must reference the finalized proxy signature")
        if self.tie_break != "lowest_vertex_index":
            raise ValueError("unsupported Mesh baseline tie break")

    def compact_native_baseline(self):
        baseline = self.baseline
        final_proxy = self.final_proxy
        proxy_metadata = getattr(final_proxy, "metadata", None)
        if not isinstance(baseline, MC2MeshBaselineNativeData) and not callable(
            proxy_metadata
        ):
            return self
        return MC2MeshBaselineBuildResult(
            final_proxy=proxy_metadata() if callable(proxy_metadata) else final_proxy,
            baseline=(
                baseline.metadata()
                if isinstance(baseline, MC2MeshBaselineNativeData)
                else baseline
            ),
            tie_break=self.tie_break,
        )


@dataclass(frozen=True)
class MC2MeshBaselineMetadata:
    proxy_signature: str
    vertex_count: int
    baseline_count: int
    depths: np.ndarray
    baseline_signature: str
    native_owned: bool = True


@dataclass(frozen=True)
class MC2MeshBaselineNativeData:
    proxy_signature: str
    vertex_count: int
    parent_indices: np.ndarray
    child_ranges: np.ndarray
    child_data: np.ndarray
    baseline_flags: np.ndarray
    baseline_ranges: np.ndarray
    baseline_data: np.ndarray
    root_indices: np.ndarray
    depths: np.ndarray
    vertex_local_positions: np.ndarray
    vertex_local_rotations: np.ndarray
    baseline_signature: str
    native_registration: dict | None = None
    native_owned: bool = True

    @property
    def baseline_count(self) -> int:
        return len(self.baseline_ranges)

    def metadata(self) -> MC2MeshBaselineMetadata:
        depths = np.ascontiguousarray(self.depths, dtype=np.float32)
        depths.setflags(write=False)
        return MC2MeshBaselineMetadata(
            proxy_signature=self.proxy_signature,
            vertex_count=self.vertex_count,
            baseline_count=self.baseline_count,
            depths=depths,
            baseline_signature=self.baseline_signature,
        )


def _baseline_content_signature(proxy_signature: str, values: dict) -> str:
    return mc2_baseline_content_signature(
        proxy_signature=proxy_signature,
        vertex_count=len(values["parents"]),
        parent_indices=values["parents"],
        child_ranges=values["child_ranges"],
        child_data=values["child_data"],
        baseline_flags=values["baseline_flags"],
        baseline_ranges=values["baseline_ranges"],
        baseline_data=values["baseline_data"],
        root_indices=values["roots"],
        depths=values["depths"],
        vertex_local_positions=values["local_positions"],
        vertex_local_rotations=values["local_rotations"],
    )


def _replace_proxy_attributes(
    proxy,
    attributes: tuple[int, ...],
) -> object:
    native_update = getattr(proxy, "with_vertex_attributes", None)
    if callable(native_update):
        if np.array_equal(attributes, proxy.vertex_attributes):
            return proxy
        return native_update(attributes)
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


def _build_native_baseline(proxy: MC2ProxyStaticSpec, *, native_context=None) -> dict:
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
        native_context is not None,
    )
    child_count = int(counts["child_count"])
    baseline_count = int(counts["baseline_count"])
    baseline_data_count = int(counts["baseline_data_count"])
    if native_context is not None:
        return {
            "attributes": attributes,
            "parents": parents,
            "child_ranges": child_ranges,
            "child_data": child_data[:child_count],
            "baseline_flags": baseline_flags[:baseline_count],
            "baseline_ranges": baseline_ranges[:baseline_count],
            "baseline_data": baseline_data[:baseline_data_count],
            "roots": roots,
            "depths": depths,
            "local_positions": local_positions,
            "local_rotations": local_rotations,
            "native_registration": {
                "parents": counts["baseline_parents"],
                "child_ranges": counts["baseline_child_ranges"],
                "child_data": counts["baseline_child_data"],
                "baseline_flags": counts["baseline_flags"],
                "baseline_ranges": counts["baseline_ranges"],
                "baseline_data": counts["baseline_data"],
                "roots": counts["baseline_roots"],
                "depths": counts["baseline_depths"],
                "local_positions": counts["baseline_local_positions"],
                "local_rotations": counts["baseline_local_rotations"],
                "owners": (
                    counts["_baseline_parents_owner"],
                    counts["_baseline_child_ranges_owner"],
                    counts["_baseline_child_data_owner"],
                    counts["_baseline_flags_owner"],
                    counts["_baseline_ranges_owner"],
                    counts["_baseline_data_owner"],
                    counts["_baseline_roots_owner"],
                    counts["_baseline_depths_owner"],
                    counts["_baseline_local_positions_owner"],
                    counts["_baseline_local_rotations_owner"],
                ),
            },
        }
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


def build_mc2_mesh_baseline(
    proxy: MC2ProxyStaticSpec,
    *,
    native_context=None,
) -> MC2MeshBaselineBuildResult:
    if not isinstance(proxy, MC2ProxyStaticSpec) and not bool(
        getattr(proxy, "native_owned", False)
    ):
        raise TypeError("proxy must be an MC2 proxy static result")
    if proxy.setup_type != "mesh_cloth":
        raise ValueError("Mesh baseline builder only accepts mesh_cloth")

    derived = _build_native_baseline(proxy, native_context=native_context)
    final_attributes = derived["attributes"]
    if native_context is None:
        final_attributes = tuple(int(value) for value in final_attributes)
    final_proxy = _replace_proxy_attributes(proxy, final_attributes)
    if native_context is None:
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
    else:
        baseline = MC2MeshBaselineNativeData(
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
            baseline_signature=_baseline_content_signature(
                final_proxy.proxy_signature, derived
            ),
            native_registration=derived["native_registration"],
        )
    return MC2MeshBaselineBuildResult(final_proxy=final_proxy, baseline=baseline)


__all__ = [
    "MC2_BASELINE_INCLUDE_LINE",
    "MC2_VERTEX_FIXED",
    "MC2_VERTEX_MOVE",
    "MC2_VERTEX_TRIANGLE",
    "MC2_VERTEX_ZERO_DISTANCE",
    "MC2MeshBaselineBuildResult",
    "MC2MeshBaselineMetadata",
    "MC2MeshBaselineNativeData",
    "build_mc2_mesh_baseline",
]
