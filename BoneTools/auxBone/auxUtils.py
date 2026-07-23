"""Shared helpers for auxiliary-bone viewport previews."""

import bpy
import blf
import gpu
import math
from gpu_extras.batch import batch_for_shader


class AuxPreviewUtils:
    """Static viewport plumbing shared by aux preview implementations."""

    @staticmethod
    def safe_normalized_vector(vector, epsilon=1e-6):
        if vector.length < epsilon:
            return None
        return vector.normalized()

    @staticmethod
    def clamp(value, minimum, maximum):
        return max(minimum, min(maximum, value))

    @staticmethod
    def rotate_vector_around_axis(vector, axis, angle_rad, epsilon=1e-6):
        axis = AuxPreviewUtils.safe_normalized_vector(axis, epsilon)
        if axis is None:
            return None
        return (
            vector * math.cos(angle_rad)
            + axis.cross(vector) * math.sin(angle_rad)
            + axis * axis.dot(vector) * (1.0 - math.cos(angle_rad))
        )

    @staticmethod
    def set_aux_bone_props(armature, bone_names, aux_type="NONE", source_bones=None):
        """Write the shared HoTools metadata carried by generated aux bones."""
        source_bones = source_bones or []
        for bone_name in bone_names:
            bone = armature.data.bones.get(bone_name)
            props = getattr(bone, "hotools_boneprops", None) if bone else None
            if not props:
                continue
            if hasattr(props, "generateMCH"):
                props.generateMCH = False
            aux = getattr(props, "auxBone", None)
            if aux is None or aux_type == "NONE":
                continue
            aux.isAuxBone = True
            aux.auxType = aux_type
            aux.sourceBones.clear()
            for source_name in source_bones:
                if source_name:
                    ref = aux.sourceBones.add()
                    ref.name = source_name

    @staticmethod
    def tag_redraw():
        wm = getattr(bpy.context, "window_manager", None)
        if wm is None:
            return
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    @staticmethod
    def find_view3d_region(context=None):
        context = context or bpy.context
        windows = []
        window = getattr(context, "window", None)
        if window is not None and window.screen is not None:
            windows.append(window)
        wm = getattr(context, "window_manager", None)
        if wm is not None:
            windows.extend(item for item in wm.windows if item not in windows)
        for window in windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for region in area.regions:
                    if region.type != "WINDOW":
                        continue
                    for space in area.spaces:
                        if space.type == "VIEW_3D" and space.region_3d is not None:
                            return window, region, space.region_3d
        return None

    @staticmethod
    def ensure_handlers(preview, draw_3d, draw_2d):
        if preview._handler_3d is None:
            preview._handler_3d = bpy.types.SpaceView3D.draw_handler_add(
                draw_3d, (), "WINDOW", "POST_VIEW"
            )
        if preview._handler_2d is None:
            preview._handler_2d = bpy.types.SpaceView3D.draw_handler_add(
                draw_2d, (), "WINDOW", "POST_PIXEL"
            )

    @staticmethod
    def remove_handlers(preview):
        if preview._handler_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(preview._handler_3d, "WINDOW")
        if preview._handler_2d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(preview._handler_2d, "WINDOW")
        preview._handler_3d = None
        preview._handler_2d = None

    @staticmethod
    def draw_lines(shader, coordinates, color, primitive="LINES"):
        """Draw a batch of 3D or 2D line coordinates with a shared shader."""
        if not coordinates:
            return
        shader.bind()
        shader.uniform_float("color", color)
        batch_for_shader(shader, primitive, {"pos": coordinates}).draw(shader)

    @staticmethod
    def append_circle(target, center, axis_x, axis_y, radius, segments=64, epsilon=1e-6):
        """Append a 3D circle as line-pair coordinates to ``target``."""
        if radius <= epsilon:
            return
        previous = center + axis_x * radius
        for index in range(1, segments + 1):
            angle = math.tau * index / segments
            point = (
                center
                + axis_x * math.cos(angle) * radius
                + axis_y * math.sin(angle) * radius
            )
            target.extend((tuple(previous), tuple(point)))
            previous = point

    @staticmethod
    def draw_points(shader, coordinates, color, size=6.0):
        """Draw preview points while restoring Blender's point-size state."""
        if not coordinates:
            return
        gpu.state.point_size_set(size)
        try:
            AuxPreviewUtils.draw_lines(shader, coordinates, color, "POINTS")
        finally:
            gpu.state.point_size_set(1.0)

    @staticmethod
    def draw_label(font_id, text, position, color, size=15, shadow=True):
        """Draw a consistent viewport label for an aux preview."""
        blf.size(font_id, size)
        if shadow:
            blf.enable(font_id, blf.SHADOW)
            blf.shadow(font_id, 3, 0, 0, 0, 0.75)
            blf.shadow_offset(font_id, 1, -1)
        blf.color(font_id, *color)
        blf.position(font_id, position[0], position[1], 0.0)
        blf.draw(font_id, text)
        if shadow:
            blf.disable(font_id, blf.SHADOW)
