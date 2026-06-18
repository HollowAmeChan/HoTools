import bpy
from bpy.types import NodeSocket, NodeSocketImage
from .OmniCurve import (
    OmniCurvePresetRegistry,
    OmniColorCurveData,
    OmniFloatCurveData,
    color_curve_payload,
    curve_preset_payload,
    float_curve_payload,
)


OMNI_MODIFIER_TYPE_ITEMS = [
    ("SUBSURF", "Subdivision Surface", ""),
    ("BOOLEAN", "Boolean", ""),
    ("ARMATURE", "Armature", ""),
]


def _collect_modifier_type_items():
    items = []
    try:
        modifier_type_prop = bpy.types.Modifier.bl_rna.properties["type"]
        for item in modifier_type_prop.enum_items:
            items.append((
                str(item.identifier),
                str(item.name or item.identifier),
                str(item.description or ""),
            ))
    except Exception:
        pass
    return items


def _refresh_modifier_type_items():
    items = _collect_modifier_type_items()
    if items:
        OMNI_MODIFIER_TYPE_ITEMS.clear()
        OMNI_MODIFIER_TYPE_ITEMS.extend(items)
    return OMNI_MODIFIER_TYPE_ITEMS


def _modifier_type_items_callback(self, context):
    return OMNI_MODIFIER_TYPE_ITEMS


def _armature_object_poll(self, obj):
    return obj is not None and getattr(obj, "type", None) == "ARMATURE"


def _mesh_object_poll(self, obj):
    return obj is not None and getattr(obj, "type", None) == "MESH"


def _curve_socket_extend(socket):
    curve = getattr(socket, "curve", None)
    return getattr(curve, "extend", "CLAMP") if curve is not None else "CLAMP"


def _curve_socket_preset_payload(socket, preset_id):
    curve_kind = "color_curve" if getattr(socket, "bl_idname", "") == "OmniNodeSocketColorCurve" else "float_curve"
    extend = _curve_socket_extend(socket)
    return curve_preset_payload(preset_id, curve_kind=curve_kind, extend=extend)


def _curve_socket_kind(socket):
    return "color_curve" if getattr(socket, "bl_idname", "") == "OmniNodeSocketColorCurve" else "float_curve"


def _find_node_socket(node, socket_identifier, socket_name):
    for collection in (getattr(node, "inputs", ()), getattr(node, "outputs", ())):
        for socket in collection:
            if socket_identifier and getattr(socket, "identifier", "") == socket_identifier:
                return socket
        if socket_name:
            socket = collection.get(socket_name)
            if socket is not None:
                return socket
    return None


def _find_curve_socket(context, tree_name, node_name, socket_identifier, socket_name):
    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
    if tree is None:
        return None, None, None

    node = tree.nodes.get(node_name)
    if node is None:
        return tree, None, None

    socket = _find_node_socket(node, socket_identifier, socket_name)
    return tree, node, socket


def _apply_curve_socket_preset(context, tree_name, node_name, socket_identifier, socket_name, preset_id):
    tree, node, socket = _find_curve_socket(context, tree_name, node_name, socket_identifier, socket_name)
    if tree is None:
        return False, "找不到节点树"
    if node is None:
        return False, "找不到节点"
    if socket is None:
        return False, "找不到曲线 socket"

    payload = _curve_socket_preset_payload(socket, preset_id)
    if payload is None:
        return False, "找不到曲线预设"

    socket.default_value = payload
    area = getattr(context, "area", None)
    if area is not None:
        area.tag_redraw()
    return True, ""


def _draw_curve_socket_controls(socket, layout, node, text, curve):
    row = layout.row(align=True)
    row.label(text=text or socket.name)
    row.prop(curve, "extend", text="")
    operator = row.operator(OmniNodeOpenCurvePresetPopup.bl_idname, text="预设", icon="PRESET")
    operator.tree_name = getattr(getattr(node, "id_data", None), "name", "")
    operator.node_name = getattr(node, "name", "")
    operator.socket_identifier = getattr(socket, "identifier", "")
    operator.socket_name = getattr(socket, "name", "")
    row.label(text=f"{len(curve.points)} 点" if len(curve.points) else "默认")


