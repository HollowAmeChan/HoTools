from typing import Set
import bpy
import os
import sys
from bpy.props import BoolProperty, StringProperty, EnumProperty
from bpy.types import Context, Operator, PropertyGroup, UIList, UILayout
from . import OmniNodeSocket
from . import OmniNodeDraw
from . import OmniRuntimeState
from ...PropertyCurve import color_curve_payload, float_curve_payload
from .OmniNodeSocketMapping import runtime_socket_type_id
import uuid

# 用于获取动态的全socket枚举
BLENDER_SOCKET_TYPES = {
    "NodeSocketFloat": "Float",
    "NodeSocketInt": "Int",
    "NodeSocketBool": "Bool",
    "NodeSocketString": "String",
    "NodeSocketStringFilePath": "File Path",

    "NodeSocketVector": "Vector",
    "NodeSocketColor": "Color",
    "NodeSocketRotation": "Rotation",

    "NodeSocketGeometry": "Geometry",

    "NodeSocketObject": "Object",
    "NodeSocketImage": "Image",
    "NodeSocketCollection": "Collection",

    "NodeSocketMaterial": "Material",
    "NodeSocketTexture": "Texture",

    "NodeSocketShader": "Shader",

    # "NodeSocketMatrix": "Matrix", #4.1不存在，高版本存在，等5.xLTS
    # "NodeSocketMenu": "Menu",
}

_OMNI_TREE_NAV_STACKS = {}


def _resolve_space_tree(space):
    return getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)


def _is_omni_tree(tree):
    return tree is not None and getattr(tree, "bl_idname", None) == "OmniNodeTree"


def _active_omni_tree(context):
    space = getattr(context, "space_data", None)
    tree = _resolve_space_tree(space)
    return tree if _is_omni_tree(tree) else None


def _operator_omni_tree(context, tree_name=""):
    tree_name = str(tree_name or "")
    return _find_omni_tree(tree_name) if tree_name else _active_omni_tree(context)


def _tree_execution_enabled(tree):
    return bool(getattr(tree, "is_execution_enabled", True))


def _find_omni_tree(tree_name):
    tree = bpy.data.node_groups.get(tree_name)
    if _is_omni_tree(tree):
        return tree

    for candidate in bpy.data.node_groups:
        if getattr(candidate, "name_full", None) == tree_name and _is_omni_tree(candidate):
            return candidate
    return None


def _tree_runtime_module(tree):
    return sys.modules.get(type(tree).__module__)


def _tree_has_compile_cache(tree):
    module = _tree_runtime_module(tree)
    cached_graph = getattr(module, "_cached_compiled_graph", None)
    if not callable(cached_graph):
        return False
    return cached_graph(tree) is not None


def _tree_frame_handler_registered(tree):
    module = _tree_runtime_module(tree)
    frame_handler = getattr(module, "_omni_frame_change_post", None)
    return frame_handler is not None and frame_handler in bpy.app.handlers.frame_change_post


def _should_alert_compile_button(tree):
    return (
        bool(getattr(tree, "is_frame_run_enabled", False))
        and _tree_frame_handler_registered(tree)
        and not _tree_has_compile_cache(tree)
    )


def _nav_space_key(context):
    space = getattr(context, "space_data", None)
    area = getattr(context, "area", None)
    if space is None or getattr(space, "type", None) != 'NODE_EDITOR':
        return None

    area_ptr = area.as_pointer() if area is not None else 0
    try:
        space_ptr = space.as_pointer()
    except Exception:
        space_ptr = id(space)
    return f"{area_ptr}:{space_ptr}"


def _resolve_tree_entry(entry):
    if not entry:
        return None

    tree = entry.get("tree")
    try:
        if _is_omni_tree(tree):
            return tree
    except Exception:
        pass

    tree_name = entry.get("tree_name")
    if not tree_name:
        return None

    tree = bpy.data.node_groups.get(tree_name)
    if _is_omni_tree(tree):
        return tree

    for candidate in bpy.data.node_groups:
        if getattr(candidate, "name_full", None) == tree_name and _is_omni_tree(candidate):
            return candidate
    return None


def _get_nav_stack(context, create=False):
    key = _nav_space_key(context)
    if key is None:
        return []

    stack = _OMNI_TREE_NAV_STACKS.setdefault(key, []) if create else _OMNI_TREE_NAV_STACKS.get(key, [])
    cleaned_stack = []
    for entry in stack:
        tree = _resolve_tree_entry(entry)
        if tree is None:
            continue
        cleaned_stack.append({
            "tree": tree,
            "tree_name": getattr(tree, "name_full", tree.name),
        })

    if cleaned_stack or create:
        _OMNI_TREE_NAV_STACKS[key] = cleaned_stack
    else:
        _OMNI_TREE_NAV_STACKS.pop(key, None)

    return cleaned_stack


def _push_nav_tree(context, tree):
    if not _is_omni_tree(tree):
        return

    stack = _get_nav_stack(context, create=True)
    entry_name = getattr(tree, "name_full", tree.name)
    if stack and stack[-1].get("tree_name") == entry_name:
        return

    stack.append({
        "tree": tree,
        "tree_name": entry_name,
    })
    key = _nav_space_key(context)
    if key is not None:
        _OMNI_TREE_NAV_STACKS[key] = stack


def _pop_nav_tree(context):
    key = _nav_space_key(context)
    if key is None:
        return None

    stack = _get_nav_stack(context)
    while stack:
        entry = stack.pop()
        tree = _resolve_tree_entry(entry)
        if tree is not None:
            if stack:
                _OMNI_TREE_NAV_STACKS[key] = stack
            else:
                _OMNI_TREE_NAV_STACKS.pop(key, None)
            return tree

    _OMNI_TREE_NAV_STACKS.pop(key, None)
    return None


def omni_nav_can_go_back(context):
    return len(_get_nav_stack(context)) > 0


def omni_nav_parent_name(context):
    stack = _get_nav_stack(context)
    if not stack:
        return ""

    tree = _resolve_tree_entry(stack[-1])
    return tree.name if tree is not None else ""


def omni_nav_depth(context):
    return len(_get_nav_stack(context))


