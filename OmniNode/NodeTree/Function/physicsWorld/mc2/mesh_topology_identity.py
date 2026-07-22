"""Pure Mesh topology identity shared by capture and BasePose validation."""

from __future__ import annotations

import hashlib

import numpy as np


def mesh_topology_signature_from_arrays(
    vertex_count: int,
    edges,
    polygon_loop_totals,
    loop_vertices,
    triangles,
) -> str:
    canonical_edges = np.asarray(edges, dtype="<i4").reshape((-1, 2)).copy()
    canonical_edges.sort(axis=1)
    if len(canonical_edges):
        order = np.lexsort((canonical_edges[:, 1], canonical_edges[:, 0]))
        canonical_edges = np.ascontiguousarray(canonical_edges[order])
    arrays = (
        canonical_edges,
        np.asarray(polygon_loop_totals, dtype="<i4").reshape((-1,)),
        np.asarray(loop_vertices, dtype="<i4").reshape((-1,)),
        np.asarray(triangles, dtype="<i4").reshape((-1, 3)),
    )
    digest = hashlib.sha256(b"mc2_mesh_topology_v1\0")
    digest.update(np.asarray((int(vertex_count),), dtype="<i8").tobytes())
    for values in arrays:
        contiguous = np.ascontiguousarray(values, dtype="<i4")
        digest.update(np.asarray(contiguous.shape, dtype="<i8").tobytes())
        digest.update(contiguous.tobytes())
    return digest.hexdigest()


__all__ = ["mesh_topology_signature_from_arrays"]
