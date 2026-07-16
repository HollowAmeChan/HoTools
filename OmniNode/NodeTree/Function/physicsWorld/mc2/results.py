"""Public MC2 result-stream helpers."""

from __future__ import annotations

from collections.abc import Iterable

from ..names import BONE_TRANSFORM_CHANNEL, GN_ATTRIBUTE_CHANNEL
from ..utils.writeback_pose import matrix_basis_from_pose_matrix
from ..writeback_commands import (
    make_bone_transform_batch_writeback,
    make_gn_offset_writeback,
)
from .candidate import MC2ResultCandidateV1
from .names import (
    MC2_SETUP_BONE_CLOTH,
    MC2_SETUP_BONE_SPRING,
    MC2_SETUP_MESH_CLOTH,
    MC2_SOLVER_ID,
    MC2_STATS_CHANNEL,
)


MC2_PUBLIC_RESULT_SCHEMA_VERSION = 0
MC2_STATS_SCHEMA = "mc2_stats_v0"
MC2_STATS_SCHEMA_VERSION = 0


_MC2_STATS_SLOT_INT_FIELDS = (
    "particle_count",
    "native_frame",
    "native_generation",
    "reset_count",
    "step_count",
    "parameter_revision",
    "dynamic_revision",
    "collider_revision",
    "self_contact_cache_count",
    "self_intersect_record_count",
)


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
    candidate: MC2ResultCandidateV1,
    frame: int,
    world_generation: int,
) -> dict:
    """Promote one private readback candidate to a public GN writeback item."""
    if not isinstance(candidate, MC2ResultCandidateV1):
        raise TypeError("candidate must be MC2ResultCandidateV1")
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


def _bone_target(spec):
    if getattr(spec, "setup_type", None) not in (
        MC2_SETUP_BONE_CLOTH,
        MC2_SETUP_BONE_SPRING,
    ):
        raise ValueError("MC2 Bone result requires a Bone task")
    sources = tuple(getattr(spec, "sources", ()) or ())
    if not sources:
        raise ValueError("MC2 Bone result requires at least one Armature source")
    armatures = []
    for source in sources:
        armature = source.get("armature") if isinstance(source, dict) else None
        if armature is None and isinstance(source, tuple) and len(source) == 2:
            armature = source[0]
        armatures.append(armature)
    armature = armatures[0]
    if any(value is not armature for value in armatures[1:]):
        raise ValueError("MC2 Bone result sources must share one Armature object")
    if getattr(armature, "type", None) != "ARMATURE":
        raise ValueError("MC2 Bone result target is not an Armature object")
    try:
        armature_ptr = int(armature.as_pointer())
        armature_data_ptr = int(armature.data.as_pointer())
    except Exception as exc:
        raise ValueError("MC2 Bone result target identity is invalid") from exc
    if armature_ptr <= 0 or armature_data_ptr <= 0:
        raise ValueError("MC2 Bone result target identity is invalid")
    return armature, armature_ptr, armature_data_ptr


