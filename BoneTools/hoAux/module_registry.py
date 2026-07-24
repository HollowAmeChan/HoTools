"""Registration and lookup for self-contained HoAux module definitions."""

import bpy
from bpy.props import PointerProperty

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
