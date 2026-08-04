"""Bone XPBD 对共享原生距离约束 context 的生命周期适配。"""

from __future__ import annotations

import numpy as np

from ..colliders import MeshXpbdColliderFrame
from ..native import require_xpbd_native_module
from .pose import BoneXpbdPoseFrame
from .specs import BoneXpbdTaskSpec
from .topology import BoneXpbdTopology


class BoneXpbdNativeContext:
    """slot 唯一持有；底层复用通用粒子/距离约束 context。"""

    __slots__ = (
        "_context",
        "topology_signature",
        "static_signature",
        "parameter_signature",
    )

    def __init__(self) -> None:
        self._context = None
        self.topology_signature = ""
        self.static_signature = ""
        self.parameter_signature = ""

    @property
    def ready(self) -> bool:
        return self._context is not None and not bool(self._context.disposed)

    def rebuild(
        self,
        topology: BoneXpbdTopology,
        frame: BoneXpbdPoseFrame,
        spec: BoneXpbdTaskSpec,
    ) -> None:
        module = require_xpbd_native_module()
        context = module.mesh_xpbd_create_context_v1(
            np.ascontiguousarray(frame.world_positions, dtype=np.float32),
            np.ascontiguousarray(topology.inverse_masses, dtype=np.float32),
            np.ascontiguousarray(topology.stretch_indices, dtype=np.int32),
            np.ascontiguousarray(topology.bend_indices, dtype=np.int32),
            np.ascontiguousarray(frame.world_collision_radii, dtype=np.float32),
            spec.damping,
            spec.stretch_compliance,
            spec.bend_compliance,
            spec.iterations,
        )
        if not hasattr(context, "update_pin_targets"):
            context.dispose()
            raise RuntimeError(
                "hotools_native 缺少 Bone XPBD 所需的 moving Pin target API"
            )
        previous = self._context
        self._context = context
        self.topology_signature = topology.topology_signature
        self.static_signature = topology.static_signature
        self.parameter_signature = spec.parameter_signature
        if previous is not None:
            previous.dispose()

    def update_pin_targets(self, frame: BoneXpbdPoseFrame) -> None:
        self._require_context().update_pin_targets(
            np.ascontiguousarray(frame.world_positions, dtype=np.float32)
        )

    def update_parameters(self, spec: BoneXpbdTaskSpec) -> None:
        self._require_context().update_parameters(
            spec.damping,
            spec.stretch_compliance,
            spec.bend_compliance,
            spec.iterations,
        )
        self.parameter_signature = spec.parameter_signature

    def reset(self, frame: BoneXpbdPoseFrame) -> None:
        self._require_context().reset(
            np.ascontiguousarray(frame.world_positions, dtype=np.float32)
        )
        self.update_pin_targets(frame)

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
            raise RuntimeError("Bone XPBD native 返回非法 positions")
        return np.ascontiguousarray(positions, dtype=np.float32)

    def read_positions(self) -> np.ndarray:
        return np.ascontiguousarray(
            self._require_context().read_positions(),
            dtype=np.float32,
        )

    def stats(self) -> dict:
        return dict(self._require_context().stats())

    def dispose(self) -> None:
        context = self._context
        self._context = None
        self.topology_signature = ""
        self.static_signature = ""
        self.parameter_signature = ""
        if context is not None:
            context.dispose()

    def _require_context(self):
        if not self.ready:
            raise RuntimeError("Bone XPBD native context 尚未建立或已释放")
        return self._context


__all__ = ["BoneXpbdNativeContext"]
