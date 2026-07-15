"""Source-ordered MC2 self-collision primitive registration data."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np

from .static_data import MC2ProxyStaticSpec


KIND_POINT = 0
KIND_EDGE = 1
KIND_TRIANGLE = 2
FLAG_FIX0 = 0x04000000
FLAG_FIX1 = 0x08000000
FLAG_FIX2 = 0x10000000
FLAG_ALL_FIX = 0x20000000
FLAG_IGNORE = 0x40000000


def _primitive_flag(kind: int, vertices: tuple[int, ...], attributes) -> int:
    flag = int(kind) << 24
    fix_flags = (FLAG_FIX0, FLAG_FIX1, FLAG_FIX2)
    fixed_count = 0
    ignored = False
    for axis, vertex in enumerate(vertices):
        attribute = int(attributes[vertex])
        if attribute & 0x02 == 0:
            flag |= fix_flags[axis]
            fixed_count += 1
        if attribute & 0x03 == 0:
            ignored = True
    if fixed_count == len(vertices):
        flag |= FLAG_ALL_FIX
    if ignored:
        flag |= FLAG_IGNORE
    return flag


@dataclass(frozen=True)
class MC2SelfCollisionStaticSpec:
    proxy_signature: str
    primitive_flags: tuple[int, ...]
    particle_indices: tuple[tuple[int, int, int], ...]
    primitive_depths: tuple[float, ...]
    point_count: int
    edge_count: int
    triangle_count: int
    static_signature: str

    @property
    def primitive_count(self) -> int:
        return len(self.primitive_flags)

    def __post_init__(self) -> None:
        count = self.point_count + self.edge_count + self.triangle_count
        if not self.proxy_signature or not self.static_signature:
            raise ValueError("self-collision signatures cannot be empty")
        if min(self.point_count, self.edge_count, self.triangle_count) < 0:
            raise ValueError("self-collision primitive counts cannot be negative")
        if count != self.primitive_count:
            raise ValueError("self-collision primitive counts do not cover flags")
        if len(self.particle_indices) != count or len(self.primitive_depths) != count:
            raise ValueError("self-collision primitive arrays must have equal length")
        if any(len(value) != 3 for value in self.particle_indices):
            raise ValueError("self-collision particle indices must be int3 records")
        if any(value < 0 or value > 0xFFFFFFFF for value in self.primitive_flags):
            raise ValueError("self-collision flags must fit uint32")
        if any(not np.isfinite(value) or not 0.0 <= value <= 1.0 for value in self.primitive_depths):
            raise ValueError("self-collision primitive depths must be normalized")
        packed = pack_mc2_self_collision_static(self)
        digest = hashlib.sha256(self.proxy_signature.encode("ascii"))
        for name in ("primitive_flags", "particle_indices", "primitive_depths"):
            digest.update(packed[name].tobytes())
        digest.update(np.asarray((self.point_count, self.edge_count, self.triangle_count), dtype=np.int64).tobytes())
        if digest.hexdigest() != self.static_signature:
            raise ValueError("self-collision static signature mismatch")

    def debug_dict(self) -> dict:
        return {
            "primitive_count": self.primitive_count,
            "point_count": self.point_count,
            "edge_count": self.edge_count,
            "triangle_count": self.triangle_count,
            "static_signature": self.static_signature,
        }


def _readonly(values, dtype, shape):
    result = np.ascontiguousarray(values, dtype=dtype).reshape(shape)
    result.setflags(write=False)
    return result


def pack_mc2_self_collision_static(spec: MC2SelfCollisionStaticSpec) -> dict[str, np.ndarray]:
    count = len(spec.primitive_flags)
    return {
        "primitive_flags": _readonly(spec.primitive_flags, np.uint32, (count,)),
        "particle_indices": _readonly(spec.particle_indices, np.int32, (count, 3)),
        "primitive_depths": _readonly(spec.primitive_depths, np.float32, (count,)),
    }


def build_mc2_self_collision_static(
    proxy: MC2ProxyStaticSpec,
    depths,
) -> MC2SelfCollisionStaticSpec:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    depths = tuple(float(value) for value in depths)
    if len(depths) != proxy.vertex_count:
        raise ValueError("self-collision depths must match proxy vertices")

    flags = []
    indices = []
    primitive_depths = []
    point_count = proxy.vertex_count if proxy.triangles else 0
    for vertex in range(point_count):
        vertices = (vertex,)
        flags.append(_primitive_flag(KIND_POINT, vertices, proxy.vertex_attributes))
        indices.append((vertex, -1, -1))
        primitive_depths.append(depths[vertex])
    for edge in proxy.edges:
        vertices = tuple(int(value) for value in edge)
        flags.append(_primitive_flag(KIND_EDGE, vertices, proxy.vertex_attributes))
        indices.append((vertices[0], vertices[1], -1))
        primitive_depths.append(sum(depths[value] for value in vertices) / 2.0)
    for triangle in proxy.triangles:
        vertices = tuple(int(value) for value in triangle)
        flags.append(_primitive_flag(KIND_TRIANGLE, vertices, proxy.vertex_attributes))
        indices.append(vertices)
        primitive_depths.append(sum(depths[value] for value in vertices) / 3.0)

    packed_flags = _readonly(flags, np.uint32, (len(flags),))
    packed_indices = _readonly(indices, np.int32, (len(flags), 3))
    packed_depths = _readonly(primitive_depths, np.float32, (len(flags),))
    digest = hashlib.sha256(proxy.proxy_signature.encode("ascii"))
    for value in (packed_flags, packed_indices, packed_depths):
        digest.update(value.tobytes())
    digest.update(np.asarray((point_count, len(proxy.edges), len(proxy.triangles)), dtype=np.int64).tobytes())
    return MC2SelfCollisionStaticSpec(
        proxy_signature=proxy.proxy_signature,
        primitive_flags=tuple(int(value) for value in packed_flags),
        particle_indices=tuple(tuple(int(axis) for axis in value) for value in packed_indices),
        primitive_depths=tuple(float(value) for value in packed_depths),
        point_count=point_count,
        edge_count=len(proxy.edges),
        triangle_count=len(proxy.triangles),
        static_signature=digest.hexdigest(),
    )


__all__ = [
    "MC2SelfCollisionStaticSpec",
    "build_mc2_self_collision_static",
    "pack_mc2_self_collision_static",
]
