import bpy
from bpy.types import Context, Operator, PropertyGroup, UILayout
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty, PointerProperty, FloatVectorProperty
from math import acos, cos, radians, sin, tau
from mathutils import Vector

from .boneSplit import BoneSplitCore
from .boneTwist import TwistBoneCore
from .boneFan import (
    BoneFanCore,
    FanRemovalBlockedError,
    _safe_normalized_vector,
    _clamp,
    _assign_bones_to_collection,
    EPS,
    HoRig_Fan,
)
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
import blf


def reg_props():
    if hasattr(bpy.types.Scene, "ho_fan_single_settings"):
        del bpy.types.Scene.ho_fan_single_settings
    bpy.types.Scene.ho_fan_single_settings = PointerProperty(type=PG_Hotools_FanSingleSettings)


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_fan_single_settings"):
        del bpy.types.Scene.ho_fan_single_settings


def _fan_single_preview_update(self, context):
    if context is None:
        return
    scene = getattr(context, "scene", None)
    settings = getattr(scene, "ho_fan_single_settings", None) if scene is not None else None
    if settings is None:
        return
    if settings.preview_enabled:
        BoneFanSinglePreview.show(context)
    else:
        BoneFanSinglePreview.clear()


def _fan_single_count_update(self, context):
    # 内/外侧 fan 骨必须成对出现，向上吸附到最近的偶数（最小 2）再刷新预览。
    for attr in ("count_in", "count_out"):
        value = getattr(self, attr, 2)
        snapped = max(2, value if value % 2 == 0 else value + 1)
        if snapped != value:
            setattr(self, attr, snapped)
    _fan_single_preview_update(self, context)


def _draw_fan_single_preview():
    BoneFanSinglePreview._draw_3d()


def _draw_fan_single_preview_2d():
    BoneFanSinglePreview._draw_2d()


class PG_Hotools_FanSingleSettings(PropertyGroup):
    ui_expanded: BoolProperty(
        name="单骨 fan 设置",
        description="展开单骨 fan 骨生成设置",
        default=False,
        update=_fan_single_preview_update,
    )  # type: ignore
    preview_enabled: BoolProperty(
        name="预览",
        description="在 3D 视图中绘制单骨 fan 预览",
        default=False,
        update=_fan_single_preview_update,
    )  # type: ignore
    virtual_direction: FloatVectorProperty(
        name="虚拟上级方向",
        description="单骨没有相连的上级关节，这里用一个世界空间向量充当虚拟上级方向，"
                    "fan 骨会在主骨方向与该向量张成的平面内展开（例如屁股骨可填 +Z）",
        subtype="XYZ",
        size=3,
        default=(0.0, 0.0, 1.0),
        update=_fan_single_preview_update,
    )  # type: ignore
    generate_in: BoolProperty(
        name="生成内侧",
        description="生成内侧（朝虚拟方向）的 fan 骨",
        default=True,
        update=_fan_single_preview_update,
    )  # type: ignore
    generate_out: BoolProperty(
        name="生成外侧",
        description="生成外侧（背向虚拟方向）的 fan 骨",
        default=False,
        update=_fan_single_preview_update,
    )  # type: ignore
    count_in: IntProperty(
        name="内侧数量",
        description="内侧 fan 骨数量，必须为偶数",
        default=2,
        min=2,
        step=2,
        update=_fan_single_count_update,
    )  # type: ignore
    count_out: IntProperty(
        name="外侧数量",
        description="外侧 fan 骨数量，必须为偶数",
        default=2,
        min=2,
        step=2,
        update=_fan_single_count_update,
    )  # type: ignore
    length_factor: FloatProperty(
        name="长度系数",
        description="fan 骨长度相对于主骨长度的比例",
        default=0.2,
        min=0.01,
        soft_max=1.0,
        update=_fan_single_preview_update,
    )  # type: ignore
    pin_length_factor: FloatProperty(
        name="pin 长度系数",
        description="fanPin 长度相对于 fan 骨长度的比例",
        default=0.2 / 5.0,
        min=0.001,
        soft_max=1.0,
        update=_fan_single_preview_update,
    )  # type: ignore
    auto_transfer_weights: BoolProperty(
        name="自动转移权重",
        description="生成时把主骨父级骨的权重转移到 fan 骨上",
        default=True,
        update=_fan_single_preview_update,
    )  # type: ignore
    process_symmetry: BoolProperty(
        name="对称操作",
        description="同时在镜像骨（.L/.R）上生成 fan 骨",
        default=False,
        update=_fan_single_preview_update,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
        update=_fan_single_preview_update,
    )  # type: ignore
    fan_weight_radius: FloatProperty(
        name="权重半径",
        description="权重转移球的半径，相对于主骨长度",
        default=0.16,
        min=0.0,
        soft_max=1.0,
        update=_fan_single_preview_update,
    )  # type: ignore
    fan_weight_blur: FloatProperty(
        name="权重模糊",
        description="硬球分割后施加的整体模糊强度（0 = 不模糊，1 = 最大平滑）",
        default=1.0,
        min=0.0,
        soft_max=1.0,
        update=_fan_single_preview_update,
    )  # type: ignore
    midline_threshold: FloatProperty(
        name="中线阈值",
        description="对称操作时，若某顶点到最近的左右 fan 的方向得分差小于该阈值，"
                    "判定它落在中线上，强制把权重在这些 fan 之间均分，避免中线顶点"
                    "被随机分到某一侧（0 = 关闭，仅严格相等才均分）",
        default=0.02,
        min=0.0,
        soft_max=0.2,
        update=_fan_single_preview_update,
    )  # type: ignore
    bone_collection_name: StringProperty(
        name="骨骼集合",
        description="生成的 fan 骨所属的骨骼集合名称",
        default=HoRig_Fan,
        update=_fan_single_preview_update,
    )  # type: ignore


