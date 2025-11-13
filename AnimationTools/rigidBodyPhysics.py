import bpy
import random
from bpy.types import Operator


# region 变量
def reg_props():
    return


def ureg_props():
    return
# endregion


class OP_SetViewPortShadingMode(Operator):
    bl_idname = "ho.set_viewport_shadingmode_rigidview"
    bl_label = "space_data.shading.color_type = 'OBJECT'"
    bl_description = "设置视图预览方便看刚体"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if bpy.context.space_data.shading.color_type == 'OBJECT':
            bpy.context.space_data.shading.color_type = 'MATERIAL'
        else:
            bpy.context.space_data.shading.color_type = 'OBJECT'
        return {'FINISHED'}


class OP_AssignColorsByCollisionGroupCombination(Operator):
    bl_idname = "ho.assign_colors_by_collision_group_combination"
    bl_label = "Assign Colors by Collision Group Combination"
    bl_description = "根据碰撞组不同，对所选物体进行颜色分类"
    bl_options = {'REGISTER', 'UNDO'}

    seed: bpy.props.IntProperty(name="Seed", default=42)  # type: ignore

    def execute(self, context):
        # 初始化随机数生成器
        random.seed(self.seed)

        selected_objs = context.selected_objects
        color_map = {}

        for obj in selected_objs:
            if obj.rigid_body:
                # 根据开启的碰撞组生成唯一组合键
                group_key = tuple(obj.rigid_body.collision_collections)

                # 如果组合键不在color_map中，生成新颜色并添加到字典中
                if group_key not in color_map:
                    color_map[group_key] = (
                        random.random(), random.random(), random.random(), 1.0)
                # 为物体分配对应颜色
                obj.color = color_map[group_key]
        return {'FINISHED'}