def omni_nav_stack_label(context):
    stack = _get_nav_stack(context)
    if not stack:
        return ""

    names = []
    for entry in stack:
        tree = _resolve_tree_entry(entry)
        if tree is not None:
            names.append(tree.name)

    if not names:
        return ""

    return " > ".join(names)


def _activate_tree_in_space(space, tree):
    if space is None or getattr(space, "type", None) != 'NODE_EDITOR' or not _is_omni_tree(tree):
        return False

    try:
        space.node_tree = tree
    except Exception:
        return False

    return _resolve_space_tree(space) == tree or getattr(space, "node_tree", None) == tree


def _space_has_tree(space, tree):
    return _resolve_space_tree(space) == tree or getattr(space, "node_tree", None) == tree


def _set_node_editor_type(area, space):
    for owner, attr_name in ((area, "ui_type"), (space, "tree_type")):
        if owner is None or not hasattr(owner, attr_name):
            continue
        try:
            if getattr(owner, attr_name) != "OmniNodeTree":
                setattr(owner, attr_name, "OmniNodeTree")
        except Exception:
            pass


def _activate_tree_in_editor(area, space, tree):
    if space is None or getattr(space, "type", None) != 'NODE_EDITOR' or not _is_omni_tree(tree):
        return False

    _set_node_editor_type(area, space)

    attempts = [lambda: setattr(space, "node_tree", tree)]
    path = getattr(space, "path", None)
    if path is not None:
        attempts.extend((
            lambda: path.start(tree),
            lambda: path.clear(),
            lambda: setattr(space, "node_tree", tree),
        ))

    for attempt in attempts:
        try:
            attempt()
        except Exception:
            pass
        if _space_has_tree(space, tree):
            if area is not None:
                area.tag_redraw()
            return True

    if _activate_tree_in_space(space, tree):
        if area is not None:
            area.tag_redraw()
        return True
    return False


def _iter_node_editor_spaces(context):
    space = getattr(context, "space_data", None)
    area = getattr(context, "area", None)
    if space is not None and getattr(space, "type", None) == 'NODE_EDITOR':
        yield area, space

    screen = getattr(getattr(context, "window", None), "screen", None)
    if screen is None:
        return

    for area in screen.areas:
        if getattr(area, "type", None) != 'NODE_EDITOR':
            continue
        space = getattr(area.spaces, "active", None)
        if space is not None:
            yield area, space


def _activate_tree_in_current_window(context, tree):
    seen = set()
    spaces = []
    for area, space in _iter_node_editor_spaces(context):
        try:
            key = int(space.as_pointer())
        except Exception:
            key = id(space)
        if key in seen:
            continue
        seen.add(key)
        spaces.append((area, space))

    omni_spaces = [
        (area, space)
        for area, space in spaces
        if _is_omni_tree(_resolve_space_tree(space))
    ]

    for area, space in omni_spaces + spaces:
        if _activate_tree_in_editor(area, space, tree):
            return True
    return False


def full_socket_type_items():
    items = []
    for idname, label in BLENDER_SOCKET_TYPES.items():
        items.append((idname, label, runtime_socket_type_id(idname)))
    for k in OmniNodeSocket.cls:
        items.append((k.bl_idname, k.bl_label, ""))
    return items


def _normalize_omni_preset(preset, index):
    name = f"Preset {index + 1}"
    description = ""
    values = None

    if isinstance(preset, dict):
        name = str(preset.get("name") or preset.get("label") or name)
        description = str(preset.get("description") or "")
        values = preset.get("values")
        if values is None:
            values = preset.get("inputs")
        if values is None:
            meta_keys = {"name", "label", "description", "values", "inputs"}
            values = {key: value for key, value in preset.items() if key not in meta_keys}
    elif isinstance(preset, (list, tuple)) and len(preset) >= 2:
        name = str(preset[0] or name)
        values = preset[1]
        if len(preset) >= 3:
            description = str(preset[2] or "")

    if not isinstance(values, dict) or not values:
        return None

    return {
        "name": name,
        "description": description,
        "values": dict(values),
    }


def _node_omni_presets(node):
    raw_presets = getattr(node, "_omni_presets", []) or []
    if isinstance(raw_presets, dict):
        raw_presets = [
            {"name": name, "values": values}
            for name, values in raw_presets.items()
        ]

    presets = []
    for index, preset in enumerate(raw_presets):
        normalized = _normalize_omni_preset(preset, index)
        if normalized is not None:
            presets.append(normalized)
    return presets


def node_omni_preset_items(node):
    items = [("NONE", "清空", "将全部输入 Socket 重置为默认值")]
    for index, preset in enumerate(_node_omni_presets(node)):
        description = str(preset.get("description") or "")
        items.append((str(index), preset["name"], description))
    return items


def sync_tree_io(tree):
    # 会同步tree内的所有特殊graph节点
    for node in tree.nodes:
        if node.bl_idname == "HO_OmniNode_GroupNode_Inputs":
            node.syncGroupIO()
        elif node.bl_idname == "HO_OmniNode_GroupNode_Outputs":
            node.syncGroupIO()
        elif node.bl_idname == "HO_OmniNode_GroupNode":
            node.syncGroupIO()
        elif node.bl_idname == "HO_OmniNode_BatchGroupNode":
            node.syncGroupIO()


def sync_all_related_tree_io(tree):
    """同步当前tree，以及所有引用这个tree的组节点。"""
    if not tree:
        return
    if getattr(tree, "bl_idname", None) != "OmniNodeTree":
        return

    sync_tree_io(tree)

    for other_tree in bpy.data.node_groups:
        if other_tree == tree:
            continue
        if getattr(other_tree, "bl_idname", None) != "OmniNodeTree":
            continue

        for node in other_tree.nodes:
            if node.bl_idname not in {"HO_OmniNode_GroupNode", "HO_OmniNode_BatchGroupNode"}:
                continue
            target_tree = getattr(node, "target_tree", None)
            if target_tree != tree:
                continue

            node.syncGroupIO()


def OmniGraphNodeIOItem_update(self, context):
    """在所有需要同步group io的地方统一使用这个函数。"""
    tree = self.id_data
    sync_all_related_tree_io(tree)