class BoneFanSingleCore(BoneFanCore):
    """单骨 fan：只选一根主骨，用一个世界空间“虚拟上级方向”充当弯折的另一侧。

    设计要点 —— 把单骨情形映射到普通 fan 的 frame 结构上，从而直接复用父类的
    权重转移 / 约束 / 删除恢复逻辑：
      - child_bone  = 选中的主骨本体（fan 骨刚性跟随它，几何方向取它的实际朝向）。
      - parent_bone = 主骨在骨架里的父级骨（权重通道：自动权重从这根骨里转移）。
      - parent_dir  = 用户填的虚拟上级方向（仅参与几何：决定 fan 的扫动平面）。
      - joint       = 主骨 head（fan 骨都从这里发散）。

    与普通 fan 的区别只在“parent_dir 来自虚拟向量而非真正相连的父骨方向”，
    以及“权重来源是扫描到的父级骨”。其余完全一致。
    """

    @staticmethod
    def _resolve_single_frame(armature, main_bone, parent_bone, virtual_dir_world):
        """构造与 BoneFanCore frame 兼容的字典。

        virtual_dir_world 是世界空间向量；这里转成骨架局部空间后参与几何计算
        （edit_bones 的坐标都在骨架局部空间）。
        """
        def _bone_points(bone):
            if hasattr(bone, "head") and hasattr(bone, "tail"):
                return bone.head, bone.tail
            if hasattr(bone, "bone") and hasattr(bone, "matrix"):
                rest_bone = bone.bone
                head = bone.matrix.translation
                tail = bone.matrix @ Vector((0.0, rest_bone.length, 0.0))
                return head, tail
            raise Exception("不支持的骨骼类型")

        main_head, main_tail = _bone_points(main_bone)
        joint = main_head.copy()

        # 主骨实际朝向（从 head 指向 tail），这是 child 通道的几何方向
        child_dir = _safe_normalized_vector(main_tail - main_head)
        if child_dir is None:
            return None, "主骨长度太短"

        # 把世界空间虚拟向量转换到骨架局部空间
        local_virtual = armature.matrix_world.to_3x3().inverted() @ virtual_dir_world
        parent_dir = _safe_normalized_vector(local_virtual)
        if parent_dir is None:
            return None, "虚拟上级方向长度为零"

        # 预检测：虚拟向量若与主骨方向平行/反向，张不成有效平面，直接报错退出
        dot = _clamp(parent_dir.dot(child_dir), -1.0, 1.0)
        angle_rad = acos(dot)
        if angle_rad <= radians(1.0) or angle_rad >= radians(179.0):
            return None, "虚拟上级方向与主骨接近平行或反向，无法张成扫动平面，请换一个方向"

        plane_normal = _safe_normalized_vector(parent_dir.cross(child_dir))
        if plane_normal is None:
            return None, "无法计算平面法线"

        main_length = (main_tail - main_head).length

        return {
            # parent = 父级骨（权重通道），child = 主骨（几何 + 跟随对象）
            "parent_bone": parent_bone,
            "child_bone": main_bone,
            "joint": joint,
            "parent_dir": parent_dir,
            "child_dir": child_dir,
            "plane_normal": plane_normal,
            "angle_rad": angle_rad,
            "base_length": main_length,
        }, None

    @staticmethod
    def _resolve_roles(armature, name_a, name_b):
        """从两根选中的骨里，按骨架层级判定谁是上级骨（权重来源）谁是主骨（fan 跟随）。

        返回 (upper_name, main_name, error)。
        - 若其中一根是另一根的祖先（直接或间接），祖先即上级骨。
        - 不要求两根相连：层级关系即可，靠虚拟向量替代相连关节的几何。
        - 没有层级关系时无法判定，报错。
        """
        bones = armature.data.edit_bones if armature.mode == "EDIT" else armature.data.bones
        bone_a = bones.get(name_a)
        bone_b = bones.get(name_b)
        if bone_a is None or bone_b is None:
            return None, None, "找不到选中的骨骼"

        def _is_ancestor(ancestor, node):
            cur = getattr(node, "parent", None)
            while cur is not None:
                if cur.name == ancestor.name:
                    return True
                cur = getattr(cur, "parent", None)
            return False

        if _is_ancestor(bone_a, bone_b):
            return name_a, name_b, None
        if _is_ancestor(bone_b, bone_a):
            return name_b, name_a, None
        return None, None, "两根骨骼之间没有父子（层级）关系，无法判定上级骨与主骨"


    @classmethod
    def _create_fan_bones_single(
        cls,
        armature,
        main_name,
        parent_name,
        virtual_dir_world,
        fan_kind,
        count,
        length_factor,
        pin_length_factor,
        bone_collection_name=HoRig_Fan,
    ):
        """单骨版本的 fan 骨创建：几何来自虚拟方向，命名跟随主骨。

        与父类 _create_fan_bones 的唯一区别：用 _resolve_single_frame 取几何、
        fan 骨名以主骨为基名（方便选主骨即可删除）。fan 的父子归属仍按方向在
        “父级骨 / 主骨”之间二选一，保证权重通道守恒。
        """
        edit_bones = armature.data.edit_bones
        main_bone = edit_bones.get(main_name)
        parent_bone = edit_bones.get(parent_name)
        if main_bone is None:
            raise Exception("找不到选中的主骨")
        if parent_bone is None:
            raise Exception("找不到上级骨")

        frame, error = cls._resolve_single_frame(armature, main_bone, parent_bone, virtual_dir_world)
        if error:
            raise Exception(error)

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
            fan_name = cls._fan_name(main_name, fan_kind, i + 1, padding)
            pin_name = cls._fan_pin_name(main_name, fan_kind, i + 1, padding)
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
            fan_name = cls._fan_name(main_name, fan_kind, i, padding)
            pin_name = cls._fan_pin_name(main_name, fan_kind, i, padding)
            direction = cls._rotate_vector_around_axis(start_dir, plane_normal, step * i)
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
            pin_bone.parent = cls._choose_parent_bone(-direction, parent_bone, parent_dir, main_bone, child_dir)
            try:
                pin_bone.align_roll(plane_normal)
            except Exception:
                pin_bone.roll = 0.0

            fan_bone = edit_bones.new(fan_name)
            fan_bone.head = joint.copy()
            fan_bone.tail = joint + direction * fan_length
            fan_bone.use_connect = False
            fan_bone.use_deform = True
            fan_bone.parent = cls._choose_parent_bone(direction, parent_bone, parent_dir, main_bone, child_dir)
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
    def apply_fan_weights_single(
        cls,
        context,
        armature,
        main_name,
        parent_name,
        virtual_dir_world,
        fan_names,
        radius_factor,
        blur_factor,
        only_selected,
    ):
        """单骨版本的权重转移：权重通道是 [父级骨, 主骨]，几何来自虚拟方向。"""
        main_bone = armature.data.edit_bones.get(main_name)
        parent_bone = armature.data.edit_bones.get(parent_name)
        if main_bone is None or parent_bone is None:
            raise Exception("找不到主骨或其父级骨")

        frame, error = cls._resolve_single_frame(armature, main_bone, parent_bone, virtual_dir_world)
        if error:
            raise Exception(error)

        mesh_objs = cls._collect_mesh_objects_for_armature(armature)
        if only_selected:
            mesh_objs = [obj for obj in mesh_objs if obj.select_get()]
        if not mesh_objs:
            raise Exception("没有找到网格物体")

        # 父类的 _transfer_fan_weights_for_object 用 selected_names 读两根主骨的
        # edit_bone，再用 frame 里的 parent/child 决定通道。这里两者都传真实存在的
        # 骨名（父级骨 + 主骨）即可。
        source_names = [parent_name, main_name]
        result = {"processed_objects": 0, "processed_sources": 0, "processed_fans": 0, "processed_vertices": 0}
        for obj in mesh_objs:
            obj_result = cls._transfer_fan_weights_for_object(
                obj, armature, source_names, fan_names, radius_factor, blur_factor, frame,
            )
            result["processed_objects"] += obj_result["processed_objects"]
            result["processed_sources"] += obj_result["processed_sources"]
            result["processed_fans"] += obj_result.get("processed_fans", 0)
            result["processed_vertices"] += obj_result["processed_vertices"]
        return result

    @classmethod
    def apply_fan_weights_multi(
        cls,
        context,
        armature,
        sites_spec,
        radius_factor,
        blur_factor,
        only_selected,
        midline_threshold=0.0,
    ):
        """对称感知的权重转移：把多个 fan 站点（site）放在一起做一次分割。

        每个 site 是一对（上级骨, 主骨）及其 fan 骨。多个 site 可能共享同一根
        上级骨（典型：左右肢共用中线父骨，如 Hips / Spine / Chest）。这时两侧的
        关节球在中线附近会重叠，独立分两遍处理会让后处理的一侧读到已被前一遍
        改写过的父骨权重，导致左右不对称、且结果依赖处理顺序。

        这里改成：对原始权重做一次快照，再把父骨通道的权重在“所有覆盖该顶点的
        site”之间按到各关节的反距离平方切分，最后在每个 site 内部交给最近的
        fan。结果对称、与处理顺序无关，且父骨通道总量守恒。
        """
        sites = []
        for spec in sites_spec:
            main_bone = armature.data.edit_bones.get(spec["main_name"])
            parent_bone = armature.data.edit_bones.get(spec["parent_name"])
            if main_bone is None or parent_bone is None:
                raise Exception("找不到主骨或其父级骨")
            frame, error = cls._resolve_single_frame(
                armature, main_bone, parent_bone, spec["virtual_dir_world"],
            )
            if error:
                raise Exception(error)
            sites.append({
                "source_names": [spec["parent_name"], spec["main_name"]],
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
                obj, armature, sites, radius_factor, blur_factor, midline_threshold,
            )
            result["processed_objects"] += obj_result["processed_objects"]
            result["processed_sources"] += obj_result["processed_sources"]
            result["processed_fans"] += obj_result.get("processed_fans", 0)
            result["processed_vertices"] += obj_result["processed_vertices"]
        return result

    @classmethod
    def _transfer_fan_weights_multi_for_object(
        cls,
        obj,
        armature,
        sites,
        radius_factor,
        blur_factor,
        midline_threshold=0.0,
    ):
        """把多个 site 的权重放在一次快照里转移，保证共享父骨通道左右对称、守恒。

        与父类逐对处理的区别：
        - 原始权重只读一次（快照），所有 site 共用，避免顺序依赖。
        - 按“真实顶点组”而非“站点”聚合通道：共享父骨的所有 fan（跨左右两侧）
          属于同一个通道，重叠区里某顶点的父骨权重只交给方向最近的那一根 fan。
        """
        mw3 = armature.matrix_world.to_3x3()

        # --- 解析每个 site 的几何 ---------------------------------------
        site_infos = []
        for site in sites:
            frame = site["frame"]
            joint_world = armature.matrix_world @ frame["joint"]
            plane_normal_world = _safe_normalized_vector(mw3 @ frame["plane_normal"])
            parent_dir_world = _safe_normalized_vector(mw3 @ frame["parent_dir"])
            child_dir_world = _safe_normalized_vector(mw3 @ frame["child_dir"])
            radius = max(frame["base_length"] * radius_factor, EPS)
            site_infos.append({
                "source_names": site["source_names"],
                "parent_name": site["source_names"][0],
                "child_name": site["source_names"][1],
                "fan_names": site["fan_names"],
                "joint_world": joint_world,
                "plane_normal_world": plane_normal_world,
                "parent_dir_world": parent_dir_world,
                "child_dir_world": child_dir_world,
                "radius": radius,
            })

        # --- 收集 fan 骨：方向投影到各自 site 的弯折平面，归属到真实顶点组通道 ---
        edit_bones = armature.data.edit_bones
        fan_items = []
        for site_idx, info in enumerate(site_infos):
            plane_normal_world = info["plane_normal_world"]
            parent_dir_world = info["parent_dir_world"]
            child_dir_world = info["child_dir_world"]
            for fan_name in info["fan_names"]:
                parsed = cls._parse_fan_name(fan_name)
                fan_bone = edit_bones.get(fan_name)
                if parsed is None or fan_bone is None:
                    continue
                fan_dir = _safe_normalized_vector(mw3 @ (fan_bone.tail - fan_bone.head))
                if fan_dir is None:
                    continue
                if plane_normal_world is not None:
                    fan_dir = _safe_normalized_vector(
                        fan_dir - plane_normal_world * fan_dir.dot(plane_normal_world)
                    )
                    if fan_dir is None:
                        continue
                # 决定这根 fan 刚性跟随哪根骨（即它从哪个权重通道接收权重）。
                fan_src = None
                parent_eb = getattr(fan_bone, "parent", None)
                if parent_eb is not None and parent_eb.name in info["source_names"]:
                    fan_src = parent_eb.name
                if fan_src is None and parent_dir_world is not None and child_dir_world is not None:
                    fan_src = (
                        info["parent_name"]
                        if fan_dir.dot(parent_dir_world) >= fan_dir.dot(child_dir_world)
                        else info["child_name"]
                    )
                if fan_src is None:
                    fan_src = info["parent_name"]
                fan_items.append({
                    "name": fan_name,
                    "src": fan_src,
                    "site_idx": site_idx,
                    "dir": fan_dir,
                })

        if not fan_items:
            return {"processed_sources": 0, "processed_fans": 0, "processed_vertices": 0, "processed_objects": 0}

        all_indices = [v.index for v in obj.data.vertices]
        num_vertices = len(all_indices)
        if num_vertices == 0:
            return {"processed_sources": 0, "processed_fans": 0, "processed_vertices": 0, "processed_objects": 0}

        world_co = [obj.matrix_world @ v.co for v in obj.data.vertices]

        # --- 快照所有相关源顶点组（每个组只读一次）----------------------
        source_names = []
        for info in site_infos:
            for name in info["source_names"]:
                if name not in source_names:
                    source_names.append(name)

        source_groups = {}
        source_weights = {}
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

        orig_total = [0.0] * num_vertices
        for source_name in present_sources:
            sw = source_weights[source_name]
            for i in range(num_vertices):
                orig_total[i] += sw[i]

        # --- 准备 fan 顶点组与工作缓冲 ----------------------------------
        fan_groups = {}
        fan_weights = {}
        for item in fan_items:
            fan_vg = obj.vertex_groups.get(item["name"])
            if fan_vg is None:
                fan_vg = obj.vertex_groups.new(name=item["name"])
            fan_vg.remove(all_indices)
            fan_groups[item["name"]] = fan_vg
            fan_weights[item["name"]] = [0.0] * num_vertices
        processed_fans = len(fan_groups)

        main_weights = {name: source_weights[name][:] for name in present_sources}

        # 按真实通道（源顶点组）聚合 fan：共享父骨的左右 fan 进同一个通道。
        channel_fans = {name: [] for name in present_sources}
        for item in fan_items:
            if item["src"] in channel_fans:
                channel_fans[item["src"]].append(item)

        # --- 阶段 1：硬球分割（跨 site 合并）---------------------------
        # 每个顶点、每个通道：在“球覆盖该顶点的所有 fan”里选平面内方向最近的那根，
        # 把整份通道权重交给它。共享父骨的重叠区因此对称、与处理顺序无关。
        #
        # 中线均分：恰好落在中线上的顶点，到左右最近 fan 的方向得分几乎相等，
        # 单纯取最大值会被浮点噪声随机分到某一侧。这里把得分在 best - 阈值 以内的
        # 候选 fan 都视为“并列最近”，把通道权重在它们之间均分，保证中线对称。
        touched_vertices = 0
        core_vertices = []
        for i in range(num_vertices):
            if orig_total[i] <= 0.0:
                continue

            touched = False
            for source_name in present_sources:
                ws = source_weights[source_name][i]
                if ws <= 0.0:
                    continue

                candidates = []
                best_score = -2.0
                for item in channel_fans[source_name]:
                    info = site_infos[item["site_idx"]]
                    rel = world_co[i] - info["joint_world"]
                    if rel.length > info["radius"]:
                        continue
                    plane_normal_world = info["plane_normal_world"]
                    vec = rel
                    if plane_normal_world is not None:
                        vec = vec - plane_normal_world * vec.dot(plane_normal_world)
                    vdir = _safe_normalized_vector(vec)
                    score = 1.0 if vdir is None else item["dir"].dot(vdir)
                    candidates.append((score, item["name"]))
                    if score > best_score:
                        best_score = score
                if not candidates:
                    continue

                # best - 阈值 以内的候选并列为“最近”，均分通道权重。
                winners = [name for score, name in candidates if best_score - score <= midline_threshold]
                if not winners:
                    continue
                share = ws / len(winners)
                for name in winners:
                    fan_weights[name][i] += share
                main_weights[source_name][i] = 0.0
                touched = True

            if touched:
                core_vertices.append(i)
                touched_vertices += 1

        # --- 阶段 2：整体模糊 -----------------------------------------
        iterations = int(round(_clamp(blur_factor, 0.0, 1.0) * cls._MAX_BLUR_ITERATIONS))
        if iterations > 0 and core_vertices:
            adjacency = cls._build_vertex_adjacency(obj, num_vertices)

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

            # 按通道（真实源顶点组）重新归一化，保证总量守恒。
            for source_name in present_sources:
                orig_s = source_weights[source_name]
                chan_buffers = [main_weights[source_name]]
                chan_buffers += [fan_weights[item["name"]] for item in channel_fans[source_name]]
                for i in region:
                    if orig_s[i] <= EPS:
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

        # --- 写回结果 -------------------------------------------------
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


class BoneFanSinglePreview:
    """单骨 fan 预览：画出虚拟方向、fan 扫动辐条和权重球。结构与 BoneFanPreview 一致。"""
    _handler_3d = None
    _handler_2d = None
    _timer_running = False
    _timer_interval = 0.08
    _state = None

    @classmethod
    def ensure_handler(cls):
        if cls._handler_3d is None:
            cls._handler_3d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_fan_single_preview, (), "WINDOW", "POST_VIEW",
            )
        if cls._handler_2d is None:
            cls._handler_2d = bpy.types.SpaceView3D.draw_handler_add(
                _draw_fan_single_preview_2d, (), "WINDOW", "POST_PIXEL",
            )

    @classmethod
    def show(cls, context):
        cls.ensure_handler()
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "ho_fan_single_settings", None) if scene is not None else None
        if settings is None or not settings.preview_enabled:
            return

        armature = context.active_object
        region_owner = cls._find_view3d_region(context)
        region = region_data = None
        if region_owner is not None:
            _, region, region_data = region_owner

        state = {"armature_name": "", "frame": None, "message": "", "region": region, "region_data": region_data}

        if armature is None or armature.type != "ARMATURE":
            state["message"] = "预览需要一个骨架"
        else:
            selected = BoneFanSingleCore._selected_bone_names(context, armature)
            if len(selected) != 2:
                state["message"] = "请正好选择两根骨骼（上级骨 + 主骨）"
            else:
                upper_name, main_name, role_error = BoneFanSingleCore._resolve_roles(
                    armature, selected[0], selected[1],
                )
                if role_error:
                    state["message"] = role_error
                else:
                    def _get_bone(name):
                        if armature.mode == "EDIT":
                            return armature.data.edit_bones.get(name)
                        return armature.pose.bones.get(name)

                    main_bone = _get_bone(main_name)
                    parent_bone = _get_bone(upper_name)
                    if main_bone is None or parent_bone is None:
                        state["message"] = "找不到选中的骨骼"
                    else:
                        virtual = Vector(settings.virtual_direction)
                        frame, error = cls._resolve_single_frame(armature, main_bone, parent_bone, virtual)
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

    @staticmethod
    def _resolve_single_frame(armature, main_bone, parent_bone, virtual):
        return BoneFanSingleCore._resolve_single_frame(armature, main_bone, parent_bone, virtual)

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
        settings = getattr(getattr(bpy.context, "scene", None), "ho_fan_single_settings", None)
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

            frame = state.get("frame")
            if frame is None:
                return

            settings = getattr(bpy.context.scene, "ho_fan_single_settings", None)
            mw3 = armature.matrix_world.to_3x3()
            joint_world = armature.matrix_world @ frame["joint"]
            plane_normal_world = _safe_normalized_vector(mw3 @ frame["plane_normal"])
            parent_dir_world = _safe_normalized_vector(mw3 @ frame["parent_dir"])
            child_dir_world = _safe_normalized_vector(mw3 @ frame["child_dir"])
            if plane_normal_world is None or parent_dir_world is None or child_dir_world is None:
                return

            radius_factor = float(getattr(settings, "fan_weight_radius", 0.16)) if settings is not None else 0.16
            length_factor = float(getattr(settings, "length_factor", 0.2)) if settings is not None else 0.2
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

            # 正交辅助轴，用来画权重球的三个大圆
            axis_a = _safe_normalized_vector(parent_dir_world - plane_normal_world * parent_dir_world.dot(plane_normal_world))
            if axis_a is None:
                axis_a = child_dir_world
            axis_b = _safe_normalized_vector(plane_normal_world.cross(axis_a))

            sphere_lines = []
            if getattr(settings, "auto_transfer_weights", False) and sphere_radius > EPS and axis_b is not None:
                _append_circle(sphere_lines, joint_world, axis_a, axis_b, sphere_radius)
                _append_circle(sphere_lines, joint_world, axis_a, plane_normal_world, sphere_radius)
                _append_circle(sphere_lines, joint_world, axis_b, plane_normal_world, sphere_radius)

            # 虚拟方向：从关节指向虚拟向量，画一条醒目的参考线
            virtual_line = [
                tuple(joint_world),
                tuple(joint_world + parent_dir_world * spoke_len * 1.4),
            ]
            # 主骨方向参考
            main_line = [
                tuple(joint_world),
                tuple(joint_world + child_dir_world * spoke_len * 1.4),
            ]

            total_angle = float(frame["angle_rad"])
            in_spokes = []
            out_spokes = []
            if getattr(settings, "generate_in", False):
                in_count = max(1, int(getattr(settings, "count_in", 1)))
                step = total_angle / (in_count + 1)
                for index in range(1, in_count + 1):
                    d = BoneFanSingleCore._rotate_vector_around_axis(parent_dir_world, plane_normal_world, step * index)
                    if d is None:
                        continue
                    in_spokes.extend([tuple(joint_world), tuple(joint_world + d * spoke_len)])
            if getattr(settings, "generate_out", False):
                out_count = max(1, int(getattr(settings, "count_out", 1)))
                step = total_angle / (out_count + 1)
                for index in range(1, out_count + 1):
                    d = BoneFanSingleCore._rotate_vector_around_axis(-parent_dir_world, plane_normal_world, step * index)
                    if d is None:
                        continue
                    out_spokes.extend([tuple(joint_world), tuple(joint_world + d * spoke_len)])

            shader.bind()
            if sphere_lines:
                b = batch_for_shader(shader, "LINES", {"pos": sphere_lines})
                shader.uniform_float("color", (0.2, 0.9, 1.0, 0.95))
                b.draw(shader)
            b = batch_for_shader(shader, "LINES", {"pos": virtual_line})
            shader.uniform_float("color", (1.0, 0.3, 0.9, 0.95))
            b.draw(shader)
            b = batch_for_shader(shader, "LINES", {"pos": main_line})
            shader.uniform_float("color", (0.95, 0.95, 0.95, 0.85))
            b.draw(shader)
            if in_spokes:
                b = batch_for_shader(shader, "LINES", {"pos": in_spokes})
                shader.uniform_float("color", (1.0, 0.72, 0.2, 0.95))
                b.draw(shader)
            if out_spokes:
                b = batch_for_shader(shader, "LINES", {"pos": out_spokes})
                shader.uniform_float("color", (0.35, 0.95, 0.55, 0.95))
                b.draw(shader)
            b = batch_for_shader(shader, "POINTS", {"pos": [tuple(joint_world)]})
            shader.uniform_float("color", (1.0, 0.65, 0.15, 1.0))
            b.draw(shader)
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

        font_id = 0
        message = state.get("message", "")
        blf.size(font_id, 14)
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, 20.0, 40.0, 0.0)
        if message:
            blf.draw(font_id, f"单骨 fan 预览: {message}")
        else:
            blf.draw(font_id, "单骨 fan 预览")


