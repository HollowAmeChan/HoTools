import bpy
from bpy.types import Context, Operator, PropertyGroup, UILayout
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty, PointerProperty
from math import acos, cos, radians, sin, tau
from mathutils import Vector

from .boneSplit import BoneSplitCore
from .boneTwist import TwistBoneCore
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
import blf


EPS = 1e-6
HoRig_Fan = "HoRig_Fan"


class FanRemovalBlockedError(Exception):
    """当 fan 骨下面挂着其他骨骼、无法安全删除时抛出。"""
    pass


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


def _fan_count_update(self, context):
    # 内/外侧 fan 骨必须成对出现，所以把数量向上吸附到最近的偶数（最小 2）再刷新预览。
    for attr in ("count_in", "count_out"):
        value = getattr(self, attr, 2)
        snapped = max(2, value if value % 2 == 0 else value + 1)
        if snapped != value:
            setattr(self, attr, snapped)
    _fan_preview_update(self, context)


def _draw_fan_preview():
    BoneFanPreview._draw_3d()


def _draw_fan_preview_2d():
    BoneFanPreview._draw_2d()


class PG_Hotools_FanSettings(PropertyGroup):
    ui_expanded: BoolProperty(
        name="fan 设置",
        description="展开 fan 骨生成设置",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    preview_enabled: BoolProperty(
        name="预览",
        description="在 3D 视图中绘制 fan 预览",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    generate_in: BoolProperty(
        name="生成内侧",
        description="生成内侧（朝主骨方向）的 fan 骨",
        default=True,
        update=_fan_preview_update,
    )  # type: ignore
    generate_out: BoolProperty(
        name="生成外侧",
        description="生成外侧（背向主骨方向）的 fan 骨",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    count_in: IntProperty(
        name="内侧数量",
        description="内侧 fan 骨数量，必须为偶数",
        default=2,
        min=2,
        step=2,
        update=_fan_count_update,
    )  # type: ignore
    count_out: IntProperty(
        name="外侧数量",
        description="外侧 fan 骨数量，必须为偶数",
        default=2,
        min=2,
        step=2,
        update=_fan_count_update,
    )  # type: ignore
    influence_in: FloatProperty(
        name="内侧强度",
        description="内侧 fan 骨复制旋转约束强度的整体系数，乘到每根 fan 自动计算的"
                    "约束强度上（1 = 原始强度，0 = 完全不约束）",
        default=1.0,
        min=0.0,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    influence_out: FloatProperty(
        name="外侧强度",
        description="外侧 fan 骨复制旋转约束强度的整体系数，乘到每根 fan 自动计算的"
                    "约束强度上（1 = 原始强度，0 = 完全不约束）",
        default=1.0,
        min=0.0,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    length_factor: FloatProperty(
        name="长度系数",
        description="fan 骨长度相对于关节侧主骨长度的比例",
        default=0.2,
        min=0.01,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    pin_length_factor: FloatProperty(
        name="pin 长度系数",
        description="fanPin 长度相对于 fan 骨长度的比例",
        default=0.2 / 5.0,
        min=0.001,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    auto_transfer_weights: BoolProperty(
        name="自动转移权重",
        description="生成时把主骨权重转移到 fan 骨上",
        default=True,
        update=_fan_preview_update,
    )  # type: ignore
    process_symmetry: BoolProperty(
        name="对称操作",
        description="同时在镜像骨对（.L/.R）上生成 fan 骨",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
        update=_fan_preview_update,
    )  # type: ignore
    fan_weight_radius: FloatProperty(
        name="权重半径",
        description="权重转移球的半径，相对于关节侧主骨长度",
        default=0.16,
        min=0.0,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    fan_weight_blur: FloatProperty(
        name="权重模糊",
        description="硬球分割后施加的整体模糊强度（0 = 不模糊，1 = 最大平滑）",
        default=1.0,
        min=0.0,
        soft_max=1.0,
        update=_fan_preview_update,
    )  # type: ignore
    bone_collection_name: StringProperty(
        name="骨骼集合",
        description="生成的 fan 骨所属的骨骼集合名称",
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
    header.label(text="fan关节体积保持")

    row = header.row(align=True)
    row.operator(OP_FanGenerate.bl_idname, text="生成")
    row.operator(OP_RemoveFanBone.bl_idname, text="安全移除")
    
    row = header.row(align=True)
    row.alert = settings.preview_enabled
    row.prop(
        settings,
        "preview_enabled",
        text="",
        icon="HIDE_OFF" if settings.preview_enabled else "HIDE_ON",
    )

    if not settings.ui_expanded:
        return

    col = fan_box.column(align=True)
    col.separator()
    row = col.row(align=True)
    row.prop(settings, "generate_in", toggle=True)
    sub = row.row(align=True)
    sub.enabled = settings.generate_in
    sub.prop(settings, "count_in")
    sub.prop(settings, "influence_in", text="")

    row = col.row(align=True)
    row.prop(settings, "generate_out", toggle=True)
    sub = row.row(align=True)
    sub.enabled = settings.generate_out
    sub.prop(settings, "count_out")
    sub.prop(settings, "influence_out", text="")

    col.separator()
    col.prop(settings, "length_factor")
    col.prop(settings, "pin_length_factor")
    col.prop(settings, "bone_collection_name")
    col.prop(settings, "process_symmetry")
    col.prop(settings, "auto_transfer_weights")

    sub = col.column(align=True)
    sub.enabled = settings.auto_transfer_weights
    sub.prop(settings, "only_selected")
    sub.prop(settings, "fan_weight_radius")
    sub.prop(settings, "fan_weight_blur")


class BoneFanPreview:
    _handler_3d = None
    _handler_2d = None
    _timer_running = False
    _timer_interval = 0.08
    _state = None

    @classmethod
    def ensure_handler(cls):
        if cls._handler_3d is None:
            cls._handler_3d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_fan_preview,
                (),
                "WINDOW",
                "POST_VIEW",
            )
        if cls._handler_2d is None:
            cls._handler_2d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_fan_preview_2d,
                (),
                "WINDOW",
                "POST_PIXEL",
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
            "frames": [],
            "message": "",
            "region": region,
            "region_data": region_data,
        }

        if armature is None or armature.type != "ARMATURE":
            state["message"] = "预览需要一个骨架"
        else:
            selected_bones = BoneFanCore._selected_bones(context, armature)
            if len(selected_bones) != 2:
                state["message"] = "请正好选择两根骨骼"
            else:
                bone_a, bone_b = selected_bones
                frame, error = BoneFanCore._resolve_joint_geometry(bone_a, bone_b)
                if error:
                    state["message"] = error
                else:
                    state["armature_name"] = armature.name
                    frames = [frame]
                    # 开启对称处理时，把镜像骨对的预览几何也算进来，直接看到两边。
                    if getattr(settings, "process_symmetry", False):
                        selected_names = [b.name for b in selected_bones]
                        mirrored = BoneFanCore._mirror_pair(armature, selected_names)
                        if mirrored is not None:
                            mb_a = armature.data.edit_bones.get(mirrored[0]) if armature.mode == "EDIT" else armature.pose.bones.get(mirrored[0])
                            mb_b = armature.data.edit_bones.get(mirrored[1]) if armature.mode == "EDIT" else armature.pose.bones.get(mirrored[1])
                            if mb_a is not None and mb_b is not None:
                                m_frame, m_error = BoneFanCore._resolve_joint_geometry(mb_a, mb_b)
                                if not m_error:
                                    frames.append(m_frame)
                    state["frames"] = frames

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
        if cls._handler_2d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handler_2d, "WINDOW")
        cls._handler_3d = None
        cls._handler_2d = None
        cls._state = None
        cls._timer_running = False

    @classmethod
    def _timer(cls):
        if cls._handler_3d is None and cls._handler_2d is None:
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
        if message:
            return
        armature = bpy.data.objects.get(state.get("armature_name", ""))
        if armature is None or armature.type != "ARMATURE":
            return

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        gpu.state.line_width_set(2.0)
        gpu.state.point_size_set(8.0)
        try:
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            settings = getattr(bpy.context.scene, "ho_fan_settings", None)
            for frame in state.get("frames", []):
                cls._draw_frame_3d(shader, armature, settings, frame)
        finally:
            gpu.state.point_size_set(1.0)
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")

    @classmethod
    def _draw_frame_3d(cls, shader, armature, settings, frame):
        if frame is None:
            return

        joint_world = armature.matrix_world @ frame["joint"]
        plane_normal_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["plane_normal"])
        axis_a_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["parent_dir"])
        if axis_a_world is None:
            axis_a_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["child_dir"])
        if plane_normal_world is None or axis_a_world is None:
            return

        axis_a_world = axis_a_world - plane_normal_world * axis_a_world.dot(plane_normal_world)
        axis_a_world = _safe_normalized_vector(axis_a_world)
        if axis_a_world is None:
            return

        axis_b_world = _safe_normalized_vector(plane_normal_world.cross(axis_a_world))
        if axis_b_world is None:
            return

        radius_factor = float(getattr(settings, "fan_weight_radius", 0.5)) if settings is not None else 0.5
        radius = max(frame["base_length"] * radius_factor, 0.0)
        if radius <= EPS:
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

        points = [tuple(joint_world)]
        in_spokes = []
        out_spokes = []

        total_angle = float(frame["angle_rad"])
        parent_dir_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["parent_dir"])
        child_dir_world = _safe_normalized_vector(armature.matrix_world.to_3x3() @ frame["child_dir"])
        if parent_dir_world is None or child_dir_world is None:
            return

        center_dir_world = _safe_normalized_vector(parent_dir_world + child_dir_world)
        if center_dir_world is None:
            center_dir_world = parent_dir_world

        center_spokes = [
            tuple(joint_world),
            tuple(joint_world + center_dir_world * radius),
            tuple(joint_world),
            tuple(joint_world - center_dir_world * radius),
        ]

        sphere_lines = []
        if getattr(settings, "auto_transfer_weights", False):
            # 权重分割是关节周围的一个硬球：球内每个顶点把主骨权重交给最近的
            # fan，再用整体模糊软化。这里只画这个球。
            _append_circle_3d(sphere_lines, joint_world, axis_a_world, axis_b_world, radius)
            _append_circle_3d(sphere_lines, joint_world, axis_a_world, plane_normal_world, radius)
            _append_circle_3d(sphere_lines, joint_world, axis_b_world, plane_normal_world, radius)

        if getattr(settings, "generate_in", False):
            in_count = max(1, int(getattr(settings, "count_in", 1)))
            step = total_angle / (in_count + 1)
            start_dir = parent_dir_world
            for index in range(1, in_count + 1):
                direction = BoneFanCore._rotate_vector_around_axis(start_dir, plane_normal_world, step * index)
                if direction is None:
                    continue
                in_spokes.extend([tuple(joint_world), tuple(joint_world + direction * radius)])

        if getattr(settings, "generate_out", False):
            out_count = max(1, int(getattr(settings, "count_out", 1)))
            step = total_angle / (out_count + 1)
            start_dir = -parent_dir_world
            for index in range(1, out_count + 1):
                direction = BoneFanCore._rotate_vector_around_axis(start_dir, plane_normal_world, step * index)
                if direction is None:
                    continue
                out_spokes.extend([tuple(joint_world), tuple(joint_world + direction * radius)])

        shader.bind()

        if sphere_lines:
            line_batch = batch_for_shader(shader, "LINES", {"pos": sphere_lines})
            shader.uniform_float("color", (0.2, 0.9, 1.0, 0.95))
            line_batch.draw(shader)

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

    @classmethod
    def _draw_2d(cls):
        state = cls._state
        if state is None:
            return

        font_id = 0
        message = state.get("message", "")
        blf.size(font_id, 14)
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, 20.0, 20.0, 0.0)
        if message:
            blf.draw(font_id, f"fan 预览: {message}")
        else:
            blf.draw(font_id, "fan 预览")


class BoneFanCore:
    # 权重模糊参数：fan_weight_blur（0..1）缩放迭代次数，每次迭代是一步
    # 以此 lambda 为强度的拉普拉斯平滑。
    _MAX_BLUR_ITERATIONS = 20
    _BLUR_LAMBDA = 0.5

    @staticmethod
    def _build_vertex_adjacency(obj: bpy.types.Object, num_vertices: int) -> list[list[int]]:
        neighbors: list[set[int]] = [set() for _ in range(num_vertices)]
        for edge in obj.data.edges:
            a, b = edge.vertices
            neighbors[a].add(b)
            neighbors[b].add(a)
        return [list(group) for group in neighbors]

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
    def _mirror_pair(armature: bpy.types.Object, pair_names: list[str]) -> list[str] | None:
        # 把选中骨对的两根骨名都翻转到对侧。只有当镜像骨对真实存在、且是一对不同
        # 于原骨对的骨时才返回；否则返回 None（没有可镜像的对象，比如中线骨）。
        # 按当前模式取骨：EDIT 模式查 edit_bones，否则查 pose.bones（预览常在
        # 姿态/物体模式触发，此时 edit_bones 为空，不能拿它判定镜像骨是否存在）。
        if armature.mode == "EDIT":
            def _bone_exists(name):
                return armature.data.edit_bones.get(name) is not None
        else:
            def _bone_exists(name):
                return armature.pose.bones.get(name) is not None

        mirrored = []
        for name in pair_names:
            flipped = bpy.utils.flip_name(name)
            if flipped == name or not _bone_exists(flipped):
                return None
            mirrored.append(flipped)

        # 防止退化的翻转坍缩成单根骨，或翻回到原骨对本身（那会重复生成）。
        if len(set(mirrored)) != 2:
            return None
        if set(mirrored) == set(pair_names):
            return None
        return mirrored

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
            raise Exception("不支持的骨骼类型")

        bone_a_parent = getattr(bone_a, "parent", None)
        bone_b_parent = getattr(bone_b, "parent", None)

        # 必须是直接父子级：仅靠端点位置相接（可能是误选的两根无关骨）不算，
        # 否则会算出一个假关节、生成错误的 fan。
        if bone_b_parent == bone_a:
            parent_bone = bone_a
            child_bone = bone_b
        elif bone_a_parent == bone_b:
            parent_bone = bone_b
            child_bone = bone_a
        else:
            return None, "两根骨骼必须是直接的父子级关系"

        parent_head, parent_tail = _bone_points(parent_bone)
        child_head, child_tail = _bone_points(child_bone)

        # 父子还必须在关节处相连：父骨末端与子骨头部重合，才有唯一的弯折点。
        if (parent_tail - child_head).length > tolerance:
            return None, "父子骨骼未相连：父骨末端与子骨头部不重合"

        joint = (parent_tail + child_head) * 0.5

        parent_dir = _safe_normalized_vector(parent_head - joint)
        child_dir = _safe_normalized_vector(child_tail - joint)
        if parent_dir is None or child_dir is None:
            return None, "骨骼长度太短"

        dot = _clamp(parent_dir.dot(child_dir), -1.0, 1.0)
        angle_rad = acos(dot)
        if angle_rad <= radians(1.0) or angle_rad >= radians(179.0):
            return None, "关节夹角太小或两骨接近共线"

        plane_normal = _safe_normalized_vector(parent_dir.cross(child_dir))
        if plane_normal is None:
            return None, "无法计算平面法线"

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
        """把单个网格上、两根主骨的权重转移到 fan 骨上。

        运行原理：
        1. 以关节为中心、半径 radius 的球，决定哪些顶点参与转移。
        2. 阶段 1（硬球分割）：球内每个顶点，把每根主骨的权重整份交给"同通道内"
           平面内方向最接近的那根 fan 骨；其余顶点保持不动。
        3. 阶段 2（整体模糊）：在受影响区域做拉普拉斯平滑软化硬边界，再按通道
           重新归一化，保证每根主骨"剩余 + 名下 fan"之和恢复到它的原始权重。

        关键不变量是"按通道守恒"——fan 骨刚性跟随其父级主骨，所以只要每个通道的
        权重总量不变，无约束时的形变就和原始一致。详见阶段 2 注释。
        """
        edit_bones = armature.data.edit_bones
        bone_a = edit_bones.get(selected_names[0])
        bone_b = edit_bones.get(selected_names[1])
        if bone_a is None or bone_b is None:
            raise Exception("找不到选中的骨骼")

        joint = frame["joint"]
        base_length = frame["base_length"]
        radius = max(base_length * radius_factor, EPS)

        source_names = [frame["parent_bone"].name, frame["child_bone"].name]
        parent_name, child_name = source_names[0], source_names[1]

        # 弯折平面的法线：所有 fan 骨都铺在这个平面内，所以 fan 之间的划分纯粹是
        # 平面内夹角。顶点位于肢体管面上、有很大的平面外分量，必须先把它投影掉，
        # 否则方向比较会吸附到错误的轴上。
        plane_normal_world = _safe_normalized_vector(
            armature.matrix_world.to_3x3() @ frame["plane_normal"]
        )
        parent_dir_world = _safe_normalized_vector(
            armature.matrix_world.to_3x3() @ frame["parent_dir"]
        )
        child_dir_world = _safe_normalized_vector(
            armature.matrix_world.to_3x3() @ frame["child_dir"]
        )

        # 收集 fan 骨以及它们从关节出发的世界空间方向。
        # 从 edit_bones（而非 data.bones）读取：此时处于编辑模式，data.bones 对
        # 刚创建的 fan 是过期的；edit_bones 和预览用的是同一个实时来源，坐标空间一致。
        fan_items: list[dict] = []
        for fan_name in fan_names:
            parsed = cls._parse_fan_name(fan_name)
            fan_bone = edit_bones.get(fan_name)
            if parsed is None or fan_bone is None:
                continue

            fan_dir = _safe_normalized_vector(
                armature.matrix_world.to_3x3() @ (fan_bone.tail - fan_bone.head)
            )
            if fan_dir is None:
                continue

            # fan 骨铺在弯折平面内；精确投影一下，让比较用的轴和下面投影后的
            # 顶点方向保持一致。
            if plane_normal_world is not None:
                fan_dir = _safe_normalized_vector(
                    fan_dir - plane_normal_world * fan_dir.dot(plane_normal_world)
                )
                if fan_dir is None:
                    continue

            # 这根 fan 刚性跟随的主骨（它的 edit-bone 父级）。无约束时 fan 的形变
            # 和这根骨完全一致，所以它只能从这根骨的通道里接收权重。按通道守恒
            # 正是保证自动权重结果与原始蒙皮对齐的关键。
            fan_src = None
            parent_eb = getattr(fan_bone, "parent", None)
            if parent_eb is not None and parent_eb.name in source_names:
                fan_src = parent_eb.name
            if fan_src is None and parent_dir_world is not None and child_dir_world is not None:
                fan_src = (
                    parent_name
                    if fan_dir.dot(parent_dir_world) >= fan_dir.dot(child_dir_world)
                    else child_name
                )
            if fan_src is None:
                fan_src = parent_name

            fan_items.append({
                "name": fan_name,
                "kind": parsed["fan_kind"],
                "dir": fan_dir,
                "src": fan_src,
            })

        if not fan_items:
            return {"processed_sources": 0, "processed_fans": 0, "processed_vertices": 0, "processed_objects": 0}

        all_indices = [v.index for v in obj.data.vertices]
        num_vertices = len(all_indices)
        if num_vertices == 0:
            return {"processed_sources": 0, "processed_fans": 0, "processed_vertices": 0, "processed_objects": 0}

        joint_world = armature.matrix_world @ joint
        rel_vectors = [(obj.matrix_world @ v.co) - joint_world for v in obj.data.vertices]

        # 读取两根主骨当前的权重
        source_groups: dict[str, bpy.types.VertexGroup] = {}
        source_weights: dict[str, list[float]] = {}
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

        if not source_groups:
            return {"processed_sources": 0, "processed_fans": 0, "processed_vertices": 0, "processed_objects": 0}

        present_sources = list(source_groups.keys())
        processed_sources = len(present_sources)

        # 顶点是否被某根主骨驱动的判定门槛：两根主骨权重之和。这里只用它来判断
        # 顶点要不要参与转移，真正的守恒是后面按通道分别做的。
        orig_total = [0.0] * num_vertices
        for source_name in present_sources:
            sw = source_weights[source_name]
            for i in range(num_vertices):
                orig_total[i] += sw[i]

        # 准备 fan 顶点组（清空）和工作用的权重缓冲
        fan_groups: dict[str, bpy.types.VertexGroup] = {}
        fan_weights: dict[str, list[float]] = {}
        for item in fan_items:
            fan_vg = obj.vertex_groups.get(item["name"])
            if fan_vg is None:
                fan_vg = obj.vertex_groups.new(name=item["name"])
            fan_vg.remove(all_indices)
            fan_groups[item["name"]] = fan_vg
            fan_weights[item["name"]] = [0.0] * num_vertices

        processed_fans = len(fan_groups)

        # 主骨权重的工作副本（会就地修改）
        main_weights = {name: source_weights[name][:] for name in present_sources}

        # 把每个 buffer 按"通道"（每根主骨）分组。fan 骨刚性跟随它的父级主骨，
        # 在没有约束时形变和那根主骨完全一致。要让自动权重后的效果和原始一致，
        # 权重必须在每个通道内部守恒：每个顶点上，主骨剩余权重加上它名下所有 fan
        # 的权重，要等于这根主骨的原始权重。父通道和子通道之间永不互相搬运权重
        # （这也是 fan 数量被强制为偶数、能对称配对的原因）。
        channel_fans = {name: [] for name in present_sources}
        for item in fan_items:
            if item["src"] in channel_fans:
                channel_fans[item["src"]].append(item["name"])

        # 预先取出每根 fan 的投影方向，避免在顶点循环里反复线性查找。
        fan_dirs = {item["name"]: item["dir"] for item in fan_items}

        # --- 阶段 1：硬球分割 ---------------------------------------------
        # 关节球内的每个顶点，把每根主骨的权重交给"同通道内"在平面内方向上
        # 夹角最近的那根 fan 骨。
        touched_vertices = 0
        core_vertices: list[int] = []
        for i in range(num_vertices):
            if orig_total[i] <= 0.0:
                continue
            if rel_vectors[i].length > radius:
                continue

            # 把顶点方向投影到弯折平面上，让最近 fan 的判定只比较平面内夹角
            # （fan 骨都铺在这个平面内）。
            vec = rel_vectors[i]
            if plane_normal_world is not None:
                vec = vec - plane_normal_world * vec.dot(plane_normal_world)
            vdir = _safe_normalized_vector(vec)

            touched = False
            for source_name in present_sources:
                ws = source_weights[source_name][i]
                if ws <= 0.0:
                    continue

                best_name = None
                best_score = -2.0
                for fan_name in channel_fans[source_name]:
                    fdir = fan_dirs[fan_name]
                    score = 1.0 if vdir is None else fdir.dot(vdir)
                    if score > best_score:
                        best_score = score
                        best_name = fan_name
                if best_name is None:
                    # 这个通道没有 fan：权重保留在主骨上
                    continue

                fan_weights[best_name][i] += ws
                main_weights[source_name][i] = 0.0
                touched = True

            if touched:
                core_vertices.append(i)
                touched_vertices += 1

        # --- 阶段 2：整体模糊 ---------------------------------------------
        # 在受影响区域做网格空间的拉普拉斯平滑，软化硬边界（fan 之间、fan 与
        # 主骨之间），随后按通道重新归一化回每根主骨的原始权重。
        iterations = int(round(_clamp(blur_factor, 0.0, 1.0) * cls._MAX_BLUR_ITERATIONS))
        if iterations > 0 and core_vertices:
            adjacency = cls._build_vertex_adjacency(obj, num_vertices)

            # 把区域向外扩张，让权重能越过球边界回流到主骨上（每次迭代扩一圈）。
            in_region = [False] * num_vertices
            frontier = list(core_vertices)
            for v in frontier:
                in_region[v] = True
            for _ in range(iterations):
                next_frontier = []
                for v in frontier:
                    for nb in adjacency[v]:
                        if not in_region[nb]:
                            in_region[nb] = True
                            next_frontier.append(nb)
                if not next_frontier:
                    break
                frontier = next_frontier
            region = [i for i in range(num_vertices) if in_region[i]]

            # 同时对所有相关分组做平滑；每个 buffer 独立平滑，所以这一步不会
            # 让权重跨通道流动。
            buffers = [main_weights[name] for name in present_sources]
            buffers += [fan_weights[item["name"]] for item in fan_items]

            lam = cls._BLUR_LAMBDA
            for _ in range(iterations):
                updates = []
                for i in region:
                    nbs = adjacency[i]
                    if not nbs:
                        continue
                    inv = 1.0 / len(nbs)
                    row = []
                    for buf in buffers:
                        neighbor_avg = 0.0
                        for nb in nbs:
                            neighbor_avg += buf[nb]
                        neighbor_avg *= inv
                        row.append(buf[i] + lam * (neighbor_avg - buf[i]))
                    updates.append((i, row))
                for i, row in updates:
                    for b, value in enumerate(row):
                        buffers[b][i] = value

            # 按"通道"重新归一化：让主骨剩余权重加上它名下所有 fan，重新加合回
            # 这根主骨的原始权重。这就是保证形变对齐、且转移来的权重不会泄漏到
            # 另一个通道或区域外的不变量。
            for source_name in present_sources:
                orig_s = source_weights[source_name]
                chan_buffers = [main_weights[source_name]]
                chan_buffers += [fan_weights[name] for name in channel_fans[source_name]]
                for i in region:
                    if orig_s[i] <= EPS:
                        # 这根主骨本来就没驱动这个顶点：绝不让模糊往它的通道里
                        # 引入新的权重。
                        for buf in chan_buffers:
                            buf[i] = 0.0
                        continue
                    s = 0.0
                    for buf in chan_buffers:
                        s += buf[i]
                    if s <= EPS:
                        continue
                    scale = orig_s[i] / s
                    for buf in chan_buffers:
                        buf[i] *= scale

        # --- 写回结果 -----------------------------------------------------
        for source_name in present_sources:
            source_vg = source_groups[source_name]
            source_vg.remove(all_indices)
            weights = main_weights[source_name]
            for i in range(num_vertices):
                if weights[i] > 0.0:
                    source_vg.add([i], weights[i], "REPLACE")

        for fan_name, fan_vg in fan_groups.items():
            weights = fan_weights[fan_name]
            for i in range(num_vertices):
                if weights[i] > 0.0:
                    fan_vg.add([i], weights[i], "REPLACE")

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
            raise Exception("没有找到网格物体")

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
        influence_scale: float = 1.0,
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
                influence *= max(0.0, influence_scale)
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
        influence_scale: float = 1.0,
    ) -> list[str]:
        if len(selected_names) != 2:
            raise Exception("请正好选择两根骨骼")

        edit_bones = armature.data.edit_bones
        # 从传入的骨名解析骨对，而不是读实时选择，这样对称那一轮才会作用到
        # 镜像骨对上，而不是重复生成原本选中的那一侧。
        bone_a = edit_bones.get(selected_names[0])
        bone_b = edit_bones.get(selected_names[1])
        if bone_a is None or bone_b is None:
            raise Exception("找不到选中的骨骼")

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
            raise Exception("fan 骨已存在: " + ", ".join(sorted(set(existed))))

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
                raise Exception(f"生成 {fan_name} 失败")

            direction = _safe_normalized_vector(direction)
            if direction is None:
                raise Exception(f"{fan_name} 的方向长度为零")

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
            cls._add_fan_constraints(armature, created_names, pin_names, influence_scale)
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
    def _build_fan_restore_map(cls, armature: bpy.types.Object, removal_names: list[str]) -> dict:
        # 把每根 deform fan 映射回它刚性跟随的主骨（它的 edit-bone 父级）。把权重
        # 还回那里正好是生成时按通道分割的逆操作，主骨能拿回原始权重。pin 骨
        # 不参与变形（use_deform = False），所以这里跳过。
        edit_bones = armature.data.edit_bones
        main_to_fans: dict[str, list[str]] = {}
        for name in removal_names:
            if cls._parse_fan_name(name) is None:
                continue
            bone = edit_bones.get(name)
            main_name = None
            if bone is not None:
                parent = getattr(bone, "parent", None)
                if parent is not None:
                    main_name = parent.name
            if main_name is None:
                main_name = cls._parse_fan_name(name)["base_name"]
            main_to_fans.setdefault(main_name, []).append(name)
        return main_to_fans

    @staticmethod
    def _find_fan_removal_child_blockers(
        armature: bpy.types.Object,
        removal_names: list[str],
    ) -> list[tuple[str, str]]:
        target = set(removal_names)
        bones = armature.data.edit_bones if armature.mode == "EDIT" else armature.data.bones
        blockers = []
        for name in removal_names:
            bone = bones.get(name)
            if bone is None:
                continue
            for child in bone.children:
                if child.name not in target:
                    blockers.append((name, child.name))
        return blockers

    @classmethod
    def _assert_safe_to_remove_fan_bones(
        cls,
        armature: bpy.types.Object,
        removal_names: list[str],
    ) -> None:
        blockers = cls._find_fan_removal_child_blockers(armature, removal_names)
        if not blockers:
            return

        sample_count = 8
        blocker_text = ", ".join(
            f"{fan_name} -> {child_name}"
            for fan_name, child_name in blockers[:sample_count]
        )
        if len(blockers) > sample_count:
            blocker_text += f"，等 {len(blockers)} 处"

        raise FanRemovalBlockedError(
            "不能删除 fan 骨：待删除的 fan/pin 骨下还有其他骨骼，"
            "请先解除这些骨骼的父子关系后再删除。"
            f"阻断项: {blocker_text}"
        )

    @staticmethod
    def obj_fan_restore(obj: bpy.types.Object, main_to_fans: dict[str, list[str]]) -> int:
        # 把每根主骨的剩余权重和它名下所有 fan 的权重加合，写回主骨，再删掉 fan
        # 顶点组。这正是生成时按通道转移的逆操作。
        old_mode = obj.mode
        old_active = bpy.context.view_layer.objects.active
        mirror_state = TwistBoneCore._set_temp_mesh_mirror_off(obj)
        mode_changed = False
        removed_groups = 0

        try:
            if old_mode != "OBJECT":
                bpy.context.view_layer.objects.active = obj
                BoneSplitCore.set_object_mode(obj, "OBJECT")
                mode_changed = True

            for main_name, fan_names in main_to_fans.items():
                fan_vgs = [
                    vg for vg in (obj.vertex_groups.get(fan_name) for fan_name in fan_names)
                    if vg is not None
                ]
                main_vg = obj.vertex_groups.get(main_name)

                if main_vg is None and not fan_vgs:
                    continue

                if main_vg is None:
                    main_vg = obj.vertex_groups.new(name=main_name)

                for vertex in obj.data.vertices:
                    total_weight = 0.0
                    has_explicit_weight = False

                    try:
                        total_weight += main_vg.weight(vertex.index)
                        has_explicit_weight = True
                    except RuntimeError:
                        pass

                    for fan_vg in fan_vgs:
                        try:
                            total_weight += fan_vg.weight(vertex.index)
                            has_explicit_weight = True
                        except RuntimeError:
                            continue

                    if has_explicit_weight:
                        main_vg.add([vertex.index], total_weight, "REPLACE")

                for fan_name in fan_names:
                    fan_vg = obj.vertex_groups.get(fan_name)
                    if fan_vg:
                        obj.vertex_groups.remove(fan_vg)
                        removed_groups += 1
        finally:
            TwistBoneCore._restore_mesh_mirror_state(mirror_state)

            if mode_changed:
                bpy.context.view_layer.objects.active = obj
                BoneSplitCore.set_object_mode(obj, old_mode)

            if old_active:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass

        return removed_groups

    @classmethod
    def _remove_fan_bones(cls, armature: bpy.types.Object, removal_names: list[str]) -> int:
        edit_bones = armature.data.edit_bones
        removed = 0

        for bone_name in removal_names:
            bone = edit_bones.get(bone_name)
            if bone is None:
                continue
            edit_bones.remove(bone)
            removed += 1

        return removed


