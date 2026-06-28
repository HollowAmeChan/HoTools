import bpy
import math
import numpy as np
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Context, Operator, UILayout
from mathutils import Vector

from .boneSplit import BoneSplitCore


EPS = 1e-6
HoRig_Twist = "HoRig_Twist"


def reg_props():
    return


def ureg_props():
    return


def _safe_normalized_vector(vector):
    if vector.length < EPS:
        return None
    return vector.normalized()


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def drawBoneTwistPanel(layout: UILayout, context: Context):
    twist_box = layout.box()
    row = twist_box.row(align=True)
    row.operator(OP_TwistBoneWithWeight.bl_idname, text="生成 Twist 骨")
    row.operator(OP_RemoveTwistBoneWithWeight.bl_idname, text="清除 Twist 骨")


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
    def _parse_twist_name(name: str) -> tuple[str, int] | None:
        stem, side_suffix = TwistBoneCore._split_side_suffix(name)
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
        axis = _safe_normalized_vector(axis)
        if axis is None:
            return None

        return (
            vector * math.cos(angle_rad)
            + axis.cross(vector) * math.sin(angle_rad)
            + axis * axis.dot(vector) * (1.0 - math.cos(angle_rad))
        )

    @staticmethod
    def _selected_bone_names(context: Context, armature: bpy.types.Object) -> list[str]:
        if armature.mode == "POSE":
            return [bone.name for bone in context.selected_pose_bones]
        if armature.mode == "EDIT":
            return [bone.name for bone in armature.data.edit_bones if bone.select]
        return []

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
    def get_mirrored_bone(bone_name, armature) -> list[str]:
        names = [bone_name]
        symmetrical_name = bpy.utils.flip_name(bone_name)

        bone_container = getattr(armature, "bones", armature)
        if symmetrical_name != bone_name and bone_container.get(symmetrical_name):
            names.append(symmetrical_name)

        return names

    @staticmethod
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

    @staticmethod
    def _assign_bones_to_collection(armature: bpy.types.Object, bone_names: list[str], collection_name: str) -> None:
        collection = TwistBoneCore._ensure_bone_collection(armature, collection_name)
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
        constraint = None
        for item in pose_bone.constraints:
            if item.type == "STRETCH_TO" and item.name == "HoTools_StretchTo":
                constraint = item
                break

        if constraint is None:
            constraint = pose_bone.constraints.new("STRETCH_TO")
            constraint.name = "HoTools_StretchTo"

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
            BoneSplitCore.set_object_mode(armature, "POSE")
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
            BoneSplitCore.set_object_mode(armature, old_mode)

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
    def _set_temp_mesh_mirror_off(obj: bpy.types.Object) -> dict[str, tuple[object, bool]]:
        mirror_state = {}
        for prop_name in ("use_mesh_mirror_x", "use_mesh_mirror_y", "use_mesh_mirror_z"):
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
    def _set_temp_armature_mirror_off(armature: bpy.types.Object) -> dict[str, tuple[object, bool]]:
        mirror_state = {}

        data = getattr(armature, "data", None)
        if data is not None and hasattr(data, "use_mirror_x"):
            mirror_state["data.use_mirror_x"] = (data, data.use_mirror_x)
            data.use_mirror_x = False

        pose = getattr(armature, "pose", None)
        if pose is not None and hasattr(pose, "use_mirror_x"):
            mirror_state["pose.use_mirror_x"] = (pose, pose.use_mirror_x)
            pose.use_mirror_x = False

        return mirror_state

    @staticmethod
    def _restore_armature_mirror_state(mirror_state: dict[str, tuple[object, bool]]) -> None:
        for _, (owner, value) in mirror_state.items():
            owner.use_mirror_x = value

    @staticmethod
    def create_twist_chain(
        armature: bpy.types.Object,
        bn: str,
        count: int,
        twist_length_factor: float = 0.1,
        bone_collection_name: str = HoRig_Twist,
    ) -> dict:
        """在保留主骨的前提下，生成 Twist 子骨链。"""
        was_hidden = armature.hide_viewport
        old_mode = armature.mode
        mirror_state = TwistBoneCore._set_temp_armature_mirror_off(armature)
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
            BoneSplitCore.set_object_mode(armature, "EDIT")

            edit_bones = armature.data.edit_bones
            old_bone = edit_bones.get(bn)
            if old_bone is None:
                raise Exception(f"在编辑模式中未找到骨骼: {bn}")

            bone_vec = old_bone.tail - old_bone.head
            if bone_vec.length <= 1e-8:
                raise Exception(f"骨骼长度为 0: {bn}")

            bone_dir = bone_vec.normalized()
            twist_length = max(bone_vec.length * twist_length_factor, 1e-4)
            padding = max(2, len(str(count)))
            new_bone_names = [
                TwistBoneCore._twist_name(bn, count - i + 1, padding)
                for i in range(1, count + 1)
            ]

            existed = [name for name in new_bone_names if edit_bones.get(name)]
            if existed:
                result["replaced_names"] = existed
                result["replaced_count"] = len(existed)
                for name in reversed(existed):
                    old_twist = edit_bones.get(name)
                    if old_twist is not None:
                        edit_bones.remove(old_twist)

            corrected_points = [
                old_bone.head.lerp(old_bone.tail, i / count)
                for i in range(count + 1)
            ]

            for i, new_name in enumerate(new_bone_names, start=1):
                new_bone = edit_bones.new(new_name)
                new_bone.head = corrected_points[i - 1].copy()
                new_bone.tail = new_bone.head + bone_dir * twist_length
                new_bone.roll = 0.0
                new_bone.use_deform = True
                new_bone.parent = old_bone
                new_bone.use_connect = False

            TwistBoneCore._assign_bones_to_collection(armature, new_bone_names, bone_collection_name)
            bpy.context.view_layer.objects.active = armature
            BoneSplitCore.set_object_mode(armature, "OBJECT")
            # 设置 hotools 属性：取消保留旋转，并把 humanoidMapping 填成自身名称
            TwistBoneCore._apply_hotools_bone_props(armature, new_bone_names)
            result["created_names"] = new_bone_names
            result["created_count"] = len(new_bone_names)

            return result
        finally:
            TwistBoneCore._restore_armature_mirror_state(mirror_state)

            try:
                if armature.mode != old_mode:
                    bpy.context.view_layer.objects.active = armature
                    BoneSplitCore.set_object_mode(armature, old_mode)
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
    ):
        old_mode = obj.mode
        mirror_state = TwistBoneCore._set_temp_mesh_mirror_off(obj)

        try:
            if old_mode == "EDIT":
                bpy.context.view_layer.objects.active = obj
                BoneSplitCore.set_object_mode(obj, "OBJECT")

            new_vgs: list[bpy.types.VertexGroup] = []
            for new_name in new_bone_names:
                vg = obj.vertex_groups.new(name=new_name)
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

            n_verts = len(obj.data.vertices)
            if n_verts == 0:
                obj.vertex_groups.remove(tmp_vg)
                return

            verts_np = np.array([list(v.co) for v in obj.data.vertices], dtype=float)
            weights_np = np.zeros(n_verts, dtype=float)
            has_weight_np = np.zeros(n_verts, dtype=bool)
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
            pos = f * count - 0.5
            pos = np.clip(pos, 0, count - 1)
            i_seg = np.floor(pos).astype(int)
            local_factor = pos - i_seg

            for i in range(n_verts):
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
        twist_length_factor: float,
        objs,
        bone_collection_name: str = HoRig_Twist,
    ) -> dict:
        """把选中的主骨权重转移到 Twist 子骨链上。"""
        chain_result = TwistBoneCore.create_twist_chain(
            armature,
            bn,
            count,
            twist_length_factor,
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
                bn,
            )

        chain_result["source_bone"] = bn
        chain_result["weight_object_count"] = len(objs)
        chain_result["target_objects"] = [obj.name for obj in objs]
        chain_result["replaced_names"] = replaced_names
        return chain_result

    @staticmethod
    def _collect_mesh_objects_for_armature(armature_obj: bpy.types.Object) -> list[bpy.types.Object]:
        mesh_objs = []
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            for mod in obj.modifiers:
                if mod.type == "ARMATURE" and mod.object == armature_obj:
                    mesh_objs.append(obj)
                    break
        return mesh_objs

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
            mesh_objs = TwistBoneCore._collect_mesh_objects_for_armature(armature_obj)
        elif original_active.type == "MESH":
            for mod in original_active.modifiers:
                if mod.type == "ARMATURE" and mod.object:
                    armature_obj = mod.object
                    break
            active_bone = context.active_pose_bone
            if active_bone:
                bones = [active_bone.name]
            if armature_obj:
                mesh_objs = TwistBoneCore._collect_mesh_objects_for_armature(armature_obj)
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
                mirrored = []
                for bone_name in bones:
                    mirrored.extend(
                        TwistBoneCore.get_mirrored_bone(
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
                BoneSplitCore.set_object_mode(original_active, mode=original_mode)

            if original_mode == "WEIGHT_PAINT" and armature_obj is not None:
                armature_obj.select_set(True)
                context.view_layer.objects.active = armature_obj
                BoneSplitCore.set_object_mode(armature_obj, "POSE")
                original_active.select_set(True)
                context.view_layer.objects.active = original_active
                BoneSplitCore.set_object_mode(original_active, "WEIGHT_PAINT")

        return {
            "created_count": sum(item.get("created_count", 0) for item in results),
            "replaced_count": sum(item.get("replaced_count", 0) for item in results),
            "constraint_count": constraint_count if "constraint_count" in locals() else 0,
            "constraint_targets": target_map if "target_map" in locals() else {},
            "twist_bone_names": twist_bone_names,
            "items": results,
        }

    @staticmethod
    def _collect_removal_targets(
        context: Context,
        original_active: bpy.types.Object,
        process_vertex_groups: bool,
    ):
        armature_obj = None
        mesh_objs = []
        bones = []

        if original_active.type == "ARMATURE":
            armature_obj = original_active
            if armature_obj.mode == "POSE":
                bones = [bone.name for bone in context.selected_pose_bones]
            elif armature_obj.mode == "EDIT":
                bones = [bone.name for bone in armature_obj.data.edit_bones if bone.select]
            mesh_objs = TwistBoneCore._collect_mesh_objects_for_armature(armature_obj)
        elif original_active.type == "MESH":
            for mod in original_active.modifiers:
                if mod.type == "ARMATURE" and mod.object:
                    armature_obj = mod.object
                    break
            bones = [bone.name for bone in context.selected_pose_bones]
            if armature_obj:
                mesh_objs = TwistBoneCore._collect_mesh_objects_for_armature(armature_obj)
        else:
            raise Exception("不支持的对象")

        if not armature_obj:
            raise Exception("没有找到骨架")

        if not bones:
            raise Exception("没有找到要处理的骨骼")

        main_names = []
        for bone_name in bones:
            parsed = TwistBoneCore._parse_twist_name(bone_name)
            main_name = parsed[0] if parsed is not None else bone_name
            if armature_obj.data.bones.get(main_name) is not None:
                main_names.append(main_name)

        main_names = list(dict.fromkeys(main_names))
        if not main_names:
            raise Exception("没有选择任何主骨")

        main_to_twists: dict[str, list[str]] = {}
        twist_names: list[str] = []

        for main_name in main_names:
            main_bone = armature_obj.data.bones.get(main_name)
            if main_bone is None:
                continue

            collected = []
            stack = list(main_bone.children)
            while stack:
                bone = stack.pop()
                stack.extend(bone.children)
                parsed = TwistBoneCore._parse_twist_name(bone.name)
                if parsed is None or parsed[0] != main_name:
                    continue
                collected.append(bone.name)

            collected = list(dict.fromkeys(collected))
            collected.sort(key=lambda bone_name: TwistBoneCore._parse_twist_name(bone_name)[1])
            if collected:
                main_to_twists[main_name] = collected
                twist_names.extend(collected)

        twist_names = list(dict.fromkeys(twist_names))
        if not twist_names:
            raise Exception("没有找到任何 twist 子骨")

        if process_vertex_groups:
            return armature_obj, mesh_objs, main_to_twists, twist_names

        return armature_obj, mesh_objs, None, twist_names
    @staticmethod
    def obj_twist_restore(
        obj: bpy.types.Object,
        main_to_twists: dict[str, list[str]],
    ) -> None:
        old_mode = obj.mode
        old_active = bpy.context.view_layer.objects.active
        mirror_state = TwistBoneCore._set_temp_mesh_mirror_off(obj)
        mode_changed = False

        try:
            if old_mode != "OBJECT":
                bpy.context.view_layer.objects.active = obj
                BoneSplitCore.set_object_mode(obj, "OBJECT")
                mode_changed = True

            for main_name, twist_names in main_to_twists.items():
                twist_vgs = [
                    vg for vg in (
                        obj.vertex_groups.get(twist_name)
                        for twist_name in twist_names
                    )
                    if vg is not None
                ]
                main_vg = obj.vertex_groups.get(main_name)

                if main_vg is None and not twist_vgs:
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

                    for twist_vg in twist_vgs:
                        try:
                            total_weight += twist_vg.weight(vertex.index)
                            has_explicit_weight = True
                        except RuntimeError:
                            continue

                    if has_explicit_weight:
                        main_vg.add([vertex.index], total_weight, "REPLACE")

                for twist_name in twist_names:
                    twist_vg = obj.vertex_groups.get(twist_name)
                    if twist_vg:
                        obj.vertex_groups.remove(twist_vg)
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

    @staticmethod
    def remove_twist_bones(
        armature: bpy.types.Object,
        twist_names: list[str],
    ) -> None:
        was_hidden = armature.hide_viewport
        old_mode = armature.mode
        mirror_state = TwistBoneCore._set_temp_armature_mirror_off(armature)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            BoneSplitCore.set_object_mode(armature, "EDIT")

            edit_bones = armature.data.edit_bones
            missing = [bone_name for bone_name in twist_names if edit_bones.get(bone_name) is None]
            if missing:
                raise Exception("找不到要删除的 Twist 骨: " + ", ".join(missing))

            for bone_name in twist_names:
                bone = edit_bones.get(bone_name)
                if bone:
                    edit_bones.remove(bone)

            bpy.context.view_layer.objects.active = armature
            BoneSplitCore.set_object_mode(armature, "OBJECT")
        finally:
            try:
                if armature.mode != old_mode:
                    bpy.context.view_layer.objects.active = armature
                    BoneSplitCore.set_object_mode(armature, old_mode)
            except Exception:
                pass

            TwistBoneCore._restore_armature_mirror_state(mirror_state)

            if was_hidden:
                armature.hide_set(True)

    @staticmethod
    def remove_twist(
        context: Context,
        original_active: bpy.types.Object,
        only_selected: bool = False,
        process_vertex_groups: bool = True,
    ) -> dict:
        original_mode = original_active.mode
        armature_obj = None
        result = {
            "restored_objects": 0,
            "removed_twist_bones": 0,
            "removed_vertex_groups": 0,
        }

        try:
            armature_obj, mesh_objs, main_to_twists, twist_names = TwistBoneCore._collect_removal_targets(
                context,
                original_active,
                process_vertex_groups,
            )

            if process_vertex_groups:
                if only_selected:
                    mesh_objs = [obj for obj in mesh_objs if obj.select_get()]

                if not mesh_objs:
                    raise Exception("没有找到需要处理的网格物体")

                TwistBoneCore.objs_twist_restore(
                    main_to_twists,
                    armature_obj,
                    mesh_objs,
                )
                result["restored_objects"] = len(mesh_objs)
                result["removed_vertex_groups"] = sum(
                    len(twist_list) for twist_list in main_to_twists.values()
                )
            else:
                TwistBoneCore.remove_twist_bones(armature_obj, twist_names)
                result["removed_twist_bones"] = len(twist_names)
        finally:
            if original_active:
                context.view_layer.objects.active = original_active
                BoneSplitCore.set_object_mode(original_active, mode=original_mode)

            if original_mode == "WEIGHT_PAINT" and armature_obj is not None:
                armature_obj.select_set(True)
                context.view_layer.objects.active = armature_obj
                BoneSplitCore.set_object_mode(armature_obj, "POSE")
                original_active.select_set(True)
                context.view_layer.objects.active = original_active
                BoneSplitCore.set_object_mode(original_active, "WEIGHT_PAINT")

        return result

    @staticmethod
    def objs_twist_restore(
        main_to_twists: dict[str, list[str]],
        armature: bpy.types.Object,
        objs: list[bpy.types.Object],
    ) -> None:
        for obj in objs:
            TwistBoneCore.obj_twist_restore(obj, main_to_twists)

        twist_names = [
            twist_name
            for twist_list in main_to_twists.values()
            for twist_name in twist_list
        ]
        TwistBoneCore.remove_twist_bones(armature, twist_names)

    @staticmethod
    def set_object_mode(obj, mode):
        """保持和既有骨工具一致的模式切换方式。"""
        return BoneSplitCore.set_object_mode(obj, mode)


class OP_TwistBoneWithWeight(Operator):
    bl_idname = "ho.twistbone_withweight"
    bl_label = "生成 Twist 骨与权重"
    bl_description = """
    在所选主骨上生成 Twist 子骨，并可按权重参数同步转移权重。
    适用于姿态模式、编辑模式，以及权重绘制场景下的当前活动骨骼。
    生成的 Twist 会保留主骨本体，按主骨方向延伸；左右后缀会插在 Twist 后缀之前。
    需要切分权重时会临时关闭镜像选项，结束后恢复原设置。"""
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(
        name="细分段数",
        description="生成的 Twist 子骨数量",
        min=1,
        default=4,
    )  # type: ignore
    twist_length_factor: FloatProperty(
        name="Twist 长度",
        description="Twist 子骨长度相对于主骨长度的比例",
        min=0.0,
        max=1.0,
        step=0.01,
        default=0.1,
    )  # type: ignore
    process_symmetry: BoolProperty(
        name="对称操作",
        description="同时处理镜像骨骼",
        default=False,
    )  # type: ignore
    copy_rotation_target_bone: StringProperty(
        name="目标骨",
        description="约束指向的目标骨骼",
        default="",
    )  # type: ignore
    copy_rotation_top_influence: FloatProperty(
        name="上约束强度",
        description="链顶部 Twist 的 Copy Rotation 强度",
        default=0.1,
        min=0.0,
        max=1.0,
    )  # type: ignore
    copy_rotation_bottom_influence: FloatProperty(
        name="下约束强度",
        description="链底部 Twist 的 Copy Rotation 强度",
        default=0.8,
        min=0.0,
        max=1.0,
    )  # type: ignore
    auto_transfer_weights: BoolProperty(
        name="自动处理权重",
        description="生成 Twist 骨后自动把权重转移到新骨骼",
        default=False,
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
                self.count,
                self.twist_length_factor,
                self.process_symmetry,
                self.auto_transfer_weights,
                self.only_selected,
                self.soft_factor,
                self.copy_rotation_target_bone,
                self.copy_rotation_top_influence,
                self.copy_rotation_bottom_influence,
                self.bone_collection_name,
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
        armature = context.active_object
        selected = TwistBoneCore._selected_bone_names(context, armature) if armature and armature.type == "ARMATURE" else []
        target = ""
        if armature and armature.type == "ARMATURE":
            target = TwistBoneCore._find_copy_rotation_target_bone(armature, selected, "")
            if target:
                self.copy_rotation_target_bone = target
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "count")
        layout.prop(self, "twist_length_factor")
        row = layout.row(align=True)
        row.prop(self, "copy_rotation_target_bone")
        row = layout.row(align=True)
        row.prop(self, "copy_rotation_top_influence")
        row.prop(self, "copy_rotation_bottom_influence")
        layout.prop(self, "bone_collection_name")
        layout.prop(self, "process_symmetry")
        layout.prop(self, "auto_transfer_weights")

        sub = layout.column()
        sub.enabled = self.auto_transfer_weights
        sub.prop(self, "only_selected")
        sub.prop(self, "soft_factor")

class OP_RemoveTwistBoneWithWeight(Operator):
    bl_idname = "ho.removetwistbone_withweight"
    bl_label = "清除 Twist 骨"
    bl_description = """
    删除选中的 Twist 骨，并把它们的顶点组权重恢复到对应主骨上。
    使用方式:在姿态模式或编辑模式同时选择主骨和一个或多个对应 Twist 骨，然后运行本操作。
            也可以在权重绘制时使用当前骨骼选择；必须同时选中主骨和对应 Twist 骨。
            工具会通过 原名_twist_数字 的命名规则反推主骨名，.L/.R/_L/_R 等方向后缀会保留在最后。
            每个网格上会把主骨顶点组与被选中 Twist 顶点组的权重相加回主骨顶点组。
            读取顶点组时会区分无权重与显式 0 权重；只有无法读取权重的顶点才视为无权重。
            恢复完成后会删除被选中 Twist 骨对应的顶点组，并从骨架中删除这些 Twist 骨。"""
    bl_options = {"REGISTER", "UNDO"}

    only_selected: BoolProperty(
        name="仅选中的物体",
        description="只处理当前被选中的网格物体",
        default=False,
    )  # type: ignore
    process_vertex_groups: BoolProperty(
        name="处理顶点组",
        description="删除 Twist 骨时同步恢复并清理对应顶点组",
        default=True,
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

        return bool(context.selected_pose_bones)

    def execute(self, context):
        try:
            result = TwistBoneCore.remove_twist(
                context,
                context.active_object,
                self.only_selected,
                self.process_vertex_groups,
            )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            (
                f"Twist骨: 恢复物体 {result['restored_objects']}，"
                f"删除骨 {result['removed_twist_bones']}，"
                f"删除组 {result['removed_vertex_groups']}"
            ),
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "process_vertex_groups")

        sub = layout.column()
        sub.enabled = self.process_vertex_groups
        sub.prop(self, "only_selected")


cls = [
    OP_TwistBoneWithWeight,
    OP_RemoveTwistBoneWithWeight,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    for item in cls:
        bpy.utils.unregister_class(item)
    ureg_props()
