"""Adapt HoTools' operator parameters to the pinned FBX backend."""


def export_fbx(operator, context, **parameters):
    from bpy_extras.io_utils import axis_conversion
    from mathutils import Matrix
    from ._vendor import export_fbx_bin

    if not parameters.get("filepath"):
        raise ValueError("FBX filepath is not set")

    # Match the official ExportFBX.execute boundary, including its axis matrix.
    # Keep the existing HoTools operator, selection and undo transaction.
    keywords = dict(parameters)
    for name in ("check_existing", "filter_glob", "ui_tab"):
        keywords.pop(name, None)
    keywords["global_matrix"] = (
        axis_conversion(
            to_forward=keywords.get("axis_forward", "-Z"),
            to_up=keywords.get("axis_up", "Y"),
        ).to_4x4()
        if keywords.get("use_space_transform", True)
        else Matrix()
    )
    return export_fbx_bin.save(operator, context, **keywords)
