"""Minimal persistent identity and ownership metadata for HoAux bones."""

from uuid import uuid4

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


SCHEMA_VERSION = 1


def _preview_update(_self, context):
    from .preview import refresh_active_preview

    refresh_active_preview(context)


def _pipeline_preview_update(self, context):
    from .preview import set_pipeline_preview_enabled

    set_pipeline_preview_enabled(context, self.pipelinePreviewEnabled)


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


class PG_HoAuxGroupState(PropertyGroup):
    name: StringProperty(default="")  # type: ignore
    expanded: BoolProperty(default=True)  # type: ignore


class PG_HoAuxSettings(PropertyGroup):
    pipelineExpanded: BoolProperty(name="整臂流水线", default=True)  # type: ignore
    pipelinePreviewEnabled: BoolProperty(
        name="预览整臂流水线",
        default=False,
        update=_pipeline_preview_update,
    )  # type: ignore
    processSymmetry: BoolProperty(
        name="同时处理对称侧",
        description="同时预览并生成严格匹配的对侧角色骨",
        default=False,
        update=_preview_update,
    )  # type: ignore
    shoulderBone: StringProperty(default="", update=_preview_update)  # type: ignore
    upperArmBone: StringProperty(default="", update=_preview_update)  # type: ignore
    lowerArmBone: StringProperty(default="", update=_preview_update)  # type: ignore
    handBone: StringProperty(default="", update=_preview_update)  # type: ignore


CLASSES = (
    PG_HoAuxBoneInfo,
    PG_HoAuxGroupState,
    PG_HoAuxSettings,
)


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
    bpy.types.Armature.hoaux_group_states = CollectionProperty(
        type=PG_HoAuxGroupState
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
        (bpy.types.Armature, "hoaux_group_states"),
        (bpy.types.Armature, "hoaux_schema_version"),
    ):
        if hasattr(owner, name):
            delattr(owner, name)
