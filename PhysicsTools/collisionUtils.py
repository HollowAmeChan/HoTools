import bpy

_ROOT_COLOR = (0.45, 1.0, 0.25, 0.85)
_SHAPE_SEGMENTS = 32
_COLLISION_GROUP_COUNT = 16
_COLLISION_GROUP_ROW_SIZE = 8
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
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _overlay_show_update(self, context):
    _tag_view3d_redraw()


def _active_armature_object(context):
    obj = context.object or context.active_object
    if obj is None or obj.type != "ARMATURE":
        return None
    return obj


def _collision_props(bone):
    return getattr(bone, "hotools_collision", None)


def _object_collision_props(obj):
    return getattr(obj, "hotools_object_collision", None)


def _active_collision_props(context):
    bone = context.active_bone
    if bone is None:
        return None
    return _collision_props(bone)


def _active_object_collision_props(context):
    obj = context.object or context.active_object
    if obj is None:
        return None
    return _object_collision_props(obj)


def _set_collision_group_bit(mask, group, value):
    bit = 1 << (group - 1)
    if value:
        return mask | bit
    return mask & ~bit


def _collision_group_bit(mask, group):
    return bool(mask & (1 << (group - 1)))


def _collision_group_color(group):
    index = min(max(int(group), 1), _COLLISION_GROUP_COUNT) - 1
    return _COLLISION_GROUP_COLORS[index]


def _collision_group_target_props(context, apply_selected):
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


def _draw_group_buttons(layout, operator_id, *, active_group=None, mask=None):
    for row_index in range(2):
        row = layout.row(align=True)
        row.operator_context = "INVOKE_DEFAULT"
        for group in range(
            row_index * _COLLISION_GROUP_ROW_SIZE + 1,
            (row_index + 1) * _COLLISION_GROUP_ROW_SIZE + 1,
        ):
            if active_group is not None:
                depress = group == active_group
            else:
                icon = "CHECKBOX_HLT" if _collision_group_bit(mask or 0, group) else "CHECKBOX_DEHLT"
                depress = _collision_group_bit(mask or 0, group)

            op = row.operator(
                operator_id,
                text=str(group),
                depress=depress,
            )
            op.group = group


def _append_unique_bone_name(names, seen_names, bone):
    if bone is None or bone.name in seen_names:
        return
    names.append(bone.name)
    seen_names.add(bone.name)


def _selected_bone_names(context, armature_obj) -> list[str]:
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
    return [
        bone
        for bone in armature_obj.data.bones
        if _collision_props(bone) is not None and bone.hotools_collision.spring_root
    ]


def _bone_topology_data(bones):
    scope_names = {bone.name for bone in bones}
    roots = [bone for bone in bones if bone.parent is None or bone.parent.name not in scope_names]
    topology_data = {}

    def scan_topology(bone, root_index, current_chains, depth):
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
    return min(max(float(value), 0.0), 1.0)


def _exponent_factor(value, exponent, offset):
    t = _clamp01(float(value) + float(offset))
    return t ** max(float(exponent), 0.001)
