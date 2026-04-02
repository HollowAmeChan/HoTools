from __future__ import annotations

import bpy
from ...lib import OpenGL
from ...lib import glfw
import time
from ...lib.OpenGL.GL import *
from ...lib.OpenGL.GL.shaders import compileProgram, compileShader
import bpy
import threading
from math import *
from ...lib.pyglm import glm
import numpy as np
from ...operator.NodeBaseOps import LoadGlslFile2BlenderTextData
from ..Base.OmniNode import OmniNode
from ..NodeSocket import OmniNodeSocketText, OmniNodeSocketGlslVertexList, OmniNodeSocketGlslVertexIndicesList, OmniNodeSocketGlslMat4x4
from bpy.types import NodeSocketColor, NodeSocketVector, UILayout, NodeTree, NodeSocketFloat, NodeSocketImage
from bpy.props import BoolProperty, PointerProperty, StringProperty, IntProperty
from typing import Any
import time


class GlRenderTask:
    def __init__(self, func, *args: tuple) -> None:
        """传入的函数,要么返回None,要么返回dict,第一个参数必须是sharingData"""
        self.func = func
        self.args: tuple = args

    def process(self, sharingData: dict):
        args: tuple = (sharingData, *self.args)
        func = self.func
        return func(*args)  # 是有返回值的


def treeUpdate(node, context):
    """
    node自身值改变不会引发tree更新回调,但socket可以
    故设置一个更新使其可以触发
    """
    tree: NodeTree = node["fatherTree"]
    tree.update()


def closeGlfwWindowUpdate(node, context):
    if (not node.closeGlfwWindow):
        return
    node.closeGlfwWindow = False  # 伪按钮
    # ---------------------关闭线程--------------------
    if not hasattr(bpy.context.space_data.node_tree, "glfwStopEvent"):
        return
    else:
        nodeTree = bpy.context.space_data.node_tree
        nodeTree.glfwStopEvent.set()  # 窗口关闭事件
        print("线程结束：", str(nodeTree.GlfwThread))
        del nodeTree.GlfwThread  # 销毁线程实例(旧线程关闭了,没有运行的实例还存在)
        nodeTree.GlfwThread = None  # 手动清除线程标记
        nodeTree.GlslTaskList.clear()
    return


def launchAndCompileUpdate(node, context):
    '''为什么使用模拟按钮而不用operator
    1.operator不能直接传递node,也不能用pointerproperty
    2.用[]的IDproperty很多type也不能存
    3.layout中缺少一个button类型(本质问题,他都不支持自家的类型,只能string查找)
    '''
    if (not node.launchAndCompile):
        return
    node.launchAndCompile = False
    # ---------------------创建线程--------------------
    import threading
    from threading import Thread
    from .GlfwThread import glfwThread
    nodeTree = bpy.context.space_data.node_tree

    # 有线程但是线程卡死了没有正常关闭-手动关闭-无法调用closeGlfwWindowUpdate(开关都无法触发)
    if nodeTree.GlfwThread != None and nodeTree.GlfwThread.is_alive() == False:
        print("线程结束：", str(nodeTree.GlfwThread))
        del nodeTree.GlfwThread  # 销毁线程实例(旧线程关闭了,没有运行的实例还存在)
        nodeTree.GlfwThread = None  # 手动清除线程标记
        nodeTree.GlslTaskList.clear()

    # 没有线程就启动线程
    if nodeTree.GlfwThread == None:
        nodeTree.GlslTaskList.clear()  # 手动清空之前空载时的任务
        nodeTree.glfwStopEvent = threading.Event()  # 使用glfwStopEvent来控制进程的关闭
        windowWidth = node.ImageSaveWidth
        windowHeight = node.ImageSaveHeight
        thread = Thread(target=glfwThread,
                        args=(nodeTree, context, windowWidth, windowHeight))
        nodeTree.GlfwThread = thread  # 手动标记线程
        thread.start()  # 线程运行

    # 是输出节点就手动编译并且刷新树以获得正确的输入
    if node.is_output_node:
        node.forceCompileShader()
        nodeTree.update()  # 编译完shader了再发一遍mvp等任务
    return


