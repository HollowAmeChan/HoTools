"""Minimal persistent identity and ownership metadata for HoAux bones."""

from uuid import uuid4

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


SCHEMA_VERSION = 1


def _preview_update(_self, context):
    from .preview import ShoulderVolumePreview

    ShoulderVolumePreview.refresh(context)

ROLE_ITEMS = (
    ("NONE", "None", "Not a generated HoAux bone"),
    ("DEF", "DEF", "Deformation output bone"),
    ("TRK", "TRK", "User-adjustable track bone"),
    ("DIR", "DIR", "Shared direction infrastructure bone"),
)

SIDE_ITEMS = (
    ("NONE", "None", "No side"),
    ("L", "L", "Left"),
    ("R", "R", "Right"),
    ("C", "C", "Center"),
)


class PG_HoAuxBoneInfo(PropertyGroup):
    isHoAuxBone: BoolProperty(default=False)  # type: ignore
    schemaVersion: IntProperty(default=SCHEMA_VERSION, min=1)  # type: ignore
    rigId: StringProperty(default="")  # type: ignore
    pipelineId: StringProperty(default="")  # type: ignore
    moduleId: StringProperty(default="")  # type: ignore
    moduleType: StringProperty(default="")  # type: ignore
    roleTag: EnumProperty(items=ROLE_ITEMS, default="NONE")  # type: ignore
    part: StringProperty(default="")  # type: ignore
    function: StringProperty(default="")  # type: ignore
    marker: StringProperty(default="")  # type: ignore
    side: EnumProperty(items=SIDE_ITEMS, default="NONE")  # type: ignore
    generationId: StringProperty(default="")  # type: ignore
    sharedKey: StringProperty(default="")  # type: ignore
    nameKey: StringProperty(default="")  # type: ignore


class PG_HoAuxSettings(PropertyGroup):
    side: EnumProperty(
        items=SIDE_ITEMS[1:3], default="L", update=_preview_update
    )  # type: ignore
    shoulderBone: StringProperty(default="", update=_preview_update)  # type: ignore
    upperArmBone: StringProperty(default="", update=_preview_update)  # type: ignore
    shoulderTrackLength: FloatProperty(
        name="TRK Length",
        default=0.5,
        min=0.05,
        max=2.0,
        update=_preview_update,
    )  # type: ignore
    shoulderDefLength: FloatProperty(
        name="DEF Length",
        default=0.28,
        min=0.05,
        max=2.0,
        update=_preview_update,
    )  # type: ignore
    shoulderDirLength: FloatProperty(
        name="DIR Length",
        default=0.05,
        min=0.005,
        max=0.5,
        update=_preview_update,
    )  # type: ignore
    shoulderHalfInfluence: FloatProperty(
        name="Half Influence",
        default=0.5,
        min=0.0,
        max=1.0,
        update=_preview_update,
    )  # type: ignore
    shoulderResponseAngle: FloatProperty(
        name="Full Response Angle",
        default=90.0,
        min=1.0,
        max=180.0,
        update=_preview_update,
    )  # type: ignore
    shoulderHeadTail: FloatProperty(
        name="Target Point",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )  # type: ignore
    shoulderX0Angle: FloatProperty(
        name="X0 Direction Angle",
        default=45.0,
        min=-180.0,
        max=180.0,
        update=_preview_update,
    )  # type: ignore
    shoulderConvexAxis: EnumProperty(
        name="Convex Axis",
        items=(
            ("X", "Local X", "Map joint convexity to the frame X axis"),
            ("Z", "Local Z", "Map joint convexity to the frame Z axis"),
        ),
        default="X",
        update=_preview_update,
    )  # type: ignore
    shoulderRollFollow: FloatProperty(
        name="Roll Follow",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_preview_update,
    )  # type: ignore
    shoulderTwistOffset: FloatProperty(
        name="Twist Offset",
        default=0.0,
        min=-180.0,
        max=180.0,
        update=_preview_update,
    )  # type: ignore
    shoulderStraightThreshold: FloatProperty(
        name="Straight Threshold",
        default=5.0,
        min=0.0,
        max=45.0,
        update=_preview_update,
    )  # type: ignore
    shoulderX1Scale: FloatProperty(
        name="X1 Scale", default=1.0, min=0.05, max=3.0, update=_preview_update
    )  # type: ignore
    shoulderX0Scale: FloatProperty(
        name="X0 Scale", default=1.0, min=0.05, max=3.0, update=_preview_update
    )  # type: ignore
    shoulderZ1Scale: FloatProperty(
        name="Z1 Scale", default=1.0, min=0.05, max=3.0, update=_preview_update
    )  # type: ignore
    shoulderZ0Scale: FloatProperty(
        name="Z0 Scale", default=1.0, min=0.05, max=3.0, update=_preview_update
    )  # type: ignore
    showShoulderParameters: BoolProperty(default=False)  # type: ignore


CLASSES = (PG_HoAuxBoneInfo, PG_HoAuxSettings)


def ensure_rig_id(armature_data) -> str:
    rig_id = getattr(armature_data, "hoaux_rig_id", "")
    if not rig_id:
        rig_id = uuid4().hex
        armature_data.hoaux_rig_id = rig_id
    return rig_id


def register_rna():
    bpy.types.Armature.hoaux_schema_version = IntProperty(
        name="HoAux Schema Version",
        default=SCHEMA_VERSION,
        min=1,
    )
    bpy.types.Armature.hoaux_rig_id = StringProperty(
        name="HoAux Rig ID",
        default="",
    )
    bpy.types.Scene.hoaux_overview_expanded = BoolProperty(
        name="HoAux Overview",
        default=True,
    )
    bpy.types.Scene.hoaux_settings = PointerProperty(type=PG_HoAuxSettings)


def unregister_rna():
    for owner, name in (
        (bpy.types.Scene, "hoaux_overview_expanded"),
        (bpy.types.Scene, "hoaux_settings"),
        (bpy.types.Armature, "hoaux_rig_id"),
        (bpy.types.Armature, "hoaux_schema_version"),
    ):
        if hasattr(owner, name):
            delattr(owner, name)