class OmniGraphNodeIOItem(PropertyGroup):
    """IO输入输出组的ui绘制使用的列表单行"""
    name: StringProperty(name="IO", default="IO", update=OmniGraphNodeIOItem_update)  # type: ignore
    uid: StringProperty(name="UID", default="", options={'HIDDEN'})  # type: ignore
    socket_type: EnumProperty(  # type: ignore
        name="Socket Type",
        default=OmniNodeSocket.OmniNodeSocketAny.bl_idname,
        items=full_socket_type_items(),
        update=OmniGraphNodeIOItem_update,
    )
    # TODO: default_value无法同步需要设计
    # 目前直接不允许用户改默认值，强制要求用户给每个输入口子连节点


class HO_UL_GraphNodeIO(UIList):
    """IO输入输出组的ui绘制使用的列表"""

    def draw_item(self, context, layout: UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False)
        row.label(text="UID:" + item.uid)
        row.prop(item, "socket_type", text="")


class OP_IOItemAdd(Operator):
    bl_idname = "ho.omni_ioitemadd"
    bl_label = "Add IO"

    is_input: BoolProperty()  # type: ignore

    def generate_unique_uid(self, tree):
        existing = set()

        for item in tree.group_inputs:
            if item.uid:
                existing.add(item.uid)

        for item in tree.group_outputs:
            if item.uid:
                existing.add(item.uid)

        while True:
            uid = uuid.uuid4().hex
            if uid not in existing:
                return uid

    def execute(self, context):
        tree = context.space_data.node_tree

        if self.is_input:
            item = tree.group_inputs.add()
            item.uid = self.generate_unique_uid(tree)
            tree.group_inputs_index = len(tree.group_inputs) - 1
            item.name = "Input"
        else:
            item = tree.group_outputs.add()
            item.uid = self.generate_unique_uid(tree)
            tree.group_outputs_index = len(tree.group_outputs) - 1
            item.name = "Output"


        sync_all_related_tree_io(tree)
        return {'FINISHED'}


class OP_IOItemRemove(Operator):
    bl_idname = "ho.omni_ioitemremove"
    bl_label = "Remove IO"

    is_input: BoolProperty()  # type: ignore

    def execute(self, context):
        tree = context.space_data.node_tree

        if self.is_input:
            idx = tree.group_inputs_index
            if idx < 0 or idx >= len(tree.group_inputs):
                return {'CANCELLED'}
            tree.group_inputs.remove(idx)
            tree.group_inputs_index = max(0, idx - 1)
        else:
            idx = tree.group_outputs_index
            if idx < 0 or idx >= len(tree.group_outputs):
                return {'CANCELLED'}
            tree.group_outputs.remove(idx)
            tree.group_outputs_index = max(0, idx - 1)

        sync_all_related_tree_io(tree)
        return {'FINISHED'}

class OP_IOItemMove(Operator):
    bl_idname = "ho.omni_ioitemmove"
    bl_label = "Move IO Up/Down"

    is_input: BoolProperty()  # type: ignore
    is_Down: BoolProperty() # type: ignore

    def execute(self, context):
        tree = context.space_data.node_tree

        direction = 1 if self.is_Down else -1

        if self.is_input:
            idx = tree.group_inputs_index
            if idx < 0 or idx >= len(tree.group_inputs):
                return {'CANCELLED'}
            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(tree.group_inputs):
                return {'CANCELLED'}
            tree.group_inputs.move(idx, new_idx)
            tree.group_inputs_index = new_idx
        else:
            idx = tree.group_outputs_index
            if idx < 0 or idx >= len(tree.group_outputs):
                return {'CANCELLED'}
            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(tree.group_outputs):
                return {'CANCELLED'}
            tree.group_outputs.move(idx, new_idx)
            tree.group_outputs_index = new_idx

        sync_all_related_tree_io(tree)
        return {'FINISHED'}


class OP_JumpToNodeTree(Operator):
    bl_idname = "ho.omni_jump_to_node_tree"
    bl_label = "跳转到节点树"
    bl_description = "在当前 Node Editor 区域打开该节点引用的 OmniNodeTree"

    node_name: StringProperty(default="")  # type: ignore
    tree_attr: StringProperty(default="target_tree")  # type: ignore

    @staticmethod
    def _enter_tree_with_path(space, node, target_tree) -> bool:
        path = getattr(space, "path", None)
        if path is None:
            return False

        append_attempts = [
            # Omni 的 Group 是自定义 GraphNode，不一定能被 Blender 当作原生
            # NodeGroup 节点校验通过；先尝试只追加 tree，可以保留路径栈并支持继续下钻。
            lambda: path.append(target_tree),
            lambda: path.append(target_tree, node=node),
            lambda: path.append(target_tree, node),
            lambda: path.append(node_tree=target_tree, node=node),
        ]

        for attempt in append_attempts:
            try:
                attempt()
                if getattr(space, "edit_tree", None) == target_tree:
                    return True
            except Exception:
                pass

        return False

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return bool(
            space
            and space.type == 'NODE_EDITOR'
            and _resolve_space_tree(space)
        )

    def execute(self, context):
        space = context.space_data
        tree = _resolve_space_tree(space)
        if tree is None or not self.node_name:
            return {'CANCELLED'}

        node = tree.nodes.get(self.node_name)
        if node is None:
            self.report({'WARNING'}, "找不到源节点")
            return {'CANCELLED'}

        target_tree = getattr(node, self.tree_attr, None)
        if target_tree is None:
            self.report({'WARNING'}, "该节点没有可跳转的节点树")
            return {'CANCELLED'}

        if tree == target_tree:
            return {'FINISHED'}

        if not _activate_tree_in_space(space, target_tree):
            self.report({'WARNING'}, "Unable to open target OmniNodeTree")
            return {'CANCELLED'}
        _push_nav_tree(context, tree)
        return {'FINISHED'}


