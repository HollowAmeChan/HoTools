"""World-owned cache contract for MC2 static source observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


MC2_SOURCE_OBSERVATION_SCHEMA_VERSION = 1
MC2_SOURCE_OBSERVATION_CACHE_KEY = "mc2.source_observation.v1"


@dataclass(frozen=True)
class MC2SourceObservationToken:
    world_generation: int
    setup_type: str
    source_pointer: int
    data_pointer: int
    source_revision: int
    data_revision: int
    config_signature: str
    cacheable: bool = True
    schema_version: int = MC2_SOURCE_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_SOURCE_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 source observation schema")
        if self.world_generation < 0:
            raise ValueError("world_generation must be non-negative")
        if self.source_pointer <= 0 or self.data_pointer <= 0:
            raise ValueError("source/data pointers must be positive")
        if self.source_revision < 0 or self.data_revision < 0:
            raise ValueError("source/data revisions must be non-negative")
        if not self.setup_type:
            raise ValueError("setup_type must not be empty")
        if not self.config_signature:
            raise ValueError("config_signature must not be empty")

    @property
    def identity(self) -> tuple[int, str, int, int]:
        return (
            self.schema_version,
            self.setup_type,
            self.source_pointer,
            self.data_pointer,
        )


@dataclass(frozen=True)
class MC2SourceObservationValue:
    signature: str
    fingerprint: object
    snapshot: object

    def __post_init__(self) -> None:
        if not self.signature:
            raise ValueError("observation signature must not be empty")


@dataclass(frozen=True)
class MC2SourceObservationResult:
    value: MC2SourceObservationValue
    status: str

    @property
    def reused(self) -> bool:
        return self.status in ("hit", "audit_match")


class MC2SourceObservationCache:
    """Stores frozen observations; Blender revision production lives elsewhere."""

    def __init__(self) -> None:
        self._entries: dict[tuple, tuple[MC2SourceObservationToken, MC2SourceObservationValue]] = {}
        self.hits = 0
        self.misses = 0
        self.refreshes = 0
        self.bypasses = 0
        self.audit_matches = 0
        self.audit_mismatches = 0

    def observe(
        self,
        token: MC2SourceObservationToken,
        loader: Callable[[], MC2SourceObservationValue],
        *,
        force_audit: bool = False,
    ) -> MC2SourceObservationResult:
        if not isinstance(token, MC2SourceObservationToken):
            raise TypeError("token must be MC2SourceObservationToken")
        if not callable(loader):
            raise TypeError("loader must be callable")
        identity = token.identity
        previous = self._entries.get(identity)
        if not token.cacheable:
            self._entries.pop(identity, None)
            self.bypasses += 1
            return MC2SourceObservationResult(self._load(loader), "uncacheable")
        if previous is not None and previous[0] == token and not force_audit:
            self.hits += 1
            return MC2SourceObservationResult(previous[1], "hit")

        value = self._load(loader)
        if force_audit and previous is not None and previous[0] == token:
            if previous[1].signature == value.signature:
                self.audit_matches += 1
                status = "audit_match"
            else:
                self.audit_mismatches += 1
                status = "audit_mismatch"
        elif previous is None:
            self.misses += 1
            status = "miss"
        else:
            self.refreshes += 1
            status = "revision"
        self._entries[identity] = (token, value)
        return MC2SourceObservationResult(value, status)

    @staticmethod
    def _load(loader) -> MC2SourceObservationValue:
        value = loader()
        if not isinstance(value, MC2SourceObservationValue):
            raise TypeError("loader must return MC2SourceObservationValue")
        return value

    def prune(self, active_identities) -> int:
        active = set(active_identities)
        stale = tuple(key for key in self._entries if key not in active)
        for key in stale:
            self._entries.pop(key, None)
        return len(stale)

    def invalidate_all(self) -> None:
        self._entries.clear()

    def inspect(self) -> dict:
        return {
            "schema": "mc2_source_observation_v1",
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "refreshes": self.refreshes,
            "bypasses": self.bypasses,
            "audit_matches": self.audit_matches,
            "audit_mismatches": self.audit_mismatches,
        }
