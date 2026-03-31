from ..widgets.button import Button
from ..widgets.base import Widget

def create_main_ui():

    root = Widget("root", (0, 0, 1000, 1000))

    def hello():
        print("Hello Click")

    def cube():
        import bpy
        bpy.ops.mesh.primitive_cube_add()

    root.add(Button("btn1", (50, 150, 150, 40), "打印日志", hello))
    root.add(Button("btn2", (50, 90, 150, 40), "创建立方体", cube))

    return root