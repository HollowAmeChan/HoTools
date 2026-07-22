import bpy
from bpy.props import PointerProperty
from bpy.types import Operator

from ..BoneTools.boneHumanoid import OP_MoveHumanoidBonesToCollection
from ..BoneTools.boneOperators import OP_ApplyRestPose
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
    def _collect_pose_heads_world(obj, depsgraph):
        """读取依赖图评估后的姿态骨骼Head世界坐标。"""
        evaluated = obj.evaluated_get(depsgraph)
        world = evaluated.matrix_world
        return {
            pose_bone.name: world @ pose_bone.head
            for pose_bone in evaluated.pose.bones
        }

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
        disconnected_count = 0
        original_edit_state = {}
        operation_error = None

        try:
            active = context.view_layer.objects.active
            if active is not None and active.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            depsgraph = context.evaluated_depsgraph_get()
            reference_heads_world = self._collect_pose_heads_world(
                reference,
                depsgraph,
            )
            moving_heads_world = self._collect_pose_heads_world(
                moving,
                depsgraph,
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

            for obj in context.view_layer.objects:
                if obj.select_get():
                    obj.select_set(False)

            moving.select_set(True)
            context.view_layer.objects.active = moving
            bpy.ops.object.mode_set(mode='EDIT')

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

            moving_world_inv = moving.matrix_world.inverted_safe()
            moving_world_inv_3x3 = moving_world_inv.to_3x3()

            for bone in edit_bones:
                target_head_world = reference_heads_world.get(bone.name)
                current_head_world = moving_heads_world.get(bone.name)
                if target_head_world is None or current_head_world is None:
                    unmatched_count += 1
                    continue

                # 用姿态下的视觉位置差平移编辑骨，而不是把姿态坐标
                # 直接当作静置坐标，避免已有Pose变换被重复叠加。
                offset_world = target_head_world - current_head_world
                offset = moving_world_inv_3x3 @ offset_world
                bone_vector = bone.tail - bone.head
                target_head = bone.head + offset

                bone.head = target_head
                bone.tail = target_head + bone_vector

                aligned_count += 1
                if offset.length_squared > 1e-12:
                    moved_count += 1
                else:
                    unchanged_count += 1

            bpy.ops.object.mode_set(mode='OBJECT')

        except Exception as error:
            operation_error = error

            if (
                context.view_layer.objects.active == moving
                and moving.mode == 'EDIT'
                and original_edit_state
            ):
                for bone_name, state in original_edit_state.items():
                    bone = moving.data.edit_bones.get(bone_name)
                    if bone is None:
                        continue
                    bone.head, bone.tail, bone.use_connect = state

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
            f"无同名 {unmatched_count}，断开连接 {disconnected_count}",
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
