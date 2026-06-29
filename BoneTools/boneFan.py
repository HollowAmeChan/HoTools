import bpy
from bpy.types import Context, Operator, PropertyGroup, UILayout
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty, PointerProperty
from math import acos, atan2, cos, radians, sin, tau
from mathutils import Vector

from .boneSplit import BoneSplitCore
from .boneTwist import TwistBoneCore
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
import blf


EPS = 1e-6
HoRig_Fan = "HoRig_Fan"


def reg_props():
    if hasattr(bpy.types.Scene, "ho_fan_settings"):
        del bpy.types.Scene.ho_fan_settings
    bpy.types.Scene.ho_fan_settings = PointerProperty(type=PG_Hotools_FanSettings)


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_fan_settings"):
        del bpy.types.Scene.ho_fan_settings


def _safe_normalized_vector(vector):
    if vector.length < EPS:
        return None
    return vector.normalized()


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _fan_preview_update(self, context):
    if context is None:
        return

    scene = getattr(context, "scene", None)
    settings = getattr(scene, "ho_fan_settings", None) if scene is not None else None
    if settings is None:
        return

    if settings.preview_enabled:
        BoneFanPreview.show(context)
    else:
        BoneFanPreview.clear()


def _draw_fan_preview():
    BoneFanPreview._draw_3d()