class OmniNodeOpenCurvePresetPopup(bpy.types.Operator):
    bl_idname = "ho_tools.omni_open_curve_preset_popup"
    bl_label = "曲线预设"
    bl_description = "打开曲线预设选择窗口"
    bl_options = {"UNDO"}

    tree_name: bpy.props.StringProperty(default="")  # type: ignore
    node_name: bpy.props.StringProperty(default="")  # type: ignore
    socket_identifier: bpy.props.StringProperty(default="")  # type: ignore
    socket_name: bpy.props.StringProperty(default="")  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        _, _, socket = _find_curve_socket(
            context,
            self.tree_name,
            self.node_name,
            self.socket_identifier,
            self.socket_name,
        )
        curve_kind = _curve_socket_kind(socket) if socket is not None else "float_curve"
        presets = OmniCurvePresetRegistry.classes(curve_kind)

        layout = self.layout
        box = layout.box()
        box.label(text="曲线预设")

        columns = 4
        grid = box.grid_flow(columns=columns, even_columns=True, even_rows=True, align=True)
        for preset_cls in presets:
            cell = grid.box()
            cell.scale_y = 2.0
            cell.alignment = "CENTER"
            operator = cell.operator(
                OmniNodeApplyCurveSocketPreset.bl_idname,
                text=preset_cls.name,
            )
            operator.tree_name = self.tree_name
            operator.node_name = self.node_name
            operator.socket_identifier = self.socket_identifier
            operator.socket_name = self.socket_name
            operator.preset_id = preset_cls.identifier

    def execute(self, context):
        return {"FINISHED"}


class OmniNodeApplyCurveSocketPreset(bpy.types.Operator):
    bl_idname = "ho_tools.omni_apply_curve_socket_preset"
    bl_label = "应用曲线预设"
    bl_description = "把当前预设写入曲线"
    bl_options = {"UNDO"}

    tree_name: bpy.props.StringProperty(default="")  # type: ignore
    node_name: bpy.props.StringProperty(default="")  # type: ignore
    socket_identifier: bpy.props.StringProperty(default="")  # type: ignore
    socket_name: bpy.props.StringProperty(default="")  # type: ignore
    preset_id: bpy.props.StringProperty(default="CLEAR")  # type: ignore

    def execute(self, context):
        ok, message = _apply_curve_socket_preset(
            context,
            self.tree_name,
            self.node_name,
            self.socket_identifier,
            self.socket_name,
            self.preset_id,
        )
        if not ok:
            if message:
                self.report({"WARNING"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


class OmniNodeSocketFloatCurve(NodeSocket):
    bl_label = "浮点曲线-Omni"
    bl_idname = "OmniNodeSocketFloatCurve"

    curve: bpy.props.PointerProperty(type=OmniFloatCurveData)  # type: ignore

    @property
    def default_value(self):
        curve = getattr(self, "curve", None)
        if curve is None:
            return float_curve_payload()
        return curve.as_payload()

    @default_value.setter
    def default_value(self, value):
        curve = getattr(self, "curve", None)
        if curve is None:
            return
        if isinstance(value, (int, float)):
            curve.value = float(value)
            curve.from_payload([
                {"x": 0.0, "y": float(value)},
                {"x": 1.0, "y": float(value)},
            ])
            return
        curve.from_payload(value)

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
            return
        curve = getattr(self, "curve", None)
        if curve is None:
            layout.label(text=self.name)
            return
        _draw_curve_socket_controls(self, layout, node, text, curve)

    @classmethod
    def draw_color_simple(cls):
        return (0.38, 0.78, 0.92, 1.0)


class OmniNodeSocketColorCurve(NodeSocket):
    bl_label = "颜色曲线-Omni"
    bl_idname = "OmniNodeSocketColorCurve"

    curve: bpy.props.PointerProperty(type=OmniColorCurveData)  # type: ignore

    @property
    def default_value(self):
        curve = getattr(self, "curve", None)
        if curve is None:
            return color_curve_payload()
        return curve.as_payload()

    @default_value.setter
    def default_value(self, value):
        curve = getattr(self, "curve", None)
        if curve is None:
            return
        curve.from_payload(value)

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
            return
        curve = getattr(self, "curve", None)
        if curve is None:
            layout.label(text=self.name)
            return
        _draw_curve_socket_controls(self, layout, node, text, curve)

    @classmethod
    def draw_color_simple(cls):
        return (0.95, 0.55, 0.28, 1.0)


class OmniNodeSocketScene(NodeSocket):
    bl_label = "场景-Omni"
    bl_idname = "OmniNodeSocketScene"

    default_value: bpy.props.PointerProperty(
        type=bpy.types.Scene,
        description="场景",
    )  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (1.0, 0.4, 0.216, 1.0)


class OmniNodeSocketText(NodeSocket):
    bl_label = "文本文件-Omni"
    bl_idname = "OmniNodeSocketText"

    default_value: bpy.props.PointerProperty(
        type=bpy.types.Text,
        description="文本",
    )  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (1.0, 1.0, 1.0, 1.0)


class OmniNodeSocketAny(NodeSocket):
    bl_label = "Any-Omni"
    bl_idname = "OmniNodeSocketAny"

    default_value: bpy.props.FloatProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.5, 0.5, 0.5, 0.5)


class OmniNodeSocketCache(NodeSocket):
    bl_label = "Cache-Omni"
    bl_idname = "OmniNodeSocketCache"

    default_value: bpy.props.StringProperty(
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.1, 0.72, 0.62, 1.0)


class OmniNodeSocketBone(NodeSocket):
    bl_label = "Bone-Omni"
    bl_idname = "OmniNodeSocketBone"

    armature_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=_armature_object_poll,
        description="Armature Object",
    )  # type: ignore
    bone_name: bpy.props.StringProperty(
        name="Bone",
    )  # type: ignore

    @property
    def default_value(self):
        obj = self.armature_object
        bone = str(self.bone_name or "").strip()
        if obj is None or not bone:
            return None
        if getattr(obj, "type", None) != "ARMATURE" or bone not in obj.data.bones:
            return None
        return {
            "armature": obj,
            "bone": bone,
        }

    @default_value.setter
    def default_value(self, value):
        if not isinstance(value, dict):
            return

        obj = value.get("armature")
        bone = str(value.get("bone") or "").strip()
        if isinstance(obj, bpy.types.Object) and obj.type == "ARMATURE":
            self.armature_object = obj
        try:
            self.bone_name = bone
        except Exception:
            pass

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
            return

        row = layout.row(align=True)
        row.prop(self, "armature_object", text=text)
        obj = self.armature_object
        if obj is not None and getattr(obj, "type", None) == "ARMATURE":
            row.prop_search(self, "bone_name", obj.data, "bones", text="")
        else:
            row.prop(self, "bone_name", text="")

    @classmethod
    def draw_color_simple(cls):
        return (0.55, 0.35, 0.78, 1.0)


