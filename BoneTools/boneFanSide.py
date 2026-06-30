import bpy
from bpy.types import Context, Operator, PropertyGroup, UILayout
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty, PointerProperty, EnumProperty
from math import acos, cos, radians, sin, tau
from mathutils import Vector

from .boneSplit import BoneSplitCore
from .boneFan import (
    BoneFanCore,
    _safe_normalized_vector,
    _clamp,
    _assign_bones_to_collection,
    EPS,
    HoRig_Fan,
)
from .boneFanSingle import BoneFanSingleCore
import gpu
from gpu_extras.batch import batch_for_shader
import blf


def reg_props():
    if hasattr(bpy.types.Scene, "ho_fan_side_settings"):
        del bpy.types.Scene.ho_fan_side_settings
    bpy.types.Scene.ho_fan_side_settings = PointerProperty(type=PG_Hotools_FanSideSettings)


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_fan_side_settings"):
        del bpy.types.Scene.ho_fan_side_settings


def _fan_side_preview_update(self, context):
    if context is None:
        return
    scene = getattr(context, "scene", None)
    settings = getattr(scene, "ho_fan_side_settings", None) if scene is not None else None
    if settings is None:
        return
    if settings.preview_enabled:
        BoneFanSidePreview.show(context)
    else:
        BoneFanSidePreview.clear()


def _fan_side_prefix_preset_update(self, context):
    # 选预设即把对应前缀写入 fan_name_prefix；NONE 不改动，方便手填后保留。
    preset = getattr(self, "fan_name_prefix_preset", "NONE")
    if preset and preset != "NONE":
        self.fan_name_prefix = preset
    _fan_side_preview_update(self, context)


def _fan_side_count_update(self, context):
    _fan_side_preview_update(self, context)


def _draw_fan_side_preview():
    BoneFanSidePreview._draw_3d()


def _draw_fan_side_preview_2d():
    BoneFanSidePreview._draw_2d()