class PG_Hotools_FanSettings(PropertyGroup):
    ui_expanded: BoolProperty(
        name="fan settings",
        description="show fan generation settings",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    preview_enabled: BoolProperty(
        name="preview",
        description="draw fan preview in 3D view",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    generate_in: BoolProperty(
        name="generate in",
        description="generate in-side fan bones",
        default=True,
        update=_fan_preview_update,
    )  # type: ignore
    generate_out: BoolProperty(
        name="generate out",
        description="generate out-side fan bones",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    count_in: IntProperty(
        name="in count",
        description="number of in-side fan bones, must be even",
        default=2,
        min=2,
        update=_fan_preview_update,
    )  # type: ignore
    count_out: IntProperty(
        name="out count",
        description="number of out-side fan bones, must be even",
        default=2,
        min=2,
        update=_fan_preview_update,
    )  # type: ignore
    length_factor: FloatProperty(
        name="length factor",
        description="fan bone length ratio relative to the joint-side length",
        default=0.2,
        min=0.01,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    pin_length_factor: FloatProperty(
        name="pin length factor",
        description="fanPin length ratio relative to fan length",
        default=0.2 / 5.0,
        min=0.001,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    auto_transfer_weights: BoolProperty(
        name="auto transfer weights",
        description="transfer fan weights from the source main bones",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    only_selected: BoolProperty(
        name="only selected objects",
        description="only process selected mesh objects",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    fan_weight_radius: FloatProperty(
        name="fan weight radius",
        description="weight transfer radius relative to the joint-side length",
        default=0.12,
        min=0.0,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    fan_weight_blur: FloatProperty(
        name="fan weight blur",
        description="weight transfer blur relative to the radius",
        default=0.5,
        min=0.0,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    bone_collection_name: StringProperty(
        name="bone collection",
        description="collection name for generated fan bones",
        default=HoRig_Fan,
        update=_fan_preview_update,
    )  # type: ignore


def _ensure_bone_collection(armature: bpy.types.Object, collection_name: str):
    if not collection_name:
        return None

    collections = getattr(armature.data, "collections", None)
    if collections is None:
        return None

    collection = collections.get(collection_name)
    if collection is None:
        collection = collections.new(collection_name)
    return collection


def _assign_bones_to_collection(
    armature: bpy.types.Object,
    bone_names: list[str],
    collection_name: str,
) -> None:
    collection = _ensure_bone_collection(armature, collection_name)
    if collection is None:
        return

    edit_bones = armature.data.edit_bones
    for bone_name in bone_names:
        bone = edit_bones.get(bone_name)
        if bone is None:
            continue
        for old_collection in list(bone.collections):
            old_collection.unassign(bone)
        collection.assign(bone)


def drawBoneFanPanel(layout: UILayout, context: Context):
    settings = context.scene.ho_fan_settings
    fan_box = layout.box()

    header = fan_box.row(align=True)
    header.prop(
        settings,
        "ui_expanded",
        text="",
        icon="TRIA_DOWN" if settings.ui_expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text="fan")
    header.prop(
        settings,
        "preview_enabled",
        text="",
        icon="HIDE_OFF" if settings.preview_enabled else "HIDE_ON",
    )

    if not settings.ui_expanded:
        return

    col = fan_box.column(align=True)
    row = col.row(align=True)
    row.operator(OP_FanGenerate.bl_idname, text="fan add")
    row.operator(OP_RemoveFanBone.bl_idname, text="remove fan")

    col.separator()
    row = col.row(align=True)
    row.prop(settings, "generate_in", toggle=True)
    sub = row.row(align=True)
    sub.enabled = settings.generate_in
    sub.prop(settings, "count_in")

    row = col.row(align=True)
    row.prop(settings, "generate_out", toggle=True)
    sub = row.row(align=True)
    sub.enabled = settings.generate_out
    sub.prop(settings, "count_out")

    col.separator()
    col.prop(settings, "length_factor")
    col.prop(settings, "pin_length_factor")
    col.prop(settings, "bone_collection_name")
    col.prop(settings, "auto_transfer_weights")

    sub = col.column(align=True)
    sub.enabled = settings.auto_transfer_weights
    sub.prop(settings, "only_selected")
    sub.prop(settings, "fan_weight_radius")
    sub.prop(settings, "fan_weight_blur")


class BoneFanPreview:
    _handler_3d = None
    _timer_running = False
    _timer_interval = 0.08
    _state = None

    @classmethod
    def ensure_handler(cls):
        if cls._handler_3d is not None:
            return

        cls._handler_3d = bpy.types.SpaceView3D.draw_handler_add(
            _draw_fan_preview,
            (),
            "WINDOW",
            "POST_VIEW",
        )

    @classmethod
    def show(cls, context):
        cls.ensure_handler()
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "ho_fan_settings", None) if scene is not None else None
        if settings is None or not settings.preview_enabled:
            return

        armature = context.active_object
        region_owner = cls._find_view3d_region(context)
        region = None
        region_data = None
        if region_owner is not None:
            _, region, region_data = region_owner

        state = {
            "armature_name": "",
            "frame": None,
            "message": "",
            "region": region,
            "region_data": region_data,
        }

        if armature is None or armature.type != "ARMATURE":
            state["message"] = "preview requires an armature"
        else:
            selected_bones = BoneFanCore._selected_bones(context, armature)
            if len(selected_bones) != 2:
                state["message"] = "select exactly two bones"
            else:
                bone_a, bone_b = selected_bones
                frame, error = BoneFanCore._resolve_joint_geometry(bone_a, bone_b)
                if error:
                    state["message"] = error
                else:
                    state["armature_name"] = armature.name
                    state["frame"] = frame

        cls._state = state
        if not cls._timer_running:
            cls._timer_running = True
            bpy.app.timers.register(cls._timer)
        cls._tag_redraw()

    @classmethod
    def clear(cls):
        cls._state = None
        cls._timer_running = False
        cls._tag_redraw()

    @classmethod
    def shutdown(cls):
        if cls._handler_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handler_3d, "WINDOW")
        cls._handler_3d = None
        cls._state = None
        cls._timer_running = False

    @classmethod
    def _timer(cls):
        if cls._handler_3d is None:
            cls._timer_running = False
            return None

        settings = getattr(getattr(bpy.context, "scene", None), "ho_fan_settings", None)
        if settings is not None and settings.preview_enabled:
            cls.show(bpy.context)
            return cls._timer_interval

        if cls._state is None:
            cls._timer_running = False
            return None

        cls._tag_redraw()
        return cls._timer_interval

    @staticmethod
    def _tag_redraw():
        wm = bpy.context.window_manager
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
    def _find_view3d_region(context=None):
        if context is None:
            context = bpy.context
        windows = []

        if context.window is not None and context.window.screen is not None:
            windows.append(context.window)

        wm = context.window_manager
        if wm is not None:
            for window in wm.windows:
                if window not in windows:
                    windows.append(window)

        for window in windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for region in area.regions:
                    if region.type == "WINDOW":
                        for space in area.spaces:
                            if space.type == "VIEW_3D":
                                rv3d = space.region_3d
                                if rv3d is not None:
                                    return window, region, rv3d
        return None, None, None

    @classmethod
    def _draw_3d(cls):
        state = cls._state
        if state is None:
            return

        message = state.get("message", "")
        armature = bpy.data.objects.get(state.get("armature_name", ""))

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        gpu.state.line_width_set(2.0)
        gpu.state.point_size_set(8.0)
        try:
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            font_id = 0
            blf.size(font_id, 14)
            blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
            blf.position(font_id, 20.0, 20.0, 0.0)
            if message:
                blf.draw(font_id, f"fan preview: {message}")
                return

            if armature is None or armature.type != "ARMATURE":
                blf.draw(font_id, "fan preview")
                return

            frame = state.get("frame")
            if frame is None:
                blf.draw(font_id, "fan preview")
                return

            joint_world = armature.matrix_world @ frame["joint"]
            plane_normal_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["plane_normal"])
            axis_a_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["parent_dir"])
            if axis_a_world is None:
                axis_a_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["child_dir"])
            if plane_normal_world is None or axis_a_world is None:
                blf.draw(font_id, "fan preview")
                return

            axis_a_world = axis_a_world - plane_normal_world * axis_a_world.dot(plane_normal_world)
            axis_a_world = _safe_normalized_vector(axis_a_world)
            if axis_a_world is None:
                blf.draw(font_id, "fan preview")
                return

            axis_b_world = _safe_normalized_vector(plane_normal_world.cross(axis_a_world))
            if axis_b_world is None:
                blf.draw(font_id, "fan preview")
                return

            settings = getattr(bpy.context.scene, "ho_fan_settings", None)
            radius_factor = float(getattr(settings, "fan_weight_radius", 0.5)) if settings is not None else 0.5
            blur_factor = float(getattr(settings, "fan_weight_blur", 0.25)) if settings is not None else 0.25
            radius = max(frame["base_length"] * radius_factor, 0.0)
            blur = max(radius * blur_factor, 0.0)
            if radius <= EPS:
                blf.draw(font_id, "fan preview")
                return

            def _append_circle_3d(target, center, axis_x, axis_y, ring_radius, segments=64):
                if ring_radius <= EPS:
                    return
                previous = center + axis_x * ring_radius
                for index in range(1, segments + 1):
                    angle = tau * index / segments
                    point = center + axis_x * cos(angle) * ring_radius + axis_y * sin(angle) * ring_radius
                    target.extend([tuple(previous), tuple(point)])
                    previous = point

            lines = []
            points = [tuple(joint_world)]
            in_spokes = []
            out_spokes = []

            total_angle = float(frame["angle_rad"])
            parent_dir_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["parent_dir"])
            child_dir_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["child_dir"])
            if parent_dir_world is None or child_dir_world is None:
                blf.draw(font_id, "fan preview")
                return

            center_dir_world = _safe_normalized_vector(parent_dir_world + child_dir_world)
            if center_dir_world is None:
                center_dir_world = parent_dir_world

            _, center_axis_world, side_axis_world = BoneFanCore._classify_fan_sector(
                center_dir_world,
                parent_dir_world,
                child_dir_world,
                plane_normal_world,
            )
            if center_axis_world is None or side_axis_world is None:
                blf.draw(font_id, "fan preview")
                return

            def _append_sector_disk(target_map: dict[str, list[tuple[float, float, float]]], center, axis_x, axis_y, ring_radius, segments=96):
                if ring_radius <= EPS:
                    return
                ring_points = []
                for index in range(segments):
                    angle = tau * index / segments
                    ring_points.append(
                        center
                        + axis_x * cos(angle) * ring_radius
                        + axis_y * sin(angle) * ring_radius
                    )
                for index in range(segments):
                    p0 = ring_points[index]
                    p1 = ring_points[(index + 1) % segments]
                    mid_dir = _safe_normalized_vector((p0 - center) + (p1 - center))
                    if mid_dir is None:
                        continue
                    sector_name, _, _ = BoneFanCore._classify_fan_sector(
                        mid_dir,
                        parent_dir_world,
                        child_dir_world,
                        plane_normal_world,
                    )
                    if sector_name is None:
                        continue
                    target_map[sector_name].extend([tuple(center), tuple(p0), tuple(p1)])

            center_spokes = [
                tuple(joint_world),
                tuple(joint_world + center_dir_world * radius),
                tuple(joint_world),
                tuple(joint_world - center_dir_world * radius),
            ]

            sphere_lines = []
            blur_lines = []
            sector_fills: dict[str, list[tuple[float, float, float]]] = {
                "inup": [],
                "indown": [],
                "outup": [],
                "outdown": [],
            }
            if getattr(settings, "auto_transfer_weights", False):
                _append_sector_disk(sector_fills, joint_world, axis_a_world, axis_b_world, radius)
                _append_circle_3d(sphere_lines, joint_world, axis_a_world, axis_b_world, radius)
                _append_circle_3d(sphere_lines, joint_world, axis_a_world, plane_normal_world, radius)
                _append_circle_3d(sphere_lines, joint_world, axis_b_world, plane_normal_world, radius)
                if blur > EPS:
                    blur_radius = radius + blur
                    _append_circle_3d(blur_lines, joint_world, axis_a_world, axis_b_world, blur_radius)
                    _append_circle_3d(blur_lines, joint_world, axis_a_world, plane_normal_world, blur_radius)
                    _append_circle_3d(blur_lines, joint_world, axis_b_world, plane_normal_world, blur_radius)

            if getattr(settings, "generate_in", False):
                in_count = max(1, int(getattr(settings, "count_in", 1)))
                step = total_angle / (in_count + 1)
                start_dir = -parent_dir_world
                for index in range(1, in_count + 1):
                    direction = BoneFanCore._rotate_vector_around_axis(start_dir, plane_normal_world, step * index)
                    if direction is None:
                        continue
                    in_spokes.extend([tuple(joint_world), tuple(joint_world + direction * radius)])

            if getattr(settings, "generate_out", False):
                out_count = max(1, int(getattr(settings, "count_out", 1)))
                step = total_angle / (out_count + 1)
                start_dir = parent_dir_world
                for index in range(1, out_count + 1):
                    direction = BoneFanCore._rotate_vector_around_axis(start_dir, plane_normal_world, step * index)
                    if direction is None:
                        continue
                    out_spokes.extend([tuple(joint_world), tuple(joint_world + direction * radius)])

            shader.bind()

            if getattr(settings, "auto_transfer_weights", False):
                sector_colors = {
                    "inup": (1.0, 0.35, 0.2, 0.28),
                    "indown": (1.0, 0.85, 0.2, 0.28),
                    "outup": (0.25, 0.9, 0.55, 0.28),
                    "outdown": (0.2, 0.75, 1.0, 0.28),
                }
                for sector_name, positions in sector_fills.items():
                    if len(positions) < 3:
                        continue
                    sector_batch = batch_for_shader(shader, "TRIS", {"pos": positions})
                    shader.uniform_float("color", sector_colors[sector_name])
                    sector_batch.draw(shader)

            if sphere_lines:
                line_batch = batch_for_shader(shader, "LINES", {"pos": sphere_lines})
                shader.uniform_float("color", (0.2, 0.9, 1.0, 0.95))
                line_batch.draw(shader)

            if blur_lines:
                blur_batch = batch_for_shader(shader, "LINES", {"pos": blur_lines})
                shader.uniform_float("color", (0.45, 0.45, 0.45, 0.8))
                blur_batch.draw(shader)

            if len(center_spokes) >= 2:
                center_batch = batch_for_shader(shader, "LINES", {"pos": center_spokes})
                shader.uniform_float("color", (0.95, 0.95, 0.95, 0.85))
                center_batch.draw(shader)

            if len(in_spokes) >= 2:
                in_batch = batch_for_shader(shader, "LINES", {"pos": in_spokes})
                shader.uniform_float("color", (1.0, 0.72, 0.2, 0.95))
                in_batch.draw(shader)

            if len(out_spokes) >= 2:
                out_batch = batch_for_shader(shader, "LINES", {"pos": out_spokes})
                shader.uniform_float("color", (0.35, 0.95, 0.55, 0.95))
                out_batch.draw(shader)

            point_batch = batch_for_shader(shader, "POINTS", {"pos": points})
            shader.uniform_float("color", (1.0, 0.65, 0.15, 1.0))
            point_batch.draw(shader)

            blf.draw(font_id, "fan preview")
        finally:
            gpu.state.point_size_set(1.0)
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")


class BoneFanCore:
    @staticmethod
    def _selected_bones(context: Context, armature: bpy.types.Object):
        if armature.mode == "POSE":
            pose_bones = getattr(context, "selected_pose_bones_from_active_object", None)
            if pose_bones is None:
                pose_bones = context.selected_pose_bones or []
            return [pose_bone for pose_bone in pose_bones if getattr(pose_bone, "bone", None) is not None]

        if armature.mode == "EDIT":
            return [bone for bone in armature.data.edit_bones if bone.select]

        return []

    @staticmethod
    def _fan_name(base_name: str, fan_kind: str, index: int, padding: int) -> str:
        stem, side_suffix = TwistBoneCore._split_side_suffix(base_name)
        marker = "_fan_in_" if fan_kind == "in" else "_fan_out_"
        return f"{stem}{marker}{index:0{padding}d}{side_suffix}"

    @staticmethod
    def _fan_pin_name(base_name: str, fan_kind: str, index: int, padding: int) -> str:
        stem, side_suffix = TwistBoneCore._split_side_suffix(base_name)
        marker = "_fan_pin_in_" if fan_kind == "in" else "_fan_pin_out_"
        return f"{stem}{marker}{index:0{padding}d}{side_suffix}"

    @staticmethod
    def _parse_fan_name(name: str):
        stem, side_suffix = TwistBoneCore._split_side_suffix(name)
        for fan_kind, marker in (("in", "_fan_in_"), ("out", "_fan_out_")):
            marker_index = stem.rfind(marker)
            if marker_index < 0:
                continue

            index_text = stem[marker_index + len(marker):]
            if not index_text.isdigit():
                continue

            base_stem = stem[:marker_index]
            if not base_stem:
                continue

            return {
                "base_name": f"{base_stem}{side_suffix}",
                "fan_kind": fan_kind,
                "index": int(index_text),
            }

        return None

    @staticmethod
    def _parse_fan_pin_name(name: str):
        stem, side_suffix = TwistBoneCore._split_side_suffix(name)
        for fan_kind, marker in (("in", "_fan_pin_in_"), ("out", "_fan_pin_out_")):
            marker_index = stem.rfind(marker)
            if marker_index < 0:
                continue

            index_text = stem[marker_index + len(marker):]
            if not index_text.isdigit():
                continue

            base_stem = stem[:marker_index]
            if not base_stem:
                continue

            return {
                "base_name": f"{base_stem}{side_suffix}",
                "fan_kind": fan_kind,
                "index": int(index_text),
            }

        return None

    @staticmethod
    def _rotate_vector_around_axis(vector, axis, angle_rad):
        axis = _safe_normalized_vector(axis)
        if axis is None:
            return None

        return (
            vector * cos(angle_rad)
            + axis.cross(vector) * sin(angle_rad)
            + axis * axis.dot(vector) * (1.0 - cos(angle_rad))
        )

    @staticmethod
    def _selected_bone_names(context: Context, armature: bpy.types.Object) -> list[str]:
        if armature.mode == "POSE":
            pose_bones = getattr(context, "selected_pose_bones_from_active_object", None)
            if pose_bones is None:
                pose_bones = context.selected_pose_bones or []
            return [bone.name for bone in pose_bones if getattr(bone, "name", None)]
        if armature.mode == "EDIT":
            return [bone.name for bone in armature.data.edit_bones if bone.select]
        return []

    @staticmethod
    def _resolve_joint_geometry(bone_a, bone_b):
        tolerance = 1e-3

        def _bone_points(bone):
            if hasattr(bone, "head") and hasattr(bone, "tail"):
                return bone.head, bone.tail
            if hasattr(bone, "bone") and hasattr(bone, "matrix"):
                rest_bone = bone.bone
                head = bone.matrix.translation
                tail = bone.matrix @ Vector((0.0, rest_bone.length, 0.0))
                return head, tail
            raise Exception("unsupported bone type")

        a_head, a_tail = _bone_points(bone_a)
        b_head, b_tail = _bone_points(bone_b)

        bone_a_parent = getattr(bone_a, "parent", None)
        bone_b_parent = getattr(bone_b, "parent", None)

        if bone_b_parent == bone_a:
            parent_bone = bone_a
            child_bone = bone_b
        elif bone_a_parent == bone_b:
            parent_bone = bone_b
            child_bone = bone_a
        elif (a_tail - b_head).length <= tolerance:
            parent_bone = bone_a
            child_bone = bone_b
        elif (b_tail - a_head).length <= tolerance:
            parent_bone = bone_b
            child_bone = bone_a
        else:
            return None, "two bones must be connected"

        parent_head, parent_tail = _bone_points(parent_bone)
        child_head, child_tail = _bone_points(child_bone)

        if (parent_tail - child_head).length <= tolerance:
            joint = (parent_tail + child_head) * 0.5
        else:
            joint = child_head.copy() if (child_head - parent_tail).length < (parent_tail - child_head).length else parent_tail.copy()

        parent_dir = _safe_normalized_vector(parent_head - joint)
        child_dir = _safe_normalized_vector(child_tail - joint)
        if parent_dir is None or child_dir is None:
            return None, "bone length too short"

        dot = _clamp(parent_dir.dot(child_dir), -1.0, 1.0)
        angle_rad = acos(dot)
        if angle_rad <= radians(1.0) or angle_rad >= radians(179.0):
            return None, "joint angle too small or too straight"

        plane_normal = _safe_normalized_vector(parent_dir.cross(child_dir))
        if plane_normal is None:
            return None, "failed to compute plane normal"

        parent_length = (parent_head - joint).length
        child_length = (child_tail - joint).length

        return {
            "parent_bone": parent_bone,
            "child_bone": child_bone,
            "joint": joint,
            "parent_dir": parent_dir,
            "child_dir": child_dir,
            "plane_normal": plane_normal,
            "angle_rad": angle_rad,
            "base_length": min(parent_length, child_length),
        }, None

    @staticmethod
    def _choose_parent_bone(direction, a_bone, a_dir, b_bone, b_dir):
        score_a = direction.dot(a_dir)
        score_b = direction.dot(b_dir)
        if abs(score_a - score_b) < 1e-6:
            return a_bone
        return a_bone if score_a > score_b else b_bone

    @staticmethod
    def _apply_hotools_bone_props(armature: bpy.types.Object, bone_names: list[str]) -> None:
        for bone_name in bone_names:
            bone = armature.data.bones.get(bone_name)
            props = getattr(bone, "hotools_boneprops", None) if bone else None
            if props and hasattr(props, "keepRotation"):
                props.keepRotation = False
            if props and hasattr(props, "humanoidMapping"):
                props.humanoidMapping = bone_name

    @staticmethod
    def _smooth_falloff(value: float, start_value: float, end_value: float) -> float:
        if end_value <= start_value + EPS:
            return 1.0 if value <= start_value else 0.0

        t = _clamp((value - start_value) / (end_value - start_value), 0.0, 1.0)
        return 1.0 - (t * t * (3.0 - 2.0 * t))

    @staticmethod
    def _validate_fan_count(fan_kind: str, count: int) -> None:
        if count < 2 or count % 2 != 0:
            raise Exception(f"{fan_kind} fan count must be an even number >= 2")
    
    @staticmethod
    def _classify_fan_sector(
        vec: Vector,
        parent_dir_world: Vector,
        child_dir_world: Vector,
        plane_normal_world: Vector,
    ) -> tuple[str | None, Vector | None, Vector | None]:
        center_axis_world = _safe_normalized_vector(parent_dir_world + child_dir_world)
        if center_axis_world is None:
            center_axis_world = _safe_normalized_vector(parent_dir_world)
        if center_axis_world is None:
            return None, None, None

        side_axis_world = _safe_normalized_vector(plane_normal_world.cross(center_axis_world))
        if side_axis_world is None:
            side_axis_world = _safe_normalized_vector(center_axis_world.cross(plane_normal_world))
        if side_axis_world is None:
            return None, None, None

        orient = plane_normal_world.dot(parent_dir_world.cross(child_dir_world))
        if abs(orient) <= EPS:
            return None, center_axis_world, side_axis_world
        orient_sign = 1.0 if orient >= 0.0 else -1.0

        vec_plane = vec - plane_normal_world * vec.dot(plane_normal_world)
        if vec_plane.length <= EPS:
            return None, center_axis_world, side_axis_world
        vec_plane = vec_plane.normalized()

        parent_cross = plane_normal_world.dot(parent_dir_world.cross(vec_plane))
        child_cross = plane_normal_world.dot(vec_plane.cross(child_dir_world))
        inside = orient_sign * parent_cross >= -EPS and orient_sign * child_cross >= -EPS
        in_out = "in" if inside else "out"
        up_down = "up" if vec_plane.dot(side_axis_world) >= 0.0 else "down"
        return in_out + up_down, center_axis_world, side_axis_world

    @staticmethod
    def _collect_mesh_objects_for_armature(armature_obj: bpy.types.Object) -> list[bpy.types.Object]:
        return TwistBoneCore._collect_mesh_objects_for_armature(armature_obj)

    @classmethod
    def _transfer_fan_weights_for_object(
        cls,
        obj: bpy.types.Object,
        armature: bpy.types.Object,
        selected_names: list[str],
        fan_names: list[str],
        radius_factor: float,
        blur_factor: float,
        frame: dict,
    ) -> dict:
        edit_bones = armature.data.edit_bones
        bone_a = edit_bones.get(selected_names[0])
        bone_b = edit_bones.get(selected_names[1])
        if bone_a is None or bone_b is None:
            raise Exception("selected bones not found")

        joint = frame["joint"]
        plane_normal = frame["plane_normal"]
        total_angle = frame["angle_rad"]
        base_length = frame["base_length"]
        radius = max(base_length * radius_factor, EPS)
        blur_world = max(radius * blur_factor, 0.0)
        plane_normal_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ plane_normal)
        parent_dir_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["parent_dir"])
        child_dir_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["child_dir"])
        if plane_normal_world is None or parent_dir_world is None or child_dir_world is None:
            raise Exception("failed to compute plane normal")

        source_names = [frame["parent_bone"].name, frame["child_bone"].name]
        source_dirs = {
            frame["parent_bone"].name: parent_dir_world,
            frame["child_bone"].name: child_dir_world,
        }

        fan_items: list[dict] = []
        for fan_name in fan_names:
            parsed = cls._parse_fan_name(fan_name)
            fan_bone = armature.data.bones.get(fan_name)
            if parsed is None or fan_bone is None:
                continue

            fan_dir = _safe_normalized_vector(armature.matrix_world.to_3x3() @ fan_bone.vector)
            if fan_dir is None:
                continue

            source_name = None
            fan_parent = getattr(fan_bone, "parent", None)
            if fan_parent is not None and fan_parent.name in source_dirs:
                source_name = fan_parent.name
            else:
                parent_score = fan_dir.dot(parent_dir_world)
                child_score = fan_dir.dot(child_dir_world)
                source_name = frame["parent_bone"].name if parent_score >= child_score else frame["child_bone"].name

            fan_items.append({
                "name": fan_name,
                "kind": parsed["fan_kind"],
                "dir": fan_dir,
                "source": source_name,
            })

        if not fan_items:
            return {
                "processed_sources": 0,
                "processed_vertices": 0,
                "processed_objects": 0,
            }

        all_indices = [v.index for v in obj.data.vertices]
        if not all_indices:
            return {
                "processed_sources": 0,
                "processed_vertices": 0,
                "processed_objects": 0,
            }

        num_vertices = len(obj.data.vertices)
        verts_world = [obj.matrix_world @ v.co for v in obj.data.vertices]
        rel_vectors = [vert_world - (armature.matrix_world @ joint) for vert_world in verts_world]
        touched_vertices = 0
        processed_sources = 0
        processed_fans = 0

        source_groups: dict[str, bpy.types.VertexGroup] = {}
        source_weights: dict[str, list[float]] = {}
        final_source_weights: dict[str, list[float]] = {}
        for source_name in source_names:
            source_vg = obj.vertex_groups.get(source_name)
            if source_vg is None:
                continue

            weights = [0.0] * num_vertices
            has_any = False
            for i in range(num_vertices):
                try:
                    w = source_vg.weight(i)
                except RuntimeError:
                    w = 0.0
                weights[i] = w
                if w > 0.0:
                    has_any = True

            if not has_any:
                continue

            source_groups[source_name] = source_vg
            source_weights[source_name] = weights
            final_source_weights[source_name] = weights[:]
            processed_sources += 1

        if not source_groups:
            return {
                "processed_sources": 0,
                "processed_vertices": 0,
                "processed_objects": 0,
            }

        fan_groups: dict[str, bpy.types.VertexGroup] = {}
        final_fan_weights: dict[str, list[float]] = {}
        fans_by_source_sector: dict[tuple[str, str], list[dict]] = {}
        for item in fan_items:
            fan_vg = obj.vertex_groups.get(item["name"])
            if fan_vg is None:
                fan_vg = obj.vertex_groups.new(name=item["name"])
            fan_vg.remove(all_indices)
            fan_groups[item["name"]] = fan_vg
            final_fan_weights[item["name"]] = [0.0] * num_vertices
            source_name = item.get("source")
            if source_name in source_groups:
                pass

        processed_fans = len(fan_groups)

        def _project_angle(vec: Vector, axis_x: Vector, axis_y: Vector) -> float:
            return atan2(vec.dot(axis_y), vec.dot(axis_x))

        def _unwrap_angles(angle_items: list[tuple[float, dict]]) -> list[tuple[float, dict]]:
            if len(angle_items) <= 1:
                return angle_items

            raw = sorted(angle_items, key=lambda pair: pair[0])
            largest_gap = -1.0
            start_index = 0
            for idx in range(len(raw)):
                next_idx = (idx + 1) % len(raw)
                a0 = raw[idx][0]
                a1 = raw[next_idx][0] + (tau if next_idx == 0 else 0.0)
                gap = a1 - a0
                if gap > largest_gap:
                    largest_gap = gap
                    start_index = next_idx

            ordered = [raw[(start_index + idx) % len(raw)] for idx in range(len(raw))]
            base = ordered[0][0]
            result: list[tuple[float, dict]] = []
            prev = None
            for angle, item in ordered:
                ua = angle
                while ua < base:
                    ua += tau
                while ua >= base + tau:
                    ua -= tau
                if prev is not None and ua < prev:
                    ua += tau
                result.append((ua, item))
                prev = ua
            return result

        center_axis_world = _safe_normalized_vector(parent_dir_world + child_dir_world)
        if center_axis_world is None:
            center_axis_world = parent_dir_world
        side_axis_world = _safe_normalized_vector(plane_normal_world.cross(center_axis_world))
        if side_axis_world is None:
            side_axis_world = _safe_normalized_vector(center_axis_world.cross(plane_normal_world))
        if side_axis_world is None:
            raise Exception("failed to compute fan sector axis")

        for source_name, source_vg in source_groups.items():
            sector_fans: dict[str, list[dict]] = {
                "inup": [],
                "indown": [],
                "outup": [],
                "outdown": [],
            }
            for item in fan_items:
                if item.get("source") != source_name:
                    continue
                sector_name, _, _ = BoneFanCore._classify_fan_sector(
                    item["dir"],
                    parent_dir_world,
                    child_dir_world,
                    plane_normal_world,
                )
                if sector_name is None:
                    continue
                sector_fans[sector_name].append(item)

            for sector_name, source_fans in sector_fans.items():
                if not source_fans:
                    continue

                source_angle_items = [(_project_angle(item["dir"], center_axis_world, side_axis_world), item) for item in source_fans]
                source_angle_items = _unwrap_angles(source_angle_items)
                if not source_angle_items:
                    continue

                source_first_angle = source_angle_items[0][0]
                source_last_angle = source_angle_items[-1][0]

                for i, vec_world in enumerate(rel_vectors):
                    current_w = final_source_weights[source_name][i]
                    if current_w <= 0.0:
                        continue

                    dist = vec_world.length
                    radial = cls._smooth_falloff(dist, radius, radius + blur_world)
                    if radial <= 0.0:
                        continue

                    vec_plane = vec_world - plane_normal_world * vec_world.dot(plane_normal_world)
                    if vec_plane.length <= EPS:
                        continue

                    vertex_sector, _, _ = BoneFanCore._classify_fan_sector(
                        vec_plane,
                        parent_dir_world,
                        child_dir_world,
                        plane_normal_world,
                    )
                    if vertex_sector != sector_name:
                        continue

                    vertex_angle = _project_angle(vec_plane, center_axis_world, side_axis_world)
                    while vertex_angle < source_first_angle:
                        vertex_angle += tau
                    if vertex_angle > source_last_angle + EPS:
                        continue

                    transfer_total = current_w * radial
                    if transfer_total <= 0.0:
                        continue

                    final_source_weights[source_name][i] = current_w - transfer_total

                    if len(source_angle_items) == 1:
                        final_fan_weights[source_angle_items[0][1]["name"]][i] += transfer_total
                        touched_vertices += 1
                        continue

                    if vertex_angle <= source_angle_items[0][0]:
                        final_fan_weights[source_angle_items[0][1]["name"]][i] += transfer_total
                        touched_vertices += 1
                        continue

                    if vertex_angle >= source_angle_items[-1][0]:
                        final_fan_weights[source_angle_items[-1][1]["name"]][i] += transfer_total
                        touched_vertices += 1
                        continue

                    for seg_index in range(len(source_angle_items) - 1):
                        angle_a, item_a = source_angle_items[seg_index]
                        angle_b, item_b = source_angle_items[seg_index + 1]
                        if angle_a <= vertex_angle <= angle_b:
                            span = max(angle_b - angle_a, EPS)
                            t = _clamp((vertex_angle - angle_a) / span, 0.0, 1.0)
                            final_fan_weights[item_a["name"]][i] += transfer_total * (1.0 - t)
                            final_fan_weights[item_b["name"]][i] += transfer_total * t
                            touched_vertices += 1
                            break

        for source_name, source_vg in source_groups.items():
            source_vg.remove(all_indices)
            for i, weight in enumerate(final_source_weights[source_name]):
                if weight > 0.0:
                    source_vg.add([i], weight, "REPLACE")

        for fan_name, fan_vg in fan_groups.items():
            weights = final_fan_weights.get(fan_name)
            if weights is None:
                continue
            for i, weight in enumerate(weights):
                if weight > 0.0:
                    fan_vg.add([i], weight, "REPLACE")

        return {
            "processed_sources": processed_sources,
            "processed_fans": processed_fans,
            "processed_vertices": touched_vertices,
            "processed_objects": 1 if processed_sources > 0 else 0,
        }

    @classmethod
    def apply_fan_weights(
        cls,
        context: Context,
        armature: bpy.types.Object,
        selected_names: list[str],
        fan_names: list[str],
        radius_factor: float,
        blur_factor: float,
        only_selected: bool,
    ) -> dict:
        frame, error = cls._resolve_joint_geometry(
            armature.data.edit_bones.get(selected_names[0]),
            armature.data.edit_bones.get(selected_names[1]),
        )
        if error:
            raise Exception(error)

        mesh_objs = cls._collect_mesh_objects_for_armature(armature)
        if only_selected:
            mesh_objs = [obj for obj in mesh_objs if obj.select_get()]

        if not mesh_objs:
            raise Exception("no mesh objects found")

        result = {
            "processed_objects": 0,
            "processed_sources": 0,
            "processed_fans": 0,
            "processed_vertices": 0,
        }

        for obj in mesh_objs:
            obj_result = cls._transfer_fan_weights_for_object(
                obj,
                armature,
                selected_names,
                fan_names,
                radius_factor,
                blur_factor,
                frame,
            )
            result["processed_objects"] += obj_result["processed_objects"]
            result["processed_sources"] += obj_result["processed_sources"]
            result["processed_fans"] += obj_result.get("processed_fans", 0)
            result["processed_vertices"] += obj_result["processed_vertices"]

        return result

    @staticmethod
    def _ensure_copy_rotation_constraint(pose_bone, target_armature: bpy.types.Object, target_bone_name: str, influence: float = 1.0):
        constraint = None
        for item in pose_bone.constraints:
            if item.type == "COPY_ROTATION" and item.name == "HoTools_CopyRotation":
                constraint = item
                break

        if constraint is None:
            constraint = pose_bone.constraints.new("COPY_ROTATION")
            constraint.name = "HoTools_CopyRotation"

        constraint.target = target_armature
        constraint.subtarget = target_bone_name
        constraint.owner_space = "WORLD"
        constraint.target_space = "WORLD"
        constraint.mix_mode = "REPLACE"
        constraint.influence = max(0.0, min(1.0, influence))
        constraint.use_x = True
        constraint.use_y = True
        constraint.use_z = True
        return constraint

    @classmethod
    def _add_fan_constraints(
        cls,
        armature: bpy.types.Object,
        fan_names: list[str],
        pin_names: list[str],
    ) -> None:
        if not fan_names:
            return

        kind_totals: dict[str, int] = {}
        fan_infos: list[tuple[str, str, int, int]] = []
        for fan_name in fan_names:
            parsed = cls._parse_fan_name(fan_name)
            if parsed is None:
                continue
            kind = parsed["fan_kind"]
            index = parsed["index"]
            kind_totals[kind] = max(kind_totals.get(kind, 0), index)
            fan_infos.append((fan_name, kind, index, 0))

        old_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        try:
            armature.select_set(True)
            bpy.context.view_layer.objects.active = armature
            BoneSplitCore.set_object_mode(armature, "POSE")
            for fan_name, pin_name in zip(fan_names, pin_names):
                parsed = cls._parse_fan_name(fan_name)
                if parsed is None:
                    continue
                total = kind_totals.get(parsed["fan_kind"], parsed["index"])
                influence = min(parsed["index"], total + 1 - parsed["index"]) / float(total + 1)
                pose_bone = armature.pose.bones.get(fan_name)
                if pose_bone is None:
                    continue
                cls._ensure_copy_rotation_constraint(
                    pose_bone,
                    armature,
                    pin_name,
                    influence,
                )
        finally:
            if old_active is not None:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass
            try:
                BoneSplitCore.set_object_mode(armature, old_mode)
            except Exception:
                pass

    @classmethod
    def _create_fan_bones(
        cls,
        armature: bpy.types.Object,
        selected_names: list[str],
        fan_kind: str,
        count: int,
        length_factor: float,
        pin_length_factor: float,
        bone_collection_name: str = HoRig_Fan,
    ) -> list[str]:
        if len(selected_names) != 2:
            raise Exception("please select exactly two bones")

        selected_bones = cls._selected_bones(bpy.context, armature)
        if len(selected_bones) != 2:
            raise Exception("selected bones not found")

        edit_bones = armature.data.edit_bones
        bone_a, bone_b = selected_bones

        frame, error = cls._resolve_joint_geometry(bone_a, bone_b)
        if error:
            raise Exception(error)

        parent_bone = frame["parent_bone"]
        child_bone = frame["child_bone"]
        joint = frame["joint"]
        parent_dir = frame["parent_dir"]
        child_dir = frame["child_dir"]
        plane_normal = frame["plane_normal"]
        total_angle = frame["angle_rad"]
        base_length = frame["base_length"]

        padding = max(2, len(str(count)))
        fan_length = max(base_length * length_factor, EPS)
        pin_length = max(fan_length * pin_length_factor, EPS)

        existed = []
        for i in range(count):
            fan_name = cls._fan_name(parent_bone.name, fan_kind, i + 1, padding)
            pin_name = cls._fan_pin_name(parent_bone.name, fan_kind, i + 1, padding)
            if edit_bones.get(fan_name) is not None:
                existed.append(fan_name)
            if edit_bones.get(pin_name) is not None:
                existed.append(pin_name)

        if existed:
            raise Exception("fan bone already exists: " + ", ".join(sorted(set(existed))))

        created_names = []
        pin_names = []
        step = total_angle / (count + 1)
        start_dir = parent_dir if fan_kind == "in" else -parent_dir

        for i in range(1, count + 1):
            fan_name = cls._fan_name(parent_bone.name, fan_kind, i, padding)
            pin_name = cls._fan_pin_name(parent_bone.name, fan_kind, i, padding)
            direction = cls._rotate_vector_around_axis(
                start_dir,
                plane_normal,
                step * i,
            )
            if direction is None:
                raise Exception(f"failed to generate {fan_name}")

            direction = _safe_normalized_vector(direction)
            if direction is None:
                raise Exception(f"{fan_name} direction length is zero")

            pin_bone = edit_bones.new(pin_name)
            pin_bone.head = joint.copy()
            pin_bone.tail = joint + direction * pin_length
            pin_bone.use_connect = False
            pin_bone.use_deform = False
            pin_bone.parent = cls._choose_parent_bone(
                -direction,
                parent_bone,
                parent_dir,
                child_bone,
                child_dir,
            )
            try:
                pin_bone.align_roll(plane_normal)
            except Exception:
                pin_bone.roll = 0.0

            fan_bone = edit_bones.new(fan_name)
            fan_bone.head = joint.copy()
            fan_bone.tail = joint + direction * fan_length
            fan_bone.use_connect = False
            fan_bone.use_deform = True
            fan_bone.parent = cls._choose_parent_bone(
                direction,
                parent_bone,
                parent_dir,
                child_bone,
                child_dir,
            )
            try:
                fan_bone.align_roll(plane_normal)
            except Exception:
                fan_bone.roll = 0.0

            created_names.append(fan_name)
            pin_names.append(pin_name)

        bpy.context.view_layer.objects.active = armature
        try:
            _assign_bones_to_collection(armature, created_names + pin_names, bone_collection_name)
            BoneSplitCore.set_object_mode(armature, "OBJECT")
            cls._apply_hotools_bone_props(armature, created_names)
            cls._add_fan_constraints(armature, created_names, pin_names)
        finally:
            if armature.mode != "EDIT":
                try:
                    BoneSplitCore.set_object_mode(armature, "EDIT")
                except Exception:
                    pass

        return created_names

    @classmethod
    def _collect_fan_bone_names(cls, armature: bpy.types.Object, selected_names: list[str]) -> list[str]:
        edit_bones = armature.data.edit_bones
        removal = set()
        selected_set = set(selected_names)

        if not selected_names:
            for bone in edit_bones:
                if cls._parse_fan_name(bone.name) is not None or cls._parse_fan_pin_name(bone.name) is not None:
                    removal.add(bone.name)
            return sorted(removal)

        for name in selected_names:
            if cls._parse_fan_name(name) is not None or cls._parse_fan_pin_name(name) is not None:
                removal.add(name)

        for bone in edit_bones:
            parsed = cls._parse_fan_name(bone.name)
            pin_parsed = cls._parse_fan_pin_name(bone.name)
            if parsed is None and pin_parsed is None:
                continue
            base_name = parsed["base_name"] if parsed is not None else pin_parsed["base_name"]
            if base_name in selected_set:
                removal.add(bone.name)

        return sorted(removal)

    @classmethod
    def _remove_fan_bones(cls, armature: bpy.types.Object, selected_names: list[str]) -> int:
        edit_bones = armature.data.edit_bones
        removed = 0

        for bone_name in cls._collect_fan_bone_names(armature, selected_names):
            bone = edit_bones.get(bone_name)
            if bone is None:
                continue
            edit_bones.remove(bone)
            removed += 1

        return removed


