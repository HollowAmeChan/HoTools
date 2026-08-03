"""把显式 Bone 列表编译为无向 BoneSegment XPBD 图。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from itertools import combinations, product

import numpy as np

from ..spring_vrm.bone_collision import resolve_bone_pin
from .specs import BoneXpbdTaskSpec


_EPSILON = 1.0e-8
_NEIGHBOR_CELLS = tuple(product((-1, 0, 1), repeat=3))


def _readonly(values, dtype, shape) -> np.ndarray:
    result = np.array(values, dtype=dtype, order="C", copy=True).reshape(shape)
    if not np.isfinite(result).all():
        raise ValueError("Bone XPBD 数组不能包含 NaN 或 Inf")
    result.setflags(write=False)
    return result


def _vec3(value, label: str) -> np.ndarray:
    try:
        result = np.asarray(tuple(value), dtype=np.float64)
    except Exception:
        raise ValueError(f"{label} 必须是有限 float3") from None
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{label} 必须是有限 float3")
    return result


def _digest(label: str, arrays=(), extra=()) -> str:
    digest = hashlib.sha256(label.encode("ascii"))
    for value in extra:
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    for values in arrays:
        array = np.ascontiguousarray(values)
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
        digest.update(array.tobytes())
    return digest.hexdigest()


def _canonical_pairs(values) -> np.ndarray:
    pairs = {
        (min(int(first), int(second)), max(int(first), int(second)))
        for first, second in values
        if int(first) != int(second)
    }
    return np.asarray(sorted(pairs), dtype=np.int32).reshape((-1, 2))


class _DisjointSet:
    def __init__(self, count: int) -> None:
        self.parent = list(range(count))
        self.segment_members = [{index // 2} for index in range(count)]

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            parent = self.find(parent)
            self.parent[value] = parent
        return parent

    def join(self, first: int, second: int) -> bool:
        left = self.find(first)
        right = self.find(second)
        if left == right:
            return True
        if self.segment_members[left].intersection(self.segment_members[right]):
            # 即使经过第三个端点传递，也不能把同一骨段的head/tail折叠。
            return False
        target = min(left, right)
        source = max(left, right)
        self.parent[source] = target
        self.segment_members[target].update(self.segment_members[source])
        self.segment_members[source].clear()
        return True


def _weld_endpoint_groups(
    raw_positions: np.ndarray,
    tolerance: float,
) -> _DisjointSet:
    """用确定性空间桶构造端点等价类，避免常规链条上的 O(N^2) 扫描。"""

    count = int(raw_positions.shape[0])
    disjoint = _DisjointSet(count)
    if count <= 1:
        return disjoint

    tolerance = float(tolerance)
    if tolerance <= 0.0:
        exact_buckets: dict[tuple[float, float, float], list[int]] = {}
        for endpoint in range(count):
            position = raw_positions[endpoint]
            key = tuple(float(value) for value in position)
            candidates = exact_buckets.setdefault(key, [])
            for candidate in candidates:
                if (
                    candidate // 2 != endpoint // 2
                    and disjoint.join(candidate, endpoint)
                ):
                    # 同一精确坐标桶天然属于一个等价类，连接一个代表即可。
                    break
            candidates.append(endpoint)
        return disjoint

    cells: dict[tuple[int, int, int], list[int]] = {}
    for endpoint in range(count):
        position = raw_positions[endpoint]
        cell = tuple(math.floor(float(value) / tolerance) for value in position)
        for offset in _NEIGHBOR_CELLS:
            neighbor = (
                cell[0] + offset[0],
                cell[1] + offset[1],
                cell[2] + offset[2],
            )
            for candidate in cells.get(neighbor, ()):
                if candidate // 2 == endpoint // 2:
                    continue
                if math.dist(raw_positions[candidate], position) <= tolerance:
                    disjoint.join(candidate, endpoint)
        cells.setdefault(cell, []).append(endpoint)
    return disjoint


@dataclass(frozen=True, slots=True)
class BoneXpbdSegment:
    bone_name: str
    parent_name: str
    pose_index: int
    head_particle: int
    tail_particle: int
    rest_length: float

    def debug_dict(self) -> dict:
        return {
            "bone_name": self.bone_name,
            "parent_name": self.parent_name,
            "pose_index": self.pose_index,
            "head_particle": self.head_particle,
            "tail_particle": self.tail_particle,
            "rest_length": self.rest_length,
        }


@dataclass(frozen=True)
class BoneXpbdTopology:
    armature_ptr: int
    armature_data_ptr: int
    bone_names: tuple[str, ...]
    segments: tuple[BoneXpbdSegment, ...]
    particle_count: int
    rest_armature_positions: np.ndarray
    endpoint_particles: np.ndarray
    stretch_indices: np.ndarray
    bend_indices: np.ndarray
    inverse_masses: np.ndarray
    local_collision_radii: np.ndarray
    topology_signature: str
    static_signature: str
    shared_endpoint_count: int
    joint_constraint_count: int

    def debug_dict(self) -> dict:
        return {
            "schema": "bone_xpbd_topology_v1",
            "armature_ptr": self.armature_ptr,
            "armature_data_ptr": self.armature_data_ptr,
            "bone_names": self.bone_names,
            "particle_count": self.particle_count,
            "segment_count": len(self.segments),
            "stretch_constraint_count": int(self.stretch_indices.shape[0]),
            "bend_constraint_count": int(self.bend_indices.shape[0]),
            "shared_endpoint_count": self.shared_endpoint_count,
            "joint_constraint_count": self.joint_constraint_count,
            "topology_signature": self.topology_signature,
            "static_signature": self.static_signature,
        }


def build_bone_xpbd_topology(
    spec: BoneXpbdTaskSpec,
    *,
    world=None,
) -> BoneXpbdTopology:
    if not isinstance(spec, BoneXpbdTaskSpec):
        raise TypeError("build_bone_xpbd_topology 需要 BoneXpbdTaskSpec")
    armature = spec.armature
    data_bones = getattr(getattr(armature, "data", None), "bones", None)
    pose_bones = getattr(getattr(armature, "pose", None), "bones", None)
    if data_bones is None or pose_bones is None:
        raise ValueError("Bone XPBD Armature pose/data 不可用")
    pose_indices = {bone.name: index for index, bone in enumerate(pose_bones)}
    raw_positions = np.empty((len(spec.bone_names) * 2, 3), dtype=np.float64)
    raw_records = []
    for index, name in enumerate(spec.bone_names):
        bone = data_bones.get(name)
        pose_bone = pose_bones.get(name)
        if bone is None or pose_bone is None:
            raise ValueError(f"Bone XPBD 骨骼引用已失效: {name!r}")
        if bool(getattr(bone, "use_connect", False)):
            raise ValueError(
                f"Bone XPBD 不支持 use_connect=True 的骨骼: {name!r}；"
                "请先关闭骨骼的连接选项再注册"
            )
        head = _vec3(getattr(bone, "head_local", None), f"Bone {name} head_local")
        tail = _vec3(getattr(bone, "tail_local", None), f"Bone {name} tail_local")
        length = float(np.linalg.norm(tail - head))
        if not math.isfinite(length) or length <= _EPSILON:
            raise ValueError(f"Bone XPBD 不接受零长度骨骼: {name!r}")
        raw_positions[index * 2] = head
        raw_positions[index * 2 + 1] = tail
        parent = getattr(pose_bone, "parent", None)
        parent_name = str(getattr(parent, "name", "") or "")
        raw_records.append((name, parent_name, int(pose_indices.get(name, -1)), length))

    disjoint = _DisjointSet(len(raw_positions))
    if spec.weld_shared_endpoints:
        # 拓扑只认显式输入与 rest 几何，不读取 parent/use_connect 生成物理深度。
        disjoint = _weld_endpoint_groups(raw_positions, spec.weld_tolerance)

    roots = [disjoint.find(index) for index in range(len(raw_positions))]
    unique_roots = sorted(set(roots))
    root_to_particle = {root: index for index, root in enumerate(unique_roots)}
    endpoint_particles = np.asarray(
        [root_to_particle[root] for root in roots], dtype=np.int32
    ).reshape((-1, 2))
    collapsed = [
        spec.bone_names[index]
        for index, (head, tail) in enumerate(endpoint_particles)
        if int(head) == int(tail)
    ]
    if collapsed:
        raise RuntimeError(
            "Bone XPBD 端点焊接破坏骨段不变量: "
            f"{', '.join(collapsed)}"
        )
    particle_count = len(unique_roots)
    rest_positions = np.zeros((particle_count, 3), dtype=np.float64)
    counts = np.zeros((particle_count,), dtype=np.int32)
    for raw_endpoint, particle in enumerate(endpoint_particles.reshape(-1)):
        rest_positions[particle] += raw_positions[raw_endpoint]
        counts[particle] += 1
    rest_positions /= counts[:, None]

    stretch_pairs = []
    bend_pairs = []
    segments = []
    for index, (name, parent_name, pose_index, length) in enumerate(raw_records):
        head_particle, tail_particle = (
            int(endpoint_particles[index, 0]),
            int(endpoint_particles[index, 1]),
        )
        stretch_pairs.append((head_particle, tail_particle))
        segments.append(BoneXpbdSegment(
            name,
            parent_name,
            pose_index,
            head_particle,
            tail_particle,
            length,
        ))
    incident_segments: dict[int, list[tuple[int, int]]] = {}
    for segment_index, segment in enumerate(segments):
        incident_segments.setdefault(segment.head_particle, []).append((
            segment_index,
            segment.tail_particle,
        ))
        incident_segments.setdefault(segment.tail_particle, []).append((
            segment_index,
            segment.head_particle,
        ))
    for joint in sorted(incident_segments):
        incident = incident_segments[joint]
        for first, second in combinations(incident, 2):
            first_segment, first_opposite = first
            second_segment, second_opposite = second
            if (
                first_segment != second_segment
                and first_opposite != second_opposite
            ):
                bend_pairs.append((first_opposite, second_opposite))

    inverse_masses = np.ones((particle_count,), dtype=np.float32)
    for index, segment in enumerate(segments):
        pin_override = spec.object_spec.pin_overrides[index]
        pinned = (
            resolve_bone_pin(armature, segment.bone_name, world=world)
            if pin_override is None
            else pin_override
        )
        if pinned:
            inverse_masses[segment.head_particle] = 0.0
            inverse_masses[segment.tail_particle] = 0.0
    radii = np.zeros((particle_count,), dtype=np.float32)
    if spec.collision_enabled and spec.particle_radius > 0.0:
        radii.fill(np.float32(spec.particle_radius))

    rest_positions = _readonly(rest_positions, np.float32, (particle_count, 3))
    endpoint_particles = _readonly(endpoint_particles, np.int32, (-1, 2))
    stretch_indices = _readonly(_canonical_pairs(stretch_pairs), np.int32, (-1, 2))
    bend_indices = _readonly(_canonical_pairs(bend_pairs), np.int32, (-1, 2))
    inverse_masses = _readonly(inverse_masses, np.float32, (particle_count,))
    radii = _readonly(radii, np.float32, (particle_count,))
    topology_signature = _digest(
        "bone_xpbd_topology_v1",
        (rest_positions, endpoint_particles, stretch_indices, bend_indices),
        (
            spec.object_spec.armature_ptr,
            spec.object_spec.armature_data_ptr,
            spec.bone_names,
        ),
    )
    static_signature = _digest(
        "bone_xpbd_static_v1",
        (inverse_masses, radii),
        (topology_signature, spec.static_signature),
    )
    return BoneXpbdTopology(
        spec.object_spec.armature_ptr,
        spec.object_spec.armature_data_ptr,
        spec.bone_names,
        tuple(segments),
        particle_count,
        rest_positions,
        endpoint_particles,
        stretch_indices,
        bend_indices,
        inverse_masses,
        radii,
        topology_signature,
        static_signature,
        len(raw_positions) - particle_count,
        0,
    )


__all__ = [
    "BoneXpbdSegment",
    "BoneXpbdTopology",
    "build_bone_xpbd_topology",
]
