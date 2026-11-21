"""Lossless dictionary model for ordinary Rig Constraint IR v4.

The dictionaries deliberately have no closed dataclass projection: extension
fields and unknown Blender parameters must survive a read/write round trip.
This module never imports bpy or the separate, large HoAux authoring system.
"""

from datetime import datetime, timezone

SCHEMA = "hotools.rig-constraint-ir"
SCHEMA_VERSION = 4
BACKENDS = ("Standard", "HoAux", "Vrc")
CAPTURE_STAGES = ("AUTHORING", "POSTPROCESS", "EXPORT_GENERATED")
EVIDENCE_KINDS = ("RAW_TYPE", "GENERATED", "EXPLICIT", "LEGACY")


def new_document(armature_name, blender_version="", capture_stage="AUTHORING"):
    """Create an empty, valid authoring snapshot without inventing FBX bindings."""
    if not isinstance(armature_name, str) or not armature_name:
        raise ValueError("armature_name must be a nonempty string")
    if not isinstance(blender_version, str):
        raise ValueError("blender_version must be a string")
    if capture_stage not in CAPTURE_STAGES:
        raise ValueError("unknown capture_stage")
    from .registry import registry_manifest
    from .codec import fingerprint

    document = {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "armatureName": armature_name,
        "exportTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "blenderVersion": blender_version,
        "captureStage": capture_stage,
        "registry": registry_manifest(),
        "sources": [],
        "semantics": [],
        "implementationBindings": [],
        "sourceContext": {},
    }
    document["inputFingerprint"] = fingerprint(document)
    return document
