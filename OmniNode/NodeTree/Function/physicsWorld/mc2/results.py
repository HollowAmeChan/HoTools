"""Public MC2 result-stream helpers."""

from __future__ import annotations

from collections.abc import Iterable

from ..names import BONE_TRANSFORM_CHANNEL, GN_ATTRIBUTE_CHANNEL
from ..writeback_commands import make_gn_offset_writeback
from .candidate import MC2ResultCandidateV0
from .names import MC2_SETUP_MESH_CLOTH, MC2_SOLVER_ID, MC2_STATS_CHANNEL


MC2_PUBLIC_RESULT_SCHEMA_VERSION = 0


def _mesh_target_identity(spec) -> tuple[int, int]:
    if getattr(spec, "setup_type", None) != MC2_SETUP_MESH_CLOTH:
        raise ValueError("MC2 Mesh result requires a mesh_cloth task")
    sources = tuple(getattr(spec, "sources", ()) or ())
    if len(sources) != 1:
        raise ValueError("MC2 Mesh result requires exactly one final-proxy source")
    source = sources[0]
    if getattr(source, "type", None) != "MESH":
        raise ValueError("MC2 Mesh result target is not a Mesh object")
    pointer = getattr(source, "as_pointer", None)
    data = getattr(source, "data", None)
    data_pointer = getattr(data, "as_pointer", None)
    if not callable(pointer) or not callable(data_pointer):
        raise ValueError("MC2 Mesh result target is not a live Blender Mesh object")
    try:
        object_ptr = int(pointer())
        object_data_ptr = int(data_pointer())
    except Exception as exc:
        raise ValueError("MC2 Mesh result target identity is invalid") from exc
    if object_ptr <= 0 or object_data_ptr <= 0:
        raise ValueError("MC2 Mesh result target identity is invalid")
    return object_ptr, object_data_ptr


def make_mc2_mesh_result(
    *,
    spec,
    candidate: MC2ResultCandidateV0,
    frame: int,
    world_generation: int,
) -> dict:
    """Promote one private readback candidate to a public GN writeback item."""
    if not isinstance(candidate, MC2ResultCandidateV0):
        raise TypeError("candidate must be MC2ResultCandidateV0")
    if candidate.setup_type != MC2_SETUP_MESH_CLOTH:
        raise ValueError("MC2 public Mesh result requires a Mesh candidate")
    if candidate.task_id != getattr(spec, "task_id", None):
        raise ValueError("MC2 public result task identity mismatch")
    if candidate.slot_id != candidate.task_id:
        raise ValueError("MC2 public result slot identity mismatch")
    if candidate.frame != int(frame):
        raise ValueError("MC2 public result frame identity mismatch")
    if candidate.world_generation != int(world_generation) or int(world_generation) <= 0:
        raise ValueError("MC2 public result world generation mismatch")
    if candidate.mesh_object_local_offsets is None:
        raise ValueError("MC2 Mesh candidate has no object-local offsets")

    object_ptr, object_data_ptr = _mesh_target_identity(spec)
    result = make_gn_offset_writeback(
        solver=MC2_SOLVER_ID,
        slot_id=candidate.slot_id,
        object_ptr=object_ptr,
        object_data_ptr=object_data_ptr,
        frame=candidate.frame,
        generation=candidate.world_generation,
        local_offsets=candidate.mesh_object_local_offsets,
    )
    result.update({
        "mc2_result_schema": MC2_PUBLIC_RESULT_SCHEMA_VERSION,
        "ready": True,
        "setup_type": candidate.setup_type,
        "task_id": candidate.task_id,
        "frame_generation": candidate.generation,
        "world_generation": candidate.world_generation,
        "topology_signature": candidate.topology_signature,
        "revision": candidate.revision,
        "native_reset_count": candidate.native_reset_count,
        "native_step_count": candidate.native_step_count,
        "native_dynamic_revision": candidate.native_dynamic_revision,
    })
    return result


def _validated_result_batch(world, results: Iterable[dict]) -> tuple[dict, ...]:
    frame = int(getattr(getattr(world, "frame_context", None), "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)
    if generation <= 0:
        raise ValueError("MC2 public result transaction requires an active world generation")
    batch = tuple(results)
    slot_ids: set[str] = set()
    target_keys: set[str] = set()
    for result in batch:
        if not isinstance(result, dict):
            raise TypeError("MC2 public result batch items must be dicts")
        if result.get("solver") != MC2_SOLVER_ID:
            raise ValueError("MC2 public result batch contains another solver")
        if result.get("channel") != GN_ATTRIBUTE_CHANNEL:
            raise ValueError("MC2 V0 public result batch only accepts GN Mesh results")
        if result.get("ready") is not True:
            raise ValueError("MC2 public result must be ready")
        if int(result.get("frame", -1)) != frame:
            raise ValueError("MC2 public result batch frame mismatch")
        if int(result.get("generation", -1)) != generation:
            raise ValueError("MC2 public result batch generation mismatch")
        slot_id = str(result.get("slot_id") or "")
        target_key = str(result.get("target_key") or "")
        if not slot_id or slot_id in slot_ids:
            raise ValueError("MC2 public result batch has duplicate slot identity")
        if not target_key or target_key in target_keys:
            raise ValueError("MC2 public result batch has duplicate Mesh target")
        slot_ids.add(slot_id)
        target_keys.add(target_key)
    return batch


def publish_mc2_result_transaction(world, results: Iterable[dict]) -> tuple[dict, ...]:
    """Replace MC2 public results atomically while preserving other solvers."""
    batch = _validated_result_batch(world, results)
    previous = {
        str(channel): list(items)
        for channel, items in getattr(world, "result_streams", {}).items()
    }
    published: list[dict] = []
    try:
        world.clear_results(solver=MC2_SOLVER_ID)
        for result in batch:
            item = world.publish_result(
                dict(result),
                channel=result["channel"],
                solver=MC2_SOLVER_ID,
            )
            if item is None:
                raise RuntimeError("MC2 public result publication returned no item")
            published.append(item)
    except Exception:
        world.result_streams.clear()
        world.result_streams.update(previous)
        raise
    return tuple(published)


def iter_mc2_results(world, channel: str | None = None):
    channels = (
        (str(channel),)
        if channel
        else (GN_ATTRIBUTE_CHANNEL, BONE_TRANSFORM_CHANNEL, MC2_STATS_CHANNEL)
    )
    consume = getattr(world, "consume_results", None)
    if not callable(consume):
        return iter(())

    def _iter():
        for result_channel in channels:
            yield from consume(result_channel, solver=MC2_SOLVER_ID)

    return _iter()


__all__ = [
    "MC2_PUBLIC_RESULT_SCHEMA_VERSION",
    "iter_mc2_results",
    "make_mc2_mesh_result",
    "publish_mc2_result_transaction",
]
