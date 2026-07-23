import bpy
import math
import numpy as np
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty, PointerProperty
from bpy.types import Context, Operator, PropertyGroup, UILayout
from mathutils import Vector

import gpu
from bpy_extras import view3d_utils
import blf

from ..boneUtils import BoneUtils
from .auxUtils import AuxPreviewUtils


EPS = 1e-6
HoRig_Twist = "HoRig_Twist"


def _twist_preview_update(self, context):
    if context is None:
        return
    scene = getattr(context, "scene", None)
    settings = getattr(scene, "ho_twist_settings", None) if scene is not None else None
    if settings is None:
        return
    if settings.preview_enabled:
        TwistBonePreview.show(context)
    else:
        TwistBonePreview.clear()


def _draw_twist_preview():
    TwistBonePreview._draw_3d()


def _draw_twist_preview_2d():
    TwistBonePreview._draw_2d()


class PG_Hotools_TwistSettings(PropertyGroup):
    ui_expanded: BoolProperty(
        name="twist 设置",
        description="展开 Twist 骨生成设置",
        default=False,
        update=_twist_preview_update,
    )  # type: ignore
    preview_enabled: BoolProperty(
        name="预览",
        description="在 3D 视图中绘制 Twist 分割预览",
        default=False,
        update=_twist_preview_update,
    )  # type: ignore
    count: IntProperty(
        name="细分段数",
        description="Twist 细分数量；关闭保留头端权重时会生成完整数量",
        min=2,
        default=4,
        update=_twist_preview_update,
    )  # type: ignore
    twist_length_factor: FloatProperty(
        name="Twist 长度",
        description="Twist 子骨长度相对于主骨长度的比例",
        min=0.0,
        max=1.0,
        step=0.01,
        default=0.1,
        update=_twist_preview_update,
    )  # type: ignore
    process_symmetry: BoolProperty(
        name="对称操作",
        description="同时处理镜像骨骼",
        default=False,
        update=_twist_preview_update,
    )  # type: ignore
    copy_rotation_top_influence: FloatProperty(
        name="上约束强度",
        description="链顶部 Twist 的 Copy Rotation 强度",
        default=0.1,
        min=0.0,
        max=1.0,
        update=_twist_preview_update,
    )  # type: ignore
    copy_rotation_bottom_influence: FloatProperty(
        name="下约束强度",
        description="链底部 Twist 的 Copy Rotation 强度",
        default=0.8,
        min=0.0,
        max=1.0,
        update=_twist_preview_update,
    )  # type: ignore
    auto_transfer_weights: BoolProperty(
        name="自动处理权重",
        description="生成 Twist 骨后自动把权重转移到新骨骼",
        default=True,
        update=_twist_preview_update,
    )  # type: ignore
    # 这个开关会同时影响骨链生成和权重转移：
    # 开启后保留主骨头端的一小段权重，让编号最大的 Twist 落在头侧，
    # 方便和旁边的 fan 骨做拆权；关闭时回到完整数量和尾端保留方式。
    keep_head_end_weight: BoolProperty(
        name="保留头端权重",
        description="让主骨保留头端一小段权重；编号最大的 Twist 会贴近头侧",
        default=True,
        update=_twist_preview_update,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅处理选中的物体权重",
        description="只处理当前被选中的网格物体",
        default=False,
    )  # type: ignore
    soft_factor: FloatProperty(
        name="过渡",
        description="Twist 骨之间的权重过渡",
        min=0.0,
        max=1.0,
        step=0.05,
        default=1.0,
    )  # type: ignore
    bone_collection_name: StringProperty(
        name="输出到骨骼集合",
        description="生成的Twsit骨放入指定的骨骼集合中，若不存在则创建",
        default=HoRig_Twist,
    )  # type: ignore


def reg_props():
    if hasattr(bpy.types.Scene, "ho_twist_settings"):
        del bpy.types.Scene.ho_twist_settings
    bpy.types.Scene.ho_twist_settings = PointerProperty(type=PG_Hotools_TwistSettings)


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_twist_settings"):
        del bpy.types.Scene.ho_twist_settings


_safe_normalized_vector = AuxPreviewUtils.safe_normalized_vector
_clamp = AuxPreviewUtils.clamp


