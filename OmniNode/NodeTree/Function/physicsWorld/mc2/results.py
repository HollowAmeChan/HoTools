"""Public MC2 result-stream helpers."""

from __future__ import annotations

from collections.abc import Iterable
import numpy as np

from ..names import BONE_TRANSFORM_CHANNEL, GN_ATTRIBUTE_CHANNEL
from ..utils.writeback_pose import matrix_basis_from_pose_matrix
from ..writeback_commands import (
    make_bone_transform_batch_writeback,
    make_gn_offset_writeback,
)
from .domain_output import MC2MeshWritebackBatchV1
from .names import (
    MC2_SETUP_BONE_CLOTH,
    MC2_SETUP_BONE_SPRING,
    MC2_SETUP_MESH_CLOTH,
    MC2_SOLVER_ID,
)


MC2_PUBLIC_RESULT_SCHEMA_VERSION = 0
MC2_BONE_MOTION_POSITION_ROTATION = "position_rotation"
MC2_BONE_MOTION_ROTATION_ONLY_CONNECTED = "rotation_only_connected"


def mc2_bone_motion_mode(pose_bone) -> str:
    return (
        MC2_BONE_MOTION_ROTATION_ONLY_CONNECTED
        if bool(getattr(getattr(pose_bone, "bone", None), "use_connect", False))
        else MC2_BONE_MOTION_POSITION_ROTATION
    )


def _mc2_bone_writeback_basis(
    pose_bone,
    target_matrix,
    target_pose_matrices,
):
    basis = matrix_basis_from_pose_matrix(
        pose_bone,
        target_matrix,
        target_pose_matrices,
    )
    if (
        mc2_bone_motion_mode(pose_bone)
        == MC2_BONE_MOTION_ROTATION_ONLY_CONNECTED
    ):
        basis.translation = (0.0, 0.0, 0.0)
    return basis


def _mc2_bone_motion_counts(records) -> tuple[int, int]:
    connected_count = sum(
        record.get("motion_mode") == MC2_BONE_MOTION_ROTATION_ONLY_CONNECTED
        for record in records
    )
    return connected_count, len(records) - connected_count

def make_mc2_mesh_domain_results(
    *,
    batch: MC2MeshWritebackBatchV1,
    slot_id: str,
    world_generation: int,
) -> tuple[dict, ...]:
    """将统一域的多 target commands 转成同一公共 GN 事务。"""

    if not isinstance(batch, MC2MeshWritebackBatchV1):
        raise TypeError("batch must be MC2MeshWritebackBatchV1")
    if int(world_generation) != int(batch.generation) or int(world_generation) <= 0:
        raise ValueError("MC2 Mesh domain result generation mismatch")
    stable_slot_id = str(slot_id or "").strip()
    if not stable_slot_id:
        raise ValueError("MC2 Mesh domain result requires a stable slot id")
    count = len(batch.commands)
    results = []
    for index, command in enumerate(batch.commands):
        target = str(command.target_id or "")
        parts = target.split(":")
        if len(parts) != 3 or parts[0] != "mesh":
            raise ValueError("MC2 Mesh domain target id must be mesh:<object>:<data>")
        try:
            object_ptr, object_data_ptr = int(parts[1]), int(parts[2])
        except Exception as exc:
            raise ValueError("MC2 Mesh domain target id is malformed") from exc
        result = make_gn_offset_writeback(
            solver=MC2_SOLVER_ID,
            slot_id=stable_slot_id,
            object_ptr=object_ptr,
            object_data_ptr=object_data_ptr,
            frame=batch.frame,
            generation=batch.generation,
            local_offsets=command.object_local_offsets,
            transaction_id=batch.transaction_id,
            transaction_index=index,
            transaction_size=count,
        )
        result.update({
            "mc2_result_schema": MC2_PUBLIC_RESULT_SCHEMA_VERSION,
            "ready": True,
            "setup_type": MC2_SETUP_MESH_CLOTH,
            "task_id": stable_slot_id,
            "frame_generation": batch.generation,
            "world_generation": batch.generation,
            "domain_signature": batch.domain_signature,
            "layout_signature": batch.layout_signature,
            "partition_index": int(command.partition_index),
            "target_id": target,
        })
        results.append(result)
    return tuple(results)