class OmniNodeSocketBoneChain(NodeSocket):
    bl_label = "BoneChain-Omni"
    bl_idname = "OmniNodeSocketBoneChain"

    default_value: bpy.props.StringProperty(
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.42, 0.26, 0.68, 1.0)


class OmniNodeSocketImageFormat(NodeSocket):
    bl_label = "图片后缀格式-Omni"
    bl_idname = "OmniNodeSocketImageFormat"

    format_items = [
        ("PNG", "PNG", ""),
        ("JPG", "JPG", ""),
        ("JPEG", "JPEG", ""),
        ("TGA", "TGA", ""),
        ("EXR", "EXR", ""),
        ("BMP", "BMP", ""),
    ]

    default_value: bpy.props.EnumProperty(
        items=format_items,
        name="Image Format",
    )  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.439216, 0.698039, 1.0, 1.0)


class OmniNodeSocketRegex(NodeSocket):
    bl_label = "正则表达式-Omni"
    bl_idname = "OmniNodeSocketRegex"

    default_value: bpy.props.StringProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0, 0, 0.5, 1.0)


class OmniNodeSocketGlob(NodeSocket):
    bl_label = "Glob表达式-Omni"
    bl_idname = "OmniNodeSocketGlob"

    default_value: bpy.props.StringProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.2, 0.2, 0.5, 1.0)


class OmniNodeSocketDatablock(NodeSocket):
    bl_label = "数据块-Omni"
    bl_idname = "OmniNodeSocketDatablock"

    default_value: bpy.props.PointerProperty(
        type=bpy.types.ID,
        description="Datablock",
    )  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.8, 0.55, 0.2, 1.0)


class OmniNodeSocketModifierType(NodeSocket):
    bl_label = "修改器类型-Omni"
    bl_idname = "OmniNodeSocketModifierType"

    default_value: bpy.props.EnumProperty(
        items=_modifier_type_items_callback,
        name="Modifier Type",
    )  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)        

    @classmethod
    def draw_color_simple(cls):
        return (0.439216, 0.698039, 1.0, 1.0)


class OmniNodeSocketModifier(NodeSocket):
    bl_label = "修改器-Omni"
    bl_idname = "OmniNodeSocketModifier"

    # 仅作为运行时占位，避免未连接时编译阶段直接访问属性失败。
    default_value: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.85, 0.63, 0.18, 1.0)


class OmniNodeSocketMaterialSlot(NodeSocket):
    bl_label = "材质槽-Omni"
    bl_idname = "OmniNodeSocketMaterialSlot"

    default_value: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.92, 0.55, 0.23, 1.0)


class OmniNodeSocketUVLayer(NodeSocket):
    bl_label = "UV层-Omni"
    bl_idname = "OmniNodeSocketUVLayer"

    default_value: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.28, 0.72, 0.86, 1.0)


class OmniNodeSocketColorAttribute(NodeSocket):
    bl_label = "顶点色属性-Omni"
    bl_idname = "OmniNodeSocketColorAttribute"

    default_value: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.78, 0.36, 0.18, 1.0)


