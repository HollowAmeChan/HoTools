"""Export authored Humanoid labels and saved T-Pose calibration together.

The FBX exporter may insert MCH bones and change the exported hierarchy.  The
custom Blender properties are therefore captured before that transformation
and written as an explicit mapping sidecar instead of asking Unity to guess
from bone names. Reference transforms are expressed against the final export
rest skeleton; they calibrate the Avatar without changing mesh bind poses.
"""

import json
from datetime import datetime, timezone


class HumanoidMappingExporter:
    VERSION = "2.0"

    _BASE_NAMES = {
        "hips": "Hips",
        "spine": "Spine",
        "chest": "Chest",
        "upperchest": "UpperChest",
        "neck": "Neck",
        "head": "Head",
        "eye": "Eye",
        "jaw": "Jaw",
        "shoulder": "Shoulder",
        "upperarm": "UpperArm",
        "lowerarm": "LowerArm",
        "hand": "Hand",
        "upperleg": "UpperLeg",
        "lowerleg": "LowerLeg",
        "foot": "Foot",
        "toes": "Toes",
    }
    _FINGER_NAMES = {"thumb", "index", "middle", "ring", "little"}
    _FINGER_SEGMENTS = {
        "proximal": "Proximal",
        "intermediate": "Intermediate",
        "distal": "Distal",
    }

    @staticmethod
    def _normalise(value):
        return "".join(ch for ch in value.strip().lower() if ch not in " ._-")

    @classmethod
    def to_unity_human_name(cls, mapping):
        """Convert a HoTools mapping label to Unity's HumanBone name."""
        value = (mapping or "").strip()
        if not value or value.lower() == "root":
            return ""

        # The authored humanoidMapping property uses labels such as
        # upper_arm.L. No source-bone-name inference is performed here.
        side = ""
        lower = value.lower()
        if lower.endswith(".l") or lower.endswith("_l") or lower.endswith("-l"):
            side, value = "Left", value[:-2]
        elif lower.endswith(".r") or lower.endswith("_r") or lower.endswith("-r"):
            side, value = "Right", value[:-2]
        else:
            compact = cls._normalise(value)
            if compact.startswith("left"):
                side, value = "Left", compact[4:]
            elif compact.startswith("right"):
                side, value = "Right", compact[5:]

        compact = cls._normalise(value)
        if compact == "root":
            return ""

        if compact in cls._BASE_NAMES:
            base = cls._BASE_NAMES[compact]
            if base in {"Eye", "Shoulder", "UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot", "Toes"} and not side:
                return ""
            return f"{side}{base}" if side else base

        for finger in cls._FINGER_NAMES:
            prefix = finger
            for segment, segment_name in cls._FINGER_SEGMENTS.items():
                if compact in {
                    f"{prefix}{segment}",
                    f"{prefix}{segment_name.lower()}",
                }:
                    if not side:
                        return ""
                    # Unity's HumanTrait uses spaces for finger slots, e.g.
                    # "Right Thumb Proximal", while body slots stay compact.
                    return f"{side} {finger.capitalize()} {segment_name}"

        # Unity's spelling is useful when a user entered a standard name
        # directly rather than one of HoTools' dotted layout names.
        standard = {
            "hips": "Hips",
            "spine": "Spine",
            "chest": "Chest",
            "upperchest": "UpperChest",
            "neck": "Neck",
            "head": "Head",
            "jaw": "Jaw",
        }
        return standard.get(compact, "")

    @classmethod
    def build_armature_dict(cls, armature_object):
        bones = []
        seen_humanoid = set()
        data = getattr(armature_object, "data", None)
        if data is None:
            return {"armatureName": getattr(armature_object, "name", ""), "bones": bones}

        for bone in data.bones:
            props = getattr(bone, "hotools_boneprops", None)
            mapping = getattr(props, "humanoidMapping", "").strip() if props else ""
            human_name = cls.to_unity_human_name(mapping)
            if not human_name or human_name in seen_humanoid:
                continue

            seen_humanoid.add(human_name)
            parent = getattr(bone, "parent", None)
            bones.append({
                "boneName": bone.name,
                "humanName": human_name,
                "sourceMapping": mapping,
                "parentName": parent.name if parent else "",
            })

        return {
            "armatureName": getattr(armature_object, "name", ""),
            "bones": bones,
        }

    @classmethod
    def capture_reference_poses(cls, armature_objects):
        """Read saved calibration without evaluating constraints or changing pose."""
        from mathutils import Matrix

        result = {}
        for armature in armature_objects:
            if getattr(armature, "type", None) != "ARMATURE":
                continue
            mapped = cls.build_armature_dict(armature)["bones"]
            if not mapped:
                continue
            cached = {bone.name for bone in armature.data.bones
                      if getattr(getattr(bone, "hotools_boneprops", None), "humanoidTPoseCached", False)}
            if not cached:
                continue
            missing = [item["boneName"] for item in mapped if item["boneName"] not in cached]
            if missing:
                raise ValueError(f"骨架 {armature.name} 的 T-Pose 标定不完整，请重新保存：" + "、".join(missing))
            poses, snapshot = {}, {}
            for bone in armature.pose.bones:
                basis = Matrix.Identity(4)
                if bone.name in cached:
                    values = bone.bone.hotools_boneprops.humanoidTPoseMatrixBasis
                    basis = Matrix(tuple(tuple(values[row * 4 + col] for col in range(4)) for row in range(4)))
                kwargs = {}
                if bone.parent:
                    kwargs = {"parent_matrix": poses[bone.parent.name],
                              "parent_matrix_local": bone.parent.bone.matrix_local}
                pose = bone.bone.convert_local_to_pose(basis, bone.bone.matrix_local, **kwargs)
                poses[bone.name] = pose
                snapshot[bone.name] = {"rest": armature.matrix_world @ bone.bone.matrix_local,
                                       "pose": armature.matrix_world @ pose}
            result[armature.name] = snapshot
        return result

    @staticmethod
    def rebase_reference_rest(reference_poses, armature_objects):
        """Keep the saved physical T-Pose when an export applies a new rest pose."""
        for armature in armature_objects:
            for name, item in reference_poses.get(armature.name, {}).items():
                item["rest"] = armature.matrix_world @ armature.data.bones[name].matrix_local

    @classmethod
    def update_reference_poses(cls, data, armature_objects, reference_poses, mch_name_maps=None):
        """Express calibration against the final FBX rest hierarchy and bone axes."""
        from mathutils import Matrix

        armatures = {armature.name: armature for armature in armature_objects}
        for entry in data["armatures"]:
            snapshot = reference_poses.get(entry["armatureName"])
            if not snapshot:
                continue
            armature = armatures[entry["armatureName"]]
            sources = {target: source for source, target in (mch_name_maps or {}).get(armature.name, {}).items()}
            rest, poses, rows = {}, {}, []
            for bone in armature.data.bones:
                rest[bone.name] = armature.matrix_world @ bone.matrix_local
                item = snapshot.get(sources.get(bone.name, bone.name))
                if item:
                    poses[bone.name] = item["pose"] @ item["rest"].inverted() @ rest[bone.name]
                elif bone.parent:
                    poses[bone.name] = poses[bone.parent.name] @ rest[bone.parent.name].inverted() @ rest[bone.name]
                else:
                    poses[bone.name] = rest[bone.name].copy()
                parent_rest = rest[bone.parent.name] if bone.parent else armature.matrix_world
                parent_pose = poses[bone.parent.name] if bone.parent else armature.matrix_world
                local_rest = parent_rest.inverted() @ rest[bone.name]
                local_pose = parent_pose.inverted() @ poses[bone.name]
                delta = local_rest.inverted() @ local_pose
                position, rotation, scale = delta.decompose()
                rebuilt = Matrix.LocRotScale(position, rotation, scale)
                if max(abs(delta[r][c] - rebuilt[r][c]) for r in range(4) for c in range(4)) > 1e-4:
                    raise ValueError(f"骨骼 {bone.name} 的 T-Pose 含有 Unity 无法表示的剪切变换")
                rows.append({"boneName": bone.name, "parentName": bone.parent.name if bone.parent else "",
                             "restPosition": list(local_rest.translation), "position": list(position),
                             "rotation": [rotation.x, rotation.y, rotation.z, rotation.w], "scale": list(scale)})
            entry["tPose"] = {"space": "BONE_REST_LOCAL", "fbxBoneAxes": "Y_X",
                              "rotationRepresentation": "quaternion-xyzw", "bones": rows}

    @classmethod
    def build_export_dict(cls, armature_objects, reference_poses=None):
        armature_objects = list(armature_objects)
        armatures = [
            cls.build_armature_dict(armature)
            for armature in armature_objects
            if getattr(armature, "type", None) == "ARMATURE"
        ]
        data = {
            "version": cls.VERSION,
            "exportTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mchPrefix": "MCH_",
            "armatures": armatures,
        }
        if reference_poses is None:
            reference_poses = cls.capture_reference_poses(armature_objects)
        cls.update_reference_poses(data, armature_objects, reference_poses)
        return data

    @classmethod
    def export_to_file(cls, armature_objects, filepath):
        data = cls.build_export_dict(armature_objects)
        return cls.write_export_dict(data, filepath)

    @classmethod
    def write_export_dict(cls, data, filepath):
        """Write a previously captured mapping dictionary."""
        if not any(item["bones"] for item in data["armatures"]):
            return None
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return data
