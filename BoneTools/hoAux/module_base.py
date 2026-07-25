"""Small UI and preview conventions shared by self-contained HoAux modules."""

from dataclasses import dataclass

import bpy
from bpy.props import PointerProperty
from mathutils import Vector

try:
    from ..boneUtils import BoneUtils
except ImportError:
    from boneUtils import BoneUtils


@dataclass(frozen=True)
class PlannedBone:
    resource_key: str
    preferred_name: str
    role_tag: str
    marker: str
    head: Vector
    tail: Vector
    roll_reference: Vector
    parent_name: str


def require_side(expected_side, *bone_names):
    return BoneUtils.require_same_side(*bone_names, expected=expected_side)


def mirrored_role_names(armature_data, *bone_names):
    return BoneUtils.mirrored_role_names(armature_data, *bone_names)


def role_name_sets(context, *bone_names):
    side = require_side(None, *bone_names)
    result = [(tuple(bone_names), side)]
    if context.scene.hoaux_settings.processSymmetry:
        mirrored = mirrored_role_names(context.object.data, *bone_names)
        result.append((mirrored, require_side(None, *mirrored)))
    return result


def generate_role_sets(
    context,
    module_type,
    bone_names,
    preflight_one,
    generate_one,
):
    from .operations import remove_scope
    from .generation import restore_armature_mode

    role_sets = role_name_sets(context, *bone_names)
    for names, side in role_sets:
        preflight_one(names, side)

    original_mode = context.object.mode
    results = []
    try:
        for names, side in role_sets:
            results.append(generate_one(names, side))
    except Exception:
        for _names, side in role_sets[: len(results)]:
            remove_scope(
                context.object,
                f"ARM.{side}",
                f"{module_type}.{side}",
            )
        raise
    finally:
        restore_armature_mode(context.object, original_mode)

    created_dir_count = sum(int(result.get("createdDir", False)) for result in results)
    merged = dict(results[0])
    merged["bones"] = [
        bone_name for result in results for bone_name in result.get("bones", ())
    ]
    merged["createdDir"] = created_dir_count > 0
    merged["createdDirCount"] = created_dir_count
    merged["sideResults"] = results
    return merged


def refresh_preview(_self, context):
    from .preview import refresh_active_preview

    refresh_active_preview(context)


def preview_toggle(module_type):
    def _toggle(self, context):
        from .preview import set_module_preview_enabled

        set_module_preview_enabled(context, module_type, self.preview_enabled)

    return _toggle


class ModuleDefinition:
    type_id = ""
    label = ""
    order = 0
    settings_class = None
    settings_attr = ""
    required_roles = ()
    parameter_rows = ()

    def settings(self, scene):
        return getattr(scene, self.settings_attr)

    def draw_panel(self, layout, context):
        root = context.scene.hoaux_settings
        settings = self.settings(context.scene)
        obj = context.object
        box = layout.box()
        header = box.row(align=True)
        header.prop(
            settings,
            "ui_expanded",
            text="",
            icon="TRIA_DOWN" if settings.ui_expanded else "TRIA_RIGHT",
            emboss=False,
        )
        header.label(text=self.label)
        generate_button = header.operator("hoaux.generate_module", text="生成")
        generate_button.module_type = self.type_id
        preview_row = header.row(align=True)
        preview_row.alert = settings.preview_enabled
        preview_row.prop(
            settings,
            "preview_enabled",
            text="",
            icon="HIDE_OFF" if settings.preview_enabled else "HIDE_ON",
        )
        if not settings.ui_expanded:
            return

        column = box.column(align=True)
        for property_name, label in self.required_roles:
            column.prop_search(
                root,
                property_name,
                obj.data,
                "bones",
                text=label,
            )
        column.prop(root, "processSymmetry")
        for property_names in self.parameter_rows:
            row = column.row(align=True)
            for property_name in property_names:
                row.prop(settings, property_name)


from .modules import DEFINITIONS


def _build_index():
    result = {}
    for definition in DEFINITIONS:
        for attribute in (
            "type_id",
            "label",
            "order",
            "settings_class",
            "settings_attr",
            "generate_from_context",
            "build_preview_scene",
        ):
            if not getattr(definition, attribute, None):
                raise TypeError(
                    f"HoAux module {definition!r} is missing {attribute}"
                )
        if definition.type_id in result:
            raise ValueError(f"重复 HoAux 模块类型：{definition.type_id}")
        result[definition.type_id] = definition
    return result


_BY_TYPE = _build_index()


def definitions():
    return tuple(sorted(DEFINITIONS, key=lambda definition: definition.order))


def get_definition(module_type):
    try:
        return _BY_TYPE[module_type]
    except KeyError as exc:
        raise ValueError(f"未知 HoAux 模块类型：{module_type}") from exc


def register_rna():
    for definition in definitions():
        bpy.utils.register_class(definition.settings_class)
        setattr(
            bpy.types.Scene,
            definition.settings_attr,
            PointerProperty(type=definition.settings_class),
        )


def unregister_rna():
    for definition in reversed(definitions()):
        if hasattr(bpy.types.Scene, definition.settings_attr):
            delattr(bpy.types.Scene, definition.settings_attr)
        bpy.utils.unregister_class(definition.settings_class)
