import mathutils
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty
from bpy.types import Operator

from .collisionUtils import (
    _COLLISION_GROUP_COUNT,
    _active_armature_object,
    _active_collision_props,
    _active_mesh_collision_props,
    _active_object_collision_props,
    _bone_topology_data,
    _collision_group_bit,
    _collision_group_target_props,
    _collision_props,
    _exponent_factor,
    _object_collision_group_target_props,
    _selected_bone_names,
    _set_collision_group_bit,
    _spring_root_bones,
    _tag_view3d_redraw,
)


class OP_Hotools_BoneCollision_AddSelectedSpringRoots(Operator):
    bl_idname = "ho.bone_collision_add_selected_spring_roots"
    bl_label = "选中骨设为Root"
    bl_description = "把当前选中的骨骼标记为Spring Root"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature_obj = _active_armature_object(context)
        return armature_obj is not None and armature_obj.mode in {"EDIT", "POSE"}

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        selected_names = _selected_bone_names(context, armature_obj)
        if not selected_names:
            self.report({"WARNING"}, "没有选中骨骼")
            return {"CANCELLED"}

        changed = 0
        for name in selected_names:
            bone = armature_obj.data.bones.get(name)
            props = _collision_props(bone) if bone else None
            if props is None:
                continue
            props.spring_root = True
            changed += 1

        self.report({"INFO"}, f"已设置 {changed} 个Spring Root")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_ClearAllSpringRoots(Operator):
    bl_idname = "ho.bone_collision_clear_all_spring_roots"
    bl_label = "清空全部Root"
    bl_description = "清空当前骨架所有骨骼的Spring Root标记"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_armature_object(context) is not None

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        changed = 0
        for bone in armature_obj.data.bones:
            props = _collision_props(bone)
            if props is None:
                continue
            if props.spring_root:
                changed += 1
            props.spring_root = False

        self.report({"INFO"}, f"已清空 {changed} 个Spring Root")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_SelectSpringRoots(Operator):
    bl_idname = "ho.bone_collision_select_spring_roots"
    bl_label = "选择全部Root"
    bl_description = "选择当前骨架中所有标记为Spring Root的骨骼"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature_obj = _active_armature_object(context)
        return armature_obj is not None and armature_obj.mode in {"EDIT", "POSE"}

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        root_names = {bone.name for bone in _spring_root_bones(armature_obj)}
        if not root_names:
            self.report({"WARNING"}, "当前骨架没有Spring Root")
            return {"CANCELLED"}

        if armature_obj.mode == "EDIT":
            for bone in armature_obj.data.edit_bones:
                bone.select = bone.name in root_names
        else:
            for bone in armature_obj.data.bones:
                bone.select = bone.name in root_names
            active_name = next(iter(root_names))
            armature_obj.data.bones.active = armature_obj.data.bones.get(active_name)

        self.report({"INFO"}, f"已选择 {len(root_names)} 个Spring Root")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_SetPrimaryGroup(Operator):
    bl_idname = "ho.bone_collision_set_primary_group"
    bl_label = "设置主碰撞组"
    bl_description = "设置当前活动骨碰撞体所属的主碰撞组"
    bl_options = {"REGISTER", "UNDO"}

    group: IntProperty(
        name="组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    apply_selected: BoolProperty(
        name="应用到选中骨",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_collision_props(context) is not None

    def invoke(self, context, event):
        self.apply_selected = bool(event.alt)
        return self.execute(context)

    def execute(self, context):
        targets = _collision_group_target_props(context, self.apply_selected)
        if not targets:
            return {"CANCELLED"}

        group = min(max(int(self.group), 1), _COLLISION_GROUP_COUNT)
        for props in targets:
            props.primary_collision_group = group

        _tag_view3d_redraw()
        if self.apply_selected:
            self.report({"INFO"}, f"已设置 {len(targets)} 根选中骨的主碰撞组")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_ToggleCollidedByGroup(Operator):
    bl_idname = "ho.bone_collision_toggle_collided_by_group"
    bl_label = "切换被碰撞组"
    bl_description = "切换允许哪些主碰撞组碰撞到当前活动骨碰撞体"
    bl_options = {"REGISTER", "UNDO"}

    group: IntProperty(
        name="组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    apply_selected: BoolProperty(
        name="应用到选中骨",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_collision_props(context) is not None

    def invoke(self, context, event):
        self.apply_selected = bool(event.shift or event.ctrl or event.alt)
        return self.execute(context)

    def execute(self, context):
        targets = _collision_group_target_props(context, self.apply_selected)
        if not targets:
            return {"CANCELLED"}

        group = min(max(int(self.group), 1), _COLLISION_GROUP_COUNT)
        active_props = _active_collision_props(context)
        if active_props is not None:
            enable = not _collision_group_bit(active_props.collided_by_groups, group)
        else:
            enable = not all(_collision_group_bit(props.collided_by_groups, group) for props in targets)

        for props in targets:
            props.collided_by_groups = _set_collision_group_bit(
                props.collided_by_groups,
                group,
                enable,
            )

        _tag_view3d_redraw()
        if self.apply_selected:
            self.report({"INFO"}, f"已更新 {len(targets)} 根选中骨的被碰撞组")
        return {"FINISHED"}


class OP_Hotools_ObjectCollision_SetPrimaryGroup(Operator):
    bl_idname = "ho.object_collision_set_primary_group"
    bl_label = "设置Object主碰撞组"
    bl_description = "设置当前Object被动碰撞体所属的主碰撞组"
    bl_options = {"REGISTER", "UNDO"}

    group: IntProperty(
        name="组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    apply_selected: BoolProperty(
        name="应用到选中Object",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_object_collision_props(context) is not None

    def invoke(self, context, event):
        self.apply_selected = bool(event.alt)
        return self.execute(context)

    def execute(self, context):
        targets = _object_collision_group_target_props(context, self.apply_selected)
        if not targets:
            return {"CANCELLED"}

        group = min(max(int(self.group), 1), _COLLISION_GROUP_COUNT)
        for props in targets:
            props.primary_collision_group = group

        _tag_view3d_redraw()
        if self.apply_selected:
            self.report({"INFO"}, f"已设置 {len(targets)} 个选中Object的主碰撞组")
        return {"FINISHED"}


class OP_Hotools_MeshCollision_SetPrimaryGroup(Operator):
    bl_idname = "ho.mesh_collision_set_primary_group"
    bl_label = "设置网格主碰撞组"
    bl_description = "设置当前Mesh逐顶点碰撞球所属的主碰撞组"
    bl_options = {"REGISTER", "UNDO"}

    group: IntProperty(
        name="组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_mesh_collision_props(context) is not None

    def execute(self, context):
        props = _active_mesh_collision_props(context)
        if props is None:
            return {"CANCELLED"}

        props.primary_collision_group = min(max(int(self.group), 1), _COLLISION_GROUP_COUNT)
        _tag_view3d_redraw()
        return {"FINISHED"}


class OP_Hotools_MeshCollision_ToggleCollidedByGroup(Operator):
    bl_idname = "ho.mesh_collision_toggle_collided_by_group"
    bl_label = "切换网格被碰撞组"
    bl_description = "切换允许哪些主碰撞组碰撞到当前Mesh逐顶点碰撞球"
    bl_options = {"REGISTER", "UNDO"}

    group: IntProperty(
        name="组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_mesh_collision_props(context) is not None

    def execute(self, context):
        props = _active_mesh_collision_props(context)
        if props is None:
            return {"CANCELLED"}

        group = min(max(int(self.group), 1), _COLLISION_GROUP_COUNT)
        enable = not _collision_group_bit(props.collided_by_groups, group)
        props.collided_by_groups = _set_collision_group_bit(
            props.collided_by_groups,
            group,
            enable,
        )
        _tag_view3d_redraw()
        return {"FINISHED"}


class OP_Hotools_BoneCollision_AddSelectedColliders(Operator):
    bl_idname = "ho.bone_collision_add_selected_colliders"
    bl_label = "选中骨添加碰撞"
    bl_description = "给当前选中的所有骨骼批量添加碰撞体"
    bl_options = {"REGISTER", "UNDO"}

    collision_type: EnumProperty(
        name="类型",
        description="要写入选中骨骼的碰撞体类型",
        items=[
            ("SPHERE", "球体", "批量添加球形碰撞体"),
            ("CAPSULE", "胶囊", "批量添加胶囊碰撞体"),
        ],
        default="SPHERE",
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="碰撞体半径，使用Blender单位",
        default=0.2,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    height: FloatProperty(
        name="高度",
        description="胶囊中段长度；球体也会写入，方便之后切换到胶囊体",
        default=1.0,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    offset_delta: FloatVectorProperty(
        name="相对偏移增量",
        description="在每根骨骼head/tail中点基础上追加的局部XYZ偏移",
        size=3,
        subtype="XYZ",
        default=(0.0, 0.0, 0.0),
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        armature_obj = _active_armature_object(context)
        return armature_obj is not None and armature_obj.mode in {"EDIT", "POSE"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "collision_type")
        layout.prop(self, "radius")
        layout.prop(self, "height")
        layout.prop(self, "offset_delta")

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        selected_names = _selected_bone_names(context, armature_obj)
        target_bones = []
        seen_names = set()
        for name in selected_names:
            if name in seen_names:
                continue
            bone = armature_obj.data.bones.get(name)
            props = _collision_props(bone) if bone else None
            if props is None:
                continue
            target_bones.append(bone)
            seen_names.add(name)

        if not target_bones:
            self.report({"WARNING"}, "没有选中可处理的骨骼")
            return {"CANCELLED"}

        delta = mathutils.Vector(self.offset_delta)
        for bone in target_bones:
            props = _collision_props(bone)
            if props is None:
                continue

            midpoint_offset = mathutils.Vector((0.0, bone.length * 0.5, 0.0))
            props.collision_type = self.collision_type
            props.radius = self.radius
            props.length = self.height
            props.offset = midpoint_offset + delta

        _tag_view3d_redraw()
        self.report({"INFO"}, f"已给 {len(target_bones)} 根选中骨添加碰撞体")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_GradientRadius(Operator):
    bl_idname = "ho.bone_collision_gradient_radius"
    bl_label = "碰撞半径渐变"
    bl_description = "按骨骼层级顺序批量递增或递减已有碰撞体半径"
    bl_options = {"REGISTER", "UNDO"}

    target_scope: EnumProperty(
        name="范围",
        description="选择只处理当前选中骨的碰撞体，或处理当前骨架的全部碰撞体",
        items=[
            ("SELECTED", "选中碰撞体", "只处理当前选中骨骼中已有碰撞体"),
            ("ALL", "全部碰撞体", "处理当前骨架中所有已有碰撞体"),
        ],
        default="SELECTED",
    )  # type: ignore
    direction: EnumProperty(
        name="方向",
        description="半径沿骨骼顺序递减或递增",
        items=[
            ("DECREASE", "递减", "从头倍率过渡到尾倍率"),
            ("INCREASE", "递增", "从尾倍率过渡到头倍率"),
        ],
        default="DECREASE",
    )  # type: ignore
    head_factor: FloatProperty(
        name="头倍率",
        description="链头半径倍率；按每根骨当前半径乘以该渐变倍率",
        default=1.0,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    tail_factor: FloatProperty(
        name="尾倍率",
        description="链尾半径倍率；默认让尾部变为当前半径的0.2倍",
        default=0.2,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    exponent: FloatProperty(
        name="指数",
        description="控制半径渐变曲线；1为线性，大于1前段更慢，小于1前段更快",
        default=2.0,
        min=0.001,
        soft_min=0.1,
        soft_max=8.0,
    )  # type: ignore
    factor_offset: FloatProperty(
        name="曲线偏移",
        description="先偏移归一化顺序再计算指数，负值延后变化，正值提前变化",
        default=0.0,
        min=-1.0,
        max=1.0,
        soft_min=-0.5,
        soft_max=0.5,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_armature_object(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target_scope")
        layout.prop(self, "direction")

        row = layout.row(align=True)
        row.prop(self, "head_factor")
        row.prop(self, "tail_factor")

        layout.prop(self, "exponent")
        layout.prop(self, "factor_offset")

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        selected_names = set(_selected_bone_names(context, armature_obj))
        scope_bones = []
        target_items = []

        if self.target_scope == "SELECTED" and not selected_names:
            self.report({"WARNING"}, "没有选中骨骼")
            return {"CANCELLED"}

        for bone in armature_obj.data.bones:
            if self.target_scope == "ALL" or bone.name in selected_names:
                scope_bones.append(bone)

        topology_data = _bone_topology_data(scope_bones)
        max_depth_by_root = {}

        for bone in scope_bones:
            props = _collision_props(bone)
            if props is None or props.collision_type == "NONE":
                continue

            data = topology_data.get(bone.name)
            if data is None:
                continue

            target_items.append((bone, props, data))
            root_index = data["root_index"]
            max_depth_by_root[root_index] = max(
                max_depth_by_root.get(root_index, 0),
                data["depth"],
            )

        if not target_items:
            if self.target_scope == "SELECTED":
                self.report({"WARNING"}, "选中骨骼中没有已有碰撞体")
            else:
                self.report({"WARNING"}, "当前骨架没有已有碰撞体")
            return {"CANCELLED"}

        first_factor = self.head_factor if self.direction == "DECREASE" else self.tail_factor
        last_factor = self.tail_factor if self.direction == "DECREASE" else self.head_factor

        for bone, props, data in target_items:
            denominator = max(max_depth_by_root.get(data["root_index"], 0), 1)
            factor = _exponent_factor(data["depth"] / denominator, self.exponent, self.factor_offset)
            radius_factor = first_factor + (last_factor - first_factor) * factor
            props.radius = max(props.radius * radius_factor, 0.0)

        _tag_view3d_redraw()
        self.report({"INFO"}, f"已调整 {len(target_items)} 个碰撞体半径")
        return {"FINISHED"}