class TwistBonePreview:
    """Twist 分割预览：在每个 Twist 骨的落点画一个垂直于主骨的圆盘，
    并用指向线 + 文字标出该 Twist 的名字和 Copy Rotation 约束强度。

    运行原理：
    - 选中一根主骨后，按生成逻辑算出各 Twist 骨的落点（head 位置）和
      对应的约束强度（沿链从上约束强度线性过渡到下约束强度）。
    - 3D（POST_VIEW）handler 在视图里画圆盘和落点（GPU）。
    - 2D（POST_PIXEL）handler 把落点投影到屏幕，画一条指向线，
      末端用 blf 标出 Twist 骨名和强度（风格对齐 humanoid 预览）。
    - 一个定时器在预览开启时持续刷新状态，跟随骨骼/参数变化。
    """
    _handler_3d = None
    _handler_2d = None
    _timer_running = False
    _timer_interval = 0.08
    _state = None

    # 指向线 / 标签布局（像素），对齐 humanoid 预览风格
    _line_length_x = 48
    _line_length_y = 18
    _line_end_offset_x = 14
    _line_end_offset_y = 12
    _label_stagger = 14
    _font_size = 15

    @classmethod
    def ensure_handler(cls):
        if cls._handler_3d is None:
            cls._handler_3d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_twist_preview,
                (),
                "WINDOW",
                "POST_VIEW",
            )
        if cls._handler_2d is None:
            cls._handler_2d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_twist_preview_2d,
                (),
                "WINDOW",
                "POST_PIXEL",
            )

    @classmethod
    def show(cls, context):
        cls.ensure_handler()
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "ho_twist_settings", None) if scene is not None else None
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
            "disks": [],
            "message": "",
            "region": region,
            "region_data": region_data,
        }

        if armature is None or armature.type != "ARMATURE":
            state["message"] = "预览需要一个骨架"
        else:
            disks, error = cls._compute_disks(context, armature, settings)
            if error:
                state["message"] = error
            else:
                state["armature_name"] = armature.name
                state["disks"] = disks

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

        settings = getattr(getattr(bpy.context, "scene", None), "ho_twist_settings", None)
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
    def _compute_disks(cls, context, armature, settings):
        """算出每个 Twist 骨的落点（世界空间）、约束强度和圆盘半径。

        选中一根主骨；若开启对称处理，则把镜像骨（.L/.R）的圆盘也一并算出，
        这样预览里能直接同时看到两侧。
        """
        selected = BoneUtils.selected_bone_names(context, armature)
        if len(selected) != 1:
            return None, "请正好选择一根主骨"

        bone_names = [selected[0]]
        if getattr(settings, "process_symmetry", False):
            flipped = bpy.utils.flip_name(selected[0])
            if flipped != selected[0] and flipped not in bone_names:
                exists = (
                    armature.data.edit_bones.get(flipped) is not None
                    if armature.mode == "EDIT"
                    else armature.data.bones.get(flipped) is not None
                )
                if exists:
                    bone_names.append(flipped)

        all_disks = []
        for bone_name in bone_names:
            disks, error = cls._compute_disks_for_bone(armature, settings, bone_name)
            if error:
                # 主骨自身出错才算失败；镜像骨缺失/异常只是跳过。
                if bone_name == selected[0]:
                    return None, error
                continue
            all_disks.extend(disks)

        return all_disks, None

    @classmethod
    def _compute_disks_for_bone(cls, armature, settings, bone_name):
        """对单根主骨计算圆盘。几何完全对齐生成逻辑：
        - 把主骨从 head 到 tail 均分成 count 段，落点取各分段端点。
        - 开启“保留头端权重”时只生成 count-1 根、并整体偏移 1 段（头侧留缓冲）。
        - 约束强度沿链从上约束强度线性过渡到下约束强度。
        """
        head_local = tail_local = None
        if armature.mode == "EDIT":
            eb = armature.data.edit_bones.get(bone_name)
            if eb is not None:
                head_local, tail_local = eb.head.copy(), eb.tail.copy()
        else:
            db = armature.data.bones.get(bone_name)
            if db is not None:
                head_local = db.head_local.copy()
                tail_local = db.tail_local.copy()
        if head_local is None or tail_local is None:
            return None, "找不到选中的骨骼"

        bone_vec = tail_local - head_local
        if bone_vec.length <= 1e-8:
            return None, "骨骼长度为 0"

        count = max(2, int(settings.count))
        keep_head = bool(settings.keep_head_end_weight)
        twist_count = max(count - 1 if keep_head else count, 0)
        if twist_count <= 0:
            return None, "细分段数过小"
        point_offset = 1 if keep_head else 0

        top = float(settings.copy_rotation_top_influence)
        bottom = float(settings.copy_rotation_bottom_influence)

        mw = armature.matrix_world
        bone_dir_world = _safe_normalized_vector(mw.to_3x3() @ bone_vec)
        if bone_dir_world is None:
            return None, "无法计算骨骼方向"

        # 在垂直于主骨方向的平面里取两条正交轴，用来铺圆盘
        ref = Vector((0.0, 0.0, 1.0))
        if abs(bone_dir_world.dot(ref)) > 0.95:
            ref = Vector((1.0, 0.0, 0.0))
        axis_x = _safe_normalized_vector(bone_dir_world.cross(ref))
        if axis_x is None:
            return None, "无法计算圆盘平面"
        axis_y = _safe_normalized_vector(bone_dir_world.cross(axis_x))
        if axis_y is None:
            return None, "无法计算圆盘平面"

        bone_len_world = (mw.to_3x3() @ bone_vec).length
        radius = max(bone_len_world * 0.12, EPS)

        padding = max(2, len(str(count)))
        disks = []
        for j in range(twist_count):
            t = (j + point_offset) / count
            center_local = head_local.lerp(tail_local, t)
            center_world = mw @ center_local
            if twist_count <= 1:
                influence = bottom
            else:
                influence = top + (bottom - top) * (j / (twist_count - 1))
            # 命名与 create_twist_chain 对齐：第 j 根的编号是 count - j
            twist_name = TwistBoneCore._twist_name(bone_name, count - j, padding)
            disks.append({
                "center": center_world,
                "axis_x": axis_x,
                "axis_y": axis_y,
                "radius": radius,
                "influence": influence,
                "name": twist_name,
            })

        return disks, None

    @classmethod
    def _draw_3d(cls):
        state = cls._state
        if state is None:
            return

        if state.get("message"):
            return

        disks = state.get("disks", [])
        if not disks:
            return

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        gpu.state.line_width_set(2.0)
        gpu.state.point_size_set(6.0)
        try:
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            shader.bind()
            segments = 48
            for disk in disks:
                center = disk["center"]
                axis_x = disk["axis_x"]
                axis_y = disk["axis_y"]
                radius = disk["radius"]

                ring = []
                AuxPreviewUtils.append_circle(ring, center, axis_x, axis_y, radius, segments)

                AuxPreviewUtils.draw_lines(shader, ring, (0.2, 0.9, 1.0, 0.95))

                AuxPreviewUtils.draw_points(
                    shader, [tuple(center)], (1.0, 0.65, 0.15, 1.0), size=6.0
                )
        finally:
            gpu.state.point_size_set(1.0)
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")

    @classmethod
    def _draw_2d(cls):
        state = cls._state
        if state is None:
            return

        context = bpy.context
        region = context.region
        rv3d = context.region_data
        font_id = 0

        message = state.get("message", "")
        if message:
            blf.size(font_id, cls._font_size)
            blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
            blf.position(font_id, 20.0, 20.0, 0.0)
            blf.draw(font_id, f"twist 预览: {message}")
            return

        disks = state.get("disks", [])
        if not disks or region is None or rv3d is None:
            return

        line_shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(1.5)
        try:
            for index, disk in enumerate(disks):
                pos_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, disk["center"])
                if pos_2d is None:
                    continue

                x, y = pos_2d
                label_x = x + cls._line_length_x
                label_y = y + cls._line_length_y + (index % 3) * cls._label_stagger

                coords = [
                    (x, y),
                    (label_x - cls._line_end_offset_x, label_y + cls._line_end_offset_y),
                ]
                AuxPreviewUtils.draw_lines(line_shader, coords, (0.1, 0.85, 1.0, 0.85))

                label = f"{disk['name']}  ({disk['influence']:.2f})"
                AuxPreviewUtils.draw_label(
                    font_id, label, (label_x, label_y), (0.85, 0.97, 1.0, 1.0), cls._font_size
                )
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.blend_set("NONE")


