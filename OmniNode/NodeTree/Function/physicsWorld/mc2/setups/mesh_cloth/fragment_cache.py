"""Transactional cache for host-owned MeshCloth static fragments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ...domain_ir import MC2MeshPartitionStaticSnapshotV1
from .static_fragment import MC2MeshStaticFragmentV1
from .static_fragment import build_mc2_mesh_static_fragment


FragmentCacheKey = tuple[str, tuple[float, float, float]]


def _gravity_key(value) -> tuple[float, float, float]:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError("world_gravity_direction must be finite xyz")
    return tuple(float(component) for component in array)


@dataclass(frozen=True)
class MC2MeshFragmentCacheBatchV1:
    """A staged cache result that has not changed the live cache yet."""

    fragments: tuple[MC2MeshStaticFragmentV1, ...]
    keys: tuple[FragmentCacheKey, ...]
    cache_hits: tuple[bool, ...]
    pending_entries: tuple[tuple[FragmentCacheKey, MC2MeshStaticFragmentV1], ...]
    base_revision: int
    _owner_token: object = field(repr=False, compare=False)

    @property
    def hit_count(self) -> int:
        return sum(self.cache_hits)

    @property
    def build_count(self) -> int:
        return len(self.pending_entries)

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_mesh_fragment_cache_batch_v1",
            "partition_ids": [fragment.partition_id for fragment in self.fragments],
            "hit_count": self.hit_count,
            "build_count": self.build_count,
            "base_revision": self.base_revision,
        }


class MC2MeshFragmentCacheV1:
    """Stages expensive Tier A products and publishes them batch-atomically."""

    def __init__(
        self,
        builder: Callable[..., MC2MeshStaticFragmentV1] = build_mc2_mesh_static_fragment,
    ) -> None:
        if not callable(builder):
            raise TypeError("builder must be callable")
        self._builder = builder
        self._entries: dict[FragmentCacheKey, MC2MeshStaticFragmentV1] = {}
        self._revision = 0
        self._owner_token = object()

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def stage(
        self,
        snapshots,
        *,
        world_gravity_direction=(0.0, -1.0, 0.0),
    ) -> MC2MeshFragmentCacheBatchV1:
        snapshots = tuple(snapshots)
        if not snapshots:
            raise ValueError("Mesh fragment cache batch cannot be empty")
        if any(
            not isinstance(snapshot, MC2MeshPartitionStaticSnapshotV1)
            for snapshot in snapshots
        ):
            raise TypeError("snapshots must contain Mesh static snapshot V1 values")
        partition_ids = tuple(snapshot.partition_id for snapshot in snapshots)
        if len(set(partition_ids)) != len(partition_ids):
            raise ValueError("Mesh fragment cache batch partition ids must be unique")

        gravity = _gravity_key(world_gravity_direction)
        fragments = []
        keys = []
        hits = []
        pending: dict[FragmentCacheKey, MC2MeshStaticFragmentV1] = {}
        for snapshot in snapshots:
            key = (snapshot.static_signature, gravity)
            fragment = self._entries.get(key)
            hit = fragment is not None
            if fragment is None:
                fragment = pending.get(key)
            if fragment is None:
                fragment = self._builder(
                    snapshot,
                    world_gravity_direction=gravity,
                )
                if not isinstance(fragment, MC2MeshStaticFragmentV1):
                    raise TypeError("Mesh fragment builder returned an invalid value")
                if (
                    fragment.snapshot_signature != snapshot.static_signature
                    or fragment.partition_id != snapshot.partition_id
                    or fragment.output_target_id != snapshot.output_target_id
                ):
                    raise ValueError("Mesh fragment builder changed snapshot identity")
                pending[key] = fragment
            fragments.append(fragment)
            keys.append(key)
            hits.append(hit)
        return MC2MeshFragmentCacheBatchV1(
            fragments=tuple(fragments),
            keys=tuple(keys),
            cache_hits=tuple(hits),
            pending_entries=tuple(pending.items()),
            base_revision=self._revision,
            _owner_token=self._owner_token,
        )

    def commit(self, batch: MC2MeshFragmentCacheBatchV1) -> None:
        if not isinstance(batch, MC2MeshFragmentCacheBatchV1):
            raise TypeError("batch must be MC2MeshFragmentCacheBatchV1")
        if batch._owner_token is not self._owner_token:
            raise ValueError("Mesh fragment cache batch belongs to another cache")
        if batch.base_revision != self._revision:
            raise RuntimeError("Mesh fragment cache batch is stale")
        entries = dict(self._entries)
        entries.update(batch.pending_entries)
        self._entries = {key: entries[key] for key in batch.keys}
        self._revision += 1

    def inspect(self) -> dict:
        return {
            "schema": "mc2_mesh_fragment_cache_v1",
            "revision": self._revision,
            "entry_count": len(self._entries),
            "partition_ids": [
                fragment.partition_id for fragment in self._entries.values()
            ],
        }

    def clear(self) -> None:
        self._entries = {}
        self._revision += 1


__all__ = [
    "MC2MeshFragmentCacheBatchV1",
    "MC2MeshFragmentCacheV1",
]