def saveWindow2ImageUpdate(node, context):
    if (not node.saveWindow2Image):
        return
    node.saveWindow2Image = False
    # ---------------------图像保存--------------------
    nodeTree = bpy.context.space_data.node_tree
    # 线程正在运行时
    if nodeTree.GlfwThread.is_alive() == True:
        node.saveImage()
    return


class GlslCodeRenderNode(OmniNode):
    bl_label = "Glsl渲染输出"
    bl_idname = "HO_OmniNode_GlslCodeRenderNode"

    closeGlfwWindow: BoolProperty(
        name="关闭窗口", update=closeGlfwWindowUpdate, default=False)  # type: ignore
    launchAndCompile: BoolProperty(
        name="唤起/编译", update=launchAndCompileUpdate, default=False)  # type: ignore
    saveWindow2Image: BoolProperty(
        name="截帧保存", update=saveWindow2ImageUpdate, default=False)  # type: ignore

    ImageSaveName: StringProperty(
        name="保存到图像的名称", default="Omni_RenderOutput")  # type: ignore
    ImageSaveWidth: IntProperty(
        name="保存到图像宽", description="同时影响视窗大小", default=1024)  # type: ignore
    ImageSaveHeight: IntProperty(
        name="保存到图像高", description="同时影响视窗大小", default=1024)  # type: ignore

    def init(self, context):
        super().init(context)
        self.is_output_node = True
        self.default_width = 400
        self.size2default()  # 更新自己的大小
        self.inputs.new(NodeSocketColor.__name__,
                        name="背景颜色",
                        identifier="glClearColor")
        self.inputs.new(OmniNodeSocketText.__name__,
                        name="GLSL顶点shader",
                        identifier="vertex_shader")
        self.inputs.new(OmniNodeSocketText.__name__,
                        name="GLSL片段shader",
                        identifier="fragment_shader")
        self.inputs.new(OmniNodeSocketGlslVertexList.__name__,
                        name="顶点",
                        identifier="vertices")
        self.inputs.new(OmniNodeSocketGlslVertexIndicesList.__name__,
                        name="面索引",
                        identifier="indices")
        self.inputs.new(OmniNodeSocketGlslMat4x4.__name__,
                        name="M矩阵",
                        identifier="model")
        self.inputs.new(OmniNodeSocketGlslMat4x4.__name__,
                        name="V矩阵",
                        identifier="view")
        self.inputs.new(OmniNodeSocketGlslMat4x4.__name__,
                        name="P矩阵",
                        identifier="projection")

        self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        super().draw_buttons(context, layout)
        col = layout.column_flow(columns=1, align=True)  # 大盒子
        row = col.row(align=True)  # 第一行
        row.operator(LoadGlslFile2BlenderTextData.bl_idname, text="载入默认shader")
        row.prop(self, "closeGlfwWindow",
                 text="关闭窗口", toggle=True)
        row.prop(self, "launchAndCompile",
                 text="唤起/编译", toggle=True,
                 icon="CON_TRANSFORM_CACHE")
        row.prop(self, "saveWindow2Image",
                 text="截帧保存", toggle=True)

        col.prop(self, "ImageSaveName",  # 第二行
                 text="保存名")

        row = col.row(align=True)  # 第三行
        row.prop(self, "ImageSaveWidth", text="")
        row.prop(self, "ImageSaveHeight", text="")

    def compileShader(self, sharingData: dict, vertex_shader: str, fragment_shader: str):
        """
        编译一个shader存进线程-单次运行
        VertexPosition显存类型: GL_STATIC_DRAW
        TriangleIndex显存类型:  GL_STATIC_DRAW
        """
        shaderProgram = compileProgram(compileShader(vertex_shader, GL_VERTEX_SHADER),
                                       compileShader(fragment_shader, GL_FRAGMENT_SHADER))
        dic = {"shaderProgram": shaderProgram}
        sharingData.update(dic)
        return

    def create_VAO_VBO_EBO_Bind(self, sharingData: dict, vertices: np.ndarray, indices: np.ndarray):
        """
        使用顶点与面索引构建vao、vbo、ebo存进线程-单次运行
        vbo、ebo更新时感觉需要重新绑定,测试了不行
        """
        vao = sharingData["vao"]
        vbo = sharingData["vbo"]
        ebo = sharingData["ebo"]

        vao = glGenVertexArrays(1)
        vbo = glGenBuffers(1)
        ebo = glGenBuffers(1)  # buffer类型空对象
        realVertexCount = len(indices)
        glBindVertexArray(vao)  # -------VAO链接区(引用绑定)--------
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.itemsize * len(vertices),
                     vertices, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.itemsize * realVertexCount,
                     indices, GL_STATIC_DRAW)
        # 注入顶点位置并启用-vao配置
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE,
                              vertices.itemsize * 3, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glBindVertexArray(0)    # ------------VAO修改区-------------

        dic = {"vao": vao, "vbo": vbo, "ebo": ebo,
               "realVertexCount": realVertexCount}
        sharingData.update(dic)
        return

    def useShaderOneTimeOnly(self, sharingData: dict):
        """用于编译shader后没有及时use,补充一个单次运行的task"""
        shaderProgram = sharingData.get("shaderProgram")
        vao = sharingData.get("vao")
        realVertexCount = sharingData.get("realVertexCount")
        if shaderProgram and vao and realVertexCount:
            glUseProgram(shaderProgram)
            # 渲染立方体-抓vao渲染
            glBindVertexArray(vao)
            glDrawElements(GL_TRIANGLES, realVertexCount, GL_UNSIGNED_INT,
                           None)  # realVertexCount是涉及到的顶点数量 = 三角面*3
            glBindVertexArray(0)  # 解绑

    def clear_VAO_VBO_EBO(self, sharingData: dict):
        """
        退出渲染时清空vao-单次运行
        vao、vbo、ebo不建议频繁删除,因为删除也耗费性能
        """
        vao = sharingData["vao"]
        vbo = sharingData["vbo"]
        ebo = sharingData["ebo"]

        glDeleteVertexArrays(1, vao)
        glDeleteBuffers(1, vbo)
        glDeleteBuffers(1, ebo)
        return

    def setMVPtransform(self, sharingData: dict, moudelMat: glm.mat4x4, viewMat: glm.mat4x4, projectionMat: glm.mat4x4):
        shaderProgram = sharingData.get("shaderProgram")
        # 获取shader参数位置
        modelLoc = glGetUniformLocation(shaderProgram, "model")
        viewLoc = glGetUniformLocation(shaderProgram, "view")
        projLoc = glGetUniformLocation(shaderProgram, "projection")
        # 变换载入到shader参数
        glUniformMatrix4fv(modelLoc, 1, GL_FALSE, glm.value_ptr(moudelMat))
        glUniformMatrix4fv(viewLoc, 1, GL_FALSE, glm.value_ptr(viewMat))
        glUniformMatrix4fv(projLoc, 1, GL_FALSE,
                           glm.value_ptr(projectionMat))
        return

    def readPixelsSave2Image(self, shadingData: dict, bl_image: bpy.types.Image):
        window = shadingData.get("window")
        if not window:
            return
        width, height = glfw.get_framebuffer_size(window)
        glPixelStorei(GL_PACK_ALIGNMENT, 4)
        glReadBuffer(GL_FRONT)
        data = glReadPixels(0, 0, width, height, GL_RGBA, GL_FLOAT)
        data_array = np.frombuffer(data, dtype=np.float32)
        data_array = data_array.reshape((height, width, 4))
        # nowTime = time.time()
        # bl_image.pixels = data_array.flatten()
        # print("截帧保存使用时间: {:.6f} seconds".format(time.time()-nowTime))
        nowTime = time.time()
        bl_image.pixels.foreach_set(data_array.ravel())
        print("截帧保存使用时间: {:.6f} seconds".format(time.time()-nowTime))
        return

    def setWindowSize(self, sharingData: dict, new_width: int, new_height: int):
        window = sharingData.get("window")
        if not window:
            return
        glfw.set_window_size(window, new_width, new_height)

    def forceCompileShader(self):
        """使用ops来调用的强制编译shader"""
        cls = []
        inputs = self["fatherTree"].pool[self.name].inputs
        taskList: list = self["fatherTree"].GlslTaskList

        color = tuple(inputs["glClearColor"])
        colorFixed: glm.vec3 = glm.pow(
            glm.vec3(color), glm.vec3(1/2.2))  # 伽马矫正

        vertices = inputs["vertices"]
        indices = inputs["indices"]

        vertex_shader = inputs["vertex_shader"] if type(inputs["vertex_shader"]) == str else inputs["vertex_shader"].as_string()
        fragment_shader = inputs["fragment_shader"] if type(inputs["fragment_shader"]) == str else inputs["fragment_shader"].as_string()

        new_width = self.ImageSaveWidth
        new_height = self.ImageSaveHeight

        def _glClearColor(sharingData: dict, *args):  # GlRenderTask.func必须要传入sharingData
            glClearColor(*args)

        cls.append(
            GlRenderTask(_glClearColor,
                         colorFixed.x, colorFixed.y, colorFixed.z, 1.0))
        cls.append(
            GlRenderTask(self.setWindowSize,
                         new_width, new_height))
        cls.append(
            GlRenderTask(self.compileShader,
                         vertex_shader, fragment_shader))
        cls.append(
            GlRenderTask(self.create_VAO_VBO_EBO_Bind,
                         vertices, indices))
        cls.append(
            GlRenderTask(self.useShaderOneTimeOnly
                         ))

        taskList.extend(cls)

    def saveImage(self):
        cls = []
        taskList: list = self["fatherTree"].GlslTaskList

        saveImageName = self.ImageSaveName
        saveImageWidth = self.ImageSaveWidth
        saveImageHeight = self.ImageSaveHeight

        saveImage = bpy.data.images.get(saveImageName)

        # 如果存在但尺寸不对 → 删除
        if saveImage and (saveImageWidth, saveImageHeight) != saveImage.size[:]:
            bpy.data.images.remove(saveImage)
            saveImage = None

        # 如果不存在 → 创建
        if not saveImage:
            bpy.ops.image.new(
                name=saveImageName,
                width=saveImageWidth,
                height=saveImageHeight,
                color=(0, 0, 0, 1),
                alpha=True
            )
            saveImage = bpy.data.images[saveImageName]

        cls.append(
            GlRenderTask(self.readPixelsSave2Image, saveImage)
        )

        taskList.extend(cls)

    def process(self):
        super().process()
        # pool中的数据,使用socket的identifier查找
        inputs = self["fatherTree"].pool[self.name].inputs
        taskList: list = self["fatherTree"].GlslTaskList
        # ---------创建渲染任务------
        cls = []
        # 改变背景颜色(一次)
        color = tuple(inputs["glClearColor"])
        colorFixed: glm.vec3 = glm.pow(
            glm.vec3(color), glm.vec3(1/2.2))  # 伽马矫正

        vertices = inputs["vertices"]
        indices = inputs["indices"]
        model = inputs["model"]
        view = inputs["view"]
        projection = inputs["projection"]
        new_width = self.ImageSaveWidth
        new_height = self.ImageSaveHeight

        def _glClearColor(sharingData: dict, *args):  # 必须要传入sharingData
            glClearColor(*args)

        cls.append(
            GlRenderTask(self.setWindowSize,
                         new_width, new_height))
        cls.append(
            GlRenderTask(_glClearColor,
                         colorFixed.x, colorFixed.y, colorFixed.z, 1.0))
        cls.append(
            GlRenderTask(self.create_VAO_VBO_EBO_Bind,
                         vertices, indices))
        cls.append(
            GlRenderTask(self.setMVPtransform,
                         model, view, projection))
        # ---------发送渲染任务------
        taskList.extend(cls)


