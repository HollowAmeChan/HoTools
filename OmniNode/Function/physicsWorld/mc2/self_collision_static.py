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
    if not isinstance(spec, MC2SelfCollisionStaticSpec):
        raise TypeError("only full self-collision static specs can be packed")
    count = len(spec.primitive_flags)
    return {
        "primitive_flags": _readonly(spec.primitive_flags, np.uint32, (count,)),
        "particle_indices": _readonly(spec.particle_indices, np.int32, (count, 3)),
        "primitive_depths": _readonly(spec.primitive_depths, np.float32, (count,)),
    }


def _static_signature(
    proxy_signature: str,
    primitive_flags,
    particle_indices,
    primitive_depths,
    counts: tuple[int, int, int],
) -> str:
    digest = hashlib.sha256(proxy_signature.encode("ascii"))
    digest.update(np.ascontiguousarray(primitive_flags, dtype=np.uint32).tobytes())
    digest.update(np.ascontiguousarray(particle_indices, dtype=np.int32).tobytes())
    digest.update(np.ascontiguousarray(primitive_depths, dtype=np.float32).tobytes())
    digest.update(np.asarray(counts, dtype=np.int64).tobytes())
    return digest.hexdigest()


def make_empty_mc2_self_collision_static(
    proxy_signature: str,
) -> MC2SelfCollisionStaticSpec:
    """构造 setup 明确禁用 self collision 时的稳定空静态表。"""

    signature = str(proxy_signature or "").strip()
    if not signature:
        raise ValueError("self-collision proxy signature cannot be empty")
    counts = (0, 0, 0)
    return MC2SelfCollisionStaticSpec(
        proxy_signature=signature,
        primitive_flags=(),
        particle_indices=(),
        primitive_depths=(),
        point_count=0,
        edge_count=0,
        triangle_count=0,
        static_signature=_static_signature(signature, (), (), (), counts),
    )


def build_mc2_self_collision_static(
    proxy: MC2ProxyStaticSpec,
    depths,
) -> MC2SelfCollisionStaticSpec:
    if not isinstance(proxy, MC2ProxyStaticSpec) and not bool(
        getattr(proxy, "native_owned", False)
    ):
        raise TypeError("proxy must be an MC2 proxy static result")
    depth_values = np.ascontiguousarray(depths, dtype=np.float64)
    if depth_values.shape != (proxy.vertex_count,):
        raise ValueError("self-collision depths must match proxy vertices")

    from .native import native_module

    derived = native_module().mc2_build_self_collision_derived(
        np.ascontiguousarray(proxy.vertex_attributes, dtype=np.uint8),
        depth_values,
        np.ascontiguousarray(proxy.edges, dtype=np.int32).reshape((-1, 2)),
        np.ascontiguousarray(proxy.triangles, dtype=np.int32).reshape((-1, 3)),
    )
    packed_flags = derived["primitive_flags"]
    packed_indices = derived["particle_indices"]
    packed_depths = derived["primitive_depths"]
    point_count = int(derived["point_count"])
    edge_count = int(derived["edge_count"])
    triangle_count = int(derived["triangle_count"])
    static_signature = _static_signature(
        proxy.proxy_signature,
        packed_flags,
        packed_indices,
        packed_depths,
        (point_count, edge_count, triangle_count),
    )
    return MC2SelfCollisionStaticSpec(
        proxy_signature=proxy.proxy_signature,
        primitive_flags=tuple(int(value) for value in packed_flags),
        particle_indices=tuple(tuple(int(axis) for axis in value) for value in packed_indices),
        primitive_depths=tuple(float(value) for value in packed_depths),
        point_count=point_count,
        edge_count=edge_count,
        triangle_count=triangle_count,
        static_signature=static_signature,
    )


__all__ = [
    "MC2SelfCollisionStaticSpec",
    "build_mc2_self_collision_static",
    "make_empty_mc2_self_collision_static",
    "pack_mc2_self_collision_static",
]
