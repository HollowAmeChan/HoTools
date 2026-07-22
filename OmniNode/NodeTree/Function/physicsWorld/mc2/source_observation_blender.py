"""Blender adapter for the world-owned MC2 static source observation cache."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType

from ..writeback import get_gn_writeback_receipts
from .source_observation import (
    MC2_SOURCE_OBSERVATION_CACHE_KEY,
    MC2_SOURCE_OBSERVATION_SCHEMA_VERSION,
    MC2SourceObservationCache,
    MC2SourceRevisionTracker,
    MC2SourceObservationToken,
    MC2SourceObservationValue,
)
from .topology import (
    MC2StaticInputFingerprint,
    compose_mc2_static_inputs,
    compose_mc2_partition_static_inputs,
    prepare_static_inputs_for_task,
    prepare_static_inputs_for_partition,
    read_mc2_partition_static_source_observation,
    read_mc2_static_source_observation,
)


MC2_SOURCE_OBSERVATION_FORCE_AUDIT_KEY = "mc2.source_observation.force_audit"
MC2_SOURCE_OBSERVATION_AUDIT_INTERVAL_KEY = (
    "mc2.source_observation.audit_interval"
)
MC2_SOURCE_OBSERVATION_DEFAULT_AUDIT_INTERVAL = 240
_MC2_SOURCE_REVISION_STATE_KEY = "mc2.source_observation.revision_state.v1"
_REVISION_TRACKER = MC2SourceRevisionTracker()
_ACTIVE = False


@dataclass(frozen=True)
class MC2ObservedStaticInputs:
    fingerprint: MC2StaticInputFingerprint
    snapshots: tuple[object, ...]
    identities: tuple[tuple, ...]
    statuses: tuple[str, ...]


def _pointer(value) -> int:
    callback = getattr(value, "as_pointer", None)
    if not callable(callback):
        return 0
    try:
        return int(callback())
    except Exception:
        return 0


def _mesh_source_config_signature(source) -> str:
    mesh = getattr(source, "data", None)
    properties = getattr(source, "hotools_mesh_collision", None)
    pin_name = str(getattr(properties, "pin_vertex_group", "") or "")
    radius_name = str(getattr(properties, "radius_vertex_group", "") or "")
    vertex_groups = getattr(source, "vertex_groups", None)
    pin_group = vertex_groups.get(pin_name) if vertex_groups is not None and pin_name else None
    radius_group = (
        vertex_groups.get(radius_name)
        if vertex_groups is not None and radius_name
        else None
    )
    uv_layer = getattr(getattr(mesh, "uv_layers", None), "active", None)
    payload = (
        "mc2_mesh_source_observation_config_v1",
        len(getattr(mesh, "vertices", ())),
        len(getattr(mesh, "edges", ())),
        len(getattr(mesh, "polygons", ())),
        len(getattr(mesh, "loops", ())),
        bool(getattr(properties, "pin_enabled", False)),
        pin_name,
        int(getattr(pin_group, "index", -1)) if pin_group is not None else -1,
        radius_name,
        int(getattr(radius_group, "index", -1)) if radius_group is not None else -1,
        str(getattr(uv_layer, "name", "") or ""),
        _pointer(uv_layer),
        len(getattr(uv_layer, "data", ())) if uv_layer is not None else 0,
        MC2_SOURCE_OBSERVATION_SCHEMA_VERSION,
    )
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return hashlib.blake2b(encoded.encode("ascii"), digest_size=16).hexdigest()


def _cache_for_world(world) -> MC2SourceObservationCache:
    cache = world.runtime_cache(MC2_SOURCE_OBSERVATION_CACHE_KEY)
    if cache is None:
        cache = MC2SourceObservationCache()
        world.set_runtime_cache(MC2_SOURCE_OBSERVATION_CACHE_KEY, cache)
    if not isinstance(cache, MC2SourceObservationCache):
        raise RuntimeError("MC2 source observation cache key is occupied")
    return cache


def _matching_receipt(receipts, task_id: str, target_key: str) -> tuple[int, int] | None:
    matches = (
        receipt
        for receipt in receipts
        if receipt.get("schema") == "gn_writeback_receipt_v1"
        and receipt.get("solver") == "mc2"
        and receipt.get("slot_id") == task_id
        and receipt.get("target_key") == target_key
    )
    receipt = max(matches, key=lambda item: int(item.get("serial", 0)), default=None)
    if receipt is None:
        return None
    return int(receipt.get("generation", 0)), int(receipt.get("serial", 0))


def _effective_revisions(
    world,
    *,
    identity: tuple,
    raw_revisions: tuple[int, int],
    receipt: tuple[int, int] | None,
) -> tuple[int, int]:
    states = world.runtime_cache(_MC2_SOURCE_REVISION_STATE_KEY)
    if states is None:
        states = {}
        world.set_runtime_cache(_MC2_SOURCE_REVISION_STATE_KEY, states)
    if not isinstance(states, dict):
        raise RuntimeError("MC2 source revision state key is occupied")
    generation = int(getattr(world, "generation", 0) or 0)
    state = states.get(identity)
    if not isinstance(state, dict) or int(state.get("generation", -1)) != generation:
        states[identity] = {
            "generation": generation,
            "raw": raw_revisions,
            "effective": raw_revisions,
            "receipt": receipt,
        }
        return raw_revisions

    previous_raw = tuple(int(value) for value in state["raw"])
    effective = tuple(int(value) for value in state["effective"])
    delta = tuple(
        current - previous
        for current, previous in zip(raw_revisions, previous_raw)
    )
    new_receipt = receipt is not None and receipt != state.get("receipt")
    internal_only = (
        new_receipt
        and all(0 <= value <= 1 for value in delta)
        and any(value > 0 for value in delta)
    )
    if not internal_only and any(value != 0 for value in delta):
        effective = tuple(
            value + (max(1, change) if change > 0 else 1)
            if change != 0
            else value
            for value, change in zip(effective, delta)
        )
    state["raw"] = raw_revisions
    state["effective"] = effective
    if new_receipt and (internal_only or any(value != 0 for value in delta)):
        state["receipt"] = receipt
    return effective


def _periodic_audit_due(world, source_pointer: int) -> bool:
    raw_interval = world.runtime_cache(MC2_SOURCE_OBSERVATION_AUDIT_INTERVAL_KEY)
    interval = (
        MC2_SOURCE_OBSERVATION_DEFAULT_AUDIT_INTERVAL
        if raw_interval is None
        else int(raw_interval)
    )
    if interval <= 0:
        return False
    frame = int(getattr(getattr(world, "frame_context", None), "frame", 0) or 0)
    if frame <= 0:
        return False
    phase = (int(source_pointer) >> 4) % interval
    return (frame + phase) % interval == 0


def _prepare_observed_static_inputs(
    world,
    *,
    setup_type: str,
    sources: tuple,
    receipt_slot_id: str,
    read_source,
    compose,
    prepare_uncached,
    force_audit: bool | None = None,
) -> MC2ObservedStaticInputs:
    """按显式domain身份复用Mesh观察；其他setup保守全扫。"""

    if setup_type != "mesh_cloth":
        fingerprint, snapshots = prepare_uncached()
        return MC2ObservedStaticInputs(
            fingerprint=fingerprint,
            snapshots=snapshots,
            identities=(),
            statuses=tuple("uncacheable" for _source in sources),
        )

    cache = _cache_for_world(world)
    explicit_audit = (
        bool(world.runtime_cache(MC2_SOURCE_OBSERVATION_FORCE_AUDIT_KEY))
        if force_audit is None
        else bool(force_audit)
    )
    source_fingerprints = []
    snapshots = []
    identities = []
    statuses = []
    receipts = get_gn_writeback_receipts(world)
    for source in sources:
        source_pointer = _pointer(source)
        data_pointer = _pointer(getattr(source, "data", None))
        if source_pointer <= 0 or data_pointer <= 0:
            fingerprint, snapshot = read_source(source)
            source_fingerprints.append(fingerprint)
            snapshots.append(snapshot)
            statuses.append("uncacheable")
            continue
        revision_complete = _ACTIVE
        raw_revisions = (
            _REVISION_TRACKER.revisions(source_pointer, data_pointer)
            if revision_complete
            else (0, 0)
        )
        identity = (
            MC2_SOURCE_OBSERVATION_SCHEMA_VERSION,
            setup_type,
            source_pointer,
            data_pointer,
        )
        source_revision, data_revision = _effective_revisions(
            world,
            identity=identity,
            raw_revisions=raw_revisions,
            receipt=_matching_receipt(
                receipts,
                receipt_slot_id,
                f"{source_pointer}:{data_pointer}",
            ),
        )
        token = MC2SourceObservationToken(
            world_generation=int(getattr(world, "generation", 0) or 0),
            setup_type=setup_type,
            source_pointer=source_pointer,
            data_pointer=data_pointer,
            source_revision=source_revision,
            data_revision=data_revision,
            config_signature=_mesh_source_config_signature(source),
            cacheable=revision_complete,
        )

        def load(source=source):
            fingerprint, snapshot = read_source(source)
            frozen_fingerprint = MappingProxyType(dict(fingerprint))
            return MC2SourceObservationValue(
                signature=":".join(
                    str(frozen_fingerprint[key])
                    for key in ("topology", "geometry", "surface")
                ),
                fingerprint=frozen_fingerprint,
                snapshot=snapshot,
            )

        observation = cache.observe(
            token,
            load,
            force_audit=(
                explicit_audit or _periodic_audit_due(world, source_pointer)
            ),
        )
        source_fingerprints.append(observation.value.fingerprint)
        snapshots.append(observation.value.snapshot)
        identities.append(token.identity)
        statuses.append(observation.status)
    fingerprint, frozen_snapshots = compose(source_fingerprints, snapshots)
    return MC2ObservedStaticInputs(
        fingerprint=fingerprint,
        snapshots=frozen_snapshots,
        identities=tuple(identities),
        statuses=tuple(statuses),
    )


def prepare_observed_static_inputs(
    world,
    task,
    *,
    force_audit: bool | None = None,
) -> MC2ObservedStaticInputs:
    """旧V0 oracle入口；E7-CPU删除前只供显式task调用。"""

    return _prepare_observed_static_inputs(
        world,
        setup_type=task.setup_type,
        sources=tuple(task.sources),
        receipt_slot_id=str(task.task_id),
        read_source=lambda source: read_mc2_static_source_observation(task, source),
        compose=lambda fingerprints, snapshots: compose_mc2_static_inputs(
            task, fingerprints, snapshots
        ),
        prepare_uncached=lambda: prepare_static_inputs_for_task(task),
        force_audit=force_audit,
    )


def prepare_observed_static_inputs_for_partition(
    world,
    partition,
    *,
    receipt_slot_id: str,
    force_audit: bool | None = None,
) -> MC2ObservedStaticInputs:
    """产品入口直接观察resolved partition，不构造旧task schema。"""

    slot_id = str(receipt_slot_id or "").strip()
    if not slot_id:
        raise ValueError("Mesh product observation requires receipt_slot_id")
    return _prepare_observed_static_inputs(
        world,
        setup_type=partition.setup_type,
        sources=(partition.source,),
        receipt_slot_id=slot_id,
        read_source=lambda source: read_mc2_partition_static_source_observation(
            partition, source
        ),
        compose=lambda fingerprints, snapshots: compose_mc2_partition_static_inputs(
            partition, fingerprints, snapshots
        ),
        prepare_uncached=lambda: prepare_static_inputs_for_partition(partition),
        force_audit=force_audit,
    )


def prune_source_observation_cache(world, active_identities) -> int:
    cache = world.runtime_cache(MC2_SOURCE_OBSERVATION_CACHE_KEY)
    if cache is None:
        return 0
    if not isinstance(cache, MC2SourceObservationCache):
        raise RuntimeError("MC2 source observation cache key is occupied")
    active = set(active_identities)
    pruned = cache.prune(active)
    states = world.runtime_cache(_MC2_SOURCE_REVISION_STATE_KEY)
    if isinstance(states, dict):
        for identity in tuple(states):
            if identity not in active:
                states.pop(identity, None)
    return pruned


def _mc2_depsgraph_update_post(_scene, depsgraph) -> None:
    try:
        import bpy
    except ImportError:
        return
    source_pointers = []
    data_pointers = []
    for update in getattr(depsgraph, "updates", ()):
        if not bool(getattr(update, "is_updated_geometry", False)):
            continue
        evaluated_item = getattr(update, "id", None)
        item = getattr(evaluated_item, "original", None) or evaluated_item
        pointer = getattr(item, "as_pointer", None)
        if not callable(pointer):
            continue
        try:
            value = int(pointer())
        except Exception:
            continue
        if (
            isinstance(item, bpy.types.Object)
            and getattr(item, "type", None) == "MESH"
        ):
            source_pointers.append(value)
        elif isinstance(item, bpy.types.Mesh):
            data_pointers.append(value)
    _REVISION_TRACKER.process_geometry_updates(
        source_pointers=source_pointers,
        data_pointers=data_pointers,
    )


def _invalidate_mc2_source_revisions(*_args) -> None:
    _REVISION_TRACKER.invalidate_all()


def register() -> None:
    global _ACTIVE
    if _ACTIVE:
        return
    import bpy
    from bpy.app.handlers import persistent

    persistent(_mc2_depsgraph_update_post)
    persistent(_invalidate_mc2_source_revisions)
    registrations = (
        (bpy.app.handlers.depsgraph_update_post, _mc2_depsgraph_update_post),
        (bpy.app.handlers.undo_post, _invalidate_mc2_source_revisions),
        (bpy.app.handlers.redo_post, _invalidate_mc2_source_revisions),
        (bpy.app.handlers.load_post, _invalidate_mc2_source_revisions),
    )
    for handlers, callback in registrations:
        if callback not in handlers:
            handlers.append(callback)
    _REVISION_TRACKER.invalidate_all()
    _ACTIVE = True


def unregister() -> None:
    global _ACTIVE
    if not _ACTIVE:
        return
    import bpy

    registrations = (
        (bpy.app.handlers.depsgraph_update_post, _mc2_depsgraph_update_post),
        (bpy.app.handlers.undo_post, _invalidate_mc2_source_revisions),
        (bpy.app.handlers.redo_post, _invalidate_mc2_source_revisions),
        (bpy.app.handlers.load_post, _invalidate_mc2_source_revisions),
    )
    for handlers, callback in registrations:
        while callback in handlers:
            handlers.remove(callback)
    _REVISION_TRACKER.invalidate_all()
    _ACTIVE = False


__all__ = [
    "MC2ObservedStaticInputs",
    "MC2_SOURCE_OBSERVATION_AUDIT_INTERVAL_KEY",
    "MC2_SOURCE_OBSERVATION_DEFAULT_AUDIT_INTERVAL",
    "MC2_SOURCE_OBSERVATION_FORCE_AUDIT_KEY",
    "prepare_observed_static_inputs",
    "prepare_observed_static_inputs_for_partition",
    "prune_source_observation_cache",
    "register",
    "unregister",
]