def drawBoneTwistPanel(layout: UILayout, context: Context):
    settings = context.scene.ho_twist_settings
    twist_box = layout.box()

    header = twist_box.row(align=True)
    header.prop(
        settings,
        "ui_expanded",
        text="",
        icon="TRIA_DOWN" if settings.ui_expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text="twist扭转柔性跟随")

    row = header.row(align=True)
    row.operator(OP_TwistBoneWithWeight.bl_idname, text="生成")

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

    col = twist_box.column(align=True)
    col.separator()
    col.prop(settings, "count")
    col.prop(settings, "twist_length_factor")

    col.separator()
    row = col.row(align=True)
    row.prop(settings, "copy_rotation_top_influence")
    row.prop(settings, "copy_rotation_bottom_influence")

    col.separator()
    col.prop(settings, "bone_collection_name")
    col.prop(settings, "process_symmetry")
    # 保留头端权重会同时影响骨链生成和预览，所以不受“自动处理权重”限制
    col.prop(settings, "keep_head_end_weight")
    col.prop(settings, "auto_transfer_weights")

    sub = col.column(align=True)
    sub.enabled = settings.auto_transfer_weights
    sub.prop(settings, "only_selected")
    sub.prop(settings, "soft_factor")


def draw_panel(layout, context):
    drawBoneTwistPanel(layout, context)


