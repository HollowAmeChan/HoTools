"""从 resolved Bone partition 构建 DomainV1 宿主静态 fragment。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...partition_specs import MC2ResolvedPartitionSpec
from ...topology import MC2BoneRawSnapshot, MC2StaticInputFingerprint, MC2TopologySpec
from .static_build import MC2BoneClothStaticBuildResult
from .static_build import build_mc2_bone_static_for_partition


@dataclass(frozen=True)
class _MC2BoneBaselineViewV1:
    final_proxy: object
    baseline: object


@dataclass(frozen=True)
class MC2BoneStaticFragmentV1:
    snapshot_signature: str
    partition_id: str
    output_target_id: str
    setup_type: str
    topology: MC2TopologySpec
    static: MC2BoneClothStaticBuildResult
    radius_multipliers: np.ndarray
    source_elements: np.ndarray
    output_bone_identities: tuple[str, ...]
    output_source_elements: np.ndarray
    output_endpoint_source_elements: np.ndarray

    def __post_init__(self) -> None:
        if not self.snapshot_signature or not self.partition_id or not self.output_target_id:
            raise ValueError("Bone static fragment identity 不能为空")
        if not isinstance(self.topology, MC2TopologySpec):
            raise TypeError("topology 必须是 MC2TopologySpec")
        if not isinstance(self.static, MC2BoneClothStaticBuildResult):
            raise TypeError("static 必须是 MC2BoneClothStaticBuildResult")
        if self.setup_type != self.topology.setup_type:
            raise ValueError("Bone static fragment setup_type 不一致")
        if self.partition_id != self.topology.task_id:
            raise ValueError("Bone static fragment partition/topology identity 不一致")
        count = self.static.final_proxy.vertex_count
        for values, dtype, shape, name in (
            (self.radius_multipliers, np.float32, (count,), "radius_multipliers"),
            (self.source_elements, np.uint32, (count,), "source_elements"),
            (
                self.output_source_elements,
                np.uint32,
                (len(self.output_bone_identities),),
                "output_source_elements",
            ),
            (
                self.output_endpoint_source_elements,
                np.uint32,
                (len(self.output_bone_identities),),
                "output_endpoint_source_elements",
            ),
        ):
            if (
                not isinstance(values, np.ndarray)
                or values.dtype != dtype
                or values.shape != shape
                or values.flags.writeable
                or not values.flags.c_contiguous
            ):
                raise ValueError(f"{name} 必须是只读连续 {dtype.__name__}{shape}")

        identities = tuple(str(value or "") for value in self.output_bone_identities)
        if (
            len(identities) != len(self.output_bone_identities)
            or any(not value for value in identities)
            or len(set(identities)) != len(identities)
        ):
            raise ValueError("output_bone_identities must be unique non-empty names")
        if np.any(self.output_source_elements >= count):
            raise ValueError("output_source_elements contains an invalid particle")
        if np.any(self.output_endpoint_source_elements >= count):
            raise ValueError(
                "output_endpoint_source_elements contains an invalid particle"
            )
        if len(self.output_source_elements) and len(
            np.unique(self.output_source_elements)
        ) != len(self.output_source_elements):
            raise ValueError("output_source_elements must be unique")
        if tuple(
            self.static.final_proxy.vertex_identities[int(index)]
            for index in self.output_source_elements
        ) != identities:
            raise ValueError("output identities do not match particle mapping")
        if np.any(
            self.output_endpoint_source_elements
            != self.output_source_elements + np.uint32(1)
        ):
            raise ValueError("Bone output endpoints must follow their head particles")

    @property
    def final_proxy(self):
        return self.static.final_proxy

    @property
    def finalizer(self):
        return self.static.finalizer

    @property
    def baseline(self):
        return _MC2BoneBaselineViewV1(
            final_proxy=self.static.final_proxy,
            baseline=self.static.baseline,
        )

    @property
    def distance(self):
        return self.static.distance

    @property
    def bending(self):
        return self.static.bending

    @property
    def center(self):
        return self.static.center

    @property
    def self_collision(self):
        return self.static.self_collision

    @property
    def output_space_kind(self) -> str:
        return "bone_pose"

    @property
    def vertex_to_transform_rotations(self) -> np.ndarray:
        values = np.ascontiguousarray(
            self.static.bone.vertex_to_transform_rotations,
            dtype=np.float32,
        )
        values.flags.writeable = False
        return values

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_bone_static_fragment_v1",
            "setup_type": self.setup_type,
            "snapshot_signature": self.snapshot_signature,
            "partition_id": self.partition_id,
            "output_target_id": self.output_target_id,
            "particle_count": self.final_proxy.vertex_count,
            "output_bone_count": len(self.output_bone_identities),
            "connection_mode": self.topology.connection_mode,
            "connection_model": self.topology.connection_model,
            "static": self.static.debug_dict(),
        }


def _bone_output_target_id(partition: MC2ResolvedPartitionSpec) -> str:
    armature = getattr(partition.source, "armature", None)
    pointer = getattr(armature, "as_pointer", None)
    data_pointer = getattr(getattr(armature, "data", None), "as_pointer", None)
    owner = int(pointer()) if callable(pointer) else 0
    data = int(data_pointer()) if callable(data_pointer) else 0
    if owner <= 0 or data <= 0:
        raise ValueError("Bone product Armature target identity 无效")
    return f"bone:{owner}:{data}:{partition.stable_id}"


def build_mc2_bone_static_fragment(
    partition: MC2ResolvedPartitionSpec,
    fingerprint: MC2StaticInputFingerprint,
    topology: MC2TopologySpec,
    raw_snapshots,
) -> MC2BoneStaticFragmentV1:
    if not isinstance(partition, MC2ResolvedPartitionSpec):
        raise TypeError("partition 必须是 MC2ResolvedPartitionSpec")
    if not isinstance(fingerprint, MC2StaticInputFingerprint):
        raise TypeError("fingerprint 必须是 MC2StaticInputFingerprint")
    snapshots = tuple(raw_snapshots)
    if not snapshots or any(not isinstance(value, MC2BoneRawSnapshot) for value in snapshots):
        raise TypeError("raw_snapshots 必须包含 Bone raw snapshot")
    static = build_mc2_bone_static_for_partition(
        partition,
        topology,
        raw_snapshots=snapshots,
    )
    count = static.final_proxy.vertex_count
    radius = np.ones(count, dtype=np.float32)
    source_elements = np.arange(count, dtype=np.uint32)
    output_bone_identities = []
    output_source_elements = []
    output_endpoint_source_elements = []
    offset = 0
    for snapshot in snapshots:
        output_bone_identities.extend(snapshot.names)
        output_source_elements.extend(
            range(offset, offset + len(snapshot.names))
        )
        output_endpoint_source_elements.extend(
            range(offset + 1, offset + len(snapshot.names) + 1)
        )
        offset += len(snapshot.names) + len(snapshot.terminal_names)
    if offset != count:
        raise ValueError("Bone fragment particle/source offset mismatch")
    output_source_elements = np.asarray(
        output_source_elements,
        dtype=np.uint32,
    )
    output_endpoint_source_elements = np.asarray(
        output_endpoint_source_elements,
        dtype=np.uint32,
    )
    radius.flags.writeable = False
    source_elements.flags.writeable = False
    output_source_elements.flags.writeable = False
    output_endpoint_source_elements.flags.writeable = False
    return MC2BoneStaticFragmentV1(
        snapshot_signature=fingerprint.overall,
        partition_id=partition.stable_id,
        output_target_id=_bone_output_target_id(partition),
        setup_type=partition.setup_type,
        topology=topology,
        static=static,
        radius_multipliers=radius,
        source_elements=source_elements,
        output_bone_identities=tuple(output_bone_identities),
        output_source_elements=output_source_elements,
        output_endpoint_source_elements=output_endpoint_source_elements,
    )


__all__ = ["MC2BoneStaticFragmentV1", "build_mc2_bone_static_fragment"]