class OP_ReturnToParentNodeTree(Operator):
    bl_idname = "ho.omni_return_to_parent_node_tree"
    bl_label = "返回上一级"
    bl_description = "返回到 HoTools 自己维护的上一级 OmniNodeTree"

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        tree = _resolve_space_tree(space)
        return bool(
            space
            and space.type == 'NODE_EDITOR'
            and _is_omni_tree(tree)
            and omni_nav_can_go_back(context)
        )

    def execute(self, context):
        space = context.space_data
        current_tree = _resolve_space_tree(space)
        target_tree = _pop_nav_tree(context)

        while target_tree is not None and target_tree == current_tree:
            target_tree = _pop_nav_tree(context)

        if target_tree is None:
            self.report({'WARNING'}, "返回栈为空，没有可返回的节点树")
            return {'CANCELLED'}

        if not _activate_tree_in_space(space, target_tree):
            self.report({'WARNING'}, "无法返回到上一级 OmniNodeTree")
            return {'CANCELLED'}
        return {'FINISHED'}


class NodeSetDefaultSize(Operator):
    bl_idname = "ho.nodesetdefaultsize"
    bl_label = "恢复node默认大小"

    node_name: bpy.props.StringProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            node = bpy.context.space_data.node_tree.nodes[self.node_name]
            node.size2default()
            return {'FINISHED'}
        except Exception:
            return {'FINISHED'}


class NodeSetBiggerSize(Operator):
    bl_idname = "ho.nodesetbiggersize"
    bl_label = "加宽node"

    node_name: bpy.props.StringProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            node = bpy.context.space_data.node_tree.nodes[self.node_name]
            node.width *= 2
            return {'FINISHED'}
        except Exception:
            return {'FINISHED'}


class OmniTreeCreate(Operator):
    bl_idname = "ho.omnitree_create"
    bl_label = "新建 OmniNodeTree"
    bl_description = "快速创建新的 OmniNodeTree，并在当前窗口的 Node Editor 中打开"
    bl_options = {'REGISTER', 'UNDO'}

    tree_name: StringProperty(default="OmniNodeTree", options={'HIDDEN'})  # type: ignore

    def execute(self, context: bpy.types.Context):
        tree = bpy.data.node_groups.new(name=self.tree_name or "OmniNodeTree", type="OmniNodeTree")
        tree.use_fake_user = True

        if _activate_tree_in_current_window(context, tree):
            self.report({'INFO'}, f"已创建并打开 OmniNodeTree: {tree.name}")
        else:
            self.report({'INFO'}, f"已创建 OmniNodeTree: {tree.name}，当前窗口没有可切换的 Node Editor")
        return {'FINISHED'}


class OmniTreeOpen(Operator):
    bl_idname = "ho.omnitree_open"
    bl_label = "打开 OmniNodeTree"
    bl_description = "在当前窗口已有的 Node Editor 中打开指定 OmniNodeTree"
    bl_options = {'REGISTER'}

    tree_name: StringProperty(default="", options={'HIDDEN'})  # type: ignore

    def execute(self, context: bpy.types.Context):
        tree = _find_omni_tree(self.tree_name)
        if tree is None:
            self.report({'WARNING'}, "找不到 OmniNodeTree")
            return {'CANCELLED'}

        if not _activate_tree_in_current_window(context, tree):
            self.report({'WARNING'}, "当前窗口没有可切换的 Node Editor")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已打开 OmniNodeTree: {tree.name}")
        return {'FINISHED'}


class LayerRunning(Operator):
    bl_idname = "ho.layerrunning"
    bl_label = "树手动触发回调"
    bl_options = {'REGISTER', 'UNDO'}
    reportInfo: BoolProperty(name="报告pool信息", default=True)  # type: ignore
    tree_name: StringProperty(default="", options={'HIDDEN'})  # type: ignore

    def execute(self, context: bpy.types.Context):
        tree = _operator_omni_tree(context, self.tree_name)
        if tree is None:
            if self.tree_name:
                self.report({'ERROR'}, "找不到 OmniNodeTree")
                return {'CANCELLED'}
            return {'FINISHED'}

        try:
            tree.run()
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class OmniTreeCompile(Operator):
    bl_idname = "ho.omnitree_compile"
    bl_label = "编译OMNI树"
    bl_description = "只编译当前 OmniNodeTree，并缓存编译结果"
    bl_options = {'REGISTER'}
    tree_name: StringProperty(default="", options={'HIDDEN'})  # type: ignore

    def execute(self, context: bpy.types.Context):
        tree = _operator_omni_tree(context, self.tree_name)
        if tree is None:
            return {'CANCELLED'}

        try:
            tree.compile_cached(force=True)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        self.report({'INFO'}, f"已编译 Omni 树: {tree.name}")
        return {'FINISHED'}


class OmniTreeRunCompiled(Operator):
    bl_idname = "ho.omnitree_run_compiled"
    bl_label = "运行已编译OMNI树"
    bl_description = "运行当前缓存的编译结果。没有编译缓存时请先编译。"
    bl_options = {'REGISTER', 'UNDO'}
    tree_name: StringProperty(default="", options={'HIDDEN'})  # type: ignore

    def execute(self, context: bpy.types.Context):
        tree = _operator_omni_tree(context, self.tree_name)
        if tree is None:
            return {'CANCELLED'}

        try:
            tree.run_compiled()
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        return {'FINISHED'}


class OmniTreeClearCompileCache(Operator):
    bl_idname = "ho.omnitree_clear_compile_cache"
    bl_label = "清理编译缓存"
    bl_description = "清理当前 OmniNodeTree 的编译产物缓存"
    bl_options = {'REGISTER'}
    tree_name: StringProperty(default="", options={'HIDDEN'})  # type: ignore

    def execute(self, context: bpy.types.Context):
        tree = _operator_omni_tree(context, self.tree_name)
        if tree is None:
            return {'CANCELLED'}

        tree.clear_compile_cache()
        self.report({'INFO'}, f"已清理编译缓存: {tree.name}")
        return {'FINISHED'}


class OmniTreeClearRuntimeCache(Operator):
    bl_idname = "ho.omnitree_clear_runtime_cache"
    bl_label = "清理运行缓存"
    bl_description = "清理当前 OmniNodeTree 作为根树运行时保存的缓存数据"
    bl_options = {'REGISTER'}
    tree_name: StringProperty(default="", options={'HIDDEN'})  # type: ignore

    def execute(self, context: bpy.types.Context):
        tree = _operator_omni_tree(context, self.tree_name)
        if tree is None:
            return {'CANCELLED'}

        OmniRuntimeState.clear_root_tree(tree)
        self.report({'INFO'}, f"已清理运行缓存: {tree.name}")
        return {'FINISHED'}