class GlslSimpleScreen(OmniNode):
    bl_label = "Glsl屏幕"
    bl_idname = "HO_OmniNode_GlslSimpleScreen"

    def init(self, context):
        super().init(context)
        self.outputs.new(OmniNodeSocketGlslVertexList.__name__,
                         name="顶点",
                         identifier="vertex")
        self.outputs.new(OmniNodeSocketGlslVertexIndicesList.__name__,
                         name="面索引",
                         identifier="indices")
        self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

    def draw_buttons(self, context, layout: UILayout):
        super().draw_buttons(context, layout)

    def process(self):
        super().process()
        # pool中的数据,使用socket的identifier查找
        pool = self["fatherTree"].pool
        vertices = [-1.0, -1.0, 0.0,
                    1.0, -1.0, 0.0,
                    1.0,  1.0, 0.0,
                    -1.0,  1.0, 0.0,]
        vertices = np.array(vertices, dtype=np.float32)

        indices = np.array([
            0, 1, 2,
            2, 3, 0
        ], dtype=np.uint32)
        pool[self.name].outputs["vertex"] = vertices
        pool[self.name].outputs["indices"] = indices

class DebugShader(OmniNode):
    bl_label = "DebugShader"
    bl_idname = "HO_OmniNode_GlslDebugShader"

    def init(self, context):
        super().init(context)
        self.outputs.new(OmniNodeSocketText.__name__,
                         name="顶点shader",
                         identifier="vertex_shader")
        self.outputs.new(OmniNodeSocketText.__name__,
                         name="片元shader",
                         identifier="fragment_shader")
        self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

    def process(self):
        super().process()
        # pool中的数据,使用socket的identifier查找
        pool = self["fatherTree"].pool
        vertex_shader = """
        #version 330 core
        layout (location = 0) in vec3 aPos;
        out vec3 worldPos; //输出世界坐标

        uniform mat4 model;
        uniform mat4 view;
        uniform mat4 projection;

        void main()
        {
        gl_Position = projection * view * model * vec4(aPos, 1.0);
        worldPos = vec3(model * vec4(aPos, 1.0)); 
        }
        """
        fragment_shader = """
        #version 330 core
        in vec3 worldPos;//传入世界坐标
        out vec4 FragColor;
        void main()
        {
        //FragColor = vec4(1.0f, 1.0f, 1.0f, 1.0f);
        FragColor = vec4(worldPos.x, worldPos.y, worldPos.z, 1.0);// 坐标颜色
        }
        """

        pool[self.name].outputs["vertex_shader"] = vertex_shader
        pool[self.name].outputs["fragment_shader"] = fragment_shader


