from typing import Set
import bpy
import os
from bpy.props import BoolProperty, StringProperty
from bpy.types import Context


class NodeSetDefaultSize(bpy.types.Operator):
    bl_idname = "ho.nodesetdefaultsize"  # 注册到bpy.ops下
    bl_label = "恢复node默认大小"

    node_name: bpy.props.StringProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            node = bpy.context.space_data.node_tree.nodes[self.node_name]
            node.size2default()

            return {'FINISHED'}
        except:
            return {'FINISHED'}


class NodeSetBiggerSize(bpy.types.Operator):
    bl_idname = "ho.nodesetbiggersize"  # 注册到bpy.ops下
    bl_label = "加宽node"

    node_name: bpy.props.StringProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            node = bpy.context.space_data.node_tree.nodes[self.node_name]
            node.width *= 2

            return {'FINISHED'}
        except:
            return {'FINISHED'}


class LayerRunning(bpy.types.Operator):
    bl_idname = "ho.layerrunning"
    bl_label = "树手动触发回调"
    reportInfo: BoolProperty(name="报告pool信息", default=True)  # type: ignore

    def execute(self, context: bpy.types.Context):  # TODO:最好用调用的方式
        if (not hasattr(context.space_data, "node_tree")) or (not context.space_data.node_tree):
            return {'FINISHED'}
        tree = context.space_data.node_tree
        if self.reportInfo:
            tree.reportPool()
        tree.OmniInit()
        tree.run()  # 无视是否自动更新
        return {'FINISHED'}


class LoadGlslFile2BlenderTextData(bpy.types.Operator):
    bl_idname = "ho.loadglslfile2blendertextdata"
    bl_label = "从默认文件夹加载glsl文件进入blender"

    # 从绝对路径添加默认glsl代码
    def GlslFile_2_BlenderTextData(self, file_path):  # 绝对路径
        with open(file_path, 'r') as file:
            glsl_code = file.read()
            name = os.path.basename(file_path)
            bl_textData = bpy.data.texts.get(name)
            if bl_textData:  # 如果存在就先清空
                bl_textData.clear()
            else:  # 不存在就新建
                bl_textData = bpy.data.texts.new(name)
            bl_textData.write(glsl_code)

    # 获得路径文件夹下的所有文件的绝对路径
    def get_files_in_directory(self, directory):  # 相对路径文件夹
        file_paths = []
        script_dir = os.path.dirname(os.path.realpath(__file__))
        full_path = os.path.join(script_dir, directory)
        files = os.listdir(full_path)
        for file in files:
            file_path = os.path.join(full_path, file)
            if os.path.isfile(file_path):
                file_paths.append(file_path)
        return file_paths

    def execute(self, context: bpy.types.Context):
        DefaultGlsl_foldPath = "..\\NodeTree\\GlslNode\\DefaultGlsl\\"  # 上一级目录
        file_paths = self.get_files_in_directory(DefaultGlsl_foldPath)
        print(file_paths)
        for path in file_paths:
            self.GlslFile_2_BlenderTextData(path)

        return {'FINISHED'}


clss = [NodeSetDefaultSize, NodeSetBiggerSize, LayerRunning, LoadGlslFile2BlenderTextData
        ]


def register():
    try:
        for i in clss:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__+" register failed!!!")


def unregister():
    try:
        for i in clss:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__+" unregister failed!!!")