class OmniTreeDestroy(Operator):
    bl_idname = "ho.omninodetree_destroy"
    bl_label = "销毁树"
    bl_description = "销毁当前 OmniNodeTree 数据块"
    bl_options = {'REGISTER', 'UNDO'}
    tree_name: StringProperty(default="", options={'HIDDEN'})  # type: ignore
    confirmed: BoolProperty(default=False, options={'HIDDEN'})  # type: ignore

    def invoke(self, context, event):
        self.confirmed = True
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context: bpy.types.Context):
        if not self.confirmed:
            self.report({'ERROR'}, "销毁 OmniNodeTree 需要确认")
            return {'CANCELLED'}

        tree = _operator_omni_tree(context, self.tree_name)
        if tree is None:
            return {'CANCELLED'}

        tree_name = tree.name
        if hasattr(tree, "clear_compile_cache"):
            tree.clear_compile_cache()
        OmniRuntimeState.clear_root_tree(tree)

        bpy.data.node_groups.remove(tree, do_unlink=True)

        self.report({'INFO'}, f"已销毁节点树: {tree_name}")

        return {'FINISHED'}


class OmniNodeToggleDescription(Operator):
    bl_idname = "ho.omni_toggle_node_description"
    bl_label = "查看节点描述"
    bl_description = "在节点上方显示或隐藏该节点的描述文本"
    bl_options = {'REGISTER'}

    node_tree_name: StringProperty(default="")  # type: ignore
    node_name: StringProperty(default="")  # type: ignore
    use_selected_nodes: BoolProperty(default=False)  # type: ignore
    show_description: BoolProperty(default=True)  # type: ignore

    def _resolve_tree(self, context):
        return _find_omni_tree(self.node_tree_name) if self.node_tree_name else _active_omni_tree(context)

    def _resolve_nodes(self, context):
        tree = self._resolve_tree(context)
        if tree is None:
            return []

        if self.use_selected_nodes:
            nodes = [
                node for node in (list(getattr(context, "selected_nodes", []) or []))
                if getattr(node, "id_data", None) == tree
            ]
            active_node = getattr(context, "active_node", None)
            if active_node is not None and getattr(active_node, "id_data", None) == tree and active_node not in nodes:
                nodes.append(active_node)
            return nodes

        if self.node_name:
            node = tree.nodes.get(self.node_name)
            return [node] if node is not None else []

        active_node = getattr(context, "active_node", None)
        if active_node is not None and getattr(active_node, "id_data", None) == tree:
            return [active_node]

        selected_nodes = [
            node for node in (list(getattr(context, "selected_nodes", []) or []))
            if getattr(node, "id_data", None) == tree
        ]
        return selected_nodes[:1]

    def execute(self, context: bpy.types.Context):
        nodes = self._resolve_nodes(context)
        if not nodes:
            self.report({'WARNING'}, "找不到节点")
            return {'CANCELLED'}

        nodes_with_description = [
            node for node in nodes
            if OmniNodeDraw.DrawDescription.text(node)
        ]
        if not nodes_with_description:
            self.report({'WARNING'}, "所选节点没有描述")
            return {'CANCELLED'}

        shown_count = 0
        hidden_count = 0

        for node in nodes_with_description:
            if self.show_description:
                OmniNodeDraw.DrawDescription.draw(node)
                shown_count += 1
            else:
                OmniNodeDraw.DrawDescription.clear(node)
                hidden_count += 1

            sync_all_draw = getattr(node, "omni_sync_all_draw", None)
            if callable(sync_all_draw):
                sync_all_draw()

        parts = []
        if shown_count:
            parts.append(f"显示 {shown_count} 个")
        if hidden_count:
            parts.append(f"隐藏 {hidden_count} 个")
        self.report({'INFO'}, "节点描述: " + "，".join(parts))
        return {'FINISHED'}


