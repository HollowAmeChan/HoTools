import bpy


# 预览绘制常量，由叠加层代码共享。
_ROOT_COLOR = (0.45, 1.0, 0.25, 0.85)
_SHAPE_SEGMENTS = 32
_COLLISION_GROUP_COUNT = 16
_ALL_COLLISION_GROUPS_MASK = (1 << _COLLISION_GROUP_COUNT) - 1
_COLLISION_GROUP_COLORS = (
    (0.10, 0.63, 1.00, 0.86),
    (1.00, 0.45, 0.25, 0.86),
    (0.35, 0.90, 0.35, 0.86),
    (1.00, 0.82, 0.18, 0.86),
    (0.78, 0.48, 1.00, 0.86),
    (0.12, 0.92, 0.82, 0.86),
    (1.00, 0.35, 0.62, 0.86),
    (0.62, 0.88, 0.18, 0.86),
    (0.30, 0.48, 1.00, 0.86),
    (1.00, 0.60, 0.12, 0.86),
    (0.20, 0.78, 0.55, 0.86),
    (0.92, 0.38, 1.00, 0.86),
    (0.88, 0.75, 0.55, 0.86),
    (0.52, 0.72, 0.95, 0.86),
    (0.95, 0.52, 0.52, 0.86),
    (0.78, 0.78, 0.78, 0.86),
)


def _tag_view3d_redraw():
    """
    标记所有可见的 3D 视图重绘。
    """
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _overlay_show_update(self, context):
    """
    叠加层开关变化时刷新 3D 视图。
    """
    _tag_view3d_redraw()


def _active_armature_object(context):
    """
    获取当前正在编辑碰撞属性的骨架对象。
    """
    obj = context.object or context.active_object
    if obj is None or obj.type != "ARMATURE":
        return None
    return obj


def _collision_props(bone):
    """
    读取骨骼上的 HoTools 碰撞属性。
    """
    return getattr(bone, "hotools_collision", None)


def _object_collision_props(obj):
    """
    读取物体上的 HoTools 被动碰撞属性。
    """
    return getattr(obj, "hotools_object_collision", None)


def _mesh_collision_props(obj):
    """
    读取网格上的 HoTools 逐顶点碰撞属性。
    """
    return getattr(obj, "hotools_mesh_collision", None)


def _active_collision_props(context):
    """
    获取当前激活骨骼的碰撞属性。
    """
    bone = context.active_bone
    if bone is None:
        return None
    return _collision_props(bone)


def _active_object_collision_props(context):
    """
    获取当前激活物体的被动碰撞属性。
    """
    obj = context.object or context.active_object
    if obj is None:
        return None
    return _object_collision_props(obj)


def _active_mesh_collision_props(context):
    """
    获取当前激活网格的逐顶点碰撞属性。
    """
    obj = context.object or context.active_object
    if obj is None or obj.type != "MESH":
        return None
    return _mesh_collision_props(obj)


def _set_collision_group_bit(mask, group, value):
    """
    设置或清除碰撞组位掩码中的指定分组。
    """
    bit = 1 << (group - 1)
    if value:
        return mask | bit
    return mask & ~bit


def _collision_group_bit(mask, group):
    """
    判断碰撞组位掩码中是否包含指定分组。
    """
    return bool(mask & (1 << (group - 1)))


def _collision_group_color(group):
    """
    根据碰撞组编号获取预览绘制颜色。
    """
    index = min(max(int(group), 1), _COLLISION_GROUP_COUNT) - 1
    return _COLLISION_GROUP_COLORS[index]


def _collision_group_target_props(context, apply_selected):
    """
    收集骨骼碰撞组操作需要修改的目标属性。
    """
    armature_obj = _active_armature_object(context)
    if armature_obj is None:
        return []

    if not apply_selected:
        props = _active_collision_props(context)
        return [props] if props is not None else []

    targets = []
    seen_names = set()
    for name in _selected_bone_names(context, armature_obj):
        if name in seen_names:
            continue
        bone = armature_obj.data.bones.get(name)
        props = _collision_props(bone) if bone else None
        if props is not None:
            targets.append(props)
            seen_names.add(name)

    if not targets:
        props = _active_collision_props(context)
        if props is not None:
            targets.append(props)
    return targets


