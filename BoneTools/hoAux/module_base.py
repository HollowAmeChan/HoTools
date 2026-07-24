"""Small UI and preview conventions shared by self-contained HoAux modules."""


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
        column.prop(root, "side", expand=True)
        for property_name, label in self.required_roles:
            column.prop_search(
                root,
                property_name,
                obj.data,
                "bones",
                text=label,
            )
        for property_names in self.parameter_rows:
            row = column.row(align=True)
            for property_name in property_names:
                row.prop(settings, property_name)
