"""Mesh XPBD nanobind context 的 Python 生命周期适配。"""

from __future__ import annotations

import numpy as np

from ..colliders import MeshXpbdColliderFrame
from ..native import is_available, require_xpbd_native_module
from .specs import MeshXpbdTaskSpec
from .topology import MeshXpbdReferenceFrame, MeshXpbdTopology


class MeshXpbdNativeContext:
    """一个 solver slot 持有的唯一 native context owner。"""

    __slots__ = (
        "_context",
        "topology_signature",
        "reference_signature",
        "parameter_signature",
    )

    def __init__(self) -> None:
        self._context = None
        self.topology_signature = ""
        self.reference_signature = ""
        self.parameter_signature = ""

    @property
    def ready(self) -> bool:
        return self._context is not None and not bool(self._context.disposed)

    def rebuild(
        self,
        topology: MeshXpbdTopology,
        reference: MeshXpbdReferenceFrame,
        spec: MeshXpbdTaskSpec,
    ) -> None:
        module = require_xpbd_native_module()
        next_context = module.mesh_xpbd_create_context_v1(
            np.ascontiguousarray(reference.rest_world_positions, dtype=np.float32),
            np.ascontiguousarray(topology.inverse_masses, dtype=np.float32),
            np.ascontiguousarray(topology.stretch_indices, dtype=np.int32),
            np.ascontiguousarray(topology.bend_indices, dtype=np.int32),
            np.ascontiguousarray(reference.world_collision_radii, dtype=np.float32),
            spec.damping,
            spec.stretch_compliance,
            spec.bend_compliance,
            spec.iterations,
        )
        previous = self._context
        self._context = next_context
        self.topology_signature = topology.topology_signature
        self.reference_signature = reference.signature
        self.parameter_signature = spec.parameter_signature
        if previous is not None:
            previous.dispose()

    def update_reference(
        self,
        topology: MeshXpbdTopology,
        reference: MeshXpbdReferenceFrame,
    ) -> None:
        self._require_context().update_reference(
            np.ascontiguousarray(reference.rest_world_positions, dtype=np.float32),
            np.ascontiguousarray(topology.inverse_masses, dtype=np.float32),
            np.ascontiguousarray(reference.world_collision_radii, dtype=np.float32),
        )
        self.reference_signature = reference.signature

    def update_parameters(self, spec: MeshXpbdTaskSpec) -> None:
        self._require_context().update_parameters(
            spec.damping,
            spec.stretch_compliance,
            spec.bend_compliance,
            spec.iterations,
        )
        self.parameter_signature = spec.parameter_signature

    def update_pin_targets(self, positions) -> None:
        """只移动 Fixed 粒子目标，不改变 constraint rest。"""
        self._require_context().update_pin_targets(
            np.ascontiguousarray(positions, dtype=np.float32)
        )

    def reset(self, reference: MeshXpbdReferenceFrame) -> None:
        self._require_context().reset(
            np.ascontiguousarray(reference.rest_world_positions, dtype=np.float32)
        )

    def step(
        self,
        *,
        delta_time: float,
        substeps: int,
        gravity_direction,
        gravity_power: float,
        colliders: MeshXpbdColliderFrame,
        collided_by_groups: int,
    ) -> np.ndarray:
        gravity = np.ascontiguousarray(gravity_direction, dtype=np.float32).reshape((3,))
        result = self._require_context().step(
            float(delta_time),
            int(substeps),
            gravity,
            float(gravity_power),
            *colliders.native_args(),
            int(collided_by_groups),
        )
        positions = np.asarray(result, dtype=np.float32)
        if positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all():
            raise RuntimeError("Mesh XPBD native 返回了非法 positions")
        return np.ascontiguousarray(positions, dtype=np.float32)

    def read_positions(self) -> np.ndarray:
        return np.ascontiguousarray(
            self._require_context().read_positions(), dtype=np.float32
        )

    def stats(self) -> dict:
        return dict(self._require_context().stats())

    def dispose(self) -> None:
        context = self._context
        self._context = None
        self.topology_signature = ""
        self.reference_signature = ""
        self.parameter_signature = ""
        if context is not None:
            context.dispose()

    def _require_context(self):
        if not self.ready:
            raise RuntimeError("Mesh XPBD native context 尚未建立或已释放")
        return self._context