class OP_FanGenerate(Operator):
    bl_idname = "ho.fan_generate"
    bl_label = "fan add"
    bl_description = "Generate fan bones from two connected bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False

        if obj.mode == "POSE":
            return len(context.selected_pose_bones) == 2

        if obj.mode == "EDIT":
            return len([bone for bone in obj.data.edit_bones if bone.select]) == 2

        return False

    def execute(self, context):
        armature = context.active_object
        original_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        was_hidden = armature.hide_viewport
        BoneFanPreview.clear()
        settings = getattr(context.scene, "ho_fan_settings", None)
        if settings is None:
            self.report({"ERROR"}, "fan settings are missing")
            return {"CANCELLED"}

        selected_names = BoneFanCore._selected_bone_names(context, armature)
        if len(selected_names) != 2:
            self.report({"ERROR"}, "please select exactly two bones")
            return {"CANCELLED"}

        fan_kinds = []
        if settings.generate_in:
            fan_kinds.append(("in", settings.count_in))
        if settings.generate_out:
            fan_kinds.append(("out", settings.count_out))
        if not fan_kinds:
            self.report({"ERROR"}, "select at least one direction")
            return {"CANCELLED"}

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            created_names = []
            for fan_kind, count in fan_kinds:
                created_names.extend(
                    BoneFanCore._create_fan_bones(
                        armature,
                        selected_names,
                        fan_kind,
                        count,
                        settings.length_factor,
                        settings.pin_length_factor,
                        settings.bone_collection_name,
                    )
                )

            weight_result = None
            if settings.auto_transfer_weights:
                weight_result = BoneFanCore.apply_fan_weights(
                    context,
                    armature,
                    selected_names,
                    created_names,
                    settings.fan_weight_radius,
                    settings.fan_weight_blur,
                    settings.only_selected,
                )

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            if weight_result is None:
                self.report({"INFO"}, f"generated {len(created_names)} fan bones")
            else:
                self.report(
                    {"INFO"},
                    f"generated {len(created_names)} fan bones, weights on {weight_result['processed_objects']} objects",
                )
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        finally:
            if armature.mode == "EDIT" and original_mode != "EDIT":
                try:
                    BoneSplitCore.set_object_mode(armature, original_mode)
                except Exception:
                    pass

            if old_active is not None:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass

            if was_hidden:
                armature.hide_set(True)

    def invoke(self, context, event):
        BoneFanPreview.show(context)
        return self.execute(context)


class OP_RemoveFanBone(Operator):
    bl_idname = "ho.remove_fan_bone"
    bl_label = "remove fan"
    bl_description = "Remove fan bones for the selected main bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False

        if obj.mode == "POSE":
            return len(context.selected_pose_bones) == 2

        if obj.mode == "EDIT":
            return len([bone for bone in obj.data.edit_bones if bone.select]) == 2

        return False

    def execute(self, context):
        armature = context.active_object
        original_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        was_hidden = armature.hide_viewport

        selected_names = BoneFanCore._selected_bone_names(context, armature)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            removed = BoneFanCore._remove_fan_bones(armature, selected_names)

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            self.report({"INFO"}, f"removed {removed} fan bones")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        finally:
            if armature.mode == "EDIT" and original_mode != "EDIT":
                try:
                    BoneSplitCore.set_object_mode(armature, original_mode)
                except Exception:
                    pass

            if old_active is not None:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass

            if was_hidden:
                armature.hide_set(True)


cls = [
    PG_Hotools_FanSettings,
    OP_FanGenerate,
    OP_RemoveFanBone,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    for item in cls:
        bpy.utils.unregister_class(item)
    ureg_props()