class GlslSimpleCube(OmniNode):
    bl_label = "Glsl方块"
    bl_idname = "HO_OmniNode_GlslSimpleCube"

    def init(self, context):
        super().init(context)
        self.outputs.new(OmniNodeSocketGlslVertexList.__name__,
                         name="顶点",
                         identifier="vertex")
        self.outputs.new(OmniNodeSocketGlslVertexIndicesList.__name__,
                         name="面索引",
                         identifier="indices")
        self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

    def draw_buttons(self, context, layout: UILayout):
        super().draw_buttons(context, layout)

    def process(self):
        super().process()
        # pool中的数据,使用socket的identifier查找
        pool = self["fatherTree"].pool
        vertices = np.array([
            -0.5, -0.5, -0.5,
            0.5, -0.5, -0.5,
            0.5,  0.5, -0.5,
            -0.5,  0.5, -0.5,
            -0.5, -0.5,  0.5,
            0.5, -0.5,  0.5,
            0.5,  0.5,  0.5,
            -0.5,  0.5,  0.5
        ], dtype=np.float32)
        indices = np.array([
            # 右面
            1, 5, 6,
            6, 2, 1,
            # 左面
            4, 0, 3,
            7, 4, 3,
            # 顶面
            3, 2, 6,
            3, 6, 7,
            # 底面
            4, 5, 1,
            1, 0, 4,
            # 后面
            4, 6, 5,
            4, 7, 6,
            # 前面
            0, 2, 1,
            2, 3, 0,
        ], dtype=np.uint32)

        pool[self.name].outputs["vertex"] = vertices
        pool[self.name].outputs["indices"] = indices


