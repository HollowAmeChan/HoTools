import bpy
import math
import numpy as np
from mathutils import Vector
from bpy.types import Operator, UILayout, Context
from bpy.props import BoolProperty, IntProperty, FloatProperty

from .boneSplit import BoneSplitCore


def reg_props():
    return


def ureg_props():
    return


def drawBoneTwistPanel(layout: UILayout, context: Context):
    twist_box = layout.box()
    row = twist_box.row(align=True)
    row.operator(
        OP_TwistBoneWithWeight.bl_idname,
        text="生成Twist骨",
    )


class TwistBoneCore:
    @staticmethod
    def _split_side_suffix(name: str) -> tuple[str, str]:
        if len(name) >= 2 and name[-2] in "._-" and name[-1] in "LRlr":
            return name[:-2], name[-2:]
        return name, ""

    @staticmethod
    def _twist_name(base_name: str, index: int, padding: int) -> str:
        stem, side_suffix = TwistBoneCore._split_side_suffix(base_name)
        return f"{stem}_twist_{index:0{padding}d}{side_suffix}"

    @staticmethod
    def create_twist_chain(armature: bpy.types.Object, bn: str, count: int) -> list[str]:
        """在保留主骨的前提下，生成Twist子骨链。"""
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            BoneSplitCore.set_object_mode(armature, "EDIT")

            edit_bones = armature.data.edit_bones
            old_bone = edit_bones.get(bn)
            if old_bone is None:
                raise Exception(f"在编辑模式中未找到骨骼: {bn}")

            bone_vec = old_bone.tail - old_bone.head
            if bone_vec.length <= 1e-8:
                raise Exception(f"骨骼长度为 0: {bn}")

            padding = max(2, len(str(count)))
            new_bone_names = [
                TwistBoneCore._twist_name(bn, count - i + 1, padding)
                for i in range(1, count + 1)
            ]

            existed = [name for name in new_bone_names if edit_bones.get(name)]
            if existed:
                raise Exception(
                    "Twist骨名称已存在: " + ", ".join(existed)
                )

            corrected_points = [
                old_bone.head.lerp(old_bone.tail, i / count)
                for i in range(count + 1)
            ]
            vertical_tail_offset = Vector((0, 0, bone_vec.length / count))

            new_bones = []
            for i, new_name in enumerate(new_bone_names, start=1):
                new_bone = edit_bones.new(new_name)
                new_bone.head = corrected_points[i - 1].copy()
                new_bone.tail = new_bone.head + vertical_tail_offset
                new_bone.roll = 0.0
                new_bone.use_deform = True
                new_bone.parent = old_bone
                new_bone.use_connect = False
                new_bones.append(new_bone)

            bpy.context.view_layer.objects.active = armature
            BoneSplitCore.set_object_mode(armature, "OBJECT")
            return new_bone_names
        finally:
            if armature.mode == "EDIT":
                try:
                    bpy.context.view_layer.objects.active = armature
                    BoneSplitCore.set_object_mode(armature, "OBJECT")
                except Exception:
                    pass

            if was_hidden:
                armature.hide_set(True)

    @staticmethod
    def _set_temp_mesh_mirror_off(obj: bpy.types.Object) -> dict[str, tuple[object, bool]]:
        mirror_state = {}
        for prop_name in (
            "use_mesh_mirror_x",
            "use_mesh_mirror_y",
            "use_mesh_mirror_z",
        ):
            owner = None
            if hasattr(obj, prop_name):
                owner = obj
            elif getattr(obj, "data", None) is not None and hasattr(obj.data, prop_name):
                owner = obj.data

            if owner is None:
                continue

            mirror_state[prop_name] = (owner, getattr(owner, prop_name))
            setattr(owner, prop_name, False)

        return mirror_state

    @staticmethod
    def _restore_mesh_mirror_state(mirror_state: dict[str, tuple[object, bool]]) -> None:
        for prop_name, (owner, value) in mirror_state.items():
            setattr(owner, prop_name, value)

    @staticmethod
    def splitVertexGroup_withTmp_along_source(
        obj,
        new_bone_names,
        count,
        armature,
        source_bone_name,
        tmp_vg,
        soft_factor,
    ):
        old_mode = obj.mode
        mirror_state = TwistBoneCore._set_temp_mesh_mirror_off(obj)

        try:
            if old_mode == "EDIT":
                bpy.context.view_layer.objects.active = obj
                BoneSplitCore.set_object_mode(obj, "OBJECT")

            new_vgs: list[bpy.types.VertexGroup] = []
            for new_name in new_bone_names:
                vg: bpy.types.VertexGroup = obj.vertex_groups.new(name=new_name)
                new_vgs.append(vg)

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

            N = len(obj.data.vertices)
            if N == 0:
                obj.vertex_groups.remove(tmp_vg)
                return

            verts_np = np.array([list(v.co) for v in obj.data.vertices], dtype=float)
            weights_np = np.zeros(N, dtype=float)
            has_weight_np = np.zeros(N, dtype=bool)
            for i in range(N):
                try:
                    weights_np[i] = tmp_vg.weight(i)
                    has_weight_np[i] = True
                except RuntimeError:
                    weights_np[i] = 0.0

            diff = verts_np - np.array(list(chain_start_local), dtype=float)
            chain_vec_np = np.array(list(chain_vec), dtype=float)
            f = np.dot(diff, chain_vec_np) / chain_len_sq
            f = np.clip(f, 0.0, 1.0)
            pos = f * count - 0.5
            pos = np.clip(pos, 0, count - 1)
            i_seg = np.floor(pos).astype(int)
            local_factor = pos - i_seg

            for i in range(N):
                if not has_weight_np[i]:
                    continue

                orig_w = weights_np[i]
                seg = i_seg[i]
                lf = local_factor[i]

                if seg == count - 1:
                    new_vgs[seg].add([i], orig_w, "REPLACE")
                else:
                    if soft_factor == 0.0:
                        blend = 0.0 if lf < 0.5 else 1.0
                    elif soft_factor == 1.0:
                        blend = 0.5 * (1 - math.cos(math.pi * lf))
                    else:
                        step_val = 0.0 if lf < 0.5 else 1.0
                        cos_val = 0.5 * (1 - math.cos(math.pi * lf))
                        blend = (1 - soft_factor) * step_val + soft_factor * cos_val

                    blend = max(0.0, min(blend, 1.0))
                    new_vgs[seg].add([i], orig_w * (1.0 - blend), "REPLACE")
                    new_vgs[seg + 1].add([i], orig_w * blend, "REPLACE")

            obj.vertex_groups.remove(tmp_vg)

        finally:
            TwistBoneCore._restore_mesh_mirror_state(mirror_state)

            if old_mode == "EDIT":
                BoneSplitCore.set_object_mode(obj, "EDIT")

    @staticmethod
    def obj_twist_transfer(
        obj: bpy.types.Object,
        new_bone_names: list[str],
        count: int,
        armature: bpy.types.Object,
        tmp_vg,
        soft_factor: float,
        source_group_name: str,
    ):
        TwistBoneCore.splitVertexGroup_withTmp_along_source(
            obj,
            new_bone_names,
            count,
            armature,
            source_group_name,
            tmp_vg,
            soft_factor,
        )

        source_group = obj.vertex_groups.get(source_group_name)
        if source_group:
            all_vertex_indices = [v.index for v in obj.data.vertices]
            if all_vertex_indices:
                source_group.remove(all_vertex_indices)

    @staticmethod
    def objs_bone_twist(
        bn: str,
        count: int,
        armature: bpy.types.Object,
        soft_factor: float,
        objs,
    ):
        """把选中的主骨权重转移到Twist子骨链上。"""
        new_bone_names = TwistBoneCore.create_twist_chain(armature, bn, count)

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
                bn,
            )

    @staticmethod
    def set_object_mode(obj, mode):
        """保持和既有骨工具一致的模式切换方式。"""
        return BoneSplitCore.set_object_mode(obj, mode)