class OP_FanGenerate(Operator):
    bl_idname = "ho.fan_generate"
    bl_label = "生成 fan 骨"
    bl_description = "从两根相连的骨骼生成 fan 骨"
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
            self.report({"ERROR"}, "缺少 fan 设置")
            return {"CANCELLED"}

        selected_names = BoneFanCore._selected_bone_names(context, armature)
        if len(selected_names) != 2:
            self.report({"ERROR"}, "请正好选择两根骨骼")
            return {"CANCELLED"}

        fan_kinds = []
        if settings.generate_in:
            fan_kinds.append(("in", settings.count_in))
        if settings.generate_out:
            fan_kinds.append(("out", settings.count_out))
        if not fan_kinds:
            self.report({"ERROR"}, "请至少选择一个方向")
            return {"CANCELLED"}

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            # 组装要处理的骨对：选中的那一对，外加开启对称时的镜像骨对
            # （仅当镜像骨对真实存在时才加入）。
            pairs = [selected_names]
            if settings.process_symmetry:
                mirrored = BoneFanCore._mirror_pair(armature, selected_names)
                if mirrored is not None:
                    pairs.append(mirrored)

            total_created = 0
            total_weight_objects = 0
            for pair in pairs:
                created_names = []
                for fan_kind, count in fan_kinds:
                    created_names.extend(
                        BoneFanCore._create_fan_bones(
                            armature,
                            pair,
                            fan_kind,
                            count,
                            settings.length_factor,
                            settings.pin_length_factor,
                            settings.bone_collection_name,
                            settings.influence_in if fan_kind == "in" else settings.influence_out,
                        )
                    )
                total_created += len(created_names)

                if settings.auto_transfer_weights and created_names:
                    weight_result = BoneFanCore.apply_fan_weights(
                        context,
                        armature,
                        pair,
                        created_names,
                        settings.fan_weight_radius,
                        settings.fan_weight_blur,
                        settings.only_selected,
                    )
                    total_weight_objects += weight_result["processed_objects"]

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            pair_note = "（含对称）" if len(pairs) > 1 else ""
            if not settings.auto_transfer_weights:
                self.report({"INFO"}, f"已生成 {total_created} 根 fan 骨{pair_note}")
            else:
                self.report(
                    {"INFO"},
                    f"已生成 {total_created} 根 fan 骨{pair_note}，"
                    f"在 {total_weight_objects} 个物体上转移了权重",
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
    bl_label = "删除 fan 骨"
    bl_description = "删除选中主骨对应的 fan 骨，并把权重恢复回主骨"
    bl_options = {"REGISTER", "UNDO"}

    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
    )  # type: ignore
    process_vertex_groups: BoolProperty(
        name="处理顶点组",
        description="删除 fan 骨时反向恢复权重到主骨并清理对应顶点组",
        default=True,
    )  # type: ignore

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

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "process_vertex_groups")

        sub = layout.column()
        sub.enabled = self.process_vertex_groups
        sub.prop(self, "only_selected")

    def execute(self, context):
        armature = context.active_object
        original_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        was_hidden = armature.hide_viewport

        only_selected = self.only_selected

        selected_names = BoneFanCore._selected_bone_names(context, armature)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if armature.mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            # 动手之前先确定要删除哪些 fan/pin 骨，以及每根 deform fan 把权重
            # 还给哪根主骨。
            removal_names = BoneFanCore._collect_fan_bone_names(armature, selected_names)
            if not removal_names:
                self.report({"WARNING"}, "没有找到可删除的 fan 骨")
                return {"CANCELLED"}

            BoneFanCore._assert_safe_to_remove_fan_bones(armature, removal_names)
            main_to_fans = BoneFanCore._build_fan_restore_map(armature, removal_names)

            # 先反向恢复权重（每个网格需要在物体模式下处理），再回到编辑模式删骨。
            restored_objects = 0
            removed_groups = 0
            if self.process_vertex_groups:
                mesh_objs = BoneFanCore._collect_mesh_objects_for_armature(armature)
                if only_selected:
                    mesh_objs = [obj for obj in mesh_objs if obj.select_get()]

                for obj in mesh_objs:
                    groups = BoneFanCore.obj_fan_restore(obj, main_to_fans)
                    if groups > 0:
                        restored_objects += 1
                    removed_groups += groups

            if armature.mode != "EDIT":
                bpy.context.view_layer.objects.active = armature
                BoneSplitCore.set_object_mode(armature, "EDIT")

            removed = BoneFanCore._remove_fan_bones(armature, removal_names)

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            self.report(
                {"INFO"},
                f"已删除 {removed} 根 fan 骨，在 {restored_objects} 个物体上恢复了权重"
                f"（{removed_groups} 个顶点组）",
            )
            return {"FINISHED"}
        except Exception as e:
            # FanRemovalBlockedError 也会走这里：把阻断原因直接报给用户。
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
