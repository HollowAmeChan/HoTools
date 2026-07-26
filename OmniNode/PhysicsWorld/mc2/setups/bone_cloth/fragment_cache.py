"""Bone 产品静态 fragment 的事务缓存。"""

from __future__ import annotations

from dataclasses import dataclass

from .static_fragment import MC2BoneStaticFragmentV1
from .static_fragment import build_mc2_bone_static_fragment


BoneFragmentCacheKey = tuple[str, str, str, str, int, int]


def _target_identity(static_input) -> tuple[int, int]:
    armature = getattr(static_input.partition.source, "armature", None)
    pointer = getattr(armature, "as_pointer", None)
    data_pointer = getattr(getattr(armature, "data", None), "as_pointer", None)
    owner = int(pointer()) if callable(pointer) else 0
    data = int(data_pointer()) if callable(data_pointer) else 0
    if owner <= 0 or data <= 0:
        raise ValueError("Bone product Armature target identity is invalid")
    return owner, data


def _cache_key(static_input) -> BoneFragmentCacheKey:
    owner, data = _target_identity(static_input)
    return (
        static_input.partition.setup_type,
        static_input.partition.stable_id,
        static_input.fingerprint.overall,
        static_input.topology.topology_signature,
        owner,
        data,
    )


@dataclass(frozen=True)
class MC2BoneFragmentCacheBatchV1:
    fragments: tuple[MC2BoneStaticFragmentV1, ...]
    keys: tuple[BoneFragmentCacheKey, ...]
    cache_hits: tuple[bool, ...]
    pending_entries: tuple[
        tuple[BoneFragmentCacheKey, MC2BoneStaticFragmentV1], ...
    ]
    base_revision: int
    _owner_token: object

    def __post_init__(self) -> None:
        count = len(self.fragments)
        if count != len(self.keys) or count != len(self.cache_hits):
            raise ValueError("Bone fragment cache batch rows must match")
        if any(
            not isinstance(fragment, MC2BoneStaticFragmentV1)
            for fragment in self.fragments
        ):
            raise TypeError("fragments must contain Bone static fragment V1 values")
        if self.base_revision < 0:
            raise ValueError("base_revision cannot be negative")

    @property
    def hit_count(self) -> int:
        return sum(bool(value) for value in self.cache_hits)

    @property
    def build_count(self) -> int:
        return len(self.pending_entries)


class MC2BoneFragmentCacheV1:
    """先构建、后提交，保证静态构建失败不会改变 live cache。"""

    __slots__ = ("_builder", "_entries", "_revision", "_owner_token")

    def __init__(self, builder=build_mc2_bone_static_fragment) -> None:
        if not callable(builder):
            raise TypeError("builder must be callable")
        self._builder = builder
        self._entries: dict[BoneFragmentCacheKey, MC2BoneStaticFragmentV1] = {}
        self._revision = 0
        self._owner_token = object()

    @property
    def revision(self) -> int:
        return self._revision

    def stage(self, static_inputs) -> MC2BoneFragmentCacheBatchV1:
        rows = tuple(static_inputs)
        if not rows:
            raise ValueError("Bone fragment cache requires static inputs")
        fragments = []
        keys = []
        hits = []
        pending: dict[BoneFragmentCacheKey, MC2BoneStaticFragmentV1] = {}
        for row in rows:
            key = _cache_key(row)
            fragment = self._entries.get(key)
            hit = fragment is not None
            if fragment is None:
                fragment = pending.get(key)
            if fragment is None:
                fragment = self._builder(
                    row.partition,
                    row.fingerprint,
                    row.topology,
                    row.raw_snapshots,
                )
                if not isinstance(fragment, MC2BoneStaticFragmentV1):
                    raise TypeError("Bone fragment builder returned an invalid value")
                owner, data = _target_identity(row)
                expected_target = (
                    f"bone:{owner}:{data}:{row.partition.stable_id}"
                )
                if (
                    fragment.snapshot_signature != row.fingerprint.overall
                    or fragment.partition_id != row.partition.stable_id
                    or fragment.setup_type != row.partition.setup_type
                    or fragment.topology.topology_signature
                    != row.topology.topology_signature
                    or fragment.output_target_id != expected_target
                ):
                    raise ValueError("Bone fragment builder changed static identity")
                pending[key] = fragment
            fragments.append(fragment)
            keys.append(key)
            hits.append(hit)
        return MC2BoneFragmentCacheBatchV1(
            fragments=tuple(fragments),
            keys=tuple(keys),
            cache_hits=tuple(hits),
            pending_entries=tuple(pending.items()),
            base_revision=self._revision,
            _owner_token=self._owner_token,
        )

    def commit(self, batch: MC2BoneFragmentCacheBatchV1) -> None:
        if not isinstance(batch, MC2BoneFragmentCacheBatchV1):
            raise TypeError("batch must be MC2BoneFragmentCacheBatchV1")
        if batch._owner_token is not self._owner_token:
            raise ValueError("Bone fragment cache batch belongs to another cache")
        if batch.base_revision != self._revision:
            raise RuntimeError("Bone fragment cache batch is stale")
        entries = dict(self._entries)
        entries.update(batch.pending_entries)
        self._entries = {key: entries[key] for key in batch.keys}
        self._revision += 1

    def inspect(self) -> dict:
        return {
            "schema": "mc2_bone_fragment_cache_v1",
            "revision": self._revision,
            "entry_count": len(self._entries),
            "partition_ids": [
                fragment.partition_id for fragment in self._entries.values()
            ],
        }

    def clear(self) -> None:
        self._entries = {}
        self._revision += 1


__all__ = ["MC2BoneFragmentCacheBatchV1", "MC2BoneFragmentCacheV1"]
