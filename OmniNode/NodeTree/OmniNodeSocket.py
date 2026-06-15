import bpy
from bpy.types import NodeSocket, NodeSocketImage


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


cls = [
    OmniNodeSocketScene,
    OmniNodeSocketText,
    OmniNodeSocketAny,
    OmniNodeSocketCache,
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


def register():
    try:
        _refresh_modifier_type_items()
        for i in cls:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__ + " register failed!!!")


def unregister():
    try:
        for i in cls:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__ + " unregister failed!!!")