class OmniNodeApplyPreset(Operator):
    bl_idname = "ho.omni_apply_node_preset"
    bl_label = "填入节点预设"
    bl_description = "将 omni 装饰器定义的预设值填入当前节点输入"
    bl_options = {'REGISTER', 'UNDO'}

    node_tree_name: StringProperty(default="")  # type: ignore
    node_name: StringProperty(default="")  # type: ignore
    preset_id: StringProperty(default="NONE")  # type: ignore

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return bool(
            space
            and space.type == 'NODE_EDITOR'
            and _is_omni_tree(_resolve_space_tree(space))
        )

    def _resolve_node(self, context):
        tree = _find_omni_tree(self.node_tree_name) if self.node_tree_name else _active_omni_tree(context)
        if tree is None:
            return None
        if self.node_name:
            return tree.nodes.get(self.node_name)
        node = getattr(context, "active_node", None)
        if node is not None and getattr(node, "id_data", None) == tree:
            return node
        return None

    @staticmethod
    def _set_socket_default(sock, value):
        try:
            sock.default_value = value
            return True
        except Exception:
            pass

        try:
            current_value = sock.default_value
        except Exception:
            return False

        if not isinstance(value, (list, tuple)):
            return False

        try:
            if len(current_value) != len(value):
                return False
            for index, item in enumerate(value):
                current_value[index] = item
            return True
        except Exception:
            return False

    @staticmethod
    def _declared_socket_defaults(node):
        defaults = getattr(node, "_omni_socket_defaults", None)
        return defaults if isinstance(defaults, dict) else {}

    @staticmethod
    def _rna_default(sock):
        try:
            prop = sock.bl_rna.properties.get("default_value")
        except Exception:
            return None
        if prop is None:
            return None

        try:
            if prop.type == 'ENUM':
                enum_items = list(prop.enum_items)
                if enum_items:
                    return enum_items[0].identifier
        except Exception:
            pass

        try:
            return prop.default
        except Exception:
            return None

    @staticmethod
    def _socket_type_default(sock):
        socket_type = getattr(sock, "bl_idname", type(sock).__name__)
        if socket_type == "OmniNodeSocketFloatCurve":
            return float_curve_payload()
        if socket_type == "OmniNodeSocketColorCurve":
            return color_curve_payload()

        defaults = {
            "NodeSocketFloat": 0.0,
            "NodeSocketInt": 0,
            "NodeSocketBool": False,
            "NodeSocketString": "",
            "NodeSocketStringFilePath": "",
            "NodeSocketVector": (0.0, 0.0, 0.0),
            "NodeSocketRotation": (0.0, 0.0, 0.0),
            "NodeSocketColor": (0.0, 0.0, 0.0, 1.0),
            "OmniNodeSocketAny": 0.0,
            "OmniNodeSocketCache": "",
            "OmniNodeSocketBoneChain": "",
            "OmniNodeSocketImageFormat": "PNG",
            "OmniNodeSocketRegex": "",
            "OmniNodeSocketGlob": "",
            "OmniNodeSocketModifier": "",
            "OmniNodeSocketMaterialSlot": "",
            "OmniNodeSocketUVLayer": "",
            "OmniNodeSocketColorAttribute": "",
        }
        if socket_type in defaults:
            return defaults[socket_type]

        rna_default = OmniNodeApplyPreset._rna_default(sock)
        if rna_default is not None:
            return rna_default
        return None

    @staticmethod
    def _clear_compound_socket(sock):
        socket_type = getattr(sock, "bl_idname", type(sock).__name__)
        cleared = False

        for attr_name in (
            "armature_object",
            "mesh_object",
            "bone_name",
            "group_name",
            "shape_key_name",
        ):
            if not hasattr(sock, attr_name):
                continue
            try:
                current = getattr(sock, attr_name)
                if isinstance(current, bpy.types.ID):
                    reset_value = None
                else:
                    try:
                        reset_value = sock.bl_rna.properties[attr_name].default
                    except Exception:
                        reset_value = ""
                setattr(sock, attr_name, reset_value)
                cleared = True
            except Exception:
                pass

        if socket_type in {
            "NodeSocketObject",
            "NodeSocketImage",
            "NodeSocketCollection",
            "NodeSocketMaterial",
            "NodeSocketTexture",
            "OmniNodeSocketScene",
            "OmniNodeSocketText",
            "OmniNodeSocketDatablock",
        }:
            try:
                sock.default_value = None
                cleared = True
            except Exception:
                pass

        return cleared

    @staticmethod
    def _apply_reset_value(sock, value):
        if value is None and OmniNodeApplyPreset._clear_compound_socket(sock):
            return True
        return OmniNodeApplyPreset._set_socket_default(sock, value)

    @staticmethod
    def _reset_socket_default(sock, declared_defaults):
        identifier = getattr(sock, "identifier", "")
        if identifier in declared_defaults:
            return OmniNodeApplyPreset._apply_reset_value(sock, declared_defaults[identifier])

        name = getattr(sock, "name", "")
        if name in declared_defaults:
            return OmniNodeApplyPreset._apply_reset_value(sock, declared_defaults[name])

        value = OmniNodeApplyPreset._socket_type_default(sock)
        if OmniNodeApplyPreset._apply_reset_value(sock, value):
            return True

        return OmniNodeApplyPreset._clear_compound_socket(sock)

    @staticmethod
    def _reset_node_inputs(node):
        declared_defaults = OmniNodeApplyPreset._declared_socket_defaults(node)
        updated_count = 0
        skipped_count = 0

        for sock in getattr(node, "inputs", ()):
            if OmniNodeApplyPreset._reset_socket_default(sock, declared_defaults):
                updated_count += 1
            else:
                skipped_count += 1

        return updated_count, skipped_count

    @staticmethod
    def _sync_node_after_default_change(context, node):
        sync_all_draw = getattr(node, "omni_sync_all_draw", None)
        if callable(sync_all_draw):
            sync_all_draw()

        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def execute(self, context):
        node = self._resolve_node(context)
        if node is None:
            self.report({'WARNING'}, "找不到节点")
            return {'CANCELLED'}

        presets = _node_omni_presets(node)
        if self.preset_id == "NONE":
            updated_count, skipped_count = self._reset_node_inputs(node)
            self._sync_node_after_default_change(context, node)

            parts = [f"重置 {updated_count} 项"]
            if skipped_count:
                parts.append(f"跳过 {skipped_count} 项")
            self.report({'INFO'}, "已清空预设: " + ", ".join(parts))
            return {'FINISHED'}

        try:
            preset_index = int(self.preset_id)
        except ValueError:
            self.report({'WARNING'}, "找不到预设")
            return {'CANCELLED'}

        if preset_index < 0 or preset_index >= len(presets):
            self.report({'WARNING'}, "找不到预设")
            return {'CANCELLED'}

        preset = presets[preset_index]
        updated_count = 0
        missing_count = 0
        skipped_count = 0

        for identifier, value in preset["values"].items():
            sock = node.inputs.get(identifier)
            if sock is None:
                missing_count += 1
                continue

            if self._set_socket_default(sock, value):
                updated_count += 1
            else:
                skipped_count += 1

        self._sync_node_after_default_change(context, node)

        parts = [f"更新 {updated_count} 项"]
        if missing_count:
            parts.append(f"缺失 {missing_count} 项")
        if skipped_count:
            parts.append(f"跳过 {skipped_count} 项")
        self.report({'INFO'}, f"已填入预设 {preset['name']}: " + ", ".join(parts))
        return {'FINISHED'}