class OmniNodeSocketVertexGroup(NodeSocket):
    bl_label = "顶点组-Omni"
    bl_idname = "OmniNodeSocketVertexGroup"

    mesh_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=_mesh_object_poll,
        description="Mesh Object",
    )  # type: ignore
    group_name: bpy.props.StringProperty(
        name="Vertex Group",
    )  # type: ignore

    @property
    def default_value(self):
        obj = self.mesh_object
        group_name = str(self.group_name or "").strip()
        if obj is None or not group_name:
            return None
        if getattr(obj, "type", None) != "MESH":
            return None
        return obj.vertex_groups.get(group_name)

    @default_value.setter
    def default_value(self, value):
        if not isinstance(value, bpy.types.VertexGroup):
            return

        obj = getattr(value, "id_data", None)
        if isinstance(obj, bpy.types.Object) and obj.type == "MESH":
            self.mesh_object = obj
        try:
            self.group_name = value.name
        except Exception:
            pass

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
            return

        row = layout.row(align=True)
        row.prop(self, "mesh_object", text=text)
        obj = self.mesh_object
        if obj is not None and getattr(obj, "type", None) == "MESH":
            row.prop_search(self, "group_name", obj, "vertex_groups", text="")
        else:
            row.prop(self, "group_name", text="")

    @classmethod
    def draw_color_simple(cls):
        return (0.22, 0.66, 0.26, 1.0)


class OmniNodeSocketShapeKey(NodeSocket):
    bl_label = "形态键-Omni"
    bl_idname = "OmniNodeSocketShapeKey"

    mesh_object: bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=_mesh_object_poll,
        description="Mesh Object",
    )  # type: ignore
    shape_key_name: bpy.props.StringProperty(
        name="Shape Key",
        default="MeshPhysics",
    )  # type: ignore

    @property
    def default_value(self):
        obj = self.mesh_object
        shape_key_name = str(self.shape_key_name or "").strip()
        if obj is None or not shape_key_name:
            return None
        if getattr(obj, "type", None) != "MESH":
            return None
        return {
            "object": obj,
            "shape_key": shape_key_name,
        }

    @default_value.setter
    def default_value(self, value):
        if isinstance(value, dict):
            obj = value.get("object")
            shape_key_name = str(value.get("shape_key") or value.get("shape_key_name") or "").strip()
            if isinstance(obj, bpy.types.Object) and obj.type == "MESH":
                self.mesh_object = obj
            if shape_key_name:
                self.shape_key_name = shape_key_name
            return

        if not isinstance(value, bpy.types.ShapeKey):
            return

        key_data = getattr(value, "id_data", None)
        for obj in bpy.data.objects:
            if getattr(obj, "type", None) == "MESH" and getattr(obj.data, "shape_keys", None) == key_data:
                self.mesh_object = obj
                break
        try:
            self.shape_key_name = value.name
        except Exception:
            pass

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
            return

        row = layout.row(align=True)
        row.prop(self, "mesh_object", text=text)
        obj = self.mesh_object
        shape_keys = getattr(getattr(obj, "data", None), "shape_keys", None)
        if obj is not None and getattr(obj, "type", None) == "MESH" and shape_keys is not None:
            row.prop_search(self, "shape_key_name", shape_keys, "key_blocks", text="")
        else:
            row.prop(self, "shape_key_name", text="")

    @classmethod
    def draw_color_simple(cls):
        return (0.22, 0.52, 0.78, 1.0)


socket_cls = [
    OmniNodeSocketScene,
    OmniNodeSocketText,
    OmniNodeSocketAny,
    OmniNodeSocketCache,
    OmniNodeSocketFloatCurve,
    OmniNodeSocketColorCurve,
    OmniNodeSocketBone,
    OmniNodeSocketBoneChain,
    OmniNodeSocketImageFormat,
    OmniNodeSocketRegex,
    OmniNodeSocketGlob,
    OmniNodeSocketDatablock,
    OmniNodeSocketModifierType,
    OmniNodeSocketModifier,
    OmniNodeSocketMaterialSlot,
    OmniNodeSocketUVLayer,
    OmniNodeSocketColorAttribute,
    OmniNodeSocketVertexGroup,
    OmniNodeSocketShapeKey,
]

operator_cls = [
    OmniNodeOpenCurvePresetPopup,
    OmniNodeApplyCurveSocketPreset,
]

# 保留旧入口，图节点 IO 类型枚举和外部脚本还会读取 OmniNodeSocket.cls。
cls = socket_cls


def register():
    try:
        _refresh_modifier_type_items()
        for item in operator_cls:
            bpy.utils.register_class(item)
        for item in socket_cls:
            bpy.utils.register_class(item)
    except Exception:
        print(__file__ + " register failed!!!")


def unregister():
    try:
        for item in reversed(socket_cls):
            bpy.utils.unregister_class(item)
        for item in reversed(operator_cls):
            bpy.utils.unregister_class(item)
    except Exception:
        print(__file__ + " unregister failed!!!")