def _object_collision_group_target_props(context, apply_selected):
    """
    收集物体碰撞组操作需要修改的目标属性。
    """
    if not apply_selected:
        props = _active_object_collision_props(context)
        return [props] if props is not None else []

    targets = []
    seen_names = set()
    for obj in getattr(context, "selected_objects", None) or []:
        if obj.name in seen_names:
            continue
        props = _object_collision_props(obj)
        if props is not None:
            targets.append(props)
            seen_names.add(obj.name)

    if not targets:
        props = _active_object_collision_props(context)
        if props is not None:
            targets.append(props)
    return targets


def _append_unique_bone_name(names, seen_names, bone):
    """
    将骨骼名称加入列表，并避免重复记录。
    """
    if bone is None or bone.name in seen_names:
        return
    names.append(bone.name)
    seen_names.add(bone.name)


def _selected_bone_names(context, armature_obj) -> list[str]:
    """
    统一读取编辑、姿态、物体模式下的骨骼选择结果。
    """
    mode = getattr(context, "mode", "")
    object_mode = getattr(armature_obj, "mode", "")
    names = []
    seen_names = set()

    if mode == "EDIT_ARMATURE" or object_mode == "EDIT":
        selected_editable_bones = getattr(context, "selected_editable_bones", None) or []
        for bone in selected_editable_bones:
            _append_unique_bone_name(names, seen_names, bone)

        selected_bones = getattr(context, "selected_bones", None) or []
        for bone in selected_bones:
            _append_unique_bone_name(names, seen_names, bone)

        for bone in armature_obj.data.edit_bones:
            if (
                getattr(bone, "select", False)
                or getattr(bone, "select_head", False)
                or getattr(bone, "select_tail", False)
            ):
                _append_unique_bone_name(names, seen_names, bone)
        return names

    if mode == "POSE" or object_mode == "POSE":
        selected_pose_bones = getattr(context, "selected_pose_bones", None) or []
        for pose_bone in selected_pose_bones:
            _append_unique_bone_name(names, seen_names, pose_bone)

        selected_bones = getattr(context, "selected_bones", None) or []
        for bone in selected_bones:
            _append_unique_bone_name(names, seen_names, bone)

        if armature_obj.pose is not None:
            for pose_bone in armature_obj.pose.bones:
                if pose_bone.bone.select:
                    _append_unique_bone_name(names, seen_names, pose_bone)

        for bone in armature_obj.data.bones:
            if bone.select:
                _append_unique_bone_name(names, seen_names, bone)
        return names

    selected_bones = getattr(context, "selected_bones", None) or []
    for bone in selected_bones:
        _append_unique_bone_name(names, seen_names, bone)

    for bone in armature_obj.data.bones:
        if getattr(bone, "select", False):
            _append_unique_bone_name(names, seen_names, bone)
    return names


def _spring_root_bones(armature_obj):
    """
    获取骨架中启用弹簧根节点标记的碰撞骨骼。
    """
    return [
        bone
        for bone in armature_obj.data.bones
        if _collision_props(bone) is not None and bone.hotools_collision.spring_root
    ]


def _bone_topology_data(bones):
    """
    构建批量半径渐变需要的骨骼层级拓扑数据。
    """
    scope_names = {bone.name for bone in bones}
    roots = [bone for bone in bones if bone.parent is None or bone.parent.name not in scope_names]
    topology_data = {}

    def scan_topology(bone, root_index, current_chains, depth):
        """
        递归扫描骨骼层级并记录链路信息。
        """
        topology_data[bone.name] = {
            "bone": bone,
            "root_index": root_index,
            "chains": tuple(current_chains),
            "depth": depth,
        }

        children = [child for child in bone.children if child.name in scope_names]
        for index, child in enumerate(children):
            next_chains = list(current_chains)
            if len(children) > 1:
                next_chains.append(index)
            scan_topology(child, root_index, next_chains, depth + 1)

    for root_index, root in enumerate(roots):
        scan_topology(root, root_index, [root_index], 0)

    return topology_data


def _clamp01(value):
    """
    将数值限制在 0 到 1 的范围内。
    """
    return min(max(float(value), 0.0), 1.0)


def _exponent_factor(value, exponent, offset):
    """
    计算带偏移和指数控制的渐变因子。
    """
    t = _clamp01(float(value) + float(offset))
    return t ** max(float(exponent), 0.001)
