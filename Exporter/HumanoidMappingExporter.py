"""Export the authored Humanoid labels used by the Unity model importer.

The FBX exporter may insert MCH bones and change the exported hierarchy.  The
custom Blender properties are therefore captured before that transformation
and written as an explicit mapping sidecar instead of asking Unity to guess
from bone names.
"""

import json
from datetime import datetime, timezone


class HumanoidMappingExporter:
    VERSION = "1.0"

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

        # The authored layout uses names such as upper_arm.L.  Also accept
        # Unity names and common compact spellings for hand-authored labels.
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
                    return f"{side}{finger.capitalize()}{segment_name}"

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
    def build_export_dict(cls, armature_objects):
        armatures = [
            cls.build_armature_dict(armature)
            for armature in armature_objects
            if getattr(armature, "type", None) == "ARMATURE"
        ]
        return {
            "version": cls.VERSION,
            "exportTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mchPrefix": "MCH_",
            "armatures": armatures,
        }

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
