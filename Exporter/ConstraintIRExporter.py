"""Read Blender armature facts into the neutral HoTools rig constraint IR."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .ConstraintIR import (
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
            is_mch = aux_type.strip().upper() == cls.MCH_AUX_TYPE
            pose_bone = cls._bone_get(pose_bones, bone.name)
            constraints = []
            # MCH constraints can only be claimed by the strict binding path.
            # A malformed MCH record must remain visible in unknownConstraints.
            if pose_bone is not None and not is_mch:
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
                            else "未被 MCH/Aux 关系认领"
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
