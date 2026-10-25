"""Read Blender armature facts into the neutral HoTools rig constraint IR."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .ConstraintIR import (
    AimBindingIR,
    AuxBoneIR,
    KnownConstraintIR,
    MCHBindingIR,
    RawConstraintIR,
    RigConstraintIR,
    UnknownConstraintIR,
)


class ConstraintIRExporter:
    """Export Aux and MCH relations without choosing Unity runtime semantics."""

    MCH_AUX_TYPE = "MCH"
    DIRECT_TYPES = frozenset({"COPY_LOCATION", "COPY_ROTATION", "ARMATURE"})

    _NON_PARAMETER_PROPERTIES = {
        "rna_type",
        "name",
        "type",
        "target",
        "subtarget",
        "is_valid",
        "error_location",
        "error_rotation",
        "show_expanded",
        # Blender UI/transient flags are not part of the constraint result.
        "active",
        "set_inverse_pending",
    }

    # Pure-Python fakes have no Blender RNA metadata.  These names also make the
    # minimum contract explicit; Blender itself is serialized through RNA below.
    _COMMON_FALLBACK_PARAMETERS = (
        "influence",
        "mute",
        "owner_space",
        "target_space",
    )
    _TYPE_FALLBACK_PARAMETERS = {
        "ARMATURE": (
            "use_deform_preserve_volume", "use_bone_envelopes", "use_current_location",
        ),
        "DAMPED_TRACK": ("head_tail", "use_bbone_shape", "track_axis"),
        "LOCKED_TRACK": ("head_tail", "use_bbone_shape", "track_axis", "lock_axis"),
        "COPY_ROTATION": (
            "euler_order",
            "mix_mode",
            "use_x",
            "use_y",
            "use_z",
            "invert_x",
            "invert_y",
            "invert_z",
        ),
        "COPY_LOCATION": (
            "head_tail",
            "use_bbone_shape",
            "use_offset",
            "use_x",
            "use_y",
            "use_z",
            "invert_x",
            "invert_y",
            "invert_z",
        ),
        "COPY_SCALE": (
            "power",
            "use_offset",
            "use_add",
            "use_make_uniform",
            "use_x",
            "use_y",
            "use_z",
        ),
        "COPY_TRANSFORMS": (
            "head_tail",
            "use_bbone_shape",
            "mix_mode",
            "remove_target_shear",
        ),
        "STRETCH_TO": (
            "head_tail",
            "use_bbone_shape",
            "rest_length",
            "bulge",
            "volume",
            "keep_axis",
            "use_original_length",
            "use_bulge_min",
            "use_bulge_max",
            "bulge_min",
            "bulge_max",
            "bulge_smooth",
        ),
        "CHILD_OF": (
            "inverse_matrix",
            "use_location_x",
            "use_location_y",
            "use_location_z",
            "use_rotation_x",
            "use_rotation_y",
            "use_rotation_z",
            "use_scale_x",
            "use_scale_y",
            "use_scale_z",
        ),
    }

    @classmethod
    def build_ir(
        cls,
        armature: Any,
        *,
        export_time: str | None = None,
    ) -> RigConstraintIR:
        if getattr(armature, "type", None) != "ARMATURE":
            raise ValueError("Constraint IR can only be built from an armature object")

        data_bones = cls._sorted_bones(getattr(armature.data, "bones", ()))
        pose_bones = getattr(getattr(armature, "pose", None), "bones", ())

        mch_enabled_bones = [
            bone.name
            for bone in data_bones
            if cls._mch_enabled(bone)
        ]
        mch_enabled_set = set(mch_enabled_bones)
        known_constraint_ids: set[tuple[str, int]] = set()
        mch_bindings = cls._collect_mch_bindings(
            armature,
            pose_bones,
            known_constraint_ids,
            mch_enabled_set,
        )
        aux_bones = cls._collect_aux_bones(
            armature,
            data_bones,
            pose_bones,
            known_constraint_ids,
        )
        aim_bindings, aim_records = cls._collect_aim_bindings(
            armature, data_bones, pose_bones, known_constraint_ids,
        )
        direct_records = cls._collect_direct_constraints(
            armature, pose_bones, known_constraint_ids,
        )
        unknown_constraints = cls._collect_unknown_constraints(
            armature,
            pose_bones,
            known_constraint_ids,
        )
        known_constraints = cls._collect_known_constraint_records(
            armature,
            mch_bindings,
            aux_bones,
        )
        known_constraints.extend(aim_records)
        known_constraints.extend(direct_records)
        known_constraints.sort(key=lambda item: (item.owner_bone, item.constraint.stack_index))

        kwargs = {}
        if export_time is not None:
            kwargs["export_time"] = export_time
        return RigConstraintIR(
            armature_name=str(getattr(armature, "name", "")),
            mch_enabled_bones=mch_enabled_bones,
            mch_bindings=mch_bindings,
            aux_bones=aux_bones,
            known_constraints=known_constraints,
            unknown_constraints=unknown_constraints,
            aim_bindings=aim_bindings,
            binding_context=cls._binding_context(armature, data_bones),
            **kwargs,
        )

    @classmethod
    def export_to_dict(
        cls,
        armature: Any,
        *,
        export_time: str | None = None,
    ) -> dict[str, Any]:
        return cls.build_ir(armature, export_time=export_time).to_dict()

    @classmethod
    def export_to_json(
        cls,
        armature: Any,
        *,
        export_time: str | None = None,
    ) -> str:
        data = cls.export_to_dict(armature, export_time=export_time)
        return json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)

    @classmethod
    def export_to_file(cls, armature: Any, filepath: str) -> RigConstraintIR:
        ir = cls.build_ir(armature)
        with open(filepath, "w", encoding="utf-8") as output:
            json.dump(
                ir.to_dict(),
                output,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            output.write("\n")
        return ir

    @classmethod
    def _collect_mch_bindings(
        cls,
        armature: Any,
        pose_bones: Any,
        known_constraint_ids: set[tuple[str, int]],
        mch_enabled_bones: set[str],
    ) -> list[MCHBindingIR]:
        result = []
        for pose_bone in cls._sorted_bones(pose_bones):
            for stack_index, constraint in enumerate(
                getattr(pose_bone, "constraints", ())
            ):
                if getattr(constraint, "type", "") != "CHILD_OF":
                    continue
                if not cls._targets_armature_bone(constraint, armature):
                    continue
                owner_name = str(getattr(pose_bone, "name", ""))
                owner_bone = cls._bone_get(armature.data.bones, owner_name)
                props = getattr(owner_bone, "hotools_boneprops", None)
                aux = getattr(props, "auxBone", None) if props is not None else None
                if aux is None or not bool(getattr(aux, "isAuxBone", False)):
                    continue
                if str(getattr(aux, "auxType", "")).strip().upper() != cls.MCH_AUX_TYPE:
                    continue
                if getattr(constraint, "name", "") not in cls._constraint_names(aux):
                    continue
                source_names = cls._source_bone_names(aux)
                source_name = str(getattr(constraint, "subtarget", ""))
                if source_names != [source_name] or source_name not in mch_enabled_bones:
                    continue
                if cls._bone_get(armature.data.bones, source_name) is None:
                    continue
                known_constraint_ids.add((owner_name, stack_index))
                result.append(
                    MCHBindingIR(
                        source_bone=source_name,
                        mch_bone=owner_name,
                        constraint=cls._raw_constraint(
                            constraint,
                            armature,
                            stack_index,
                        ),
                    )
                )
        return result

    @classmethod
    def _collect_aux_bones(
        cls,
        armature: Any,
        data_bones: list[Any],
        pose_bones: Any,
        known_constraint_ids: set[tuple[str, int]],
    ) -> list[AuxBoneIR]:
        descriptors = []
        for bone in data_bones:
            props = getattr(bone, "hotools_boneprops", None)
            aux = getattr(props, "auxBone", None) if props is not None else None
            if aux is None or not bool(getattr(aux, "isAuxBone", False)):
                continue
            source_bones = cls._source_bone_names(aux)
            constraint_names = cls._constraint_names(aux)
            constraint_name_set = set(constraint_names)
            aux_type = str(getattr(aux, "auxType", "NONE") or "NONE")
            strict_binding = aux_type.strip().upper() in {cls.MCH_AUX_TYPE, "AIM"}
            pose_bone = cls._bone_get(pose_bones, bone.name)
            constraints = []
            # MCH/Aim must pass their own structural recognition, rather than
            # being claimed just because a name was registered on the bone.
            if pose_bone is not None and not strict_binding:
                constraints = []
                for stack_index, constraint in enumerate(
                    getattr(pose_bone, "constraints", ())
                ):
                    owner_name = str(getattr(pose_bone, "name", ""))
                    if (owner_name, stack_index) in known_constraint_ids:
                        continue
                    if getattr(constraint, "name", "") not in constraint_name_set:
                        continue
                    known_constraint_ids.add((owner_name, stack_index))
                    constraints.append(
                        cls._raw_constraint(constraint, armature, stack_index)
                    )

            descriptors.append(
                {
                    "bone": bone,
                    "aux_type": aux_type,
                    "source_bones": source_bones,
                    "constraint_names": constraint_names,
                    "constraints": constraints,
                }
            )

        groups: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
        for descriptor in descriptors:
            key = (
                descriptor["aux_type"],
                tuple(descriptor["source_bones"]),
            )
            groups.setdefault(key, []).append(descriptor)

        result = []
        for descriptor in descriptors:
            group = groups[
                (
                    descriptor["aux_type"],
                    tuple(descriptor["source_bones"]),
                )
            ]
            involved_bones = cls._unique_names(
                [*descriptor["source_bones"]]
                + [item["bone"].name for item in group]
                + [
                    constraint.target_bone_name
                    for item in group
                    for constraint in item["constraints"]
                    if constraint.target_object_name == str(getattr(armature, "name", ""))
                ]
            )
            result.append(
                AuxBoneIR(
                    bone_name=str(descriptor["bone"].name),
                    aux_type=descriptor["aux_type"],
                    source_bones=descriptor["source_bones"],
                    constraint_names=descriptor["constraint_names"],
                    involved_bones=involved_bones,
                    constraints=descriptor["constraints"],
                )
            )
        return result

    @classmethod
    def _collect_direct_constraints(cls, armature, pose_bones, claimed):
        result = []
        for owner in cls._sorted_bones(pose_bones):
            for index, constraint in enumerate(getattr(owner, "constraints", ())):
                key = (owner.name, index)
                if key in claimed or getattr(constraint, "type", "") not in cls.DIRECT_TYPES:
                    continue
                claimed.add(key)
                result.append(KnownConstraintIR(
                    owner_bone=owner.name,
                    relation_type="DIRECT_CONSTRAINT",
                    constraint=cls._raw_constraint(constraint, armature, index),
                ))
        return result

    @classmethod
    def _collect_aim_bindings(cls, armature, data_bones, pose_bones, claimed):
        bindings, records = [], []
        for bone in data_bones:
            props = getattr(bone, "hotools_boneprops", None)
            aux = getattr(props, "auxBone", None)
            if not getattr(aux, "isAuxBone", False) or getattr(aux, "auxType", "") != "AIM":
                continue
            if getattr(aux, "aimVersion", 0) != 1:
                continue
            sources = cls._source_bone_names(aux)
            if len(sources) != 2 or len(set(sources)) != 2 or bone.name in sources:
                continue
            if any(cls._bone_get(armature.data.bones, name) is None for name in sources):
                continue
            owner = cls._bone_get(pose_bones, bone.name)
            stack = list(getattr(owner, "constraints", ()))
            names = cls._constraint_names(aux)
            # Aim owns rotation only. Location and LBS references are independent.
            if len(names) < 2 or len(set(names)) != len(names):
                continue
            selected = [(i, c) for i, c in enumerate(stack) if c.name in names and c.type in {"DAMPED_TRACK", "LOCKED_TRACK"}]
            if len(selected) != 2 or selected[1][0] != selected[0][0] + 1:
                continue
            indices = [i for i, _ in selected]
            pair = [c for _, c in selected]
            if [getattr(c, "type", "") for c in pair] != ["DAMPED_TRACK", "LOCKED_TRACK"]:
                continue
            if any(not cls._targets_armature_bone(c, armature) or c.subtarget != source for c, source in zip(pair, sources)):
                continue
            if any(getattr(c, "influence", 0) != 1.0 or getattr(c, "owner_space", "") != "WORLD" or getattr(c, "target_space", "") != "WORLD" or getattr(c, "head_tail", 0) != 0 or getattr(c, "use_bbone_shape", False) for c in pair):
                continue
            if len({bool(getattr(c, "mute", False)) for c in pair}) != 1:
                continue
            damped, locked = pair
            aim_axis = getattr(damped, "track_axis", "")
            up_axis = getattr(locked, "track_axis", "")
            axes = {"TRACK_X", "TRACK_Y", "TRACK_Z", "TRACK_NEGATIVE_X", "TRACK_NEGATIVE_Y", "TRACK_NEGATIVE_Z"}
            if aim_axis not in axes or up_axis not in axes or aim_axis[-1] == up_axis[-1] or getattr(locked, "lock_axis", "") != "LOCK_" + aim_axis[-1]:
                continue
            raw = [cls._raw_constraint(c, armature, i) for i, c in selected]
            bindings.append(AimBindingIR(
                bone.name, sources[0], sources[1], aim_axis, up_axis, indices,
                bool(getattr(damped, "mute", False)),
            ))
            for item in raw:
                claimed.add((bone.name, item.stack_index))
                records.append(KnownConstraintIR(bone.name, "AIM_BINDING", item, bone.name, "AIM"))
        return bindings, records

    @classmethod
    def _binding_context(cls, armature, bones):
        def matrix(value):
            if value is None:
                return []
            return [float(v) for row in value for v in row]
        position_only = cls._position_only_bones(armature, bones)
        return {
            "space": "BLENDER_ARMATURE", "matrixLayout": "ROW_MAJOR",
            "objectMatrix": matrix(getattr(armature, "matrix_world", None)),
            "bones": [{
                "boneName": b.name,
                "parentBone": str(getattr(getattr(b, "parent", None), "name", "")),
                "restMatrix": matrix(getattr(b, "matrix_local", None)),
                "poseBasis": matrix(getattr(cls._bone_get(getattr(getattr(armature, "pose", None), "bones", ()), b.name), "matrix_basis", None)),
                "inheritScale": str(getattr(b, "inherit_scale", "FULL")),
                "connected": bool(getattr(b, "use_connect", False)),
                "positionOnly": b.name in position_only,
                "hasPoseAnimation": cls._has_pose_animation(armature, b.name),
            } for b in bones],
        }

    @staticmethod
    def _has_pose_animation(armature, bone_name):
        anim = getattr(armature, "animation_data", None)
        if anim is None:
            return False
        prefix = 'pose.bones[' + json.dumps(bone_name, ensure_ascii=False) + ']'
        curves = list(getattr(anim, "drivers", ()))
        actions = [getattr(anim, "action", None)]
        actions.extend(getattr(strip, "action", None) for track in getattr(anim, "nla_tracks", ()) for strip in track.strips)
        for action in actions:
            if action is None:
                continue
            curves.extend(getattr(action, "fcurves", ()))
            for layer in getattr(action, "layers", ()):
                for strip in layer.strips:
                    for bag in getattr(strip, "channelbags", ()):
                        curves.extend(bag.fcurves)
        return any(getattr(curve, "data_path", "").startswith(prefix) for curve in curves)

    @classmethod
    def _position_only_bones(cls, armature, bones):
        """Conservative channel-use proof; never infer point semantics from a name."""
        scenes = getattr(armature, "users_scene", None)
        if scenes is None:
            return set()
        names = {b.name for b in bones}
        full = {getattr(getattr(b, "parent", None), "name", "") for b in bones}
        objects = {o.name: o for scene in scenes for o in scene.objects}.values()
        for obj in objects:
            if getattr(obj, "parent", None) == armature and getattr(obj, "parent_type", "") == "BONE":
                full.add(getattr(obj, "parent_bone", ""))
            modifiers = getattr(obj, "modifiers", ())
            if any(getattr(m, "object", None) == armature for m in modifiers):
                if any(getattr(m, "type", "") == "NODES" for m in modifiers):
                    return set()
                full.update(getattr(g, "name", "") for g in getattr(obj, "vertex_groups", ()))
            anim = getattr(obj, "animation_data", None)
            for driver in getattr(anim, "drivers", ()):
                for variable in driver.driver.variables:
                    for target in variable.targets:
                        if getattr(target, "id", None) == armature:
                            full.add(getattr(target, "bone_target", ""))
        owners = list(getattr(getattr(armature, "pose", None), "bones", ())) + list(objects)
        positional = {"COPY_LOCATION", "DAMPED_TRACK", "LOCKED_TRACK", "STRETCH_TO"}
        for owner in owners:
            for c in getattr(owner, "constraints", ()):
                if getattr(c, "target", None) == armature:
                    if getattr(c, "type", "") not in positional or getattr(c, "head_tail", 0) != 0 or getattr(c, "use_bbone_shape", False):
                        full.add(getattr(c, "subtarget", ""))
                for target in getattr(c, "targets", ()):
                    if getattr(target, "target", None) == armature:
                        full.add(getattr(target, "subtarget", ""))
        return names - full

    @classmethod
    def _collect_known_constraint_records(
        cls,
        armature: Any,
        mch_bindings: list[MCHBindingIR],
        aux_bones: list[AuxBoneIR],
    ) -> list[KnownConstraintIR]:
        result = [
            KnownConstraintIR(
                owner_bone=binding.mch_bone,
                relation_type="MCH_BINDING",
                constraint=binding.constraint,
                aux_bone=binding.mch_bone,
                aux_type="MCH",
            )
            for binding in mch_bindings
        ]
        for aux in aux_bones:
            for constraint in aux.constraints:
                result.append(
                    KnownConstraintIR(
                        owner_bone=aux.bone_name,
                        relation_type="AUX_CONSTRAINT",
                        aux_bone=aux.bone_name,
                        aux_type=aux.aux_type,
                        constraint=constraint,
                    )
                )
        result.sort(key=lambda item: (
            item.owner_bone,
            item.constraint.stack_index,
            item.relation_type,
        ))
        return result

    @staticmethod
    def _is_aux_bone(armature: Any, bone_name: str) -> bool:
        bone = ConstraintIRExporter._bone_get(armature.data.bones, bone_name)
        props = getattr(bone, "hotools_boneprops", None) if bone is not None else None
        aux = getattr(props, "auxBone", None) if props is not None else None
        return bool(getattr(aux, "isAuxBone", False)) if aux is not None else False

    @classmethod
    def _collect_unknown_constraints(
        cls,
        armature: Any,
        pose_bones: Any,
        known_constraint_ids: set[tuple[str, int]],
    ) -> list[UnknownConstraintIR]:
        """Scan every remaining constraint after known MCH/Aux claims."""
        result = []
        emitted_ids: set[tuple[str, int]] = set()
        for pose_bone in cls._sorted_bones(pose_bones):
            for stack_index, constraint in enumerate(
                getattr(pose_bone, "constraints", ())
            ):
                constraint_id = (str(getattr(pose_bone, "name", "")), stack_index)
                if constraint_id in known_constraint_ids or constraint_id in emitted_ids:
                    continue
                emitted_ids.add(constraint_id)
                result.append(
                    UnknownConstraintIR(
                        owner_bone=str(pose_bone.name),
                        constraint=cls._raw_constraint(
                            constraint,
                            armature,
                            stack_index,
                        ),
                        reason=(
                            "辅助骨约束未匹配 HoTools 生成规则"
                            if cls._is_aux_bone(armature, pose_bone.name)
                            else "约束类型或生成关系尚未识别"
                        ),
                    )
                )
        return result

    @classmethod
    def _raw_constraint(
        cls,
        constraint: Any,
        armature: Any,
        stack_index: int,
    ) -> RawConstraintIR:
        target_object = getattr(constraint, "target", None)
        target_object_name = str(getattr(target_object, "name", ""))
        return RawConstraintIR(
            stack_index=stack_index,
            name=str(getattr(constraint, "name", "")),
            constraint_type=str(getattr(constraint, "type", "")),
            target_object_name=target_object_name,
            target_bone_name=str(getattr(constraint, "subtarget", "")),
            parameters=cls._constraint_parameters(constraint),
            references=cls._constraint_references(constraint),
            custom_properties=cls._custom_properties(constraint),
        )

    @classmethod
    def _constraint_parameters(cls, constraint: Any) -> dict[str, Any]:
        names = cls._rna_parameter_names(constraint)
        if names is None:
            names = set(cls._COMMON_FALLBACK_PARAMETERS)
            names.update(
                cls._TYPE_FALLBACK_PARAMETERS.get(
                    str(getattr(constraint, "type", "")),
                    (),
                )
            )

        result = {}
        for name in sorted(names):
            if name in cls._NON_PARAMETER_PROPERTIES or not hasattr(constraint, name):
                continue
            value = cls._json_value(getattr(constraint, name))
            if value is not cls._UNSERIALIZABLE:
                result[name] = value
        return result

    @classmethod
    def _rna_parameter_names(cls, constraint: Any) -> set[str] | None:
        rna = getattr(constraint, "bl_rna", None)
        properties = getattr(rna, "properties", None)
        if properties is None:
            return None

        names = set()
        for prop in properties:
            identifier = str(getattr(prop, "identifier", ""))
            if not identifier or bool(getattr(prop, "is_readonly", False)):
                continue
            if getattr(prop, "type", "") in {"POINTER", "COLLECTION"}:
                continue
            names.add(identifier)
        return names

    @classmethod
    def _constraint_references(cls, constraint: Any) -> dict[str, Any]:
        """Preserve additional RNA pointer/collection facts without engine mapping."""
        rna = getattr(constraint, "bl_rna", None)
        properties = getattr(rna, "properties", None)
        if properties is None:
            if getattr(constraint, "type", "") == "ARMATURE":
                return {"targets": [{"rnaType": "ArmatureConstraintTarget", "properties": {
                    "target": None if getattr(t, "target", None) is None else {"name": str(getattr(t.target, "name", "")), "rnaType": "Object"},
                    "subtarget": str(getattr(t, "subtarget", "")), "weight": getattr(t, "weight", 0.0),
                }} for t in getattr(constraint, "targets", ())]}
            return {}

        result = {}
        for prop in properties:
            identifier = str(getattr(prop, "identifier", ""))
            if (
                not identifier
                or identifier in cls._NON_PARAMETER_PROPERTIES
                or getattr(prop, "type", "") not in {"POINTER", "COLLECTION"}
                or not hasattr(constraint, identifier)
            ):
                continue
            try:
                value = getattr(constraint, identifier)
            except (AttributeError, ReferenceError, RuntimeError):
                continue
            serialized = (
                cls._reference_collection(value)
                if getattr(prop, "type", "") == "COLLECTION"
                else cls._reference_value(value)
            )
            if serialized is not cls._UNSERIALIZABLE:
                result[identifier] = serialized
        return dict(sorted(result.items()))

    @classmethod
    def _reference_collection(
        cls,
        value: Any,
        *,
        depth: int = 0,
        seen: set[int] | None = None,
    ) -> Any:
        """Serialize an RNA collection before treating it as an RNA struct."""
        if value is None:
            return []
        if depth > 4:
            return cls._UNSERIALIZABLE
        seen = set() if seen is None else seen
        value_id = id(value)
        if value_id in seen:
            return cls._UNSERIALIZABLE
        try:
            iterator = iter(value)
        except TypeError:
            return cls._UNSERIALIZABLE

        seen.add(value_id)
        result = []
        try:
            for item in iterator:
                converted = cls._reference_value(
                    item,
                    depth=depth + 1,
                    seen=seen,
                )
                if converted is cls._UNSERIALIZABLE:
                    return cls._UNSERIALIZABLE
                result.append(converted)
        finally:
            seen.remove(value_id)
        return result

    @classmethod
    def _reference_value(
        cls,
        value: Any,
        *,
        depth: int = 0,
        seen: set[int] | None = None,
    ) -> Any:
        """Serialize an RNA reference by stable identity or nested RNA fields."""
        if value is None:
            return None
        if depth > 4:
            return cls._UNSERIALIZABLE

        seen = set() if seen is None else seen
        value_id = id(value)
        if value_id in seen:
            return cls._UNSERIALIZABLE

        rna = getattr(value, "bl_rna", None)
        rna_type = str(getattr(rna, "identifier", ""))
        name_full = getattr(value, "name_full", None)
        if name_full is not None:
            result = {"name": str(name_full)}
            if rna_type:
                result["rnaType"] = rna_type
            return result

        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                converted = cls._reference_value(
                    item,
                    depth=depth + 1,
                    seen=seen,
                )
                if converted is not cls._UNSERIALIZABLE:
                    result[str(key)] = converted
            return result
        if isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, (bytes, bytearray)):
            return cls._UNSERIALIZABLE

        properties = getattr(rna, "properties", None)
        if properties is not None:
            seen.add(value_id)
            fields = {}
            try:
                for prop in properties:
                    identifier = str(getattr(prop, "identifier", ""))
                    if (
                        not identifier
                        or identifier == "rna_type"
                        or not hasattr(value, identifier)
                    ):
                        continue
                    try:
                        item = getattr(value, identifier)
                    except (AttributeError, ReferenceError, RuntimeError):
                        continue
                    if getattr(prop, "type", "") == "COLLECTION":
                        converted = cls._reference_collection(
                            item,
                            depth=depth + 1,
                            seen=seen,
                        )
                    elif getattr(prop, "type", "") == "POINTER":
                        converted = cls._reference_value(
                            item,
                            depth=depth + 1,
                            seen=seen,
                        )
                    else:
                        converted = cls._json_value(item)
                    if converted is not cls._UNSERIALIZABLE:
                        fields[identifier] = converted
            finally:
                seen.remove(value_id)
            result = {"properties": dict(sorted(fields.items()))}
            if rna_type:
                result["rnaType"] = rna_type
            return result

        return cls._reference_collection(value, depth=depth, seen=seen)

    @classmethod
    def _custom_properties(cls, constraint: Any) -> dict[str, Any]:
        items = getattr(constraint, "items", None)
        if not callable(items):
            return {}
        try:
            raw_items = items()
        except (AttributeError, TypeError, RuntimeError):
            return {}

        result = {}
        for key, value in raw_items:
            serialized = cls._json_value(value)
            if serialized is not cls._UNSERIALIZABLE:
                result[str(key)] = serialized
        return dict(sorted(result.items()))

    @staticmethod
    def _targets_armature_bone(constraint: Any, armature: Any) -> bool:
        return (
            getattr(constraint, "target", None) == armature
            and bool(getattr(constraint, "subtarget", ""))
        )

    @staticmethod
    def _mch_enabled(bone: Any) -> bool:
        props = getattr(bone, "hotools_boneprops", None)
        return bool(getattr(props, "generateMCH", False)) if props is not None else False

    @staticmethod
    def _source_bone_names(aux: Any) -> list[str]:
        result = []
        for item in getattr(aux, "sourceBones", ()):
            name = str(getattr(item, "name", ""))
            if name:
                result.append(name)
        return result

    @staticmethod
    def _constraint_names(aux: Any) -> list[str]:
        result = []
        for item in getattr(aux, "constraintNames", ()):
            name = str(getattr(item, "name", ""))
            if name:
                result.append(name)
        return result

    @staticmethod
    def _bone_get(bones: Any, name: str) -> Any | None:
        getter = getattr(bones, "get", None)
        if callable(getter):
            return getter(name)
        for bone in bones:
            if getattr(bone, "name", None) == name:
                return bone
        return None

    @staticmethod
    def _sorted_bones(bones: Any) -> list[Any]:
        return sorted(list(bones), key=lambda bone: str(getattr(bone, "name", "")))

    @staticmethod
    def _unique_names(names: Iterable[str]) -> list[str]:
        result = []
        for name in names:
            text = str(name)
            if text and text not in result:
                result.append(text)
        return result

    class _Unserializable:
        pass

    _UNSERIALIZABLE = _Unserializable()

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                value = to_dict()
            except (AttributeError, TypeError, RuntimeError):
                return cls._UNSERIALIZABLE

        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                converted = cls._json_value(item)
                if converted is not cls._UNSERIALIZABLE:
                    result[str(key)] = converted
            return result
        if isinstance(value, (bytes, bytearray)):
            return cls._UNSERIALIZABLE
        try:
            iterator = iter(value)
        except TypeError:
            return cls._UNSERIALIZABLE

        result = []
        for item in iterator:
            converted = cls._json_value(item)
            if converted is cls._UNSERIALIZABLE:
                return cls._UNSERIALIZABLE
            result.append(converted)
        return result
