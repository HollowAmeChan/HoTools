import bpy
from bpy.types import NodeSocket,NodeSocketImage


class OmniNodeSocketScene(NodeSocket):
    bl_label = "Omni节点场景Socket"
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
    bl_label = "Omni节点文本文件Socket"
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
    bl_label = "Omni节点虚Socket"
    bl_idname = 'OmniNodeSocketAny'

    # 无用

    default_value: bpy.props.FloatProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        layout.label(text=self.name)

    @classmethod
    def draw_color_simple(cls):
        return (0.5, 0.5, 0.5, 0.5)

class OmniNodeSocketImageFormat(NodeSocket):
    bl_label = "Omni图片后缀格式Socket"
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
    bl_label = "Omni正则表达式Socket"
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
    bl_label = "OmniGlob表达式Socket"
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

cls = [OmniNodeSocketScene, OmniNodeSocketText,
       OmniNodeSocketAny,OmniNodeSocketImageFormat,
       OmniNodeSocketRegex, OmniNodeSocketGlob
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