class GlslSimpleMVPgenerator(OmniNode):
    bl_label = "GlslMVP矩阵生成器"
    bl_idname = "HO_OmniNode_GlslSimpleMVPgenerator"

    is_M_unit_matrix: BoolProperty(
        name="M矩阵单位矩阵", default=False)  # type: ignore
    is_V_unit_matrix: BoolProperty(
        name="V矩阵单位矩阵", default=False)  # type: ignore
    is_P_unit_matrix: BoolProperty(
        name="P矩阵单位矩阵", default=False)  # type: ignore

    def init(self, context):
        super().init(context)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="位置",
                                                identifier="translation")
        skt.default_value = (0, 0, 0)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="旋转",
                                                identifier="rotate")
        skt.default_value = (0, 0, 0)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="缩放",
                                                identifier="scale")
        skt.default_value = (1, 1, 1)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="摄像机位置",
                                                identifier="cameraTranslation")
        skt.default_value = (0, 0, -3)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="摄像机旋转",
                                                identifier="cameraRotate")
        skt.default_value = (0, 0, 0)
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="yFOV",
                                                identifier="yFOV")
        skt.default_value = 45
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="比例",
                                                identifier="aspect")
        skt.default_value = 1
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="裁剪最近",
                                                identifier="near")
        skt.default_value = 0.1
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="裁剪最远",
                                                identifier="far")
        skt.default_value = 100
        self.outputs.new(OmniNodeSocketGlslMat4x4.__name__,
                         name="M矩阵",
                         identifier="model")
        self.outputs.new(OmniNodeSocketGlslMat4x4.__name__,
                         name="V矩阵",
                         identifier="view")
        self.outputs.new(OmniNodeSocketGlslMat4x4.__name__,
                         name="P矩阵",
                         identifier="projection")
        self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

    def process(self):
        super().process()
        # pool中的数据,使用socket的identifier查找
        pool = self["fatherTree"].pool
        _translation = pool[self.name].inputs["translation"]
        translation = glm.vec3(
            _translation[0],
            _translation[1],
            _translation[2])
        _rotate = pool[self.name].inputs["rotate"]
        rotationAngles = glm.vec3(
            glm.radians(_rotate[0]),
            glm.radians(_rotate[1]),
            glm.radians(_rotate[2]))
        _scale = pool[self.name].inputs["scale"]
        scale = glm.vec3(
            _scale[0],
            _scale[1],
            _scale[2])
        model = glm.mat4(1.0)
        model = glm.scale(model, scale)
        model = glm.rotate(model, rotationAngles.z, glm.vec3(0, 0, 1))
        model = glm.rotate(model, rotationAngles.y, glm.vec3(0, 1, 0))
        model = glm.rotate(model, rotationAngles.x, glm.vec3(1, 0, 0))
        model = glm.translate(model, translation)

        view = glm.mat4(1.0)
        _cameraRotate = pool[self.name].inputs["cameraRotate"]
        cameraRotationAngles = glm.vec3(
            glm.radians(_cameraRotate[0]),
            glm.radians(_cameraRotate[1]),
            glm.radians(_cameraRotate[2]))
        _cameraTranslation = pool[self.name].inputs["cameraTranslation"]
        cameraTranslation = glm.vec3(
            _cameraTranslation[0],
            _cameraTranslation[1],
            _cameraTranslation[2])
        view = glm.rotate(view, cameraRotationAngles.z, glm.vec3(0, 0, 1))
        view = glm.rotate(view, cameraRotationAngles.y, glm.vec3(0, 1, 0))
        view = glm.rotate(view, cameraRotationAngles.x, glm.vec3(1, 0, 0))
        view = glm.translate(view, cameraTranslation)

        projection = glm.mat4(1.0)
        _yFOV = pool[self.name].inputs["yFOV"]
        _aspect = pool[self.name].inputs["aspect"]
        _near = pool[self.name].inputs["near"]
        _far = pool[self.name].inputs["far"]
        projection = glm.perspective(glm.radians(
            _yFOV), _aspect, _near, _far)

        if self.is_M_unit_matrix:
            pool[self.name].outputs["model"] = glm.mat4(1.0)
        else:
            pool[self.name].outputs["model"] = model
        if self.is_V_unit_matrix:
            pool[self.name].outputs["view"] = glm.mat4(1.0)
        else:
            pool[self.name].outputs["view"] = view
        if self.is_P_unit_matrix:
            pool[self.name].outputs["projection"] = glm.mat4(1.0)
        else:
            pool[self.name].outputs["projection"] = projection

    def draw_buttons(self, context, layout: UILayout):
        super().draw_buttons(context, layout)
        row = layout.row()
        row.prop(self, "is_M_unit_matrix", text="unit_M?")
        row.prop(self, "is_V_unit_matrix", text="unit_V?")
        row.prop(self, "is_P_unit_matrix", text="unit_P?")


