"""MeshCloth main-thread capture adapter for the unified-domain pipeline.

The expensive Mesh arrays are supplied by ``MC2MeshRawSnapshot`` so this
adapter never scans Blender mesh collections a second time.  It reads only the
source transform and freezes backend-neutral POD for later fragment building.
"""

from __future__ import annotations

import numpy as np

from ...domain_ir import MC2MeshPartitionStaticSnapshotV1
from ...domain_ir import make_mc2_mesh_partition_static_snapshot
from ...topology import MC2MeshRawSnapshot


def _source_pointer(source) -> int:
    pointer = getattr(source, "as_pointer", None)
    if not callable(pointer):
        raise TypeError("MeshCloth capture source must expose as_pointer()")
    value = int(pointer())
    if value <= 0:
        raise ValueError("MeshCloth capture source is no longer valid")
    return value


def _source_bind_matrix(source) -> tuple[tuple[float, ...], ...]:
    matrix = getattr(source, "matrix_world", None)
    if matrix is None:
        return (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    try:
        return tuple(
            tuple(float(matrix[row][column]) for column in range(4))
            for row in range(4)
        )
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("MeshCloth source matrix_world must be a finite 4x4 matrix") from exc


def _pin_weights(snapshot: MC2MeshRawSnapshot) -> tuple[bool, object]:
    if not snapshot.pin_enabled:
        return False, ()
    vertex_count = len(snapshot.positions)
    values = np.asarray(snapshot.pin_weights)
    if values.shape == (vertex_count,):
        return True, values
    if values.size == 0 and not snapshot.pin_name:
        return True, np.ones(vertex_count, dtype=np.float32)
    raise ValueError("enabled MeshCloth pin capture must resolve one weight per vertex")


def capture_mc2_mesh_partition_static_snapshot(
    source,
    raw_snapshot: MC2MeshRawSnapshot,
    *,
    partition_id: str,
    source_identity: str,
    source_revision: str,
    output_target_id: str,
) -> MC2MeshPartitionStaticSnapshotV1:
    """Freeze one already-read Mesh source without touching solver state."""

    if not isinstance(raw_snapshot, MC2MeshRawSnapshot):
        raise TypeError("raw_snapshot must be MC2MeshRawSnapshot")
    if _source_pointer(source) != int(raw_snapshot.source_pointer):
        raise ValueError("MeshCloth raw snapshot does not belong to the source object")
    pin_present, pin_weights = _pin_weights(raw_snapshot)
    return make_mc2_mesh_partition_static_snapshot(
        partition_id=partition_id,
        source_identity=source_identity,
        source_revision=source_revision,
        output_target_id=output_target_id,
        local_positions=raw_snapshot.positions,
        local_normals=raw_snapshot.normals,
        edges=raw_snapshot.edges,
        triangles=raw_snapshot.triangles,
        triangle_loops=raw_snapshot.triangle_loops,
        loop_vertices=raw_snapshot.loop_vertices,
        loop_uvs=raw_snapshot.loop_uvs if raw_snapshot.has_uv else None,
        pin_weights=pin_weights if pin_present else None,
        pin_present=pin_present,
        radius_multipliers=raw_snapshot.radius_multipliers,
        source_bind_matrix=_source_bind_matrix(source),
        source_element_ids=range(len(raw_snapshot.positions)),
        has_uv=bool(raw_snapshot.has_uv),
    )


__all__ = ["capture_mc2_mesh_partition_static_snapshot"]