class PG_Hotools_FanSideSettings(PropertyGroup):
    ui_expanded: BoolProperty(
        name="侧向 fan 设置",
        description="展开侧向 fan 骨生成设置",
        default=False,
        update=_fan_side_preview_update,
    )  # type: ignore
    preview_enabled: BoolProperty(
        name="预览",
        description="在 3D 视图中绘制侧向 fan 预览",
        default=False,
        update=_fan_side_preview_update,
    )  # type: ignore
    count: IntProperty(
        name="每侧数量",
        description="每一侧（左/右）的侧向 fan 骨数量；左右两侧完全对称，总数为该值的两倍",
        default=2,
        min=1,
        update=_fan_side_count_update,
    )  # type: ignore
    influence: FloatProperty(
        name="强度",
        description="fan 骨复制旋转约束强度的整体系数，乘到每根 fan 自动计算的"
                    "约束强度上（1 = 原始强度，0 = 完全不约束）",
        default=1.0,
        min=0.0,
        soft_max=1.0,
        update=_fan_side_preview_update,
    )  # type: ignore
    spread_factor: FloatProperty(
        name="展开系数",
        description="侧向扫动总角度相对于关节弯折夹角的比例。fan 以角平分线为中心，"
                    "沿弯折面法线向两侧对称展开，展开半角 = 弯折夹角 × 系数 ÷ 2",
        default=1.0,
        min=0.05,
        soft_max=2.0,
        update=_fan_side_preview_update,
    )  # type: ignore
    length_factor: FloatProperty(
        name="长度系数",
        description="fan 骨长度相对于关节较短一侧骨长的比例",
        default=0.2,
        min=0.01,
        soft_max=1.0,
        update=_fan_side_preview_update,
    )  # type: ignore
    pin_length_factor: FloatProperty(
        name="pin 长度系数",
        description="fanPin 长度相对于 fan 骨长度的比例",
        default=0.2 / 5.0,
        min=0.001,
        soft_max=1.0,
        update=_fan_side_preview_update,
    )  # type: ignore
    auto_transfer_weights: BoolProperty(
        name="自动转移权重",
        description="生成时把两根主骨的权重转移到 fan 骨上",
        default=True,
        update=_fan_side_preview_update,
    )  # type: ignore
    process_symmetry: BoolProperty(
        name="对称操作",
        description="同时在镜像骨对（.L/.R）上生成 fan 骨",
        default=False,
        update=_fan_side_preview_update,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
        update=_fan_side_preview_update,
    )  # type: ignore
    fan_weight_radius: FloatProperty(
        name="权重半径",
        description="权重转移球的半径，相对于关节较短一侧骨长",
        default=0.16,
        min=0.0,
        soft_max=1.0,
        update=_fan_side_preview_update,
    )  # type: ignore
    fan_weight_blur: FloatProperty(
        name="权重模糊",
        description="硬球分割后施加的整体模糊强度（0 = 不模糊，1 = 最大平滑）",
        default=1.0,
        min=0.0,
        soft_max=1.0,
        update=_fan_side_preview_update,
    )  # type: ignore
    midline_threshold: FloatProperty(
        name="中线阈值",
        description="对称操作时，若某顶点到最近的左右 fan 的方向得分差小于该阈值，"
                    "判定它落在中线上，强制把权重在这些 fan 之间均分（0 = 关闭）",
        default=0.02,
        min=0.0,
        soft_max=0.2,
        update=_fan_side_preview_update,
    )  # type: ignore
    midplane_threshold: FloatProperty(
        name="中面距离阈值",
        description="对称操作时，骨架局部 X=0 镜像面附近该距离内的顶点视为正好落在"
                    "中面上，把球内左右 fan 权重均分，保证自身对称体的中线严格对称"
                    "（0 = 关闭几何判定，单位为骨架局部空间长度）",
        default=0.0,
        min=0.0,
        soft_max=0.1,
        update=_fan_side_preview_update,
    )  # type: ignore
    bone_collection_name: StringProperty(
        name="骨骼集合",
        description="生成的 fan 骨所属的骨骼集合名称",
        default=HoRig_Fan,
        update=_fan_side_preview_update,
    )  # type: ignore
    fan_name_prefix_preset: EnumProperty(
        name="前缀预设",
        description="常用部位前缀，选中后写入名称前缀",
        items=[
            ("NONE", "自定义", "不使用预设，手动填写前缀"),
            ("elbow_", "手肘 elbow", "手肘 fan 常用前缀"),
            ("knee_", "膝盖 knee", "膝盖 fan 常用前缀"),
            ("shoulder_", "肩 shoulder", "肩部 fan 常用前缀"),
        ],
        default="NONE",
        update=_fan_side_prefix_preset_update,
    )  # type: ignore
    fan_name_prefix: StringProperty(
        name="名称前缀",
        description=(
            "fan 骨名前缀。最终名为 前缀+父骨基名+方向标记+序号+本侧.L/R。"
            "用于同一关节生成多组 fan 时区分、避免命名冲突。留空则沿用原命名。"
        ),
        default="side_",
        update=_fan_side_preview_update,
    )  # type: ignore