def make_mc2_bone_result(
    *,
    spec,
    slot,
    candidate: MC2ResultCandidateV1,
    frame: int,
    world_generation: int,
) -> tuple[dict, dict]:
    """Build a public Bone Line envelope and its staged live writeback plan."""
    if not isinstance(candidate, MC2ResultCandidateV1):
        raise TypeError("candidate must be MC2ResultCandidateV1")
    if candidate.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
        raise ValueError("MC2 public Bone result requires a Bone candidate")
    if candidate.task_id != getattr(spec, "task_id", None):
        raise ValueError("MC2 public result task identity mismatch")
    if candidate.slot_id != getattr(slot, "slot_id", None):
        raise ValueError("MC2 public result slot identity mismatch")
    if candidate.frame != int(frame):
        raise ValueError("MC2 public result frame identity mismatch")
    if candidate.world_generation != int(world_generation) or int(world_generation) <= 0:
        raise ValueError("MC2 public result world generation mismatch")

    bone_static = slot.data.get("bone_static")
    bone = getattr(bone_static, "bone", None)
    identities = tuple(
        getattr(getattr(bone, "proxy", None), "vertex_identities", ()) or ()
    )
    if len(identities) != candidate.particle_count:
        raise ValueError("MC2 Bone result identity count mismatch")
    armature, armature_ptr, armature_data_ptr = _bone_target(spec)
    pose_bones = armature.pose.bones
    pose_indices = {pose_bone.name: index for index, pose_bone in enumerate(pose_bones)}

    import mathutils

    inverse_armature = armature.matrix_world.inverted()
    component_xyzw = candidate.bone_component_world_rotation_xyzw
    if component_xyzw is None:
        raise ValueError("MC2 Bone result is missing its component rotation snapshot")
    cx, cy, cz, cw = component_xyzw
    inverse_component_rotation = mathutils.Quaternion((cw, cx, cy, cz)).inverted()
    target_pose_matrices = {}
    records = []
    for name, position, rotation_xyzw in zip(
        identities,
        candidate.world_positions,
        candidate.world_rotations_xyzw,
    ):
        pose_bone = pose_bones.get(name)
        pose_index = pose_indices.get(name, -1)
        if pose_bone is None or pose_index < 0:
            raise ValueError(f"MC2 Bone result target is missing stable bone {name!r}")
        x, y, z, w = (float(value) for value in rotation_xyzw)
        pose_rotation = inverse_component_rotation @ mathutils.Quaternion((w, x, y, z))
        pose_rotation.normalize()
        pose_matrix = pose_rotation.to_matrix().to_4x4()
        pose_matrix.translation = inverse_armature @ mathutils.Vector(
            tuple(float(value) for value in position)
        )
        target_pose_matrices[name] = pose_matrix
        records.append({
            "bone_name": name,
            "pose_index": pose_index,
            "pose_bone": pose_bone,
        })

    matrix_bases = tuple(
        matrix_basis_from_pose_matrix(
            record["pose_bone"],
            target_pose_matrices[record["bone_name"]],
            target_pose_matrices,
        )
        for record in records
    )
    plan = {
        "schema": "mc2_bone_writeback_plan_v0",
        "armature": armature,
        "bone_count": len(records),
        "batches": ({
            "source_kind": candidate.setup_type,
            "source_root": identities[0] if identities else "",
            "records": tuple(records),
            "matrix_bases": matrix_bases,
            "target_pose_matrices": tuple(
                target_pose_matrices[record["bone_name"]] for record in records
            ),
            "current_tails": (),
        },),
    }
    result = make_bone_transform_batch_writeback(
        solver=MC2_SOLVER_ID,
        slot_id=candidate.slot_id,
        armature_ptr=armature_ptr,
        armature_data_ptr=armature_data_ptr,
        frame=candidate.frame,
        generation=candidate.world_generation,
        bone_count=len(records),
        backend="mc2",
        plan_schema=plan["schema"],
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
        "target_key": f"{armature_ptr}:{armature_data_ptr}",
    })
    return result, plan


