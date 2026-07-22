"""Backend-independent MC2 partition entry and collector contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
import hashlib
import json

from .parameters import (
    MC2ParticleProfileSpec,
    MC2SetupOptionsSpec,
    MC2TaskParametersSpec,
    make_mc2_particle_profile,
    make_mc2_setup_options,
    make_mc2_task_parameters,
)
from .source_identity import mc2_source_token, normalize_mc2_setup_type


class _MC2UnsetType:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MC2_UNSET"


MC2_UNSET = _MC2UnsetType()

_PROFILE_FIELDS = frozenset(field.name for field in fields(MC2ParticleProfileSpec))
_TASK_FIELDS = frozenset(field.name for field in fields(MC2TaskParametersSpec))
_SETUP_FIELDS = frozenset(
    field.name for field in fields(MC2SetupOptionsSpec) if field.name != "setup_type"
)
_PARTITION_FIELDS = frozenset((
    "anchor_object",
    "enabled",
    "collision_group",
    "collision_mask",
))
_ENTRY_ORIGINS = frozenset(("explicit", "implicit"))
_PROFILE_CURVE_FIELDS = frozenset((
    "damping",
    "radius",
    "distance_stiffness",
    "angle_restoration_stiffness",
    "angle_limit",
    "max_distance",
    "backstop_distance",
    "collision_limit_distance",
    "self_collision_thickness",
))


def _canonical_source_token(source) -> tuple[dict, str]:
    token = mc2_source_token(source)
    canonical = json.dumps(
        token, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return token, canonical


def _default_stable_id(setup_type: str, source) -> str:
    _token, canonical = _canonical_source_token(source)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"mc2.{setup_type}:{digest[:24]}"


def _freeze_mapping(
    values: Mapping[str, object] | None,
    *,
    allowed: frozenset[str],
    namespace: str,
) -> tuple[tuple[str, object], ...]:
    if values is None:
        return ()
    if not isinstance(values, Mapping):
        raise TypeError(f"{namespace} patch 必须是 mapping")
    unknown = sorted(str(key) for key in values if str(key) not in allowed)
    if unknown:
        raise ValueError(f"{namespace} patch 包含未知字段: {unknown!r}")
    return tuple(sorted((str(key), value) for key, value in values.items()))


def _normalize_profile_patch(
    values: tuple[tuple[str, object], ...],
) -> tuple[tuple[str, object], ...]:
    normalized = []
    for name, value in values:
        if name in _PROFILE_CURVE_FIELDS:
            default = make_mc2_particle_profile(spring_enabled=False)
            expected_type = type(getattr(default, name))
            if not isinstance(value, expected_type):
                raise TypeError(
                    f"profile.{name} patch 必须是 {expected_type.__name__}"
                )
            normalized.append((name, value))
            continue
        kwargs = {"spring_enabled": False}
        kwargs[name] = value
        probe = make_mc2_particle_profile(**kwargs)
        normalized.append((name, getattr(probe, name)))
    return tuple(normalized)


def _normalize_task_patch(
    values: tuple[tuple[str, object], ...],
) -> tuple[tuple[str, object], ...]:
    normalized = []
    for name, value in values:
        probe = make_mc2_task_parameters(**{name: value})
        normalized.append((name, getattr(probe, name)))
    return tuple(normalized)


def _normalize_partition_patch(
    values: tuple[tuple[str, object], ...],
) -> tuple[tuple[str, object], ...]:
    normalized = []
    for name, value in values:
        if name == "enabled" and type(value) is not bool:
            raise TypeError("partition.enabled patch 必须是 bool")
        if name == "collision_group":
            value = _collision_group(value)
        elif name == "collision_mask":
            value = _collision_mask(value)
        normalized.append((name, value))
    return tuple(normalized)


def _collision_group(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("partition.collision_group 必须是单个uint32 bit或None")
    result = int(value)
    if not 1 <= result <= 0x80000000 or result & (result - 1):
        raise ValueError("partition.collision_group 必须是单个正uint32 bit")
    return result


def _collision_mask(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("partition.collision_mask 必须是uint32")
    result = int(value)
    if not 0 <= result <= 0xFFFFFFFF:
        raise ValueError("partition.collision_mask 必须位于0..0xFFFFFFFF")
    return result


def _debug_value(value):
    debug_dict = getattr(value, "debug_dict", None)
    if callable(debug_dict):
        return debug_dict()
    if value is MC2_UNSET:
        return {"unset": True}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return mc2_source_token(value)
    except (TypeError, ValueError):
        return {"type": type(value).__name__}


def _signature(payload: object) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MC2PartitionPatchSpec:
    """Sparse, ordered patch applied deliberately to a partition entry."""

    profile_values: tuple[tuple[str, object], ...] = ()
    task_values: tuple[tuple[str, object], ...] = ()
    setup_values: tuple[tuple[str, object], ...] = ()
    partition_values: tuple[tuple[str, object], ...] = ()
    producer: str = "mc2.partition_override"

    def __post_init__(self) -> None:
        producer = str(self.producer or "").strip()
        if not producer:
            raise ValueError("MC2 partition patch producer 不能为空")
        object.__setattr__(self, "producer", producer)
        for namespace, values, allowed in (
            ("profile", self.profile_values, _PROFILE_FIELDS),
            ("task", self.task_values, _TASK_FIELDS),
            ("setup", self.setup_values, _SETUP_FIELDS),
            ("partition", self.partition_values, _PARTITION_FIELDS),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"{namespace} patch values 必须是 tuple")
            names = [name for name, _value in values]
            if names != sorted(names) or len(names) != len(set(names)):
                raise ValueError(f"{namespace} patch fields 必须排序且唯一")
            unknown = sorted(set(names) - allowed)
            if unknown:
                raise ValueError(f"{namespace} patch 包含未知字段: {unknown!r}")

    @property
    def signature(self) -> str:
        return _signature(self.debug_dict())

    def debug_dict(self) -> dict:
        return {
            "producer": self.producer,
            "profile": {name: _debug_value(value) for name, value in self.profile_values},
            "task": {name: _debug_value(value) for name, value in self.task_values},
            "setup": {name: _debug_value(value) for name, value in self.setup_values},
            "partition": {
                name: _debug_value(value) for name, value in self.partition_values
            },
        }


def make_mc2_partition_patch(
    *,
    profile_values: Mapping[str, object] | None = None,
    task_values: Mapping[str, object] | None = None,
    setup_values: Mapping[str, object] | None = None,
    partition_values: Mapping[str, object] | None = None,
    producer: str = "mc2.partition_override",
) -> MC2PartitionPatchSpec:
    return MC2PartitionPatchSpec(
        profile_values=_normalize_profile_patch(_freeze_mapping(
            profile_values, allowed=_PROFILE_FIELDS, namespace="profile"
        )),
        task_values=_normalize_task_patch(_freeze_mapping(
            task_values, allowed=_TASK_FIELDS, namespace="task"
        )),
        setup_values=_freeze_mapping(
            setup_values, allowed=_SETUP_FIELDS, namespace="setup"
        ),
        partition_values=_normalize_partition_patch(_freeze_mapping(
            partition_values, allowed=_PARTITION_FIELDS, namespace="partition"
        )),
        producer=producer,
    )


@dataclass(frozen=True)
class MC2PartitionEntry:
    """One authoring source before collector defaults and patches are resolved."""

    stable_id: str
    setup_type: str
    source: object
    origin: str
    producer: str
    profile: object = MC2_UNSET
    task_parameters: object = MC2_UNSET
    setup_options: object = MC2_UNSET
    anchor_object: object = MC2_UNSET
    enabled: object = MC2_UNSET
    collision_group: object = MC2_UNSET
    collision_mask: object = MC2_UNSET
    patches: tuple[MC2PartitionPatchSpec, ...] = ()

    def __post_init__(self) -> None:
        stable_id = str(self.stable_id or "").strip()
        if not stable_id:
            raise ValueError("MC2 partition stable_id 不能为空")
        object.__setattr__(self, "stable_id", stable_id)
        setup_type = normalize_mc2_setup_type(self.setup_type)
        object.__setattr__(self, "setup_type", setup_type)
        _canonical_source_token(self.source)
        origin = str(self.origin or "").strip().lower()
        if origin not in _ENTRY_ORIGINS:
            raise ValueError("MC2 partition origin 必须是 explicit 或 implicit")
        object.__setattr__(self, "origin", origin)
        producer = str(self.producer or "").strip()
        if not producer:
            raise ValueError("MC2 partition producer 不能为空")
        object.__setattr__(self, "producer", producer)
        if self.profile is not MC2_UNSET and not isinstance(
            self.profile, MC2ParticleProfileSpec
        ):
            raise TypeError("MC2 partition profile 必须是 MC2ParticleProfileSpec 或 unset")
        if self.task_parameters is not MC2_UNSET and not isinstance(
            self.task_parameters, MC2TaskParametersSpec
        ):
            raise TypeError(
                "MC2 partition task_parameters 必须是 MC2TaskParametersSpec 或 unset"
            )
        if self.setup_options is not MC2_UNSET:
            if not isinstance(self.setup_options, MC2SetupOptionsSpec):
                raise TypeError(
                    "MC2 partition setup_options 必须是 MC2SetupOptionsSpec 或 unset"
                )
            if self.setup_options.setup_type != setup_type:
                raise ValueError("MC2 partition setup_options 与 setup_type 不一致")
        if self.enabled is not MC2_UNSET and type(self.enabled) is not bool:
            raise TypeError("MC2 partition enabled 必须是 bool 或 unset")
        if self.collision_group is not MC2_UNSET:
            _collision_group(self.collision_group)
        if self.collision_mask is not MC2_UNSET:
            _collision_mask(self.collision_mask)
        if not isinstance(self.patches, tuple) or any(
            not isinstance(value, MC2PartitionPatchSpec) for value in self.patches
        ):
            raise TypeError("MC2 partition patches 必须是 MC2PartitionPatchSpec tuple")

    @property
    def signature(self) -> str:
        token, _canonical = _canonical_source_token(self.source)
        return _signature({
            "stable_id": self.stable_id,
            "setup_type": self.setup_type,
            "source": token,
            "origin": self.origin,
            "producer": self.producer,
            "profile": _debug_value(self.profile),
            "task_parameters": _debug_value(self.task_parameters),
            "setup_options": _debug_value(self.setup_options),
            "anchor_object": _debug_value(self.anchor_object),
            "enabled": _debug_value(self.enabled),
            "collision_group": _debug_value(self.collision_group),
            "collision_mask": _debug_value(self.collision_mask),
            "patches": [patch.debug_dict() for patch in self.patches],
        })

    def with_patch(self, patch: MC2PartitionPatchSpec) -> "MC2PartitionEntry":
        if not isinstance(patch, MC2PartitionPatchSpec):
            raise TypeError("patch 必须是 MC2PartitionPatchSpec")
        return replace(self, patches=(*self.patches, patch))


def make_mc2_partition_entry(
    source,
    *,
    setup_type: object,
    stable_id: str | None = None,
    origin: str = "explicit",
    producer: str = "mc2.partition_source",
    profile=MC2_UNSET,
    task_parameters=MC2_UNSET,
    setup_options=MC2_UNSET,
    anchor_object=MC2_UNSET,
    enabled=MC2_UNSET,
    collision_group=MC2_UNSET,
    collision_mask=MC2_UNSET,
    patches=(),
) -> MC2PartitionEntry:
    normalized_setup = normalize_mc2_setup_type(setup_type)
    return MC2PartitionEntry(
        stable_id=str(stable_id or _default_stable_id(normalized_setup, source)),
        setup_type=normalized_setup,
        source=source,
        origin=origin,
        producer=producer,
        profile=profile,
        task_parameters=task_parameters,
        setup_options=setup_options,
        anchor_object=anchor_object,
        enabled=enabled,
        collision_group=collision_group,
        collision_mask=collision_mask,
        patches=tuple(patches),
    )


class MC2PartitionConflictError(ValueError):
    def __init__(self, kind: str, stable_id: str, detail: str) -> None:
        self.kind = str(kind)
        self.stable_id = str(stable_id)
        self.detail = str(detail)
        super().__init__(
            f"MC2 partition conflict [{self.kind}] {self.stable_id}: {self.detail}"
        )


@dataclass(frozen=True)
class MC2ResolvedPartitionSpec:
    stable_id: str
    partition_index: int
    setup_type: str
    source: object
    source_token: tuple
    profile: MC2ParticleProfileSpec
    task_parameters: MC2TaskParametersSpec
    setup_options: MC2SetupOptionsSpec
    anchor_object: object | None
    enabled: bool
    collision_group: int | None
    collision_mask: int
    origins: tuple[str, ...]
    field_sources: tuple[tuple[str, str], ...]
    field_history: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        if self.partition_index < 0:
            raise ValueError("partition_index 必须非负")
        if not isinstance(self.profile, MC2ParticleProfileSpec):
            raise TypeError("resolved profile 类型错误")
        if not isinstance(self.task_parameters, MC2TaskParametersSpec):
            raise TypeError("resolved task_parameters 类型错误")
        if not isinstance(self.setup_options, MC2SetupOptionsSpec):
            raise TypeError("resolved setup_options 类型错误")
        if type(self.enabled) is not bool:
            raise TypeError("resolved enabled 必须是 bool")
        _collision_group(self.collision_group)
        _collision_mask(self.collision_mask)

    def field_source(self, path: str) -> str | None:
        target = str(path)
        for field_path, owner in self.field_sources:
            if field_path == target:
                return owner
        return None

    def field_source_history(self, path: str) -> tuple[str, ...]:
        target = str(path)
        for field_path, owners in self.field_history:
            if field_path == target:
                return owners
        return ()

    def debug_dict(self) -> dict:
        return {
            "stable_id": self.stable_id,
            "partition_index": self.partition_index,
            "setup_type": self.setup_type,
            "source_token": dict(self.source_token),
            "profile_signature": self.profile.signature,
            "task_parameters_signature": self.task_parameters.signature,
            "setup_options_signature": self.setup_options.signature,
            "anchor": _debug_value(self.anchor_object),
            "enabled": self.enabled,
            "collision_group": self.collision_group,
            "collision_mask": self.collision_mask,
            "origins": list(self.origins),
            "field_sources": dict(self.field_sources),
            "field_history": {
                path: list(owners) for path, owners in self.field_history
            },
        }


@dataclass(frozen=True)
class MC2PartitionCollectorReport:
    setup_type: str
    domain_signature: str
    partition_count: int
    active_partition_count: int
    implicit_input_count: int
    explicit_input_count: int
    merged_partition_count: int
    ordered_stable_ids: tuple[str, ...]

    def debug_dict(self) -> dict:
        return {
            "setup_type": self.setup_type,
            "domain_signature": self.domain_signature,
            "partition_count": self.partition_count,
            "active_partition_count": self.active_partition_count,
            "implicit_input_count": self.implicit_input_count,
            "explicit_input_count": self.explicit_input_count,
            "merged_partition_count": self.merged_partition_count,
            "ordered_stable_ids": list(self.ordered_stable_ids),
        }


@dataclass(frozen=True)
class MC2PartitionCollectorPlan:
    setup_type: str
    partitions: tuple[MC2ResolvedPartitionSpec, ...]
    report: MC2PartitionCollectorReport

    @property
    def active_partitions(self) -> tuple[MC2ResolvedPartitionSpec, ...]:
        return tuple(partition for partition in self.partitions if partition.enabled)


def _flatten_entries(values, *, expected_origin: str) -> list[MC2PartitionEntry]:
    pending = [values]
    result: list[MC2PartitionEntry] = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, MC2PartitionEntry):
            raise TypeError(
                f"MC2 partition collector 包含非法值: {type(value).__name__}"
            )
        if value.origin != expected_origin:
            raise ValueError(
                f"MC2 {expected_origin} input 收到 {value.origin} entry: {value.stable_id}"
            )
        result.append(value)
    return result


def _index_unique(entries: list[MC2PartitionEntry]) -> tuple[dict[str, MC2PartitionEntry], list[str]]:
    indexed: dict[str, MC2PartitionEntry] = {}
    order: list[str] = []
    for entry in entries:
        previous = indexed.get(entry.stable_id)
        if previous is None:
            indexed[entry.stable_id] = entry
            order.append(entry.stable_id)
            continue
        if previous.signature != entry.signature:
            previous_values = _entry_field_assignments(previous)
            current_values = _entry_field_assignments(entry)
            differing_paths = sorted(
                path
                for path in set(previous_values) | set(current_values)
                if previous_values.get(path, MC2_UNSET)
                != current_values.get(path, MC2_UNSET)
            )
            if not differing_paths:
                differing_paths = ["entry"]
            raise MC2PartitionConflictError(
                "duplicate_explicit" if entry.origin == "explicit" else "duplicate_implicit",
                entry.stable_id,
                f"字段 {differing_paths!r} 由 {previous.producer!r} 与 "
                f"{entry.producer!r} 重复定义",
            )
    return indexed, order


def _source_tuple(source) -> tuple:
    token, _canonical = _canonical_source_token(source)
    return tuple(sorted(token.items()))


def _entry_field_assignments(entry: MC2PartitionEntry) -> dict[str, object]:
    result = {}
    if entry.profile is not MC2_UNSET:
        result.update({
            f"profile.{field.name}": _debug_value(getattr(entry.profile, field.name))
            for field in fields(MC2ParticleProfileSpec)
        })
    if entry.task_parameters is not MC2_UNSET:
        result.update({
            f"task.{field.name}": _debug_value(
                getattr(entry.task_parameters, field.name)
            )
            for field in fields(MC2TaskParametersSpec)
        })
    if entry.setup_options is not MC2_UNSET:
        result.update({
            f"setup.{field.name}": _debug_value(
                getattr(entry.setup_options, field.name)
            )
            for field in fields(MC2SetupOptionsSpec)
            if field.name != "setup_type"
        })
    for name in _PARTITION_FIELDS:
        value = getattr(entry, name)
        if value is not MC2_UNSET:
            result[f"partition.{name}"] = _debug_value(value)
    for patch in entry.patches:
        for namespace, values in (
            ("profile", patch.profile_values),
            ("task", patch.task_values),
            ("setup", patch.setup_values),
            ("partition", patch.partition_values),
        ):
            for name, value in values:
                result[f"{namespace}.{name}"] = _debug_value(value)
    return result


def _record_field_owner(
    field_sources: dict[str, str],
    field_history: dict[str, list[str]],
    path: str,
    owner: str,
) -> None:
    field_sources[path] = owner
    field_history.setdefault(path, []).append(owner)


def _apply_entry(
    state: dict,
    field_sources: dict[str, str],
    field_history: dict[str, list[str]],
    entry: MC2PartitionEntry,
) -> None:
    owner = f"{entry.origin}:{entry.producer}"
    if entry.profile is not MC2_UNSET:
        state["profile"] = entry.profile
        for name in _PROFILE_FIELDS:
            _record_field_owner(
                field_sources, field_history, f"profile.{name}", owner
            )
    if entry.task_parameters is not MC2_UNSET:
        state["task_parameters"] = entry.task_parameters
        for name in _TASK_FIELDS:
            _record_field_owner(
                field_sources, field_history, f"task.{name}", owner
            )
    if entry.setup_options is not MC2_UNSET:
        state["setup_options"] = entry.setup_options
        for name in _SETUP_FIELDS:
            _record_field_owner(
                field_sources, field_history, f"setup.{name}", owner
            )
    for name in _PARTITION_FIELDS:
        value = getattr(entry, name)
        if value is not MC2_UNSET:
            state[name] = value
            _record_field_owner(
                field_sources, field_history, f"partition.{name}", owner
            )

    for patch in entry.patches:
        patch_owner = f"override:{patch.producer}"
        if patch.profile_values:
            state["profile"] = replace(state["profile"], **dict(patch.profile_values))
            for name, _value in patch.profile_values:
                _record_field_owner(
                    field_sources, field_history, f"profile.{name}", patch_owner
                )
        if patch.task_values:
            state["task_parameters"] = replace(
                state["task_parameters"], **dict(patch.task_values)
            )
            for name, _value in patch.task_values:
                _record_field_owner(
                    field_sources, field_history, f"task.{name}", patch_owner
                )
        if patch.setup_values:
            setup_values = state["setup_options"].debug_dict()
            setup_values.update(dict(patch.setup_values))
            setup_values.pop("setup_type", None)
            state["setup_options"] = make_mc2_setup_options(
                state["setup_options"].setup_type,
                **setup_values,
            )
            for name, _value in patch.setup_values:
                _record_field_owner(
                    field_sources, field_history, f"setup.{name}", patch_owner
                )
        for name, value in patch.partition_values:
            state[name] = value
            _record_field_owner(
                field_sources, field_history, f"partition.{name}", patch_owner
            )


def collect_mc2_partition_entries(
    *,
    setup_type: object,
    explicit_entries=(),
    implicit_entries=(),
    default_profile: MC2ParticleProfileSpec | None = None,
    default_task_parameters: MC2TaskParametersSpec | None = None,
    default_setup_options: MC2SetupOptionsSpec | None = None,
    default_anchor_object=None,
    default_enabled: bool = True,
    default_collision_group: int | None = None,
    default_collision_mask: int = 0xFFFFFFFF,
) -> MC2PartitionCollectorPlan:
    """Resolve collector inputs without creating tasks, slots, or native state."""

    normalized_setup = normalize_mc2_setup_type(setup_type)
    if default_profile is None:
        default_profile = make_mc2_particle_profile(spring_enabled=False)
    if default_task_parameters is None:
        default_task_parameters = make_mc2_task_parameters()
    if default_setup_options is None:
        default_setup_options = make_mc2_setup_options(normalized_setup)
    if not isinstance(default_profile, MC2ParticleProfileSpec):
        raise TypeError("default_profile 必须是 MC2ParticleProfileSpec")
    if not isinstance(default_task_parameters, MC2TaskParametersSpec):
        raise TypeError("default_task_parameters 必须是 MC2TaskParametersSpec")
    if not isinstance(default_setup_options, MC2SetupOptionsSpec):
        raise TypeError("default_setup_options 必须是 MC2SetupOptionsSpec")
    if default_setup_options.setup_type != normalized_setup:
        raise ValueError("default_setup_options 与 collector setup_type 不一致")
    if type(default_enabled) is not bool:
        raise TypeError("default_enabled 必须是 bool")
    default_collision_group = _collision_group(default_collision_group)
    default_collision_mask = _collision_mask(default_collision_mask)

    implicit = _flatten_entries(implicit_entries, expected_origin="implicit")
    explicit = _flatten_entries(explicit_entries, expected_origin="explicit")
    implicit_by_id, _implicit_order = _index_unique(implicit)
    explicit_by_id, explicit_order = _index_unique(explicit)
    ordered_ids = [*explicit_order, *sorted(set(implicit_by_id) - set(explicit_by_id))]

    resolved: list[MC2ResolvedPartitionSpec] = []
    merged_count = 0
    for partition_index, stable_id in enumerate(ordered_ids):
        implicit_entry = implicit_by_id.get(stable_id)
        explicit_entry = explicit_by_id.get(stable_id)
        entries = tuple(
            entry for entry in (implicit_entry, explicit_entry) if entry is not None
        )
        if any(entry.setup_type != normalized_setup for entry in entries):
            raise MC2PartitionConflictError(
                "setup_mismatch", stable_id, f"collector 只接受 {normalized_setup}"
            )
        source_entry = explicit_entry or implicit_entry
        assert source_entry is not None
        source_token, source_canonical = _canonical_source_token(source_entry.source)
        for entry in entries:
            _token, candidate_canonical = _canonical_source_token(entry.source)
            if candidate_canonical != source_canonical:
                raise MC2PartitionConflictError(
                    "source_mismatch",
                    stable_id,
                    "相同 stable_id 指向不同 source",
                )
        if implicit_entry is not None and explicit_entry is not None:
            merged_count += 1

        state = {
            "profile": default_profile,
            "task_parameters": default_task_parameters,
            "setup_options": default_setup_options,
            "anchor_object": default_anchor_object,
            "enabled": default_enabled,
            "collision_group": default_collision_group,
            "collision_mask": default_collision_mask,
        }
        field_sources = {
            **{f"profile.{name}": "collector.default" for name in _PROFILE_FIELDS},
            **{f"task.{name}": "collector.default" for name in _TASK_FIELDS},
            **{f"setup.{name}": "collector.default" for name in _SETUP_FIELDS},
            "partition.anchor_object": "collector.default",
            "partition.enabled": "collector.default",
            "partition.collision_group": "collector.default",
            "partition.collision_mask": "collector.default",
        }
        field_history = {
            path: [owner] for path, owner in field_sources.items()
        }
        for entry in entries:
            _apply_entry(state, field_sources, field_history, entry)
        if state["setup_options"].setup_type != normalized_setup:
            raise MC2PartitionConflictError(
                "setup_mismatch", stable_id, "patch 产生了不匹配的 setup options"
            )
        if type(state["enabled"]) is not bool:
            raise TypeError("resolved partition enabled 必须是 bool")
        resolved.append(MC2ResolvedPartitionSpec(
            stable_id=stable_id,
            partition_index=partition_index,
            setup_type=normalized_setup,
            source=source_entry.source,
            source_token=tuple(sorted(source_token.items())),
            profile=state["profile"],
            task_parameters=state["task_parameters"],
            setup_options=state["setup_options"],
            anchor_object=state["anchor_object"],
            enabled=state["enabled"],
            collision_group=_collision_group(state["collision_group"]),
            collision_mask=_collision_mask(state["collision_mask"]),
            origins=tuple(f"{entry.origin}:{entry.producer}" for entry in entries),
            field_sources=tuple(sorted(field_sources.items())),
            field_history=tuple(
                sorted(
                    (path, tuple(owners))
                    for path, owners in field_history.items()
                )
            ),
        ))

    domain_signature = _signature({
        "setup_type": normalized_setup,
        "partitions": [
            {
                "stable_id": partition.stable_id,
                "source": dict(partition.source_token),
            }
            for partition in resolved
        ],
    })
    report = MC2PartitionCollectorReport(
        setup_type=normalized_setup,
        domain_signature=domain_signature,
        partition_count=len(resolved),
        active_partition_count=sum(partition.enabled for partition in resolved),
        implicit_input_count=len(implicit),
        explicit_input_count=len(explicit),
        merged_partition_count=merged_count,
        ordered_stable_ids=tuple(partition.stable_id for partition in resolved),
    )
    return MC2PartitionCollectorPlan(
        setup_type=normalized_setup,
        partitions=tuple(resolved),
        report=report,
    )


__all__ = [
    "MC2PartitionCollectorPlan",
    "MC2PartitionCollectorReport",
    "MC2PartitionConflictError",
    "MC2PartitionEntry",
    "MC2PartitionPatchSpec",
    "MC2ResolvedPartitionSpec",
    "MC2_UNSET",
    "collect_mc2_partition_entries",
    "make_mc2_partition_entry",
    "make_mc2_partition_patch",
]
