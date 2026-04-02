from ...lib import glfw
from ...lib.pyglm import glm
from ...lib import OpenGL
from ...lib.OpenGL.GL import *
from ...lib.OpenGL.GL.shaders import compileProgram, compileShader
import bpy
from bpy.types import NodeTree
from math import *
from ctypes import windll, Structure, c_long, byref
import numpy as np
from typing import Any


def getMousePosition() -> tuple[int, int]:
    """获取鼠标显示器位置"""
    class POINT(Structure):
        _fields_ = [("x", c_long), ("y", c_long)]
    pt = POINT()
    windll.user32.GetCursorPos(byref(pt))
    return pt.x, pt.y


"""拖动窗口使用的全局变量"""
window_drag_active: int = 0  # 窗口是否正在被拖动
cursor_pos_x: float = 0  # 拖动前x
cursor_pos_y: float = 0  # 拖动前y
delta_x: float = 0  # 拖动x变换
delta_y: float = 0  # 拖动y变换


def mouseCallback_dragWindow(window, button: int, action: int, mods: int):
    """鼠标回调-左键拖动窗口移动"""
    global window_drag_active, cursor_pos_x, cursor_pos_y  # 使用全局/引用传入
    if (button == glfw.MOUSE_BUTTON_LEFT and action == glfw.PRESS):
        window_drag_active = 1
        x, y = glfw.get_cursor_pos(window)
        cursor_pos_x = floor(x)
        cursor_pos_y = floor(y)
    if (button == glfw.MOUSE_BUTTON_LEFT and action == glfw.RELEASE):
        window_drag_active = 0
    return


def keyCallback_escCloseWindow(window, key: int, scancode: int, action: int, mods: int):
    """键盘回调-esc关闭窗口"""
    if (key == glfw.KEY_ESCAPE and action == glfw.PRESS):
        glfw.set_window_should_close(window, glfw.TRUE)


def useShader(sharingData):
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


def setShader_iTime(sharingData: dict):
    """uniform float iTime;"""
    iTime = glfw.get_time()
    sharingData["iTime"] = iTime
    shaderProgram = sharingData.get("shaderProgram")
    if shaderProgram:
        iTimeLoc = glGetUniformLocation(shaderProgram, "iTime")
        glUniform1fv(iTimeLoc, 1, glm.value_ptr(glm.vec1(
            iTime)))
    return


def setShader_iResolution(sharingData: dict, window):
    "uniform vec3 iResolution;"
    iResolution = glfw.get_framebuffer_size(window)
    iResolution = [iResolution[0], iResolution[1], 0]
    sharingData["iResolution"] = iResolution
    shaderProgram = sharingData.get("shaderProgram")
    if shaderProgram:
        iResolutionLoc = glGetUniformLocation(shaderProgram, "iResolution")
        glUniform3fv(iResolutionLoc, 1, glm.value_ptr(glm.vec3(
            iResolution)))
    return


def setShader_iMouse(sharingData: dict, window):
    iMouse = (0, 0, 0, 0)
    shaderProgram = sharingData.get("shaderProgram")
    if shaderProgram:
        iMouseLoc = glGetUniformLocation(shaderProgram, "iMouse")
        glUniform4fv(iMouseLoc, 1, glm.value_ptr(glm.vec4(iMouse)))
    return


def setShader_iFrame(sharingData: dict):
    iFrame = 0
    shaderProgram = sharingData.get("shaderProgram")
    if shaderProgram:
        iFrameLoc = glGetUniformLocation(shaderProgram, "iFrame")
        glUniform1fv(iFrameLoc, 1, glm.value_ptr(glm.vec1(iFrame)))
    return


def glfwThread(nodeTree: NodeTree, context: bpy.types.Context, windowWidth: int, windowHeight: int):
    """GLFW窗口绘制线程"""
    # 初始化并创建窗口
    glfw.init()
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)  # 不要显示标题栏
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)  # 显示在最前
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, True)  # 支持透明buffer

    window = glfw.create_window(
        windowWidth, windowHeight, "OMNI Rendering Window", None, None)

    # 设置窗口上下文属性与回调
    glfw.make_context_current(window)
    print("OPENGL版本:", glGetString(GL_VERSION))
    mousePos = getMousePosition()                   # 初始鼠标位置
    glClearColor(0.2, 0.3, 0.3, 0.8)                # 背景颜色
    glEnable(GL_DEPTH_TEST)                         # 开启深度测试
    glDepthFunc(GL_LESS)                            # 深度测试-近的在上
    taskSharingData = {                             # 两种队列共享的数据,用于传递shaderProgram、vao
        "window": window,
        "tree": nodeTree,
        "GlslTaskList": nodeTree.GlslTaskList,
        "realVertexCount": 0,
        "vao": None,
        "vbo": None,
        "ebo": None,
        "shaderProgram": None,
        "iTime": 0,
        "iResolution": (0, 0, 0),
        "iMouse": (0, 0, 0, 0),
        "iFrame": 0,
    }
    """
    暂时同时只能存在一个vao,vbo,ebo,shaderProgram
    useShaderTask是只能缓存一个的使用shader的任务,单独执行,类型是GlRenderTask
    realVertexCount提供给shader的参数(渲染的面数)
    iTime:float           适配shadertoy运行时间iTime
    iResolution:vec3      适配shadertoy分辨率iResolution
    iMouse:vec4           适配shadertoy鼠标位置iMouseTODO:
    iFrame:float          适配shadertoy帧iFrameTODO:
    """

    glfw.set_window_pos(window, mousePos[0], mousePos[1])  # 设置初始窗口位置
    glfw.set_key_callback(window, keyCallback_escCloseWindow)  # 键盘回调
    glfw.set_mouse_button_callback(window, mouseCallback_dragWindow)  # 鼠标回调

    # 主循环
    while ((not glfw.window_should_close(window)) and (not nodeTree.glfwStopEvent.is_set())):

        glClear(GL_COLOR_BUFFER_BIT)  # 清空颜色缓冲区
        glClear(GL_DEPTH_BUFFER_BIT)  # 清空深度缓冲区

        useShader(taskSharingData)                      # 总使用着色器
        setShader_iTime(taskSharingData)                # iTime
        setShader_iResolution(taskSharingData, window)  # iResolution
        setShader_iMouse(taskSharingData, window)       # iMouse
        setShader_iFrame(taskSharingData)               # iFrame

        if nodeTree.GlslTaskList:  # 任务清单
            for task in nodeTree.GlslTaskList[:]:  # 拷贝列表防止remove错误
                # 传入sharingData,以修改sharingData
                task.process(taskSharingData)
                nodeTree.GlslTaskList.remove(task)

        # 更新窗口位置-配合drag回调
        global window_drag_active, cursor_pos_x, cursor_pos_y, delta_x, delta_y
        if (window_drag_active):
            xpos, ypos = glfw.get_cursor_pos(window)
            delta_x = xpos - cursor_pos_x
            delta_y = ypos - cursor_pos_y
            x, y = glfw.get_window_pos(window)
            glfw.set_window_pos(window, int(x+delta_x), int(y+delta_y))
        # 交换双缓冲
        glfw.poll_events()  # 启用监听
        glfw.swap_buffers(window)  # 交换双buffer
    glfw.terminate()

    if nodeTree.GlfwThread:
        del nodeTree.GlfwThread  # 销毁线程实例(线程关闭了,没有运行的实例还存在)
        nodeTree.GlfwThread = None