def merge_mc2_bone_results(entries) -> tuple[tuple[dict, ...], dict[str, dict]]:
    """Merge disjoint Bone components that publish to the same Armature target."""

    grouped: dict[str, list[tuple[dict, dict]]] = {}
    for result, plan in entries:
        if not isinstance(result, dict) or not isinstance(plan, dict):
            raise TypeError("MC2 Bone result entries must contain result/plan dicts")
        target_key = str(result.get("target_key") or "")
        slot_id = str(result.get("slot_id") or "")
        if not target_key or not slot_id:
            raise ValueError("MC2 Bone result entry is missing target or slot identity")
        grouped.setdefault(target_key, []).append((result, plan))

    merged_results = []
    staged_plans: dict[str, dict] = {}
    for target_key in sorted(grouped):
        target_entries = sorted(
            grouped[target_key],
            key=lambda item: str(item[0].get("slot_id") or ""),
        )
        for result, plan in target_entries:
            staged_plans[str(result["slot_id"])] = plan
        if len(target_entries) == 1:
            merged_results.append(target_entries[0][0])
            continue

        primary_result, primary_plan = target_entries[0]
        armature = primary_plan.get("armature")
        global_target_pose_matrices = {}
        source_batches = []
        task_ids = []
        topology_signatures = []
        revisions = []
        for result, plan in target_entries:
            if plan.get("armature") is not armature:
                raise ValueError("MC2 Bone target group does not share one Armature object")
            task_ids.append(str(result.get("task_id") or result.get("slot_id") or ""))
            topology_signatures.append(str(result.get("topology_signature") or ""))
            revisions.append(int(result.get("revision", 0) or 0))
            for batch in plan.get("batches") or ():
                records = tuple(batch.get("records") or ())
                target_matrices = tuple(batch.get("target_pose_matrices") or ())
                if len(records) != len(target_matrices):
                    raise ValueError("MC2 Bone writeback batch target count mismatch")
                for record, target_matrix in zip(records, target_matrices):
                    bone_name = str(record.get("bone_name") or "")
                    if not bone_name or bone_name in global_target_pose_matrices:
                        raise ValueError(
                            f"MC2 Bone components overlap on target bone {bone_name!r}"
                        )
                    global_target_pose_matrices[bone_name] = target_matrix
                source_batches.append(batch)

        merged_batches = []
        for batch in source_batches:
            records = tuple(batch.get("records") or ())
            target_matrices = tuple(batch.get("target_pose_matrices") or ())
            matrix_bases = tuple(
                matrix_basis_from_pose_matrix(
                    record["pose_bone"],
                    target_matrix,
                    global_target_pose_matrices,
                )
                for record, target_matrix in zip(records, target_matrices)
            )
            merged_batch = dict(batch)
            merged_batch["records"] = records
            merged_batch["matrix_bases"] = matrix_bases
            merged_batch["target_pose_matrices"] = target_matrices
            merged_batches.append(merged_batch)

        merged_plan = {
            "schema": primary_plan.get("schema", "mc2_bone_writeback_plan_v0"),
            "armature": armature,
            "bone_count": len(global_target_pose_matrices),
            "component_count": len(target_entries),
            "task_ids": tuple(task_ids),
            "batches": tuple(merged_batches),
        }
        primary_slot_id = str(primary_result["slot_id"])
        staged_plans[primary_slot_id] = merged_plan
        merged_result = dict(primary_result)
        merged_result.update({
            "target_key": target_key,
            "bone_count": merged_plan["bone_count"],
            "component_count": len(target_entries),
            "task_ids": tuple(task_ids),
            "topology_signatures": tuple(topology_signatures),
            "revisions": tuple(revisions),
            "revision": max(revisions, default=0),
        })
        merged_results.append(merged_result)

    return tuple(merged_results), staged_plans


def make_mc2_stats_result(
    *,
    frame: int,
    generation: int,
    slots: Iterable[dict],
    writeback_result_count: int,
) -> dict:
    """Build one stable, backend-handle-free MC2 frame summary."""
    normalized_slots = []
    for item in slots:
        if not isinstance(item, dict):
            raise TypeError("MC2 stats slot items must be dicts")
        slot_id = str(item.get("slot_id") or "")
        setup_type = str(item.get("setup_type") or "")
        if not slot_id or setup_type not in (
            MC2_SETUP_MESH_CLOTH,
            MC2_SETUP_BONE_CLOTH,
            MC2_SETUP_BONE_SPRING,
        ):
            raise ValueError("MC2 stats slot identity is invalid")
        slot_result = {
            "slot_id": slot_id,
            "setup_type": setup_type,
            "native_schema": str(item.get("native_schema") or ""),
            "native_available": bool(item.get("native_available", False)),
            "initialized": bool(item.get("initialized", False)),
        }
        slot_result.update({
            field: int(item.get(field, 0) or 0)
            for field in _MC2_STATS_SLOT_INT_FIELDS
        })
        normalized_slots.append(slot_result)
    normalized_slots.sort(key=lambda item: item["slot_id"])
    slot_results = tuple(normalized_slots)
    setup_counts = {
        setup_type: sum(1 for item in slot_results if item["setup_type"] == setup_type)
        for setup_type in (
            MC2_SETUP_MESH_CLOTH,
            MC2_SETUP_BONE_CLOTH,
            MC2_SETUP_BONE_SPRING,
        )
    }
    return {
        "channel": MC2_STATS_CHANNEL,
        "solver": MC2_SOLVER_ID,
        "schema": MC2_STATS_SCHEMA,
        "backend": "mc2_context_v0",
        "mc2_stats_schema": MC2_STATS_SCHEMA_VERSION,
        "ready": True,
        "frame": int(frame),
        "generation": int(generation),
        "slot_count": len(slot_results),
        "mesh_cloth_count": setup_counts[MC2_SETUP_MESH_CLOTH],
        "bone_cloth_count": setup_counts[MC2_SETUP_BONE_CLOTH],
        "bone_spring_count": setup_counts[MC2_SETUP_BONE_SPRING],
        "native_context_count": sum(
            1 for item in slot_results if item["native_available"]
        ),
        "initialized_count": sum(1 for item in slot_results if item["initialized"]),
        "particle_count": sum(item["particle_count"] for item in slot_results),
        "reset_count": sum(item["reset_count"] for item in slot_results),
        "step_count": sum(item["step_count"] for item in slot_results),
        "writeback_result_count": int(writeback_result_count),
        "slots": slot_results,
    }