class TwistBoneCore:
    # 该核心生成的辅助骨类型，与 hotools_boneprops.auxBone.auxType 一致；约束命名前缀按它区分。
    AUX_TYPE = "TWIST"

    @staticmethod
    def _twist_name(base_name: str, index: int, padding: int) -> str:
        stem, side_suffix = BoneUtils.split_side_suffix(base_name)
        return f"{stem}_twist_{index:0{padding}d}{side_suffix}"

    @staticmethod
    def _parse_twist_name(name: str) -> tuple[str, int] | None:
        stem, side_suffix = BoneUtils.split_side_suffix(name)
        marker = "_twist_"
        marker_index = stem.rfind(marker)
        if marker_index < 0:
            return None

        index_text = stem[marker_index + len(marker):]
        if not index_text.isdigit():
            return None

        main_stem = stem[:marker_index]
        if not main_stem:
            return None

        return f"{main_stem}{side_suffix}", int(index_text)

    @staticmethod
    def _rotate_vector_around_axis(vector, axis, angle_rad):
        return AuxPreviewUtils.rotate_vector_around_axis(vector, axis, angle_rad)

    @staticmethod
    def _apply_hotools_bone_props(
        armature: bpy.types.Object,
        bone_names: list[str],
        aux_type: str = "NONE",
        source_bones: list[str] | None = None,
    ) -> None:
        """给生成的辅助骨写入 HoTools 属性。

        - generateMCH 一律置 False（辅助骨保留旋转，带变换直接进引擎，不走 MCH 清零流程）。
        - 当 aux_type 不为 NONE 时，同时写入辅助骨自描述信息：isAuxBone、
          auxType 与关联骨集合 sourceBones（用于后续精确识别骨上挂了什么辅助骨）。
        """
        source_bones = source_bones or []
        for bone_name in bone_names:
            bone = armature.data.bones.get(bone_name)
            props = getattr(bone, "hotools_boneprops", None) if bone else None
            if not props:
                continue
            if hasattr(props, "generateMCH"):
                props.generateMCH = False
            aux = getattr(props, "auxBone", None)
            if aux is not None and aux_type != "NONE":
                aux.isAuxBone = True
                aux.auxType = aux_type
                aux.sourceBones.clear()
                for src in source_bones:
                    if not src:
                        continue
                    ref = aux.sourceBones.add()
                    ref.name = src

    @staticmethod
    def _find_copy_rotation_target_bone(
        armature: bpy.types.Object,
        source_bones: list[str],
        manual_target: str = "",
    ) -> str | None:
        if manual_target and armature.data.bones.get(manual_target):
            return manual_target

        selected_set = set(source_bones)
        for source_name in source_bones:
            source_bone = armature.data.bones.get(source_name)
            if source_bone is None:
                continue
            for child in source_bone.children:
                if child.name not in selected_set:
                    return child.name
        return None

    @staticmethod
    def _ensure_copy_rotation_constraint(
        pose_bone,
        target_armature: bpy.types.Object,
        target_bone_name: str,
        influence: float = 1.0,
    ):
        name = BoneUtils.aux_constraint_name(TwistBoneCore.AUX_TYPE, "CopyRotation")
        constraint = None
        for item in pose_bone.constraints:
            if item.type == "COPY_ROTATION" and item.name == name:
                constraint = item
                break

        if constraint is None:
            constraint = pose_bone.constraints.new("COPY_ROTATION")
            constraint.name = name

        constraint.target = target_armature
        constraint.subtarget = target_bone_name
        constraint.owner_space = "LOCAL"
        constraint.target_space = "LOCAL_OWNER_ORIENT"
        constraint.mix_mode = "REPLACE"
        constraint.influence = max(0.0, min(1.0, influence))
        constraint.use_x = True
        constraint.use_y = True
        constraint.use_z = True
        return constraint

    @staticmethod
    def _ensure_stretch_to_constraint(
        pose_bone,
        target_armature: bpy.types.Object,
        target_bone_name: str,
    ):
        name = BoneUtils.aux_constraint_name(TwistBoneCore.AUX_TYPE, "StretchTo")
        constraint = None
        for item in pose_bone.constraints:
            if item.type == "STRETCH_TO" and item.name == name:
                constraint = item
                break

        if constraint is None:
            constraint = pose_bone.constraints.new("STRETCH_TO")
            constraint.name = name

        constraint.target = target_armature
        constraint.subtarget = target_bone_name
        constraint.volume = "NO_VOLUME"
        constraint.keep_axis = "SWING_Y"
        constraint.influence = 1.0
        return constraint

    @staticmethod
    def add_copy_rotation_to_twist_bones(
        context: Context,
        armature: bpy.types.Object,
        source_bones: list[str],
        twist_bone_names: list[str],
        manual_target: str = "",
        top_influence: float = 0.1,
        bottom_influence: float = 0.8,
    ) -> tuple[int, dict[str, str]]:
        source_set = set(source_bones)
        source_to_twists: dict[str, list[str]] = {}
        for bone_name in twist_bone_names:
            parsed = TwistBoneCore._parse_twist_name(bone_name)
            if parsed is None:
                continue
            main_name = parsed[0]
            if main_name not in source_set:
                continue
            source_to_twists.setdefault(main_name, []).append(bone_name)

        if not source_to_twists:
            return 0, {}

        old_mode = armature.mode
        old_active = context.view_layer.objects.active
        added = 0
        targets: dict[str, str] = {}

        try:
            armature.select_set(True)
            context.view_layer.objects.active = armature
            BoneUtils.set_object_mode(armature, "POSE")
            for source_index, (source_bone_name, twist_list) in enumerate(source_to_twists.items()):
                target_manual = manual_target if source_index == 0 else ""
                target_bone_name = TwistBoneCore._find_copy_rotation_target_bone(
                    armature,
                    [source_bone_name],
                    target_manual,
                )
                if not target_bone_name:
                    continue
                targets[source_bone_name] = target_bone_name

                total = len(twist_list)
                for index, bone_name in enumerate(twist_list):
                    pose_bone = armature.pose.bones.get(bone_name)
                    if pose_bone is None:
                        continue
                    if total <= 1:
                        influence = bottom_influence
                    else:
                        t = index / (total - 1)
                        influence = top_influence + (bottom_influence - top_influence) * t
                    TwistBoneCore._ensure_copy_rotation_constraint(
                        pose_bone,
                        armature,
                        target_bone_name,
                        influence,
                    )
                    TwistBoneCore._ensure_stretch_to_constraint(
                        pose_bone,
                        armature,
                        target_bone_name,
                    )
                    added += 1
        finally:
            context.view_layer.objects.active = old_active
            BoneUtils.set_object_mode(armature, old_mode)

        return added, targets

    @staticmethod
    def _resolve_joint_geometry(bone_a, bone_b):
        if (bone_a.tail - bone_b.head).length <= 1e-4:
            parent_bone = bone_a
            child_bone = bone_b
            joint = (bone_a.tail + bone_b.head) * 0.5
        elif (bone_b.tail - bone_a.head).length <= 1e-4:
            parent_bone = bone_b
            child_bone = bone_a
            joint = (bone_b.tail + bone_a.head) * 0.5
        else:
            return None, "两根骨骼必须首尾相接并形成关节"

        parent_dir = _safe_normalized_vector(parent_bone.head - joint)
        child_dir = _safe_normalized_vector(child_bone.tail - joint)
        if parent_dir is None or child_dir is None:
            return None, "关节两侧骨骼太短，无法生成 fan 骨"

        dot = _clamp(parent_dir.dot(child_dir), -1.0, 1.0)
        angle_rad = math.acos(dot)
        if angle_rad <= math.radians(1.0) or angle_rad >= math.radians(179.0):
            return None, "两根骨骼夹角过小或过直，无法生成 fan 骨"

        plane_normal = _safe_normalized_vector(parent_dir.cross(child_dir))
        if plane_normal is None:
            return None, "无法计算工作平面法线"

        fan_in_axis = _safe_normalized_vector(parent_dir + child_dir)
        if fan_in_axis is None:
            return None, "无法计算 fan 中心线"

        parent_length = (parent_bone.head - joint).length
        child_length = (child_bone.tail - joint).length

        return {
            "parent_bone": parent_bone,
            "child_bone": child_bone,
            "joint": joint,
            "parent_dir": parent_dir,
            "child_dir": child_dir,
            "plane_normal": plane_normal,
            "fan_in_axis": fan_in_axis,
            "base_length": min(parent_length, child_length),
        }, None

    @staticmethod
    def _build_angles(count: int, spread_deg: float) -> list[float]:
        if count <= 1:
            return [0.0]
        if spread_deg <= 0.0:
            return [0.0 for _ in range(count)]

        half = spread_deg * 0.5
        step = spread_deg / (count - 1)
        return [-half + i * step for i in range(count)]

    @staticmethod
    def _choose_parent_bone(direction, a_bone, a_dir, b_bone, b_dir):
        score_a = direction.dot(a_dir)
        score_b = direction.dot(b_dir)
        if abs(score_a - score_b) < 1e-6:
            return a_bone
        return a_bone if score_a > score_b else b_bone

    @staticmethod
    def create_twist_chain(
        armature: bpy.types.Object,
        bn: str,
        count: int,
        twist_length_factor: float = 0.1,
        keep_head_end_weight: bool = True,
        bone_collection_name: str = HoRig_Twist,
    ) -> dict:
        """在保留主骨的前提下，生成 Twist 子骨链。"""
        was_hidden = armature.hide_viewport
        old_mode = armature.mode
        mirror_state = BoneUtils.set_temp_armature_mirror_off(armature)
        result = {
            "source_bone": bn,
            "created_names": [],
            "created_count": 0,
            "replaced_names": [],
            "replaced_count": 0,
        }

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            BoneUtils.set_object_mode(armature, "EDIT")

            edit_bones = armature.data.edit_bones
            old_bone = edit_bones.get(bn)
            if old_bone is None:
                raise Exception(f"在编辑模式中未找到骨骼: {bn}")

            bone_vec = old_bone.tail - old_bone.head
            if bone_vec.length <= 1e-8:
                raise Exception(f"骨骼长度为 0: {bn}")

            bone_dir = bone_vec.normalized()
            twist_length = max(bone_vec.length * twist_length_factor, 1e-4)
            # 开启“保留头端权重”时，把 count 解释为“总分段数”，
            # 并只生成 count - 1 根 Twist。
            # 主骨先保留头端 1 段缓冲区，Twist 链从下一段开始排布。
            # 这样编号最大的 Twist 会贴在头侧，方便和旁边的 fan 骨拆权。
            # 关闭时则沿用旧逻辑，生成完整 count 根 Twist，
            # 让骨链、权重和约束都按没有特殊保留时的传统流程处理。
            twist_count = max(count - 1 if keep_head_end_weight else count, 0)
            padding = max(2, len(str(count)))
            new_bone_names = [
                TwistBoneCore._twist_name(bn, count - i, padding)
                for i in range(twist_count)
            ]

            existed: list[tuple[int, str]] = []
            for bone in list(edit_bones):
                parsed = TwistBoneCore._parse_twist_name(bone.name)
                if parsed is None or parsed[0] != bn:
                    continue
                existed.append((parsed[1], bone.name))
            if existed:
                existed.sort(key=lambda item: item[0], reverse=True)
                result["replaced_names"] = [name for _, name in existed]
                result["replaced_count"] = len(existed)
                for _, name in existed:
                    old_twist = edit_bones.get(name)
                    if old_twist is not None:
                        edit_bones.remove(old_twist)

            corrected_points = [
                old_bone.head.lerp(old_bone.tail, i / count)
                for i in range(count + 1)
            ]
            point_offset = 1 if keep_head_end_weight else 0

            for i, new_name in enumerate(new_bone_names, start=1):
                new_bone = edit_bones.new(new_name)
                new_bone.head = corrected_points[i - 1 + point_offset].copy()
                new_bone.tail = new_bone.head + bone_dir * twist_length
                new_bone.roll = 0.0
                new_bone.use_deform = True
                new_bone.parent = old_bone
                new_bone.use_connect = False

            BoneUtils.assign_bones_to_collection(armature, new_bone_names, bone_collection_name)
            bpy.context.view_layer.objects.active = armature
            BoneUtils.set_object_mode(armature, "OBJECT")
            # 设置 hotools 属性：辅助骨不走 MCH 流程(保留旋转)，并写入辅助骨自描述信息
            TwistBoneCore._apply_hotools_bone_props(
                armature,
                new_bone_names,
                aux_type="TWIST",
                source_bones=[bn],
            )
            result["created_names"] = new_bone_names
            result["created_count"] = len(new_bone_names)

            return result
        finally:
            BoneUtils.restore_armature_mirror_state(mirror_state)

            try:
                if armature.mode != old_mode:
                    bpy.context.view_layer.objects.active = armature
                    BoneUtils.set_object_mode(armature, old_mode)
            except Exception:
                pass

            if was_hidden:
                armature.hide_set(True)

    @staticmethod
    def splitVertexGroup_withTmp_along_source(
        obj,
        new_bone_names,
        count,
        armature,
        source_bone_name,
        tmp_vg,
        soft_factor,
        keep_head_end_weight,
        source_vg,
    ):
        old_mode = obj.mode
        mirror_state = BoneUtils.set_temp_mesh_mirror_off(obj)

        try:
            if old_mode == "EDIT":
                bpy.context.view_layer.objects.active = obj
                BoneUtils.set_object_mode(obj, "OBJECT")

            if source_vg is None:
                raise Exception(f"未找到源顶点组: {source_bone_name}")

            new_vgs: list[bpy.types.VertexGroup] = []
            for new_name in new_bone_names:
                vg = obj.vertex_groups.new(name=new_name)
                new_vgs.append(vg)

            twist_count = len(new_vgs)
            if twist_count == 0:
                obj.vertex_groups.remove(tmp_vg)
                return

            source_bone = armature.data.bones.get(source_bone_name)
            if source_bone is None:
                raise Exception(f"未找到源骨骼: {source_bone_name}")

            mesh_inv = obj.matrix_world.inverted()
            chain_start_world = armature.matrix_world @ source_bone.head_local
            chain_end_world = armature.matrix_world @ source_bone.tail_local
            chain_start_local = mesh_inv @ chain_start_world
            chain_end_local = mesh_inv @ chain_end_world
            chain_vec = chain_end_local - chain_start_local
            chain_len_sq = chain_vec.length_squared
            if chain_vec.length == 0:
                raise Exception("源骨骼长度为 0")

            n_verts = len(obj.data.vertices)
            if n_verts == 0:
                obj.vertex_groups.remove(tmp_vg)
                return

            verts_np = np.array([list(v.co) for v in obj.data.vertices], dtype=float)
            weights_np = np.zeros(n_verts, dtype=float)
            has_weight_np = np.zeros(n_verts, dtype=bool)
            # 先把主骨该保留的权重记到临时数组里，再在循环结束后一次性回填。
            # 这样可以避免中途改写主骨顶点组时留下半成品状态，也方便把末端那段
            # 权重稳定地留给主骨，而不是分到不存在的最后一根 Twist 上。
            source_weights_np = np.zeros(n_verts, dtype=float)
            for i in range(n_verts):
                try:
                    weights_np[i] = tmp_vg.weight(i)
                    has_weight_np[i] = True
                except RuntimeError:
                    weights_np[i] = 0.0

            diff = verts_np - np.array(list(chain_start_local), dtype=float)
            chain_vec_np = np.array(list(chain_vec), dtype=float)
            f = np.dot(diff, chain_vec_np) / chain_len_sq
            f = np.clip(f, 0.0, 1.0)

            # 权重链也按同样的顺序拆成“保留段 + Twist 段”或“Twist 段 + 保留段”。
            # keep_head_end_weight=True 时，source_vg 放在链条最前面，
            # 主骨先保留头端一小段权重，再把后面的权重分给 Twist。
            # 这样可以留出一小段给主骨，方便和隔壁 fan 骨一起拆权。
            # False 时保持旧逻辑，把保留段放到尾端。
            segment_targets = ([source_vg] + new_vgs) if keep_head_end_weight else (new_vgs + [source_vg])
            logical_count = len(segment_targets)
            if logical_count <= 0:
                obj.vertex_groups.remove(tmp_vg)
                return
            pos = f * logical_count - 0.5
            pos = np.clip(pos, 0, logical_count - 1)
            i_seg = np.floor(pos).astype(int)
            local_factor = pos - i_seg

            def _calc_blend(local_value: float) -> float:
                if soft_factor == 0.0:
                    return 0.0 if local_value < 0.5 else 1.0
                if soft_factor == 1.0:
                    return 0.5 * (1 - math.cos(math.pi * local_value))

                step_val = 0.0 if local_value < 0.5 else 1.0
                cos_val = 0.5 * (1 - math.cos(math.pi * local_value))
                return (1 - soft_factor) * step_val + soft_factor * cos_val

            for i in range(n_verts):
                if not has_weight_np[i]:
                    continue

                orig_w = weights_np[i]
                seg = i_seg[i]
                lf = local_factor[i]

                if seg >= logical_count - 1:
                    target = segment_targets[-1]
                    if target is source_vg:
                        source_weights_np[i] += orig_w
                    else:
                        target.add([i], orig_w, "REPLACE")
                    continue

                blend = max(0.0, min(_calc_blend(lf), 1.0))
                left_target = segment_targets[seg]
                right_target = segment_targets[seg + 1]
                left_weight = orig_w * (1.0 - blend)
                right_weight = orig_w * blend

                if left_target is source_vg:
                    source_weights_np[i] += left_weight
                else:
                    left_target.add([i], left_weight, "REPLACE")

                if right_target is source_vg:
                    source_weights_np[i] += right_weight
                else:
                    right_target.add([i], right_weight, "REPLACE")

            source_vertex_indices = [v.index for v in obj.data.vertices]
            if source_vertex_indices:
                source_vg.remove(source_vertex_indices)
                for i, weight in enumerate(source_weights_np):
                    if weight != 0.0:
                        source_vg.add([i], float(weight), "REPLACE")

            obj.vertex_groups.remove(tmp_vg)
        finally:
            BoneUtils.restore_mesh_mirror_state(mirror_state)
            if old_mode == "EDIT":
                BoneUtils.set_object_mode(obj, "EDIT")

    @staticmethod
    def obj_twist_transfer(
        obj: bpy.types.Object,
        new_bone_names: list[str],
        count: int,
        armature: bpy.types.Object,
        tmp_vg,
        soft_factor: float,
        keep_head_end_weight: bool,
        source_group_name: str,
    ):
        source_group = obj.vertex_groups.get(source_group_name)
        TwistBoneCore.splitVertexGroup_withTmp_along_source(
            obj,
            new_bone_names,
            count,
            armature,
            source_group_name,
            tmp_vg,
            soft_factor,
            keep_head_end_weight,
            source_group,
        )

    @staticmethod
    def objs_bone_twist(
        bn: str,
        count: int,
        armature: bpy.types.Object,
        soft_factor: float,
        twist_length_factor: float,
        keep_head_end_weight: bool,
        objs,
        bone_collection_name: str = HoRig_Twist,
    ) -> dict:
        """把选中的主骨权重转移到 Twist 子骨链上。"""
        chain_result = TwistBoneCore.create_twist_chain(
            armature,
            bn,
            count,
            twist_length_factor,
            keep_head_end_weight,
            bone_collection_name,
        )
        new_bone_names = chain_result["created_names"]
        replaced_names = chain_result["replaced_names"]

        for obj in objs:
            b_vg = obj.vertex_groups.get(bn)
            if b_vg is None:
                continue

            tmp_name = "TMP_" + bn
            if obj.vertex_groups.get(tmp_name):
                obj.vertex_groups.remove(obj.vertex_groups.get(tmp_name))
            tmp_vg = obj.vertex_groups.new(name=tmp_name)

            for v in obj.data.vertices:
                try:
                    w = b_vg.weight(v.index)
                    tmp_vg.add([v.index], w, "REPLACE")
                except RuntimeError:
                    continue

            TwistBoneCore.obj_twist_transfer(
                obj,
                new_bone_names,
                count,
                armature,
                tmp_vg,
                soft_factor,
                keep_head_end_weight,
                bn,
            )

        chain_result["source_bone"] = bn
        chain_result["weight_object_count"] = len(objs)
        chain_result["target_objects"] = [obj.name for obj in objs]
        chain_result["replaced_names"] = replaced_names
        return chain_result

    @staticmethod
    def _collect_generation_targets(context: Context, original_active: bpy.types.Object):
        armature_obj = None
        mesh_objs = []
        bones = []

        if original_active.type == "ARMATURE":
            armature_obj = original_active
            if armature_obj.mode == "POSE":
                active_bone = context.active_pose_bone
                if active_bone:
                    bones = [active_bone.name]
            elif armature_obj.mode == "EDIT":
                active_bone = armature_obj.data.edit_bones.active
                if active_bone:
                    bones = [active_bone.name]
            mesh_objs = BoneUtils.collect_mesh_objects_for_armature(armature_obj)
        elif original_active.type == "MESH":
            for mod in original_active.modifiers:
                if mod.type == "ARMATURE" and mod.object:
                    armature_obj = mod.object
                    break
            active_bone = context.active_pose_bone
            if active_bone:
                bones = [active_bone.name]
            if armature_obj:
                mesh_objs = BoneUtils.collect_mesh_objects_for_armature(armature_obj)
        else:
            raise Exception("不支持的对象")

        if not armature_obj:
            raise Exception("没有找到骨架")

        if not bones:
            raise Exception("没有找到活动骨骼")
        if len(bones) > 1:
            raise Exception("当前只支持单个活动骨骼")

        return armature_obj, mesh_objs, bones

    @staticmethod
    def generate_twist(
        context: Context,
        original_active: bpy.types.Object,
        count: int,
        twist_length_factor: float = 0.1,
        process_symmetry: bool = False,
        auto_transfer_weights: bool = False,
        keep_head_end_weight: bool = True,
        only_selected: bool = False,
        soft_factor: float = 0.5,
        copy_rotation_target_bone: str = "",
        copy_rotation_top_influence: float = 0.1,
        copy_rotation_bottom_influence: float = 0.8,
        bone_collection_name: str = HoRig_Twist,
    ) -> dict:
        original_mode = original_active.mode
        armature_obj = None
        results = []
        twist_bone_names = []

        try:
            armature_obj, mesh_objs, bones = TwistBoneCore._collect_generation_targets(
                context,
                original_active,
            )

            if process_symmetry:
                # 对称生成需要方向后缀来区分左右：无后缀的中线骨（如 spine、pelvis）
                # 翻转后还是自己，镜像不会产生任何对侧骨，对称形同虚设。此时直接报错
                # 退出，避免用户以为生成了对称骨却没有。
                suffixless = BoneUtils.find_suffixless(bones)
                if suffixless:
                    raise Exception(
                        "对称生成需要方向后缀：骨骼 "
                        + "、".join(suffixless)
                        + " 没有 .L/.R 等后缀，无法区分镜像生成的左右骨。"
                        "请选带方向后缀的骨，或关闭对称生成。"
                    )

                mirrored = []
                for bone_name in bones:
                    mirrored.extend(
                        BoneUtils.get_mirrored_bone(
                            bone_name,
                            armature_obj.data,
                        )
                    )
                bones = list(dict.fromkeys(mirrored))
            else:
                bones = list(dict.fromkeys(bones))

            if auto_transfer_weights:
                if only_selected:
                    mesh_objs = [obj for obj in mesh_objs if obj.select_get()]

                if not mesh_objs:
                    raise Exception("没有找到需要处理的网格物体")

                for bn in bones:
                    objs_with_bone = [obj for obj in mesh_objs if obj.vertex_groups.get(bn)]
                    if not objs_with_bone:
                        continue

                    result = TwistBoneCore.objs_bone_twist(
                        bn,
                        count,
                        armature_obj,
                        soft_factor,
                        twist_length_factor,
                        keep_head_end_weight,
                        objs_with_bone,
                        bone_collection_name,
                    )
                    results.append(result)
                    twist_bone_names.extend(result.get("created_names", []))
            else:
                for bn in bones:
                    result = TwistBoneCore.create_twist_chain(
                        armature_obj,
                        bn,
                        count,
                        twist_length_factor,
                        keep_head_end_weight,
                        bone_collection_name,
                    )
                    results.append(result)
                    twist_bone_names.extend(result.get("created_names", []))

            twist_bone_names = list(dict.fromkeys(twist_bone_names))
            constraint_count, target_map = TwistBoneCore.add_copy_rotation_to_twist_bones(
                context,
                armature_obj,
                bones,
                twist_bone_names,
                copy_rotation_target_bone,
                copy_rotation_top_influence,
                copy_rotation_bottom_influence,
            )
        finally:
            if original_active:
                context.view_layer.objects.active = original_active
                BoneUtils.set_object_mode(original_active, mode=original_mode)

            if original_mode == "WEIGHT_PAINT" and armature_obj is not None:
                armature_obj.select_set(True)
                context.view_layer.objects.active = armature_obj
                BoneUtils.set_object_mode(armature_obj, "POSE")
                original_active.select_set(True)
                context.view_layer.objects.active = original_active
                BoneUtils.set_object_mode(original_active, "WEIGHT_PAINT")

        return {
            "created_count": sum(item.get("created_count", 0) for item in results),
            "replaced_count": sum(item.get("replaced_count", 0) for item in results),
            "constraint_count": constraint_count if "constraint_count" in locals() else 0,
            "constraint_targets": target_map if "target_map" in locals() else {},
            "twist_bone_names": twist_bone_names,
            "items": results,
        }