def _make_mc2_bone_result_values(
    *,
    setup_type: str,
    task_id: str,
    slot_id: str,
    armature,
    armature_ptr: int,
    armature_data_ptr: int,
    identities,
    world_positions,
    world_rotations_xyzw,
    component_world_rotation_xyzw,
    frame: int,
    world_generation: int,
    topology_signature: str,
    revision: int,
    result_metadata=None,
) -> tuple[dict, dict]:
    """把已校验的 Bone 世界姿态转换为现有单向 writeback 合同。"""

    if setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
        raise ValueError("MC2 Bone result setup type is invalid")
    stable_task_id = str(task_id or "").strip()
    stable_slot_id = str(slot_id or "").strip()
    if not stable_task_id or not stable_slot_id:
        raise ValueError("MC2 Bone result identity cannot be empty")
    positions = np.asarray(world_positions, dtype=np.float32)
    rotations = np.asarray(world_rotations_xyzw, dtype=np.float32)
    identities = tuple(str(value or "") for value in identities)
    if (
        positions.ndim != 2
        or positions.shape[1:] != (3,)
        or rotations.shape != (len(positions), 4)
        or len(identities) != len(positions)
        or any(not value for value in identities)
    ):
        raise ValueError("MC2 Bone result pose rows do not match stable identities")
    if not np.isfinite(positions).all() or not np.isfinite(rotations).all():
        raise ValueError("MC2 Bone result pose contains NaN/Inf")
    if len(rotations) and not np.allclose(
        np.linalg.norm(rotations, axis=1),
        1.0,
        rtol=1.0e-5,
        atol=1.0e-6,
    ):
        raise ValueError("MC2 Bone result rotations must be unit quaternions")
    if int(frame) < 0 or int(world_generation) <= 0 or int(revision) <= 0:
        raise ValueError("MC2 Bone result frame/revision identity is invalid")
    if getattr(armature, "type", None) != "ARMATURE":
        raise ValueError("MC2 Bone result target is not an Armature")
    pose_bones = armature.pose.bones
    pose_indices = {pose_bone.name: index for index, pose_bone in enumerate(pose_bones)}

    import mathutils

    inverse_armature = armature.matrix_world.inverted()
    component = np.asarray(component_world_rotation_xyzw, dtype=np.float64)
    if (
        component.shape != (4,)
        or not np.isfinite(component).all()
        or not np.isclose(np.linalg.norm(component), 1.0, rtol=1.0e-5, atol=1.0e-6)
    ):
        raise ValueError("MC2 Bone result requires a unit component rotation")
    cx, cy, cz, cw = (float(value) for value in component)
    inverse_component_rotation = mathutils.Quaternion((cw, cx, cy, cz)).inverted()
    target_pose_matrices = {}
    records = []
    for name, position, rotation_xyzw in zip(identities, positions, rotations):
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
            "motion_mode": mc2_bone_motion_mode(pose_bone),
        })

    matrix_bases = tuple(
        _mc2_bone_writeback_basis(
            record["pose_bone"],
            target_pose_matrices[record["bone_name"]],
            target_pose_matrices,
        )
        for record in records
    )
    connected_count, free_count = _mc2_bone_motion_counts(records)
    plan = {
        "schema": "mc2_bone_writeback_plan_v0",
        "armature": armature,
        "bone_count": len(records),
        "rotation_only_connected_count": connected_count,
        "position_rotation_count": free_count,
        "batches": ({
            "source_kind": setup_type,
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
        slot_id=stable_slot_id,
        armature_ptr=int(armature_ptr),
        armature_data_ptr=int(armature_data_ptr),
        frame=int(frame),
        generation=int(world_generation),
        bone_count=len(records),
        backend="mc2",
        plan_schema=plan["schema"],
    )
    result.update({
        "mc2_result_schema": MC2_PUBLIC_RESULT_SCHEMA_VERSION,
        "ready": True,
        "setup_type": setup_type,
        "task_id": stable_task_id,
        "frame_generation": int(world_generation),
        "world_generation": int(world_generation),
        "topology_signature": str(topology_signature or ""),
        "revision": int(revision),
        "target_key": f"{int(armature_ptr)}:{int(armature_data_ptr)}",
        "rotation_only_connected_count": connected_count,
        "position_rotation_count": free_count,
    })
    result.update(dict(result_metadata or {}))
    return result, plan




def make_mc2_bone_domain_results(
    *,
    collection,
    compiled,
    frame_packet,
    output,
    slot_id: str,
    world_generation: int,
    revision: int,
) -> tuple[tuple[dict, ...], dict[str, dict]]:
    """直接消费 DomainV1 logical output，构造同 Armature 的 Bone 结果事务。"""

    from .domain_compile import MC2CompiledDomainV1
    from .domain_ir import MC2DomainFrameOutputV1, MC2DomainFramePacketV1
    from .setups.bone_cloth.product import MC2BoneProductCollectionV1
    from .setups.bone_cloth.static_fragment import MC2BoneStaticFragmentV1

    if not isinstance(collection, MC2BoneProductCollectionV1):
        raise TypeError("collection must be MC2BoneProductCollectionV1")
    if not isinstance(compiled, MC2CompiledDomainV1):
        raise TypeError("compiled must be MC2CompiledDomainV1")
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise TypeError("frame_packet must be MC2DomainFramePacketV1")
    if not isinstance(output, MC2DomainFrameOutputV1):
        raise TypeError("output must be MC2DomainFrameOutputV1")
    program = compiled.program
    if (
        program.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING)
        or collection.draft.partition_ids != program.partition_ids
        or len(compiled.fragments) != program.partition_count
    ):
        raise ValueError("Bone domain result collection/program identity mismatch")
    if (
        output.index_order != "logical"
        or output.domain_signature != program.domain_signature
        or output.layout_signature != program.layout_signature
        or frame_packet.domain_signature != program.domain_signature
        or frame_packet.layout_signature != program.layout_signature
    ):
        raise ValueError("Bone domain output identity does not match compiled program")
    if (
        output.frame != frame_packet.frame
        or output.generation != frame_packet.generation
        or int(world_generation) != output.generation
        or int(world_generation) <= 0
    ):
        raise ValueError("Bone domain output frame/generation is stale")
    if (
        len(output.world_positions) != program.particle_count
        or output.world_rotations_xyzw.shape != (program.particle_count, 4)
    ):
        raise ValueError("Bone domain output must contain complete positions/rotations")

    entries = []
    for partition_index, (static_input, fragment) in enumerate(zip(
        collection.static_inputs,
        compiled.fragments,
    )):
        if not isinstance(fragment, MC2BoneStaticFragmentV1):
            raise TypeError("Bone compiled domain contains a non-Bone fragment")
        target_indices = tuple(
            index
            for index, target in enumerate(program.output_targets)
            if int(target.partition_index) == partition_index
        )
        if len(target_indices) != 1:
            raise ValueError("Bone partition must map to exactly one output target")
        target_index = target_indices[0]
        logical_indices = np.flatnonzero(
            program.output_target_index == target_index
        ).astype(np.uint32, copy=False)
        source_elements = program.output_source_element[logical_indices]
        order = np.argsort(source_elements, kind="stable")
        logical_indices = logical_indices[order]
        source_elements = source_elements[order]
        identities = tuple(fragment.final_proxy.vertex_identities)
        if (
            len(logical_indices) != len(identities)
            or not np.array_equal(
                source_elements,
                np.arange(len(identities), dtype=np.uint32),
            )
        ):
            raise ValueError("Bone compiled output map does not cover stable identities")
        entries.append(_make_mc2_bone_result_values(
            setup_type=program.setup_type,
            task_id=static_input.partition.stable_id,
            slot_id=slot_id,
            armature=collection.armature,
            armature_ptr=collection.armature_pointer,
            armature_data_ptr=collection.armature_data_pointer,
            identities=identities,
            world_positions=output.world_positions[logical_indices],
            world_rotations_xyzw=output.world_rotations_xyzw[logical_indices],
            component_world_rotation_xyzw=(
                frame_packet.partition_world_rotation[partition_index]
            ),
            frame=output.frame,
            world_generation=world_generation,
            topology_signature=static_input.topology.topology_signature,
            revision=revision,
            result_metadata={
                "frame_generation": frame_packet.generation,
                "domain_signature": program.domain_signature,
                "layout_signature": program.layout_signature,
                "partition_index": partition_index,
                "target_id": program.output_targets[target_index].target_id,
                "backend_revision": output.backend_revision,
                "backend_kind": output.backend_kind,
            },
        ))
    return merge_mc2_bone_results(entries)


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
                _mc2_bone_writeback_basis(
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

        merged_records = tuple(
            record
            for batch in merged_batches
            for record in batch.get("records") or ()
        )
        connected_count, free_count = _mc2_bone_motion_counts(merged_records)
        merged_plan = {
            "schema": primary_plan.get("schema", "mc2_bone_writeback_plan_v0"),
            "armature": armature,
            "bone_count": len(global_target_pose_matrices),
            "rotation_only_connected_count": connected_count,
            "position_rotation_count": free_count,
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
            "rotation_only_connected_count": connected_count,
            "position_rotation_count": free_count,
        })
        merged_results.append(merged_result)

    return tuple(merged_results), staged_plans




def _validated_result_batch(world, results: Iterable[dict]) -> tuple[dict, ...]:
    frame = int(getattr(getattr(world, "frame_context", None), "frame", 0) or 0)
    generation = int(getattr(world, "generation", 0) or 0)
    if generation <= 0:
        raise ValueError("MC2 public result transaction requires an active world generation")
    batch = tuple(results)
    slot_ids: set[str] = set()
    target_keys: set[str] = set()
    transaction_groups: dict[str, dict] = {}
    for result in batch:
        if not isinstance(result, dict):
            raise TypeError("MC2 public result batch items must be dicts")
        if result.get("solver") != MC2_SOLVER_ID:
            raise ValueError("MC2 public result batch contains another solver")
        channel = result.get("channel")
        if channel not in (GN_ATTRIBUTE_CHANNEL, BONE_TRANSFORM_CHANNEL):
            raise ValueError("MC2 public result batch contains an unsupported channel")
        if result.get("ready") is not True:
            raise ValueError("MC2 public result must be ready")
        if int(result.get("frame", -1)) != frame:
            raise ValueError("MC2 public result batch frame mismatch")
        if int(result.get("generation", -1)) != generation:
            raise ValueError("MC2 public result batch generation mismatch")
        slot_id = str(result.get("slot_id") or "")
        target_key = str(result.get("target_key") or "")
        transaction_id = str(result.get("transaction_id") or "")
        permits_shared_slot = channel == GN_ATTRIBUTE_CHANNEL and transaction_id
        if not slot_id or (slot_id in slot_ids and not permits_shared_slot):
            raise ValueError("MC2 public result batch has duplicate slot identity")
        if not target_key or target_key in target_keys:
            raise ValueError("MC2 public result batch has duplicate writeback target")
        if permits_shared_slot:
            index = int(result.get("transaction_index", -1))
            size = int(result.get("transaction_size", -1))
            if index < 0 or size <= 0 or index >= size:
                raise ValueError("MC2 GN transaction index/size is invalid")
            group = transaction_groups.setdefault(transaction_id, {
                "size": size,
                "indices": set(),
                "slot_id": slot_id,
                "frame": int(result.get("frame", -1)),
                "generation": int(result.get("generation", -1)),
            })
            if (
                group["size"] != size
                or group["slot_id"] != slot_id
                or group["frame"] != int(result.get("frame", -1))
                or group["generation"] != int(result.get("generation", -1))
                or index in group["indices"]
            ):
                raise ValueError("MC2 GN transaction metadata mismatch")
            group["indices"].add(index)
        slot_ids.add(slot_id)
        target_keys.add(target_key)
    for group in transaction_groups.values():
        if len(group["indices"]) != group["size"]:
            raise ValueError("MC2 GN transaction is incomplete")
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
        else (GN_ATTRIBUTE_CHANNEL, BONE_TRANSFORM_CHANNEL)
    )
    consume = getattr(world, "consume_results", None)
    if not callable(consume):
        return iter(())

    def _iter():
        for result_channel in channels:
            yield from consume(result_channel, solver=MC2_SOLVER_ID)

    return _iter()






__all__ = [
    "MC2_BONE_MOTION_POSITION_ROTATION",
    "MC2_BONE_MOTION_ROTATION_ONLY_CONNECTED",
    "MC2_PUBLIC_RESULT_SCHEMA_VERSION",
    "iter_mc2_results",
    "mc2_bone_motion_mode",
    "make_mc2_bone_domain_results",
    "make_mc2_mesh_domain_results",
    "merge_mc2_bone_results",
    "publish_mc2_result_transaction",
]