class BoneFanSideCore(BoneFanSingleCore):
    """侧向 fan：主要给脊椎这类近似共线的关节用，沿身体左右两侧对称生成 fan。

    左右方向不能靠两骨的弯折面（脊椎几乎共线，弯折法线/角平分线都是数值噪声，
    会让所有 fan 挤到同一侧）。改为锚定骨架对称轴（局部 X）：
      - bone_axis  = norm(parent_dir - child_dir)  —— 关节处的骨走向（脊椎≈竖直）。
      - lateral    = 局部 X 去掉 bone_axis 分量后归一化 —— 稳健的左右轴。
      - spread_axis= norm(bone_axis × lateral)      —— 前后轴，fan 绕它上下扇形展开。
      - 左侧 fan 以 +lateral 为中心、右侧以 -lateral 为中心，各绕 spread_axis
        在 ±half 内对称展开，half = 展开系数 × 45°。两侧严格镜像。
      - plane_normal 取 spread_axis：权重转移时把顶点方向投影到 {lateral, bone_axis}
        面，正好按左右+上下区分 fan。
    """

    _LATERAL_DEGENERATE = 0.999

    @staticmethod
    def _bone_head_tail(bone):
        if hasattr(bone, "head") and hasattr(bone, "tail"):
            return bone.head.copy(), bone.tail.copy()
        if hasattr(bone, "bone") and hasattr(bone, "matrix"):
            rest_bone = bone.bone
            head = bone.matrix.translation.copy()
            tail = bone.matrix @ Vector((0.0, rest_bone.length, 0.0))
            return head, tail
        raise Exception("不支持的骨骼类型")

    @classmethod
    def _resolve_side_frame(cls, armature, bone_a, bone_b):
        """构造稳健的侧向工作面（不因关节共线而拒绝）。"""
        tolerance = 1e-3

        bone_a_parent = getattr(bone_a, "parent", None)
        bone_b_parent = getattr(bone_b, "parent", None)
        if bone_b_parent == bone_a:
            parent_bone, child_bone = bone_a, bone_b
        elif bone_a_parent == bone_b:
            parent_bone, child_bone = bone_b, bone_a
        else:
            return None, "两根骨骼必须是直接的父子级关系"

        parent_head, parent_tail = cls._bone_head_tail(parent_bone)
        child_head, child_tail = cls._bone_head_tail(child_bone)
        if (parent_tail - child_head).length > tolerance:
            return None, "父子骨骼未相连：父骨末端与子骨头部不重合"

        joint = (parent_tail + child_head) * 0.5
        parent_dir = _safe_normalized_vector(parent_head - joint)
        child_dir = _safe_normalized_vector(child_tail - joint)
        if parent_dir is None or child_dir is None:
            return None, "骨骼长度太短"

        # 关节处骨走向：共线时 parent_dir≈-child_dir，相减得到稳健的轴。
        bone_axis = _safe_normalized_vector(parent_dir - child_dir)
        if bone_axis is None:
            bone_axis = parent_dir

        # 左右轴 = 局部 X 去掉沿骨方向的分量。骨与 X 近似平行（如手臂）时退回到 Y。
        x_axis = Vector((1.0, 0.0, 0.0))
        if abs(bone_axis.dot(x_axis)) >= cls._LATERAL_DEGENERATE:
            ref = Vector((0.0, 1.0, 0.0))
        else:
            ref = x_axis
        lateral = _safe_normalized_vector(ref - bone_axis * ref.dot(bone_axis))
        if lateral is None:
            return None, "无法计算左右对称轴"

        spread_axis = _safe_normalized_vector(bone_axis.cross(lateral))
        if spread_axis is None:
            return None, "无法计算前后轴"

        dot = _clamp(parent_dir.dot(child_dir), -1.0, 1.0)
        angle_rad = acos(dot)

        parent_length = (parent_head - joint).length
        child_length = (child_tail - joint).length

        return {
            "parent_bone": parent_bone,
            "child_bone": child_bone,
            "joint": joint,
            "parent_dir": parent_dir,
            "child_dir": child_dir,
            "bone_axis": bone_axis,
            "lateral": lateral,
            "spread_axis": spread_axis,
            "plane_normal": spread_axis,  # 权重投影面法线（前后轴）
            "angle_rad": angle_rad,
            "base_length": min(parent_length, child_length),
        }, None

    @staticmethod
    def _side_fan_directions(frame, count, spread_factor):
        """返回 [(direction, kind, index), ...]：左右两簇，各绕 spread_axis 上下展开。

        左簇以 +lateral 为中心（标记 left），右簇以 -lateral 为中心（标记 right）。
        每簇 count 根（count 即每侧数量），绕 spread_axis 在 [-half, +half] 内对称分布；
        half = 展开系数 × 45°。index 在簇内按顺序 1..M，配合约束强度公式中间高两端低。
        """
        lateral = frame["lateral"]
        spread_axis = frame["spread_axis"]
        per_side = max(1, count)
        half = max(spread_factor, EPS) * radians(45.0)

        def _angles():
            if per_side == 1:
                return [0.0]
            return [-half + (2.0 * half) * j / (per_side - 1) for j in range(per_side)]

        results = []
        for center, kind in ((lateral, "left"), (-lateral, "right")):
            for idx, angle in enumerate(_angles(), start=1):
                direction = BoneFanCore._rotate_vector_around_axis(center, spread_axis, angle)
                direction = _safe_normalized_vector(direction)
                if direction is None:
                    continue
                results.append((direction, kind, idx))
        return results

    @classmethod
    def _create_side_fan_bones(
        cls,
        armature,
        parent_name,
        child_name,
        count,
        spread_factor,
        length_factor,
        pin_length_factor,
        bone_collection_name=HoRig_Fan,
        influence_scale=1.0,
        name_prefix="",
    ):
        """生成一组侧向 fan 骨（左右两半，绕角平分线沿法线对称展开）。"""
        edit_bones = armature.data.edit_bones
        parent_bone = edit_bones.get(parent_name)
        child_bone = edit_bones.get(child_name)
        if parent_bone is None or child_bone is None:
            raise Exception("找不到选中的骨骼")

        frame, error = cls._resolve_side_frame(armature, parent_bone, child_bone)
        if error:
            raise Exception(error)

        # _resolve_joint_geometry 已按层级判定，重新取回真正的父/子骨
        parent_bone = frame["parent_bone"]
        child_bone = frame["child_bone"]
        joint = frame["joint"]
        parent_dir = frame["parent_dir"]
        child_dir = frame["child_dir"]
        plane_normal = frame["plane_normal"]  # bisector，用于 fan roll 对齐
        base_length = frame["base_length"]

        fan_length = max(base_length * length_factor, EPS)
        pin_length = max(fan_length * pin_length_factor, EPS)

        directions = cls._side_fan_directions(frame, count, spread_factor)
        padding = max(2, len(str(count)))

        # 先查重
        existed = []
        for direction, kind, index in directions:
            fan_name = cls._fan_name(parent_bone.name, kind, index, padding, name_prefix)
            pin_name = cls._fan_pin_name(parent_bone.name, kind, index, padding, name_prefix)
            if edit_bones.get(fan_name) is not None:
                existed.append(fan_name)
            if edit_bones.get(pin_name) is not None:
                existed.append(pin_name)
        if existed:
            raise Exception("fan 骨已存在: " + ", ".join(sorted(set(existed))))

        created_names = []
        pin_names = []
        for direction, kind, index in directions:
            fan_name = cls._fan_name(parent_bone.name, kind, index, padding, name_prefix)
            pin_name = cls._fan_pin_name(parent_bone.name, kind, index, padding, name_prefix)

            pin_bone = edit_bones.new(pin_name)
            pin_bone.head = joint.copy()
            pin_bone.tail = joint + direction * pin_length
            pin_bone.use_connect = False
            pin_bone.use_deform = False
            pin_bone.parent = cls._choose_parent_bone(-direction, parent_bone, parent_dir, child_bone, child_dir)
            try:
                pin_bone.align_roll(plane_normal)
            except Exception:
                pin_bone.roll = 0.0

            fan_bone = edit_bones.new(fan_name)
            fan_bone.head = joint.copy()
            fan_bone.tail = joint + direction * fan_length
            fan_bone.use_connect = False
            fan_bone.use_deform = True
            # fan 按偏向二选一跟随父骨 / 子骨，决定它从哪个权重通道取权
            fan_bone.parent = cls._choose_parent_bone(direction, parent_bone, parent_dir, child_bone, child_dir)
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
    def apply_fan_weights_side_multi(
        cls,
        context,
        armature,
        sites_spec,
        radius_factor,
        blur_factor,
        only_selected,
        midline_threshold=0.0,
        midplane_threshold=0.0,
    ):
        """侧向 fan 的对称感知权重转移：与父类 apply_fan_weights_multi 同构，

        差别仅在用 _resolve_side_frame 构造工作面。多个 site（左右肢镜像对、或
        共享中线父骨）放在一次快照里切分，保证对称、守恒、与顺序无关。
        """
        sites = []
        for spec in sites_spec:
            parent_bone = armature.data.edit_bones.get(spec["parent_name"])
            child_bone = armature.data.edit_bones.get(spec["child_name"])
            if parent_bone is None or child_bone is None:
                raise Exception("找不到选中的骨骼")
            frame, error = cls._resolve_side_frame(armature, parent_bone, child_bone)
            if error:
                raise Exception(error)
            sites.append({
                "source_names": [spec["parent_name"], spec["child_name"]],
                "fan_names": list(spec["fan_names"]),
                "frame": frame,
            })

        mesh_objs = cls._collect_mesh_objects_for_armature(armature)
        if only_selected:
            mesh_objs = [obj for obj in mesh_objs if obj.select_get()]
        if not mesh_objs:
            raise Exception("没有找到网格物体")

        result = {"processed_objects": 0, "processed_sources": 0, "processed_fans": 0, "processed_vertices": 0}
        for obj in mesh_objs:
            obj_result = cls._transfer_fan_weights_multi_for_object(
                obj, armature, sites, radius_factor, blur_factor, midline_threshold, midplane_threshold,
            )
            result["processed_objects"] += obj_result["processed_objects"]
            result["processed_sources"] += obj_result["processed_sources"]
            result["processed_fans"] += obj_result.get("processed_fans", 0)
            result["processed_vertices"] += obj_result["processed_vertices"]
        return result