class OP_TwistBoneWithWeight(Operator):
    bl_idname = "ho.twistbone_withweight"
    bl_label = "生成Twist骨与权重"
    bl_description = """
    为选中的骨骼生成Twist子骨链，并把主骨权重转移到新骨骼上。
    使用方式:在姿态模式或编辑模式选择要处理的骨骼，也可以在权重绘制时使用当前活动骨骼。
            原骨骼会保留；沿原骨头尾方向放置指定段数的子级Twist骨，最深子骨编号为 原名_twist_01。
            原骨骼已有子级不会被转移，生成的Twist骨全部直接挂在原骨下，彼此平级。
            Twist骨本身会竖直向上，roll 归零，子骨之间不强制连接，便于导出到引擎。
            权重分段仍按原骨骼 head 到 tail 的方向计算，不受竖直Twist骨方向影响。
            切分顶点组时会临时关闭网格 X/Y/Z 镜像选项，结束后恢复原设置。
            如果原骨末尾有 .L/.R/_L/_R 等左右后缀，Twist后缀会插入到左右后缀前面。
            原骨对应顶点组会被清掉，权重按过渡参数分配到各个Twist骨。"""
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(
        name="细分段数",
        description="生成的Twist子骨数量",
        default=3,
        min=1,
    )  # type: ignore
    process_symmetry: BoolProperty(
        name="对称操作",
        description="同时对镜像骨骼进行处理",
        default=False,
    )  # type: ignore
    only_selected: BoolProperty(
        name="仅选择的物体",
        description="只处理当前被选中的网格物体",
        default=False,
    )  # type: ignore
    soft_factor: FloatProperty(
        name="过渡",
        description="Twist骨之间的权重过渡",
        min=0.0,
        max=1.0,
        step=0.05,
        default=0.5,
    )  # type: ignore

    def get_mirrored_bone(self, bone_name, armature) -> list[str]:
        names = [bone_name]
        symmetrical_name = bpy.utils.flip_name(bone_name)
        if symmetrical_name != bone_name and symmetrical_name in armature.bones:
            names.append(symmetrical_name)
        return names

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
        original_active = context.active_object
        original_mode = original_active.mode

        armature_obj: bpy.types.Object = None
        mesh_objs: list[bpy.types.Object] = []
        bones: list[str] = []

        if original_active.type == "ARMATURE":
            armature_obj = original_active
            if armature_obj.mode == "POSE":
                bones = [bone.name for bone in context.selected_pose_bones]
            elif armature_obj.mode == "EDIT":
                bones = [bone.name for bone in armature_obj.data.edit_bones if bone.select]

            for obj in bpy.data.objects:
                if obj.type != "MESH":
                    continue
                for mod in obj.modifiers:
                    if mod.type == "ARMATURE" and mod.object == armature_obj:
                        mesh_objs.append(obj)
                        break

        elif original_active.type == "MESH":
            mesh_obj = original_active
            for mod in mesh_obj.modifiers:
                if mod.type == "ARMATURE" and mod.object:
                    armature_obj = mod.object
                    break

            bones = [bone.name for bone in context.selected_pose_bones]

            for obj in bpy.data.objects:
                if obj.type != "MESH":
                    continue
                for mod in obj.modifiers:
                    if mod.type == "ARMATURE" and mod.object == armature_obj:
                        mesh_objs.append(obj)
                        break
        else:
            self.report({"ERROR"}, "不支持的对象")
            return {"CANCELLED"}

        if not bones:
            self.report({"ERROR"}, "没有找到要处理的骨骼")
            return {"CANCELLED"}

        if self.only_selected:
            mesh_objs = [obj for obj in mesh_objs if obj.select_get()]

        if not mesh_objs:
            self.report({"ERROR"}, "没有找到需要处理的网格物体")
            return {"CANCELLED"}

        if self.process_symmetry:
            mirrored = []
            for bone_name in bones:
                mirrored.extend(self.get_mirrored_bone(bone_name, armature_obj.data))
            bones = list(dict.fromkeys(mirrored))
        else:
            bones = list(dict.fromkeys(bones))

        try:
            for bn in bones:
                objs_with_bone = [
                    obj for obj in mesh_objs
                    if obj.vertex_groups.get(bn)
                ]
                if not objs_with_bone:
                    continue

                TwistBoneCore.objs_bone_twist(
                    bn,
                    self.count,
                    armature_obj,
                    self.soft_factor,
                    objs_with_bone,
                )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        context.view_layer.objects.active = original_active
        BoneSplitCore.set_object_mode(original_active, mode=original_mode)
        if original_mode == "WEIGHT_PAINT":
            armature_obj.select_set(True)
            bpy.context.view_layer.objects.active = armature_obj
            BoneSplitCore.set_object_mode(armature_obj, "POSE")
            original_active.select_set(True)
            bpy.context.view_layer.objects.active = original_active
            BoneSplitCore.set_object_mode(original_active, "WEIGHT_PAINT")

        self.report({"INFO"}, "Twist骨生成成功")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "count")
        layout.prop(self, "process_symmetry")
        layout.prop(self, "only_selected")
        layout.prop(self, "soft_factor")


cls = [
    OP_TwistBoneWithWeight,
]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