class OP_CopyRigidBodySettings(Operator):
    bl_idname = "ho.copy_rigidbody_constraints_settings"
    bl_label = "Copy Rigid Body Constraints Setting to Selected Empties"
    bl_description = "复制刚体约束到所选的全部空物体（不复制物体"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active_obj = context.active_object
        selected_objs = context.selected_objects

        # 检查活动物体是否是空物体且具有刚体约束
        if active_obj is None or active_obj.type != 'EMPTY' or not active_obj.rigid_body_constraint:
            self.report(
                {'WARNING'}, "或动物体必须是有刚体约束的空物体。Active object must be an empty with rigid body constraint settings")
            return {'CANCELLED'}

        # 获取活动物体的刚体约束设置
        constraint_settings = active_obj.rigid_body_constraint

        for obj in selected_objs:
            # 跳过活动物体本身
            if obj == active_obj:
                continue
            # 检查对象是否是空物体
            if obj.type == 'EMPTY':
                # 如果没有刚体约束，添加刚体约束
                if not obj.rigid_body_constraint:
                    bpy.ops.rigidbody.constraint_add({'object': obj})
                # 复制刚体约束设置
                obj.rigid_body_constraint.type = constraint_settings.type  # 类型
                # 设置
                obj.rigid_body_constraint.enabled = constraint_settings.enabled  # 已开启
                obj.rigid_body_constraint.disable_collisions = constraint_settings.disable_collisions  # 禁用碰撞
                obj.rigid_body_constraint.use_breaking = constraint_settings.use_breaking  # 可断
                obj.rigid_body_constraint.breaking_threshold = constraint_settings.breaking_threshold  # 断裂阈值
                # 限制
                obj.rigid_body_constraint.use_limit_ang_x = constraint_settings.use_limit_ang_x
                obj.rigid_body_constraint.use_limit_ang_y = constraint_settings.use_limit_ang_y
                obj.rigid_body_constraint.use_limit_ang_z = constraint_settings.use_limit_ang_z
                obj.rigid_body_constraint.use_limit_lin_x = constraint_settings.use_limit_lin_x
                obj.rigid_body_constraint.use_limit_lin_y = constraint_settings.use_limit_lin_y
                obj.rigid_body_constraint.use_limit_lin_z = constraint_settings.use_limit_lin_z
                obj.rigid_body_constraint.limit_lin_x_lower = constraint_settings.limit_lin_x_lower
                obj.rigid_body_constraint.limit_lin_x_upper = constraint_settings.limit_lin_x_upper
                obj.rigid_body_constraint.limit_lin_y_lower = constraint_settings.limit_lin_y_lower
                obj.rigid_body_constraint.limit_lin_y_upper = constraint_settings.limit_lin_y_upper
                obj.rigid_body_constraint.limit_lin_z_lower = constraint_settings.limit_lin_z_lower
                obj.rigid_body_constraint.limit_lin_z_upper = constraint_settings.limit_lin_z_upper
                obj.rigid_body_constraint.limit_ang_x_lower = constraint_settings.limit_ang_x_lower
                obj.rigid_body_constraint.limit_ang_x_upper = constraint_settings.limit_ang_x_upper
                obj.rigid_body_constraint.limit_ang_y_lower = constraint_settings.limit_ang_y_lower
                obj.rigid_body_constraint.limit_ang_y_upper = constraint_settings.limit_ang_y_upper
                obj.rigid_body_constraint.limit_ang_z_lower = constraint_settings.limit_ang_z_lower
                obj.rigid_body_constraint.limit_ang_z_upper = constraint_settings.limit_ang_z_upper
                # 物体
                # NOTE:不复制物体

                # 重写迭代
                obj.rigid_body_constraint.use_override_solver_iterations = constraint_settings.use_override_solver_iterations
                obj.rigid_body_constraint.solver_iterations = constraint_settings.solver_iterations  # 解算器迭代次数
                # 弹性
                obj.rigid_body_constraint.spring_type = constraint_settings.spring_type
                obj.rigid_body_constraint.use_spring_ang_x = constraint_settings.use_spring_ang_x
                obj.rigid_body_constraint.spring_stiffness_ang_x = constraint_settings.spring_stiffness_ang_x
                obj.rigid_body_constraint.spring_damping_ang_x = constraint_settings.spring_damping_ang_x

                obj.rigid_body_constraint.use_spring_ang_y = constraint_settings.use_spring_ang_y
                obj.rigid_body_constraint.spring_stiffness_ang_y = constraint_settings.spring_stiffness_ang_y
                obj.rigid_body_constraint.spring_damping_ang_y = constraint_settings.spring_damping_ang_y

                obj.rigid_body_constraint.use_spring_ang_z = constraint_settings.use_spring_ang_z
                obj.rigid_body_constraint.spring_stiffness_ang_z = constraint_settings.spring_stiffness_ang_z
                obj.rigid_body_constraint.spring_damping_ang_z = constraint_settings.spring_damping_ang_z

                obj.rigid_body_constraint.use_spring_x = constraint_settings.use_spring_x
                obj.rigid_body_constraint.spring_stiffness_x = constraint_settings.spring_stiffness_x
                obj.rigid_body_constraint.spring_damping_x = constraint_settings.spring_damping_x

                obj.rigid_body_constraint.use_spring_y = constraint_settings.use_spring_y
                obj.rigid_body_constraint.spring_stiffness_y = constraint_settings.spring_stiffness_y
                obj.rigid_body_constraint.spring_damping_y = constraint_settings.spring_damping_y

                obj.rigid_body_constraint.use_spring_z = constraint_settings.use_spring_z
                obj.rigid_body_constraint.spring_stiffness_z = constraint_settings.spring_stiffness_z
                obj.rigid_body_constraint.spring_damping_z = constraint_settings.spring_damping_z

        return {'FINISHED'}


cls = [OP_CopyRigidBodySettings, OP_SetViewPortShadingMode,
       OP_AssignColorsByCollisionGroupCombination,
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