class OmniNodeRebuild(Operator):
    # TODO: 诡异bug，重建以后会自动拥有bl_icon，此问题在pr中被反复讨论，是有关customgroupnode的？
    # https://projects.blender.org/blender/blender/pulls/130204
    bl_idname = "ho.rebuild_node"
    bl_label = "重建节点"
    bl_description = "重建节点的输入输出socket，保持用户输入和连接不变，适用于修改了节点函数签名后更新节点"
    bl_options = {'REGISTER'}

    node_tree_name: bpy.props.StringProperty()  # type: ignore
    node_name: bpy.props.StringProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        tree = getattr(space, "node_tree", None)
        if not space or space.type != 'NODE_EDITOR':
            return False
        if not tree or getattr(tree, "bl_idname", None) != "OmniNodeTree":
            return False
        if getattr(context, "selected_nodes", None):
            return True
        return getattr(context, "active_node", None) is not None

    @staticmethod
    def _socket_type_id(sock):
        return getattr(sock, "bl_idname", type(sock).__name__)

    @staticmethod
    def _snapshot_default_value(value):
        if isinstance(value, (str, bool, int, float)) or value is None:
            return value

        if isinstance(value, dict):
            return dict(value)

        if isinstance(value, bpy.types.ID):
            return value

        try:
            return tuple(value)
        except Exception:
            pass

        try:
            return value.copy()
        except Exception:
            return value

    @staticmethod
    def _restore_default_value(sock, cache_entry):
        if not cache_entry:
            return

        if OmniNodeRebuild._socket_type_id(sock) != cache_entry["socket_type"]:
            return

        value = cache_entry["value"]

        if isinstance(value, dict):
            sock.default_value = value
            return

        try:
            current_value = sock.default_value
        except Exception:
            return

        if isinstance(current_value, (str, bool, int, float)) or current_value is None:
            sock.default_value = value
            return

        try:
            current_len = len(current_value)
            value_len = len(value)
        except Exception:
            sock.default_value = value
            return

        if current_len != value_len:
            return

        sock.default_value = value

    @staticmethod
    def rebuild_single_node(tree, node):
        if not hasattr(node, "build"):
            raise RuntimeError(f"Node '{node.name}' has no build() method")

        # 1. cache 用户 default_value
        input_value_cache = {}
        output_value_cache = {}

        for sock in node.inputs:
            try:
                input_value_cache[sock.identifier] = {
                    "socket_type": OmniNodeRebuild._socket_type_id(sock),
                    "value": OmniNodeRebuild._snapshot_default_value(sock.default_value),
                }
            except Exception:
                pass

        for sock in node.outputs:
            try:
                output_value_cache[sock.identifier] = {
                    "socket_type": OmniNodeRebuild._socket_type_id(sock),
                    "value": OmniNodeRebuild._snapshot_default_value(sock.default_value),
                }
            except Exception:
                pass

        # 2. 收集 links
        input_links = []
        for sock in node.inputs:
            for link in sock.links:
                input_links.append((
                    link.from_node.name,
                    link.from_socket.identifier,
                    sock.identifier,
                ))

        output_links = []
        for sock in node.outputs:
            for link in sock.links:
                output_links.append((
                    sock.identifier,
                    link.to_node.name,
                    link.to_socket.identifier,
                ))

        # 3. 清理 sockets + links
        for sock in list(node.inputs):
            for link in list(sock.links):
                tree.links.remove(link)
            node.inputs.remove(sock)

        for sock in list(node.outputs):
            for link in list(sock.links):
                tree.links.remove(link)
            node.outputs.remove(sock)

        # 4. rebuild
        node.build()
        OmniRuntimeState.ensure_tree_runtime_uids(tree)
        if hasattr(node, "clear_bug_state"):
            node.clear_bug_state()
        elif hasattr(node, "is_bug") and hasattr(node, "bug_text"):
            node.is_bug = False
            node.bug_text = ""

        # 5. 恢复 default_value
        for identifier, value in input_value_cache.items():
            sock = node.inputs.get(identifier)
            if sock:
                try:
                    OmniNodeRebuild._restore_default_value(sock, value)
                except Exception:
                    pass

        for identifier, value in output_value_cache.items():
            sock = node.outputs.get(identifier)
            if sock:
                try:
                    OmniNodeRebuild._restore_default_value(sock, value)
                except Exception:
                    pass

        # 6. reconnect input links
        for from_node_name, from_socket_id, to_socket_id in input_links:
            from_node = tree.nodes.get(from_node_name)
            if not from_node:
                continue

            from_socket = from_node.outputs.get(from_socket_id)
            to_socket = node.inputs.get(to_socket_id)

            if from_socket and to_socket:
                tree.links.new(from_socket, to_socket)

        # 7. reconnect output links
        for from_socket_id, to_node_name, to_socket_id in output_links:
            to_node = tree.nodes.get(to_node_name)
            if not to_node:
                continue

            from_socket = node.outputs.get(from_socket_id)
            to_socket = to_node.inputs.get(to_socket_id)

            if from_socket and to_socket:
                tree.links.new(from_socket, to_socket)

    def _resolve_target_nodes(self, context):
        if self.node_tree_name and self.node_name:
            tree = bpy.data.node_groups.get(self.node_tree_name)
            if tree is None:
                raise RuntimeError(f"NodeTree not found: {self.node_tree_name}")

            node = tree.nodes.get(self.node_name)
            if node is None:
                raise RuntimeError(f"Node not found: {self.node_name}")

            return tree, [node]

        space = getattr(context, "space_data", None)
        tree = getattr(space, "node_tree", None)
        if tree is None:
            raise RuntimeError("No active node tree")

        selected_nodes = list(getattr(context, "selected_nodes", []) or [])
        if not selected_nodes:
            active_node = getattr(context, "active_node", None)
            if active_node is not None:
                selected_nodes = [active_node]

        if not selected_nodes:
            raise RuntimeError("No nodes selected")

        return tree, selected_nodes

    def execute(self, context):
        try:
            tree, nodes = self._resolve_target_nodes(context)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        rebuilt_names = []
        failed_messages = []

        for node in nodes:
            try:
                OmniNodeRebuild.rebuild_single_node(tree, node)
                rebuilt_names.append(node.name)
            except Exception as exc:
                if hasattr(node, "set_bug_state"):
                    node.set_bug_state(exc)
                elif hasattr(node, "is_bug") and hasattr(node, "bug_text"):
                    node.is_bug = True
                    node.bug_text = str(exc)
                failed_messages.append(f"{node.name}: {exc}")

        if rebuilt_names:
            self.report({'INFO'}, f"已重建 {len(rebuilt_names)} 个节点: {', '.join(rebuilt_names)}")

        if failed_messages:
            self.report({'ERROR'}, " | ".join(failed_messages))
            if not rebuilt_names:
                return {'CANCELLED'}

        return {'FINISHED'}