class OP_TwistBoneWithWeight(Operator):
    bl_idname = "ho.twistbone_withweight"
    bl_label = "生成 Twist 骨与权重"
    bl_description = """
    在所选主骨上生成 Twist 子骨，并可按权重参数同步转移权重。
    适用于姿态模式、编辑模式，以及权重绘制场景下的当前活动骨骼。
    生成时会保留主骨本体，按主骨方向延伸；左右后缀会插在 Twist 后缀之前。
    “保留头端权重”开启时，会让主骨先保留头端一小段权重，
    这样编号最大的 Twist 会落在头侧，方便和旁边的 fan 骨拆权；
    关闭时则沿用旧逻辑，生成完整数量 Twist，并把权重保留段放到尾端。
    需要切分权重时会临时关闭镜像选项，结束后恢复原设置。"""
    bl_options = {"REGISTER", "UNDO"}

    # 目标骨放在弹窗里让用户确认/填写，打开弹窗时会自动推断一个候选。
    copy_rotation_target_bone: StringProperty(
        name="目标骨",
        description="约束指向的目标骨骼（打开时自动推断，可手动修改）",
        default="",
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object

        if not obj or obj.type not in {"MESH", "ARMATURE"}:
            return False

        if obj.type == "ARMATURE":
            if obj.mode == "POSE":
                return bool(context.selected_pose_bones)
            if obj.mode == "EDIT":
                return any(b.select for b in obj.data.edit_bones)
            return False

        armature = None
        for mod in obj.modifiers:
            if mod.type == "ARMATURE" and mod.object:
                armature = mod.object
                break

        if not armature:
            return False

        active_group = obj.vertex_groups.active
        if not active_group:
            return False

        for bone in armature.data.bones:
            if active_group.name == bone.name:
                return True

        return False

    def execute(self, context):
        settings = getattr(context.scene, "ho_twist_settings", None)
        if settings is None:
            self.report({"ERROR"}, "缺少 twist 设置")
            return {"CANCELLED"}

        TwistBonePreview.clear()

        try:
            obj = context.active_object
            selected_count = 0
            if obj and obj.type == "ARMATURE":
                if obj.mode == "POSE":
                    selected_count = len(context.selected_pose_bones or [])
                elif obj.mode == "EDIT":
                    selected_count = sum(1 for bone in obj.data.edit_bones if bone.select)
            if selected_count > 1:
                self.report({"ERROR"}, "当前只支持单个活动骨骼")
                return {"CANCELLED"}

            result = TwistBoneCore.generate_twist(
                context,
                obj,
                settings.count,
                settings.twist_length_factor,
                settings.process_symmetry,
                settings.auto_transfer_weights,
                settings.keep_head_end_weight,
                settings.only_selected,
                settings.soft_factor,
                self.copy_rotation_target_bone,
                settings.copy_rotation_top_influence,
                settings.copy_rotation_bottom_influence,
                settings.bone_collection_name,
            )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            (
                f"Twist骨: 新建 {result['created_count']}，"
                f"替换 {result['replaced_count']}，"
                f"约束 {result.get('constraint_count', 0)}"
            ),
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        # 打开弹窗时自动推断目标骨，用户可在弹窗里确认或修改
        armature = context.active_object
        if armature and armature.type == "ARMATURE":
            selected = BoneUtils.selected_bone_names(context, armature)
            target = TwistBoneCore._find_copy_rotation_target_bone(armature, selected, "")
            if target:
                self.copy_rotation_target_bone = target
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "copy_rotation_target_bone")



@classmethod
def _twist_preview_ensure_handler(cls):
    AuxPreviewUtils.ensure_handlers(cls, _draw_twist_preview, _draw_twist_preview_2d)


@classmethod
def _twist_preview_shutdown(cls):
    AuxPreviewUtils.remove_handlers(cls)
    cls._state = None
    cls._timer_running = False


TwistBonePreview.ensure_handler = _twist_preview_ensure_handler
TwistBonePreview.shutdown = _twist_preview_shutdown
TwistBonePreview._tag_redraw = staticmethod(AuxPreviewUtils.tag_redraw)
TwistBonePreview._find_view3d_region = staticmethod(AuxPreviewUtils.find_view3d_region)
TwistBoneCore._apply_hotools_bone_props = staticmethod(AuxPreviewUtils.set_aux_bone_props)


cls = [
    PG_Hotools_TwistSettings,
    OP_TwistBoneWithWeight,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    TwistBonePreview.shutdown()
    for item in cls:
        bpy.utils.unregister_class(item)
    ureg_props()