def drawBoneFanSinglePanel(layout: UILayout, context: Context):
    settings = context.scene.ho_fan_single_settings
    box = layout.box()

    header = box.row(align=True)
    header.prop(
        settings,
        "ui_expanded",
        text="",
        icon="TRIA_DOWN" if settings.ui_expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text="单骨 fan")

    row = header.row(align=True)
    row.operator(OP_FanSingleGenerate.bl_idname, text="生成 fan 骨")
    row.operator(OP_RemoveFanSingleBone.bl_idname, text="安全移除")

    header.prop(
        settings,
        "preview_enabled",
        text="",
        icon="HIDE_OFF" if settings.preview_enabled else "HIDE_ON",
    )

    if not settings.ui_expanded:
        return

    col = box.column(align=True)
    col.separator()
    col.prop(settings, "virtual_direction")

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


class OP_FanSingleGenerate(Operator):
    bl_idname = "ho.fan_single_generate"
    bl_label = "生成单骨 fan 骨"
    bl_description = "选择两根有层级关系的骨骼（上级骨 + 主骨，可不相连），用虚拟向量替代上级骨方向生成 fan 骨"
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
        BoneFanSinglePreview.clear()

        settings = getattr(context.scene, "ho_fan_single_settings", None)
        if settings is None:
            self.report({"ERROR"}, "缺少单骨 fan 设置")
            return {"CANCELLED"}

        selected_names = BoneFanSingleCore._selected_bone_names(context, armature)
        if len(selected_names) != 2:
            self.report({"ERROR"}, "请正好选择两根骨骼（上级骨 + 主骨）")
            return {"CANCELLED"}

        fan_kinds = []
        if settings.generate_in:
            fan_kinds.append(("in", settings.count_in))
        if settings.generate_out:
            fan_kinds.append(("out", settings.count_out))
        if not fan_kinds:
            self.report({"ERROR"}, "请至少选择一个方向")
            return {"CANCELLED"}

        virtual_dir = Vector(settings.virtual_direction)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            # 按骨架层级判定上级骨（权重来源）与主骨（fan 跟随）
            upper_name, main_name, role_error = BoneFanSingleCore._resolve_roles(
                armature, selected_names[0], selected_names[1],
            )
            if role_error:
                raise Exception(role_error)

            # 组装要处理的 (上级骨, 主骨) 骨对：选中的那对，外加开启对称时的镜像对
            pairs = [(upper_name, main_name)]
            if settings.process_symmetry:
                flipped_upper = bpy.utils.flip_name(upper_name)
                flipped_main = bpy.utils.flip_name(main_name)
                if (
                    (flipped_upper, flipped_main) != (upper_name, main_name)
                    and armature.data.edit_bones.get(flipped_upper) is not None
                    and armature.data.edit_bones.get(flipped_main) is not None
                ):
                    pairs.append((flipped_upper, flipped_main))

            total_created = 0
            total_weight_objects = 0
            weight_sites = []
            for parent_name, this_main in pairs:
                created_names = []
                for fan_kind, count in fan_kinds:
                    created_names.extend(
                        BoneFanSingleCore._create_fan_bones_single(
                            armature,
                            this_main,
                            parent_name,
                            virtual_dir,
                            fan_kind,
                            count,
                            settings.length_factor,
                            settings.pin_length_factor,
                            settings.bone_collection_name,
                        )
                    )
                total_created += len(created_names)

                if settings.auto_transfer_weights and created_names:
                    weight_sites.append({
                        "main_name": this_main,
                        "parent_name": parent_name,
                        "virtual_dir_world": virtual_dir,
                        "fan_names": created_names,
                    })

            # 权重转移：所有 site 放在一次快照里做，保证共享父骨（如中线 Hips /
            # Spine）的左右切分对称、与处理顺序无关、且通道总量守恒。
            if weight_sites:
                weight_result = BoneFanSingleCore.apply_fan_weights_multi(
                    context,
                    armature,
                    weight_sites,
                    settings.fan_weight_radius,
                    settings.fan_weight_blur,
                    settings.only_selected,
                    settings.midline_threshold if settings.process_symmetry else 0.0,
                )
                total_weight_objects += weight_result["processed_objects"]

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            sym_note = "（含对称）" if len(pairs) > 1 else ""
            if not settings.auto_transfer_weights:
                self.report({"INFO"}, f"已生成 {total_created} 根 fan 骨{sym_note}")
            else:
                self.report(
                    {"INFO"},
                    f"已生成 {total_created} 根 fan 骨{sym_note}，"
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
        BoneFanSinglePreview.show(context)
        return self.execute(context)


class OP_RemoveFanSingleBone(Operator):
    bl_idname = "ho.remove_fan_single_bone"
    bl_label = "删除单骨 fan 骨"
    bl_description = "删除选中主骨对应的 fan 骨，并把权重恢复回它跟随的骨"
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

        selected_names = BoneFanSingleCore._selected_bone_names(context, armature)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if armature.mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            removal_names = BoneFanSingleCore._collect_fan_bone_names(armature, selected_names)
            if not removal_names:
                self.report({"WARNING"}, "没有找到可删除的 fan 骨")
                return {"CANCELLED"}

            BoneFanSingleCore._assert_safe_to_remove_fan_bones(armature, removal_names)
            main_to_fans = BoneFanSingleCore._build_fan_restore_map(armature, removal_names)

            restored_objects = 0
            removed_groups = 0
            if self.process_vertex_groups:
                mesh_objs = BoneFanSingleCore._collect_mesh_objects_for_armature(armature)
                if only_selected:
                    mesh_objs = [obj for obj in mesh_objs if obj.select_get()]
                for obj in mesh_objs:
                    groups = BoneFanSingleCore.obj_fan_restore(obj, main_to_fans)
                    if groups > 0:
                        restored_objects += 1
                    removed_groups += groups

            if armature.mode != "EDIT":
                bpy.context.view_layer.objects.active = armature
                BoneSplitCore.set_object_mode(armature, "EDIT")

            removed = BoneFanSingleCore._remove_fan_bones(armature, removal_names)

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
    PG_Hotools_FanSingleSettings,
    OP_FanSingleGenerate,
    OP_RemoveFanSingleBone,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    BoneFanSinglePreview.shutdown()
    for item in cls:
        bpy.utils.unregister_class(item)
    ureg_props()
