"""Read the current Blender state into a one-to-one HoAux Source IR snapshot."""

import json
import re

from ..collection_registry import COLLECTION_KEY_PROP
from ..name_registry import iter_hoaux_bones
from .capabilities import derive_capabilities
from .graph import build_reverse_edges
from .model import HoAuxSourceIR, ResourceEdge, ResourceRecord


_POSE_BONE_RE = re.compile(r'pose\.bones\["((?:\\.|[^"\\])*)"\]')
_CONSTRAINT_RE = re.compile(r'constraints\["((?:\\.|[^"\\])*)"\]')


def _decode_escaped_name(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def bone_name_from_path(data_path: str):
    match = _POSE_BONE_RE.search(data_path)
    return _decode_escaped_name(match.group(1)) if match else None


def constraint_name_from_path(data_path: str):
    match = _CONSTRAINT_RE.search(data_path)
    return _decode_escaped_name(match.group(1)) if match else None


def _info_dict(info) -> dict:
    return {
        "schemaVersion": info.schemaVersion,
        "pipelineId": info.pipelineId,
        "moduleId": info.moduleId,
        "moduleType": info.moduleType,
        "roleTag": info.roleTag,
        "part": info.part,
        "function": info.function,
        "marker": info.marker,
        "side": info.side,
        "generationId": info.generationId,
        "sharedKey": info.sharedKey,
        "nameKey": info.nameKey,
    }


def _constraint_payload(constraint) -> dict:
    payload = {
        "type": constraint.type,
        "name": constraint.name,
        "mute": constraint.mute,
        "influence": constraint.influence,
    }
    fields = {
        "owner_space": "ownerSpace",
        "target_space": "targetSpace",
        "subtarget": "targetBoneName",
        "head_tail": "headTail",
        "mix_mode": "mixMode",
        "use_x": "useX",
        "use_y": "useY",
        "use_z": "useZ",
        "invert_x": "invertX",
        "invert_y": "invertY",
        "invert_z": "invertZ",
        "use_offset": "useOffset",
        "euler_order": "eulerOrder",
        "rest_length": "restLength",
        "bulge": "bulge",
        "use_bulge_min": "useBulgeMin",
        "use_bulge_max": "useBulgeMax",
        "bulge_min": "bulgeMin",
        "bulge_max": "bulgeMax",
        "bulge_smooth": "bulgeSmooth",
        "volume": "volume",
        "keep_axis": "keepAxis",
    }
    for source_name, target_name in fields.items():
        if hasattr(constraint, source_name):
            payload[target_name] = getattr(constraint, source_name)
    target = getattr(constraint, "target", None)
    payload["targetObjectName"] = target.name if target is not None else ""
    return payload


def _driver_payload(fcurve) -> dict:
    driver = fcurve.driver
    return {
        "dataPath": fcurve.data_path,
        "arrayIndex": fcurve.array_index,
        "type": driver.type,
        "expression": driver.expression,
        "useSelf": driver.use_self,
    }


def snapshot_armature(armature_object) -> HoAuxSourceIR:
    if armature_object is None or armature_object.type != "ARMATURE":
        raise TypeError("snapshot_armature requires an Armature object")

    armature_data = armature_object.data
    bones = list(iter_hoaux_bones(armature_data))
    bone_key_by_name = {
        bone.name: bone.hotools_boneprops.hoAux.nameKey or f"BONE:{bone.name}"
        for bone in bones
    }
    records = []
    record_by_key = {}

    def ensure_bone_reference(target_object, target_name: str):
        if not target_name or target_object is None or target_object.type != "ARMATURE":
            return None
        if target_object == armature_object and target_name in bone_key_by_name:
            return bone_key_by_name[target_name]
        target_bone = target_object.data.bones.get(target_name)
        if target_bone is None:
            return None
        key = f"EXTERNAL:BONE:{target_object.name}:{target_name}"
        if key not in record_by_key:
            record = ResourceRecord(
                resource_key=key,
                resource_kind="BONE",
                provenance={"external": True},
                blender_binding={
                    "objectName": target_object.name,
                    "name": target_name,
                },
                payload={
                    "name": target_name,
                    "parentName": target_bone.parent.name if target_bone.parent else "",
                    "useDeform": target_bone.use_deform,
                    "isHoAuxBone": False,
                },
            )
            records.append(record)
            record_by_key[key] = record
        return key

    for bone in bones:
        info = bone.hotools_boneprops.hoAux
        key = bone_key_by_name[bone.name]
        record = ResourceRecord(
            resource_key=key,
            resource_kind="BONE",
            provenance={
                "rigId": info.rigId,
                "pipelineId": info.pipelineId,
                "moduleId": info.moduleId,
                "generationId": info.generationId,
            },
            blender_binding={"name": bone.name},
            payload={
                **_info_dict(info),
                "parentName": bone.parent.name if bone.parent else "",
                "useDeform": bone.use_deform,
            },
        )
        if bone.parent and bone.parent.name in bone_key_by_name:
            record.uses.append(
                ResourceEdge("PARENT_OF", bone_key_by_name[bone.parent.name])
            )
        records.append(record)
        record_by_key[key] = record

    collections = getattr(armature_data, "collections_all", armature_data.collections)
    for collection in collections:
        collection_key = collection.get(COLLECTION_KEY_PROP)
        if not collection_key:
            continue
        parent_key = (
            collection.parent.get(COLLECTION_KEY_PROP)
            if collection.parent is not None
            else ""
        )
        members = [
            bone_key_by_name[bone.name]
            for bone in collection.bones
            if bone.name in bone_key_by_name
        ]
        record = ResourceRecord(
            resource_key=collection_key,
            resource_kind="BONE_COLLECTION",
            blender_binding={"name": collection.name},
            payload={
                "name": collection.name,
                "parentCollectionKey": parent_key,
                "isVisible": collection.is_visible,
                "memberBoneKeys": members,
            },
            uses=[ResourceEdge("MEMBER_OF", key) for key in members],
        )
        records.append(record)
        record_by_key[collection_key] = record

    constraint_keys = {}
    for bone in bones:
        owner_key = bone_key_by_name[bone.name]
        pose_bone = armature_object.pose.bones.get(bone.name)
        if pose_bone is None:
            continue
        for index, constraint in enumerate(pose_bone.constraints):
            key = f"{owner_key}/CONSTRAINT/{index}:{constraint.type}"
            payload = _constraint_payload(constraint)
            target_name = payload.get("targetBoneName", "")
            target_object = getattr(constraint, "target", None)
            target_key = ensure_bone_reference(target_object, target_name)
            status = "RESOLVED"
            uses = []
            if target_key:
                uses.append(ResourceEdge("TARGETS", target_key))
            elif target_name:
                status = "UNRESOLVED"
            record = ResourceRecord(
                resource_key=key,
                resource_kind="CONSTRAINT",
                status=status,
                provenance={"ownerResourceKey": owner_key},
                blender_binding={
                    "ownerBoneName": bone.name,
                    "name": constraint.name,
                    "stackIndex": index,
                },
                payload=payload,
                uses=uses,
            )
            record.requires_capabilities = derive_capabilities(record)
            records.append(record)
            record_by_key[key] = record
            record_by_key[owner_key].owns.append(key)
            constraint_keys[(bone.name, constraint.name)] = key

    animation_data = armature_object.animation_data
    if animation_data is not None:
        for driver_index, fcurve in enumerate(animation_data.drivers):
            owner_name = bone_name_from_path(fcurve.data_path)
            owner_key = bone_key_by_name.get(owner_name)
            if not owner_key:
                continue
            key = f"{owner_key}/DRIVER/{driver_index}"
            record = ResourceRecord(
                resource_key=key,
                resource_kind="DRIVER",
                provenance={"ownerResourceKey": owner_key},
                blender_binding={
                    "dataPath": fcurve.data_path,
                    "arrayIndex": fcurve.array_index,
                },
                payload=_driver_payload(fcurve),
            )
            constraint_name = constraint_name_from_path(fcurve.data_path)
            constraint_key = constraint_keys.get((owner_name, constraint_name))
            if constraint_key:
                record.uses.append(
                    ResourceEdge(
                        "DRIVES_PROPERTY",
                        constraint_key,
                        {"dataPath": fcurve.data_path},
                    )
                )
            record.requires_capabilities = derive_capabilities(record)
            records.append(record)
            record_by_key[key] = record
            record_by_key[owner_key].owns.append(key)

            for variable_index, variable in enumerate(fcurve.driver.variables):
                variable_key = f"{key}/VARIABLE/{variable_index}"
                target_payloads = []
                uses = []
                status = "RESOLVED"
                for target in variable.targets:
                    target_name = getattr(target, "bone_target", "")
                    target_object = getattr(target, "id", None)
                    target_key = ensure_bone_reference(target_object, target_name)
                    if target_key:
                        uses.append(ResourceEdge("READS_TRANSFORM", target_key))
                    elif target_name:
                        status = "UNRESOLVED"
                    target_payloads.append(
                        {
                            "idName": target.id.name if target.id is not None else "",
                            "boneTargetName": target_name,
                            "transformType": target.transform_type,
                            "transformSpace": target.transform_space,
                            "rotationMode": target.rotation_mode,
                            "dataPath": target.data_path,
                        }
                    )
                variable_record = ResourceRecord(
                    resource_key=variable_key,
                    resource_kind="DRIVER_VARIABLE",
                    status=status,
                    provenance={"ownerResourceKey": key},
                    blender_binding={"name": variable.name, "index": variable_index},
                    payload={
                        "name": variable.name,
                        "type": variable.type,
                        "targets": target_payloads,
                    },
                    uses=uses,
                )
                if target_payloads:
                    first = target_payloads[0]
                    variable_record.payload.update(
                        {
                            "transformSpace": first["transformSpace"],
                            "transformType": first["transformType"],
                        }
                    )
                variable_record.requires_capabilities = derive_capabilities(
                    variable_record
                )
                records.append(variable_record)
                record_by_key[variable_key] = variable_record
                record.owns.append(variable_key)

    build_reverse_edges(records)
    return HoAuxSourceIR(
        rig_id=getattr(armature_data, "hoaux_rig_id", "")
        or f"UNASSIGNED:{armature_data.name}",
        armature_name=armature_object.name,
        resources=records,
        metadata={"snapshotMode": "CURRENT_BLENDER_STATE"},
    )
