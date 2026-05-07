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

    default_value: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.22, 0.66, 0.26, 1.0)


class OmniNodeSocketParameterFloat(NodeSocket):
    bl_label = "Float-OmniParam"
    bl_idname = "OmniNodeSocketParameterFloat"

    default_value: bpy.props.FloatProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.63, 0.72, 1.0, 1.0)


class OmniNodeSocketParameterInt(NodeSocket):
    bl_label = "Int-OmniParam"
    bl_idname = "OmniNodeSocketParameterInt"

    default_value: bpy.props.IntProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.63, 0.72, 1.0, 1.0)


class OmniNodeSocketParameterBool(NodeSocket):
    bl_label = "Bool-OmniParam"
    bl_idname = "OmniNodeSocketParameterBool"

    default_value: bpy.props.BoolProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.63, 0.72, 1.0, 1.0)


class OmniNodeSocketParameterString(NodeSocket):
    bl_label = "String-OmniParam"
    bl_idname = "OmniNodeSocketParameterString"

    default_value: bpy.props.StringProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.63, 0.72, 1.0, 1.0)


class OmniNodeSocketParameterVector(NodeSocket):
    bl_label = "Vector-OmniParam"
    bl_idname = "OmniNodeSocketParameterVector"

    default_value: bpy.props.FloatVectorProperty(size=3, subtype="XYZ")  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.63, 0.72, 1.0, 1.0)


cls = [
    OmniNodeSocketScene,
    OmniNodeSocketText,
    OmniNodeSocketAny,
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
    OmniNodeSocketParameterFloat,
    OmniNodeSocketParameterInt,
    OmniNodeSocketParameterBool,
    OmniNodeSocketParameterString,
    OmniNodeSocketParameterVector,
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