class BoneFanSidePreview:
    """侧向 fan 预览：画出两骨方向、角平分线、侧向扫动辐条和权重球。"""
    _handler_3d = None
    _handler_2d = None
    _timer_running = False
    _timer_interval = 0.08
    _state = None

    @classmethod
    def ensure_handler(cls):
        if cls._handler_3d is None:
            cls._handler_3d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_fan_side_preview, (), "WINDOW", "POST_VIEW",
            )
        if cls._handler_2d is None:
            cls._handler_2d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_fan_side_preview_2d, (), "WINDOW", "POST_PIXEL",
            )

    @classmethod
    def show(cls, context):
        cls.ensure_handler()
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "ho_fan_side_settings", None) if scene is not None else None
        if settings is None or not settings.preview_enabled:
            return

        armature = context.active_object
        region_owner = cls._find_view3d_region(context)
        region = region_data = None
        if region_owner is not None:
            _, region, region_data = region_owner

        state = {"armature_name": "", "frames": [], "message": "", "region": region, "region_data": region_data}

        if armature is None or armature.type != "ARMATURE":
            state["message"] = "预览需要一个骨架"
        else:
            selected = BoneFanSideCore._selected_bone_names(context, armature)
            if len(selected) != 2:
                state["message"] = "请正好选择两根相连的父子骨"
            else:
                def _get_bone(name):
                    if armature.mode == "EDIT":
                        return armature.data.edit_bones.get(name)
                    return armature.pose.bones.get(name)

                bone_a = _get_bone(selected[0])
                bone_b = _get_bone(selected[1])
                if bone_a is None or bone_b is None:
                    state["message"] = "找不到选中的骨骼"
                else:
                    frame, error = BoneFanSideCore._resolve_side_frame(armature, bone_a, bone_b)
                    if error:
                        state["message"] = error
                    else:
                        state["armature_name"] = armature.name
                        frames = [frame]
                        # 对称：把镜像骨对的预览几何也算进来。镜像通过重建几何得到，
                        # 自然处理自定义/任意朝向的工作面，无需手动取反某个轴。
                        if getattr(settings, "process_symmetry", False):
                            mirrored = BoneFanSideCore._mirror_pair(armature, list(selected))
                            if mirrored is not None:
                                mb_a = _get_bone(mirrored[0])
                                mb_b = _get_bone(mirrored[1])
                                if mb_a is not None and mb_b is not None:
                                    m_frame, m_error = BoneFanSideCore._resolve_side_frame(armature, mb_a, mb_b)
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
        settings = getattr(getattr(bpy.context, "scene", None), "ho_fan_side_settings", None)
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
        if state.get("message", ""):
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
            settings = getattr(bpy.context.scene, "ho_fan_side_settings", None)
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

        mw3 = armature.matrix_world.to_3x3()
        joint_world = armature.matrix_world @ frame["joint"]
        lateral_world = _safe_normalized_vector(mw3 @ frame["lateral"])
        bone_axis_world = _safe_normalized_vector(mw3 @ frame["bone_axis"])
        spread_axis_world = _safe_normalized_vector(mw3 @ frame["spread_axis"])
        if None in (lateral_world, bone_axis_world, spread_axis_world):
            return

        radius_factor = float(getattr(settings, "fan_weight_radius", 0.16)) if settings is not None else 0.16
        length_factor = float(getattr(settings, "length_factor", 0.2)) if settings is not None else 0.2
        spread_factor = float(getattr(settings, "spread_factor", 1.0)) if settings is not None else 1.0
        count = max(2, int(getattr(settings, "count", 2))) if settings is not None else 2
        sphere_radius = max(frame["base_length"] * radius_factor, 0.0)
        spoke_len = max(frame["base_length"] * length_factor, EPS)

        def _append_circle(target, center, ax, ay, r, segments=64):
            if r <= EPS:
                return
            prev = center + ax * r
            for idx in range(1, segments + 1):
                ang = tau * idx / segments
                pt = center + ax * cos(ang) * r + ay * sin(ang) * r
                target.extend([tuple(prev), tuple(pt)])
                prev = pt

        sphere_lines = []
        if getattr(settings, "auto_transfer_weights", False) and sphere_radius > EPS:
            _append_circle(sphere_lines, joint_world, lateral_world, bone_axis_world, sphere_radius)
            _append_circle(sphere_lines, joint_world, lateral_world, spread_axis_world, sphere_radius)
            _append_circle(sphere_lines, joint_world, bone_axis_world, spread_axis_world, sphere_radius)

        per_side = max(1, count)
        half = max(spread_factor, EPS) * radians(45.0)
        if per_side == 1:
            angles = [0.0]
        else:
            angles = [-half + (2.0 * half) * j / (per_side - 1) for j in range(per_side)]
        left_spokes = []   # +lateral 簇 (left)
        right_spokes = []  # -lateral 簇 (right)
        for center, target in ((lateral_world, left_spokes), (-lateral_world, right_spokes)):
            for angle in angles:
                d = BoneFanCore._rotate_vector_around_axis(center, spread_axis_world, angle)
                d = _safe_normalized_vector(d)
                if d is None:
                    continue
                target.extend([tuple(joint_world), tuple(joint_world + d * spoke_len)])

        shader.bind()
        if sphere_lines:
            b = batch_for_shader(shader, "LINES", {"pos": sphere_lines})
            shader.uniform_float("color", (0.2, 0.9, 1.0, 0.95))
            b.draw(shader)
        if left_spokes:
            b = batch_for_shader(shader, "LINES", {"pos": left_spokes})
            shader.uniform_float("color", (0.35, 0.95, 0.55, 0.95))
            b.draw(shader)
        if right_spokes:
            b = batch_for_shader(shader, "LINES", {"pos": right_spokes})
            shader.uniform_float("color", (1.0, 0.72, 0.2, 0.95))
            b.draw(shader)
        b = batch_for_shader(shader, "POINTS", {"pos": [tuple(joint_world)]})
        shader.uniform_float("color", (1.0, 0.65, 0.15, 1.0))
        b.draw(shader)

    @classmethod
    def _draw_2d(cls):
        state = cls._state
        if state is None:
            return
        font_id = 0
        message = state.get("message", "")
        blf.size(font_id, 14)
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, 20.0, 40.0, 0.0)
        if message:
            blf.draw(font_id, f"侧向 fan 预览: {message}")
        else:
            blf.draw(font_id, "侧向 fan 预览")