def _validated_result_batch(world, results: Iterable[dict]) -> tuple[dict, ...]:
    frame = int(getattr(getattr(world, "frame_context", None), "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)
    if generation <= 0:
        raise ValueError("MC2 public result transaction requires an active world generation")
    batch = tuple(results)
    slot_ids: set[str] = set()
    target_keys: set[str] = set()
    stats_count = 0
    for result in batch:
        if not isinstance(result, dict):
            raise TypeError("MC2 public result batch items must be dicts")
        if result.get("solver") != MC2_SOLVER_ID:
            raise ValueError("MC2 public result batch contains another solver")
        channel = result.get("channel")
        if channel not in (
            GN_ATTRIBUTE_CHANNEL,
            BONE_TRANSFORM_CHANNEL,
            MC2_STATS_CHANNEL,
        ):
            raise ValueError("MC2 V0 public result batch contains an unsupported channel")
        if result.get("ready") is not True:
            raise ValueError("MC2 public result must be ready")
        if int(result.get("frame", -1)) != frame:
            raise ValueError("MC2 public result batch frame mismatch")
        if int(result.get("generation", -1)) != generation:
            raise ValueError("MC2 public result batch generation mismatch")
        if channel == MC2_STATS_CHANNEL:
            stats_count += 1
            if stats_count > 1:
                raise ValueError("MC2 public result batch has duplicate stats results")
            if result.get("schema") != MC2_STATS_SCHEMA:
                raise ValueError("MC2 public stats result schema mismatch")
            if int(result.get("mc2_stats_schema", -1)) != MC2_STATS_SCHEMA_VERSION:
                raise ValueError("MC2 public stats result schema mismatch")
        else:
            slot_id = str(result.get("slot_id") or "")
            target_key = str(result.get("target_key") or "")
            if not slot_id or slot_id in slot_ids:
                raise ValueError("MC2 public result batch has duplicate slot identity")
            if not target_key or target_key in target_keys:
                raise ValueError("MC2 public result batch has duplicate writeback target")
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


def iter_mc2_stats_results(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> list[dict]:
    consume = getattr(world, "consume_results", None)
    if not callable(consume):
        return []
    return [
        item
        for item in consume(
            MC2_STATS_CHANNEL,
            solver=MC2_SOLVER_ID,
            frame=frame,
            generation=generation,
        )
        if isinstance(item, dict) and item.get("channel") == MC2_STATS_CHANNEL
    ]


def get_mc2_stats_result(
    world,
    frame: int | None = None,
    generation: int | None = None,
) -> dict | None:
    items = iter_mc2_stats_results(world, frame=frame, generation=generation)
    return items[-1] if items else None


__all__ = [
    "MC2_PUBLIC_RESULT_SCHEMA_VERSION",
    "MC2_STATS_SCHEMA",
    "MC2_STATS_SCHEMA_VERSION",
    "get_mc2_stats_result",
    "iter_mc2_results",
    "iter_mc2_stats_results",
    "make_mc2_bone_result",
    "make_mc2_mesh_result",
    "make_mc2_stats_result",
    "merge_mc2_bone_results",
    "publish_mc2_result_transaction",
]
