"""HoFBX public entry points. See README.md for the export flow."""

from .operator import (
    FBXExporter,
    HO_MT_FBXExportPresets,
    MCH_BONE_COLLECTION_NAME,
    OP_AddFBXExportPreset,
    OP_FinalFBXExport,
    OPF_FinalFBXExport,
    register,
    unregister,
)


def __getattr__(name):
    # Preserve access to legacy diagnostic helpers and module state.
    from . import operator
    return getattr(operator, name)