def drawBoneFanSidePanel(layout: UILayout, context: Context):
    settings = context.scene.ho_fan_side_settings
    box = layout.box()

    header = box.row(align=True)
    header.prop(
        settings,
        "ui_expanded",
        text="",
        icon="TRIA_DOWN" if settings.ui_expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text="fan侧向体积保持")

    row = header.row(align=True)
    row.operator(OP_FanSideGenerate.bl_idname, text="生成")
    row.operator(OP_RemoveFanSideBone.bl_idname, text="安全移除")

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

    col = box.column(align=True)

    prefix_row = col.row(align=True)
    prefix_row.label(text="名称前缀")
    prefix_row.prop(settings, "fan_name_prefix_preset", text="")
    prefix_row.prop(settings, "fan_name_prefix", text="")

    col.separator()
    row = col.row(align=True)
    row.prop(settings, "count")
    row.prop(settings, "influence", text="")
    col.prop(settings, "spread_factor")

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

    mid = sub.column(align=True)
    mid.enabled = settings.process_symmetry
    mid.prop(settings, "midline_threshold")
    mid.prop(settings, "midplane_threshold")


class OP_FanSideGenerate(Operator):
    bl_idname = "ho.fan_side_generate"
    bl_label = "生成侧向 fan 骨"
    bl_description = "选择两根相连的父子骨，在其弯折面的垂直面内沿两侧对称生成偶数 fan 骨"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False
        if obj.mode == "POSE":
            return len(context.selected_pose_bones or []) == 2
        if obj.mode == "EDIT":
            return len([b for b in obj.data.edit_bones if b.select]) == 2
        return False

    def execute(self, context):
        armature = context.active_object
        original_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        was_hidden = armature.hide_viewport
        BoneFanSidePreview.clear()

        settings = getattr(context.scene, "ho_fan_side_settings", None)
        if settings is None:
            self.report({"ERROR"}, "缺少侧向 fan 设置")
            return {"CANCELLED"}

        selected_names = BoneFanSideCore._selected_bone_names(context, armature)
        if len(selected_names) != 2:
            self.report({"ERROR"}, "请正好选择两根相连的父子骨")
            return {"CANCELLED"}

        count = max(1, int(settings.count))  # 每侧数量

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            # 校验是否相连父子骨，并取回真正的 (父骨, 子骨) 名
            edit_bones = armature.data.edit_bones
            bone_a = edit_bones.get(selected_names[0])
            bone_b = edit_bones.get(selected_names[1])
            if bone_a is None or bone_b is None:
                raise Exception("找不到选中的骨骼")
            frame, error = BoneFanSideCore._resolve_side_frame(armature, bone_a, bone_b)
            if error:
                raise Exception(error)
            parent_name = frame["parent_bone"].name
            child_name = frame["child_bone"].name

            # 组装骨对：选中那对，外加开启对称时的镜像对（仅当镜像对真实存在）
            pairs = [(parent_name, child_name)]
            if settings.process_symmetry:
                mirrored = BoneFanSideCore._mirror_pair(armature, [parent_name, child_name])
                if mirrored is not None:
                    # 镜像后仍需按层级判定父/子，重建 frame 取回正确顺序
                    m_a = edit_bones.get(mirrored[0])
                    m_b = edit_bones.get(mirrored[1])
                    m_frame, m_error = BoneFanSideCore._resolve_side_frame(armature, m_a, m_b)
                    if not m_error:
                        pairs.append((m_frame["parent_bone"].name, m_frame["child_bone"].name))

            total_created = 0
            total_weight_objects = 0
            weight_sites = []
            for p_name, c_name in pairs:
                created_names = BoneFanSideCore._create_side_fan_bones(
                    armature,
                    p_name,
                    c_name,
                    count,
                    settings.spread_factor,
                    settings.length_factor,
                    settings.pin_length_factor,
                    settings.bone_collection_name,
                    settings.influence,
                    settings.fan_name_prefix,
                )
                total_created += len(created_names)
                if settings.auto_transfer_weights and created_names:
                    weight_sites.append({
                        "parent_name": p_name,
                        "child_name": c_name,
                        "fan_names": created_names,
                    })

            if weight_sites:
                weight_result = BoneFanSideCore.apply_fan_weights_side_multi(
                    context,
                    armature,
                    weight_sites,
                    settings.fan_weight_radius,
                    settings.fan_weight_blur,
                    settings.only_selected,
                    settings.midline_threshold if settings.process_symmetry else 0.0,
                    settings.midplane_threshold if settings.process_symmetry else 0.0,
                )
                total_weight_objects += weight_result["processed_objects"]

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            sym_note = "（含对称）" if len(pairs) > 1 else ""
            if not settings.auto_transfer_weights:
                self.report({"INFO"}, f"已生成 {total_created} 根侧向 fan 骨{sym_note}")
            else:
                self.report(
                    {"INFO"},
                    f"已生成 {total_created} 根侧向 fan 骨{sym_note}，"
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
        BoneFanSidePreview.show(context)
        return self.execute(context)


class OP_RemoveFanSideBone(Operator):
    bl_idname = "ho.remove_fan_side_bone"
    bl_label = "删除侧向 fan 骨"
    bl_description = "删除选中父子骨对应的侧向 fan 骨，并把权重恢复回主骨"
    bl_options = {"REGISTER", "UNDO"}

    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
    )  # type: ignore
    process_vertex_groups: BoolProperty(
        name="处理顶点组",
        description="删除 fan 骨时反向恢复权重并清理对应顶点组",
        default=True,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False
        if obj.mode == "POSE":
            return len(context.selected_pose_bones or []) == 2
        if obj.mode == "EDIT":
            return len([b for b in obj.data.edit_bones if b.select]) == 2
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

        selected_names = BoneFanSideCore._selected_bone_names(context, armature)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if armature.mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            removal_names = BoneFanSideCore._collect_fan_bone_names(armature, selected_names)
            if not removal_names:
                self.report({"WARNING"}, "没有找到可删除的 fan 骨")
                return {"CANCELLED"}

            BoneFanSideCore._assert_safe_to_remove_fan_bones(armature, removal_names)
            main_to_fans = BoneFanSideCore._build_fan_restore_map(armature, removal_names)

            restored_objects = 0
            removed_groups = 0
            if self.process_vertex_groups:
                mesh_objs = BoneFanSideCore._collect_mesh_objects_for_armature(armature)
                if only_selected:
                    mesh_objs = [obj for obj in mesh_objs if obj.select_get()]
                for obj in mesh_objs:
                    groups = BoneFanSideCore.obj_fan_restore(obj, main_to_fans)
                    if groups > 0:
                        restored_objects += 1
                    removed_groups += groups

            if armature.mode != "EDIT":
                bpy.context.view_layer.objects.active = armature
                BoneSplitCore.set_object_mode(armature, "EDIT")

            removed = BoneFanSideCore._remove_fan_bones(armature, removal_names)

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            self.report(
                {"INFO"},
                f"已删除 {removed} 根 fan 骨，在 {restored_objects} 个物体上恢复了权重"
                f"（{removed_groups} 个顶点组）",
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


cls = [
    PG_Hotools_FanSideSettings,
    OP_FanSideGenerate,
    OP_RemoveFanSideBone,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    BoneFanSidePreview.shutdown()
    for item in cls:
        bpy.utils.unregister_class(item)
    ureg_props()
