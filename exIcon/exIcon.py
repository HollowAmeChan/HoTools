import bpy
import gpu
import os
from gpu_extras.batch import batch_for_shader
from bpy.types import Operator
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty


class ExIcon():
    def __init__(self):
        self.handlers = []  # 存储添加的handler
        self.texture = "exIcon.png"  # 名字


exIcon = ExIcon()


def readFromFile(file_path: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, file_path)
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


class OP_drawExIcon(Operator):
    bl_idname = "ho.draw_exicon"
    bl_label = "绘制exIcon"
    bl_description = ""
    bl_options = {'REGISTER'}

    def get_v_shader(self) -> str:
        return readFromFile("exIcon/image.vert")

    def get_f_shader(self) -> str:
        return readFromFile("exIcon/image.frag")

    def makeDrawFunction(self, shader, gpuTex, batch):
        def draw():
            """添加到绘制的函数,传入draw_handler_add()方法"""
            outlinerArea = None
            for area in bpy.context.screen.areas:
                if area.type == 'OUTLINER':
                    outlinerArea = area
            if not outlinerArea:
                return  # 没有区域就不绘制了

            gpu.state.blend_set('ALPHA')  # 设置混合模式-alpha混合
            shader.uniform_sampler("tex", gpuTex)  # 设置纹理
            print(outlinerArea.regions[-1].width,
                  "    ",
                  outlinerArea.regions[-1].height)
            shader.uniform_float(
                "viewSize", (outlinerArea.regions[-1].width, outlinerArea.regions[-1].height))
            # 传递视图宽高 #这里使用regions[-1]是为了保证宽高是此区域的最大子区域，-1索引为最大的视图

            # shader.uniform_float(
            #     "texSize", (tex.size[0], tex.size[1])  # 传递图像宽高
            # )
            batch.draw(shader)
        return draw

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        shader_info = gpu.types.GPUShaderCreateInfo()  # 创建shader
        # vertexShader接口,batch_for_shader中字典参数按顺序传入
        shader_info.vertex_in(0, 'VEC2', "position")
        vert_out = gpu.types.GPUStageInterfaceInfo("ExIcon")
        vert_out.smooth('VEC2', "usingPos")  # vertexShader传输到fragmentShader
        shader_info.vertex_out(vert_out)
        # fragmentShader接口
        shader_info.sampler(0, 'FLOAT_2D', "tex")
        shader_info.push_constant('VEC2', "viewSize")
        shader_info.push_constant('VEC2', "texSize")
        shader_info.fragment_out(0, 'VEC4', "FragColor")  # 颜色输出，必要

        # 编译着色器
        shader_info.vertex_source(self.get_v_shader())  # 顶点着色器
        shader_info.fragment_source(self.get_f_shader())  # 片段着色器

        shader = gpu.shader.create_from_info(shader_info)
        del vert_out, shader_info

        batch = batch_for_shader(shader, 'TRI_FAN',
                                 {"position":  (
                                     (-1, -1), (1, -1), (1, 1), (-1, 1))},
                                 )  # 新建一个绘制任务

        global exIcon
        tex = bpy.data.images[exIcon.texture]
        if not tex:
            return {'FINISHED'}
        gpuTex = gpu.texture.from_image(tex)

        handler = bpy.types.SpaceOutliner.draw_handler_add(
            self.makeDrawFunction(shader, gpuTex, batch), (), 'WINDOW', 'POST_PIXEL')  # 添加绘制

        exIcon.handlers.append(handler)  # 全局记录绘制
        return {'FINISHED'}


class OP_removeExIcon(Operator):
    bl_idname = "ho.remove_exicon"
    bl_label = "取消exIcon"
    bl_description = ""
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        global exIcon
        while exIcon.handlers:  # 倒序删除
            handler = exIcon.handlers.pop()
            bpy.types.SpaceOutliner.draw_handler_remove(handler, 'WINDOW')

        return {'FINISHED'}


def loadExIcon(dummy):
    if "exIcon.png" not in bpy.data.images:
        script_dir = os.path.dirname(os.path.abspath(__file__))  # 获取脚本所在目录
        global exIcon
        image_path = os.path.join(script_dir, exIcon.texture)  # 拼接图片路径
        bpy.data.images.load(filepath=image_path)
    if bpy.types.Scene.hoTools_enableExIcon:
        bpy.ops.ho.draw_exicon()


cls = [OP_drawExIcon, OP_removeExIcon]

# endregion


def register():
    bpy.types.Scene.hoTools_enableExIcon = BoolProperty(default=True)
    bpy.app.handlers.load_post.append(loadExIcon)  # 在blender文件加载完毕后启用exIcon
    for i in cls:
        bpy.utils.register_class(i)


def unregister():
    del bpy.types.Scene.hoTools_enableExIcon
    bpy.app.handlers.load_post.remove(loadExIcon)
    for i in cls:
        bpy.utils.unregister_class(i)