def draw_in_NODE_MT_editor_menus(self, context: Context):
    """OmniNode树顶栏左侧"""
    space = context.space_data
    if not space or space.type != 'NODE_EDITOR':
        return
    tree = _resolve_space_tree(space)
    if not _is_omni_tree(tree):
        return

    layout: bpy.types.UILayout = self.layout
    execution_enabled = bool(getattr(tree, "is_execution_enabled", True))

    enable_row = layout.row(align=True)
    enable_row.prop(tree, "is_execution_enabled", text="", toggle=True, icon="CHECKMARK",icon_only=True)

    run_now = layout.row(align=True)
    run_now.enabled = execution_enabled
    run_now.operator(LayerRunning.bl_idname, text="运行OMNI树", icon="FILE_REFRESH")

    row = layout.row(align=True)
    compile_button = row.row(align=True)
    compile_button.alert = execution_enabled and _should_alert_compile_button(tree)
    compile_button.operator(OmniTreeCompile.bl_idname, text="编译", icon="FILE_TICK")
    run_button = row.row(align=True)
    run_button.enabled = execution_enabled
    run_button.operator(OmniTreeRunCompiled.bl_idname, text="运行", icon="PLAY")
    frame_button = row.row(align=True)
    frame_button.enabled = execution_enabled
    frame_button.prop(tree, "is_frame_run_enabled", text="每帧运行", toggle=True, icon="TIME")
    row.label(text=tree.compile_cache_status_label())
    return


def draw_in_NODE_MT_context_menu(self, context: Context):
    """OMNINODE树内右键"""
    space = context.space_data
    if not space or space.type != 'NODE_EDITOR':
        return
    tree = _resolve_space_tree(space)
    if not tree or getattr(tree, "bl_idname", None) != "OmniNodeTree":
        return

    selected_nodes = list(getattr(context, "selected_nodes", []) or [])
    active_node = getattr(context, "active_node", None)
    target_count = len(selected_nodes) if selected_nodes else (1 if active_node else 0)
    if target_count <= 0:
        return

    layout: bpy.types.UILayout = self.layout
    layout.separator()
    target_nodes = selected_nodes if selected_nodes else ([active_node] if active_node is not None else [])
    target_nodes = [
        node for node in target_nodes
        if getattr(node, "id_data", None) == tree and OmniNodeDraw.DrawDescription.text(node)
    ]
    if target_nodes:
        all_visible = all(OmniNodeDraw.DrawDescription.is_visible(node) for node in target_nodes)
        multi_target = len(target_nodes) > 1
        text = ("隐藏所选描述" if multi_target else "隐藏描述") if all_visible else (
            "查看所选描述" if multi_target else "查看描述"
        )
        op = layout.operator(OmniNodeToggleDescription.bl_idname, text=text, icon="INFO")
        op.node_tree_name = getattr(tree, "name_full", tree.name)
        op.use_selected_nodes = len(selected_nodes) > 1
        op.show_description = not all_visible
        if not op.use_selected_nodes:
            op.node_name = target_nodes[0].name

    preset_node = active_node
    if preset_node is None and len(selected_nodes) == 1:
        preset_node = selected_nodes[0]
    if preset_node is not None and getattr(preset_node, "id_data", None) == tree:
        presets = _node_omni_presets(preset_node)
        if presets:
            layout.separator()
            row = layout.row(align=True)
            row.prop(preset_node, "omni_preset_id", text="预设")
            op = row.operator(OmniNodeApplyPreset.bl_idname, text="", icon="PRESET")
            op.node_tree_name = getattr(tree, "name_full", tree.name)
            op.node_name = preset_node.name
            op.preset_id = getattr(preset_node, "omni_preset_id", "NONE")

    label = "重建所选节点" if target_count > 1 else "重建节点"
    layout.operator(OmniNodeRebuild.bl_idname, text=label, icon="NODETREE")

def draw_in_NODE_HT_header(self, context: Context):
    """OMNINODE树顶栏右侧"""
    space = context.space_data
    if not space or space.type != 'NODE_EDITOR':
        return
    tree = _resolve_space_tree(space)
    if not tree or getattr(tree, "bl_idname", None) != "OmniNodeTree":
        return
    layout: bpy.types.UILayout = self.layout
    if omni_nav_can_go_back(context):
        stack_label = omni_nav_stack_label(context)
        if stack_label:
            layout.operator(OP_ReturnToParentNodeTree.bl_idname, text=stack_label, icon="FILE_PARENT")
    row = layout.row(align=True)
    row.operator_context = 'INVOKE_DEFAULT'
    row.operator(OmniTreeDestroy.bl_idname, text="销毁树")
    row.operator_context = 'EXEC_DEFAULT'
    row.operator(OmniTreeClearCompileCache.bl_idname, text="销毁编译")
    row.operator(OmniTreeClearRuntimeCache.bl_idname, text="销毁缓存")


clss = [
    NodeSetDefaultSize,
    NodeSetBiggerSize,
    OmniTreeCreate,
    OmniTreeOpen,
    LayerRunning,
    OmniTreeCompile,
    OmniTreeRunCompiled,
    OmniTreeClearCompileCache,
    OmniTreeClearRuntimeCache,
    OmniNodeToggleDescription,
    OmniNodeApplyPreset,
    OmniNodeRebuild,
    OmniGraphNodeIOItem,
    HO_UL_GraphNodeIO,
    OP_IOItemAdd,
    OP_IOItemRemove,
    OmniTreeDestroy,
    OP_IOItemMove,
    OP_JumpToNodeTree,
    OP_ReturnToParentNodeTree,
]


def register():
    try:
        for i in clss:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__ + " register failed!!!")
    bpy.types.NODE_MT_editor_menus.append(draw_in_NODE_MT_editor_menus)
    bpy.types.NODE_MT_context_menu.append(draw_in_NODE_MT_context_menu)
    bpy.types.NODE_HT_header.append(draw_in_NODE_HT_header)


def unregister():
    try:
        for i in clss:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__ + " unregister failed!!!")
    bpy.types.NODE_MT_editor_menus.remove(draw_in_NODE_MT_editor_menus)
    bpy.types.NODE_MT_context_menu.remove(draw_in_NODE_MT_context_menu)
    bpy.types.NODE_HT_header.remove(draw_in_NODE_HT_header)