class DebugTreeGlslThread(OmniNode):
    bl_label = "Debug-查看树渲染线程"
    bl_idname = "HO_OmniNode_DebugTreeGlslThread"

    def init(self, context):
        super().init(context)
        self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

    def draw_buttons(self, context, layout: UILayout):
        super().draw_buttons(context, layout)
        tree = self["fatherTree"]
        tree: NodeTree
        GlslTaskList = tree.GlslTaskList
        GlslThread = tree.GlfwThread
        pool = tree.pool
        doing_initNode = tree.doing_initNode
        layout.label(text="Omni树:"+tree.name)
        layout.label(text="doing_initNode:"+str(doing_initNode))
        layout.label(text="GlslThread:    "+str(GlslThread))
        layout.label(text="线程数量:    "+str(threading.active_count()))

        layout.separator()
        layout.label(text="GlslTaskList:  ")
        for task in GlslTaskList:
            task: GlRenderTask
            layout.label(text=task.func.__name__)
        layout.separator()

        layout.label(text="SharingData:   ")

        layout.label(text="Pool:          ")


class DebugFullSimpleCube(OmniNode):
    bl_label = "Debug-Glsl方块"
    bl_idname = "HO_OmniNode_DebugFullSimpleCube"

    vertex_down1: bpy.props.FloatVectorProperty(
        name="底左下", default=(-0.5, -0.5, -0.5), update=treeUpdate)  # type: ignore
    vertex_down3: bpy.props.FloatVectorProperty(
        name="底右下", default=(0.5, -0.5, -0.5,), update=treeUpdate)  # type: ignore
    vertex_down7: bpy.props.FloatVectorProperty(
        name="底左上", default=(0.5,  0.5, -0.5,), update=treeUpdate)  # type: ignore
    vertex_down9: bpy.props.FloatVectorProperty(
        name="底右上", default=(-0.5,  0.5, -0.5,), update=treeUpdate)  # type: ignore

    vertex_up1: bpy.props.FloatVectorProperty(
        name="顶左下", default=(-0.5, -0.5,  0.5,), update=treeUpdate)  # type: ignore
    vertex_up3: bpy.props.FloatVectorProperty(
        name="顶右下", default=(0.5, -0.5,  0.5,), update=treeUpdate)  # type: ignore
    vertex_up7: bpy.props.FloatVectorProperty(
        name="顶左上", default=(0.5,  0.5,  0.5,), update=treeUpdate)  # type: ignore
    vertex_up9: bpy.props.FloatVectorProperty(
        name="顶右上", default=(-0.5,  0.5,  0.5), update=treeUpdate)  # type: ignore

    def init(self, context):
        super().init(context)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="位置",
                                                identifier="translation")
        skt.default_value = (0, 0, 0)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="旋转",
                                                identifier="rotate")
        skt.default_value = (0, 0, 0)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="缩放",
                                                identifier="scale")
        skt.default_value = (1, 1, 1)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="摄像机位置",
                                                identifier="cameraTranslation")
        skt.default_value = (0, 0, -3)
        skt: NodeSocketVector = self.inputs.new(NodeSocketVector.__name__,
                                                name="摄像机旋转",
                                                identifier="cameraRotate")
        skt.default_value = (0, 0, 0)
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="yFOV",
                                                identifier="yFOV")
        skt.default_value = 45
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="比例",
                                                identifier="aspect")
        skt.default_value = 1
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="裁剪最近",
                                                identifier="near")
        skt.default_value = 0.1
        skt: NodeSocketVector = self.inputs.new(NodeSocketFloat.__name__,
                                                name="裁剪最远",
                                                identifier="far")
        skt.default_value = 100

        self.outputs.new(OmniNodeSocketGlslVertexList.__name__,
                         name="顶点",
                         identifier="vertex")
        self.outputs.new(OmniNodeSocketGlslVertexIndicesList.__name__,
                         name="面索引",
                         identifier="indices")
        self.outputs.new(OmniNodeSocketGlslMat4x4.__name__,
                         name="M矩阵",
                         identifier="model")
        self.outputs.new(OmniNodeSocketGlslMat4x4.__name__,
                         name="V矩阵",
                         identifier="view")
        self.outputs.new(OmniNodeSocketGlslMat4x4.__name__,
                         name="P矩阵",
                         identifier="projection")
        self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

    def draw_buttons(self, context, layout: UILayout):
        super().draw_buttons(context, layout)
        layout.prop(self, "vertex_down1", text="")
        layout.prop(self, "vertex_down3", text="")
        layout.prop(self, "vertex_down7", text="")
        layout.prop(self, "vertex_down9", text="")
        layout.separator()
        layout.prop(self, "vertex_up1", text="")
        layout.prop(self, "vertex_up3", text="")
        layout.prop(self, "vertex_up7", text="")
        layout.prop(self, "vertex_up9", text="")

    def process(self):
        super().process()
        # pool中的数据,使用socket的identifier查找
        pool = self["fatherTree"].pool
        vertices = []
        vg = [self.vertex_down1, self.vertex_down3,
              self.vertex_down7, self.vertex_down9,
              self.vertex_up1, self.vertex_up3,
              self.vertex_up7, self.vertex_up9]
        for v in vg:
            vertices.extend(v[:])
        vertices = np.array(vertices, dtype=np.float32)

        indices = np.array([
            # 右面
            1, 5, 6,
            6, 2, 1,
            # 左面
            4, 0, 3,
            7, 4, 3,
            # 顶面
            3, 2, 6,
            3, 6, 7,
            # 底面
            4, 5, 1,
            1, 0, 4,
            # 后面
            4, 6, 5,
            4, 7, 6,
            # 前面
            0, 2, 1,
            2, 3, 0,
        ], dtype=np.uint32)

        _translation = pool[self.name].inputs["translation"]
        translation = glm.vec3(
            _translation[0],
            _translation[1],
            _translation[2])
        _rotate = pool[self.name].inputs["rotate"]
        rotationAngles = glm.vec3(
            glm.radians(_rotate[0]),
            glm.radians(_rotate[1]),
            glm.radians(_rotate[2]))
        _scale = pool[self.name].inputs["scale"]
        scale = glm.vec3(
            _scale[0],
            _scale[1],
            _scale[2])
        model = glm.mat4(1.0)
        model = glm.scale(model, scale)
        model = glm.rotate(model, rotationAngles.z, glm.vec3(0, 0, 1))
        model = glm.rotate(model, rotationAngles.y, glm.vec3(0, 1, 0))
        model = glm.rotate(model, rotationAngles.x, glm.vec3(1, 0, 0))
        model = glm.translate(model, translation)

        view = glm.mat4(1.0)
        _cameraRotate = pool[self.name].inputs["cameraRotate"]
        cameraRotationAngles = glm.vec3(
            glm.radians(_cameraRotate[0]),
            glm.radians(_cameraRotate[1]),
            glm.radians(_cameraRotate[2]))
        _cameraTranslation = pool[self.name].inputs["cameraTranslation"]
        cameraTranslation = glm.vec3(
            _cameraTranslation[0],
            _cameraTranslation[1],
            _cameraTranslation[2])
        view = glm.rotate(view, cameraRotationAngles.z, glm.vec3(0, 0, 1))
        view = glm.rotate(view, cameraRotationAngles.y, glm.vec3(0, 1, 0))
        view = glm.rotate(view, cameraRotationAngles.x, glm.vec3(1, 0, 0))
        view = glm.translate(view, cameraTranslation)

        projection = glm.mat4(1.0)
        _yFOV = pool[self.name].inputs["yFOV"]
        _aspect = pool[self.name].inputs["aspect"]
        _near = pool[self.name].inputs["near"]
        _far = pool[self.name].inputs["far"]
        projection = glm.perspective(glm.radians(
            _yFOV), _aspect, _near, _far)

        pool[self.name].outputs["vertex"] = vertices
        pool[self.name].outputs["indices"] = indices
        pool[self.name].outputs["model"] = model
        pool[self.name].outputs["view"] = view
        pool[self.name].outputs["projection"] = projection


cls = [GlslCodeRenderNode,
       GlslSimpleScreen,
       GlslSimpleCube,
       GlslSimpleMVPgenerator,
       DebugTreeGlslThread,
       DebugFullSimpleCube,
       DebugShader]
