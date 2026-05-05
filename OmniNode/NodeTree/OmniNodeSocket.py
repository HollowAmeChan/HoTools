import bpy
from bpy.types import NodeSocket,NodeSocketImage


class OmniNodeSocketScene(NodeSocket):
    bl_label = "场景-Omni"
    bl_idname = 'OmniNodeSocketScene'

    default_value: bpy.props.PointerProperty(
        type=bpy.types.Scene, description="场景")  # type: ignore

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
    bl_idname = 'OmniNodeSocketText'

    default_value: bpy.props.PointerProperty(
        type=bpy.types.Text, description="场景")  # type: ignore

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
    bl_idname = 'OmniNodeSocketAny'

    # 无用

    default_value: bpy.props.FloatProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.5, 0.5, 0.5, 0.5)

class OmniNodeSocketImageFormat(NodeSocket):
    bl_label = "图片后缀格式-Omni"
    bl_idname = 'OmniNodeSocketImageFormat'

    format_items = [
        ('PNG', "PNG", ""),
        ('JPG', "JPG", ""),
        ('JPEG', "JPEG", ""),
        ('TGA', "TGA", ""),
        ('EXR', "EXR", ""),
        ('BMP', "BMP", ""),
    ]

    default_value: bpy.props.EnumProperty(
        items=format_items,
        name="Image Format"
    )  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.439216, 0.698039, 1.0, 1.0) #内置NodeSocketString的颜色

class OmniNodeSocketRegex(NodeSocket):
    bl_label = "正则表达式-Omni"
    bl_idname = 'OmniNodeSocketRegex'

    default_value: bpy.props.StringProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0, 0, 0.5, 1.0) #内置NodeSocketString的颜色，偏色1
    
class OmniNodeSocketGlob(NodeSocket):
    bl_label = "Glob表达式-Omni"
    bl_idname = 'OmniNodeSocketGlob'

    default_value: bpy.props.StringProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=self.name)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.2, 0.2, 0.5, 1.0) #内置NodeSocketString的颜色，偏色2


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

cls = [OmniNodeSocketScene, OmniNodeSocketText,
       OmniNodeSocketAny,OmniNodeSocketImageFormat,
       OmniNodeSocketRegex, OmniNodeSocketGlob,
       OmniNodeSocketDatablock,
       OmniNodeSocketParameterFloat,
       OmniNodeSocketParameterInt,
       OmniNodeSocketParameterBool,
       OmniNodeSocketParameterString,
       OmniNodeSocketParameterVector,
       ]


def register():
    try:
        for i in cls:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__+" register failed!!!")


def unregister():
    try:
        for i in cls:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__+" unregister failed!!!")
