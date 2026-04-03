import bpy
from bpy.types import NodeSocket


class OmniNodeSocketScene(NodeSocket):
    bl_label = "Omni节点场景Socket"
    bl_idname = 'OmniNodeSocketScene'

    default_value: bpy.props.PointerProperty(
        type=bpy.types.Scene, description="场景")  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (1.0, 0.4, 0.216, 0.5)

class OmniNodeSocketText(NodeSocket):
    bl_label = "Omni节点文本文件Socket"
    bl_idname = 'OmniNodeSocketText'

    default_value: bpy.props.PointerProperty(
        type=bpy.types.Text, description="场景")  # type: ignore

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    @classmethod
    def draw_color_simple(cls):
        return (1.0, 1.0, 1.0, 0.5)


class OmniNodeSocketAny(NodeSocket):
    bl_label = "Omni节点虚Socket"
    bl_idname = 'OmniNodeSocketAny'

    # 无用

    default_value: bpy.props.FloatProperty()  # type: ignore

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.5, 0.5, 0.5, 0.9)



cls = [OmniNodeSocketScene, OmniNodeSocketText,
       OmniNodeSocketAny,
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
