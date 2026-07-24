import bpy
from bpy.props import PointerProperty
from bpy.types import Operator
from mathutils import Vector

from ..BoneTools.boneHumanoid import OP_MoveHumanoidBonesToCollection
from ..BoneTools.boneOperators import (
    OP_ApplyRestPose,
    drawMergeArmaturesPanel,
)
from ..BoneTools.boneDissolve import OP_SimpleDissolveBone


def _armature_filter(_self, obj):
    return obj.type == 'ARMATURE'


def reg_props():
    bpy.types.Scene.ho_mod_weight_reference_armature = PointerProperty(
        name="参考骨架",
        description="提供同名骨骼Head目标位置的参考骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )
    bpy.types.Scene.ho_mod_weight_moving_armature = PointerProperty(
        name="移动骨架",
        description="需要移动同名骨骼的骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )


def ureg_props():
    del bpy.types.Scene.ho_mod_weight_moving_armature
    del bpy.types.Scene.ho_mod_weight_reference_armature


class OP_SnapMatchingBoneHeads(Operator):
    bl_idname = "ho.mod_weight_snap_matching_bone_heads"
    bl_label = "吸附同名骨骼Head"
    bl_description = (
        "按当前姿态的视觉位置，将移动骨架中所有同名骨骼的Head吸附到参考骨架；"
        "只平移骨骼并保持原有长度、方向和Roll"
    )
    bl_options = {'REGISTER', 'UNDO'}

    _MAX_CORRECTION_PASSES = 4
    _WORLD_TOLERANCE = 1e-5

    @classmethod
    def poll(cls, context):
        scene = context.scene
        reference = scene.ho_mod_weight_reference_armature
        moving = scene.ho_mod_weight_moving_armature
        return (
            reference is not None
            and moving is not None
            and reference.type == 'ARMATURE'
            and moving.type == 'ARMATURE'
        )

    @staticmethod
    def _restore_context(context, previous_active, previous_selected, previous_mode):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        for obj in context.view_layer.objects:
            try:
                obj.select_set(obj in previous_selected)
            except RuntimeError:
                pass

        context.view_layer.objects.active = previous_active

        if previous_active is not None and previous_mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode=previous_mode)
            except RuntimeError:
                pass

    @staticmethod
    def _collect_pose_snapshot(obj, depsgraph):
        """读取依赖图评估后的姿态Head世界坐标和姿态矩阵。"""
        evaluated = obj.evaluated_get(depsgraph)
        world = evaluated.matrix_world
        heads_world = {
            pose_bone.name: world @ pose_bone.head
            for pose_bone in evaluated.pose.bones
        }
        pose_matrices = {
            pose_bone.name: pose_bone.matrix.copy()
            for pose_bone in evaluated.pose.bones
        }
        return heads_world, pose_matrices

    @staticmethod
    def _bone_depth(bone):
        depth = 0
        parent = bone.parent
        while parent is not None:
            depth += 1
            parent = parent.parent
        return depth

    @staticmethod
    def _enter_edit_mode(context, moving):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        for obj in context.view_layer.objects:
            if obj.select_get():
                obj.select_set(False)

        moving.select_set(True)
        context.view_layer.objects.active = moving
        bpy.ops.object.mode_set(mode='EDIT')

    @staticmethod
    def _pose_residual_to_edit_offset(
        moving,
        parent_name,
        residual_world,
        pose_matrices,
        moving_world_inv_3x3,
    ):
        residual_armature = moving_world_inv_3x3 @ residual_world
        if parent_name is None:
            return residual_armature

        parent_pose_matrix = pose_matrices.get(parent_name)
        parent_bone = moving.data.bones.get(parent_name)
        if parent_pose_matrix is None or parent_bone is None:
            return residual_armature

        # 子骨静置坐标会先经过父骨当前的姿态形变；反变换后才能得到
        # 真正应写入EditBone的位移，尤其用于父骨已有旋转/缩放的情况。
        parent_deform = (
            parent_pose_matrix
            @ parent_bone.matrix_local.inverted_safe()
        )
        return parent_deform.to_3x3().inverted_safe() @ residual_armature

    def execute(self, context):
        scene = context.scene
        reference = scene.ho_mod_weight_reference_armature
        moving = scene.ho_mod_weight_moving_armature

        if reference == moving:
            self.report({'ERROR'}, "参考骨架与移动骨架不能是同一个对象")
            return {'CANCELLED'}

        if moving.name not in context.view_layer.objects:
            self.report({'ERROR'}, "移动骨架不在当前视图层中")
            return {'CANCELLED'}

        previous_active = context.view_layer.objects.active
        previous_selected = {
            obj for obj in context.view_layer.objects if obj.select_get()
        }
        previous_mode = (
            previous_active.mode if previous_active is not None else 'OBJECT'
        )

        aligned_count = 0
        moved_count = 0
        unchanged_count = 0
        unmatched_count = 0
        inherited_count = 0
        disconnected_count = 0
        correction_passes = 0
        max_world_error = 0.0
        original_edit_state = {}
        operation_error = None

        try:
            active = context.view_layer.objects.active
            if active is not None and active.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            depsgraph = context.evaluated_depsgraph_get()
            reference_heads_world, _reference_pose_matrices = (
                self._collect_pose_snapshot(
                    reference,
                    depsgraph,
                )
            )
            moving_heads_world, _moving_pose_matrices = (
                self._collect_pose_snapshot(
                    moving,
                    depsgraph,
                )
            )
            matching_names = {
                bone.name
                for bone in moving.data.bones
                if (
                    bone.name in reference_heads_world
                    and bone.name in moving_heads_world
                )
            }

            if not matching_names:
                self.report({'WARNING'}, "两个骨架中没有同名骨骼")
                return {'CANCELLED'}

            parent_names = {
                bone.name: bone.parent.name if bone.parent else None
                for bone in moving.data.bones
            }
            bones_by_depth = {}
            for bone in moving.data.bones:
                depth = self._bone_depth(bone)
                bones_by_depth.setdefault(depth, []).append(bone.name)

            self._enter_edit_mode(context, moving)

            edit_bones = moving.data.edit_bones
            original_edit_state = {
                bone.name: (
                    bone.head.copy(),
                    bone.tail.copy(),
                    bone.use_connect,
                )
                for bone in edit_bones
            }

            # 断开全部编辑骨，避免移动父骨或子骨Head时被连接关系拉回。
            for bone in edit_bones:
                if bone.use_connect:
                    bone.use_connect = False
                    disconnected_count += 1

            bpy.ops.object.mode_set(mode='OBJECT')

            moving_world_inv_3x3 = (
                moving.matrix_world.inverted_safe().to_3x3()
            )
            total_offsets = {
                bone.name: Vector((0.0, 0.0, 0.0))
                for bone in moving.data.bones
            }
            inherited_names = set()

            for pass_index in range(self._MAX_CORRECTION_PASSES):
                pass_offsets = {}

                for depth in sorted(bones_by_depth):
                    context.view_layer.update()
                    depsgraph = context.evaluated_depsgraph_get()
                    moving_heads_world, moving_pose_matrices = (
                        self._collect_pose_snapshot(
                            moving,
                            depsgraph,
                        )
                    )

                    depth_offsets = {}
                    for bone_name in bones_by_depth[depth]:
                        parent_name = parent_names[bone_name]

                        if bone_name in matching_names:
                            target_head_world = reference_heads_world[bone_name]
                            current_head_world = moving_heads_world.get(bone_name)
                            if current_head_world is None:
                                continue

                            residual_world = (
                                target_head_world - current_head_world
                            )
                            offset = self._pose_residual_to_edit_offset(
                                moving,
                                parent_name,
                                residual_world,
                                moving_pose_matrices,
                                moving_world_inv_3x3,
                            )
                        else:
                            # 无同名目标时，沿层级继承父骨本轮使用的同一offset。
                            offset = pass_offsets.get(parent_name)
                            if offset is None:
                                offset = Vector((0.0, 0.0, 0.0))
                            elif offset.length_squared > 1e-20:
                                inherited_names.add(bone_name)

                        pass_offsets[bone_name] = offset.copy()
                        if offset.length_squared > 1e-20:
                            depth_offsets[bone_name] = offset

                    if not depth_offsets:
                        continue

                    self._enter_edit_mode(context, moving)
                    for bone_name, offset in depth_offsets.items():
                        bone = moving.data.edit_bones.get(bone_name)
                        if bone is None:
                            continue

                        bone_vector = bone.tail - bone.head
                        target_head = bone.head + offset
                        bone.head = target_head
                        bone.tail = target_head + bone_vector
                        total_offsets[bone_name] += offset

                    bpy.ops.object.mode_set(mode='OBJECT')

                correction_passes = pass_index + 1
                context.view_layer.update()
                depsgraph = context.evaluated_depsgraph_get()
                moving_heads_world, _moving_pose_matrices = (
                    self._collect_pose_snapshot(
                        moving,
                        depsgraph,
                    )
                )
                errors = [
                    (
                        reference_heads_world[bone_name]
                        - moving_heads_world[bone_name]
                    ).length
                    for bone_name in matching_names
                    if bone_name in moving_heads_world
                ]
                max_world_error = max(errors, default=0.0)
                if max_world_error <= self._WORLD_TOLERANCE:
                    break

            aligned_count = len(matching_names)
            moved_count = sum(
                1
                for bone_name in matching_names
                if total_offsets[bone_name].length_squared > 1e-20
            )
            unchanged_count = aligned_count - moved_count
            unmatched_count = len(moving.data.bones) - aligned_count
            inherited_count = len(inherited_names)

        except Exception as error:
            operation_error = error

            if original_edit_state:
                try:
                    self._enter_edit_mode(context, moving)
                except Exception:
                    pass

            if moving.mode == 'EDIT' and original_edit_state:
                for bone_name, state in original_edit_state.items():
                    bone = moving.data.edit_bones.get(bone_name)
                    if bone is None:
                        continue
                    bone.head, bone.tail, bone.use_connect = state

                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass

        finally:
            try:
                self._restore_context(
                    context,
                    previous_active,
                    previous_selected,
                    previous_mode,
                )
            except Exception as restore_error:
                print(
                    "[Mod Weight Head Snap] failed to restore context: "
                    f"{restore_error}"
                )

        if operation_error is not None:
            self.report({'ERROR'}, f"吸附同名骨骼Head失败：{operation_error}")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"同名骨骼Head吸附完成：对齐 {aligned_count}，"
            f"移动 {moved_count}，未变化 {unchanged_count}，"
            f"子级跟随 {inherited_count}，无同名 {unmatched_count}，"
            f"断开连接 {disconnected_count}，校正 {correction_passes} 轮，"
            f"最大视觉误差 {max_world_error:.6g}",
        )
        return {'FINISHED'}


def drawWeightPanel(layout, context):
    column = layout.column(align=True)
    column.operator(OP_MoveHumanoidBonesToCollection.bl_idname,)
    column.operator(
        OP_ApplyRestPose.bl_idname,
        text="强制应用姿态与Mesh",
    )
    column.operator(
        OP_SimpleDissolveBone.bl_idname,
        text="简单融并",
    )

    layout.separator()
    box = layout.box()
    box.label(text="同名骨骼Head吸附")
    row = box.row(align=True)
    row.prop(
        context.scene,
        "ho_mod_weight_reference_armature",
        text="参考骨架",
    )
    row.prop(
        context.scene,
        "ho_mod_weight_moving_armature",
        text="移动骨架",
    )
    box.operator(
        OP_SnapMatchingBoneHeads.bl_idname,
        text="吸附同名骨骼Head",
    )

    layout.separator()
    drawMergeArmaturesPanel(layout, context)


cls = [
    OP_SnapMatchingBoneHeads,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    ureg_props()
    for item in reversed(cls):
        bpy.utils.unregister_class(item)
