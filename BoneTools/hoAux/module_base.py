"""Small UI and preview conventions shared by self-contained HoAux modules."""

try:
    from ..boneUtils import BoneUtils
except ImportError:
    from boneUtils import BoneUtils


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
    from .transaction import restore_armature_mode

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
