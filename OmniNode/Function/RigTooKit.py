OMNI_NODE_REGISTRATION = {
    "category": {"id": "RIGTOOLKIT", "label": "绑定工具", "order": 120},
}

import bpy
from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob
from ..FunctionNodeCore import omni
from ..config import nodeColors


@omni(enable=True,
    bl_label="创建集合",
    base_color=nodeColors.colorCat["Operator"],
    omni_description="""
    在指定的父集合下创建一个集合
    如果没有则在活动场景下创建
    如果已经存在，则不创建，将其链接到输入集合/场景
    """,
    _INPUT_NAME = ["父集合","集合名称"],
    _OUTPUT_NAME = ["创建的集合"],
    )
def createCollection(LinkCollection: bpy.types.Collection, name: str) -> bpy.types.Collection:
    old = bpy.data.collections.get(name)
    if old:  # 已经存在就返回
        return old

    new_collection = bpy.data.collections.new(name)

    if not LinkCollection:  # 没就给父集合
        scene = bpy.context.scene
        scene.collection.children.link(new_collection)

    LinkCollection.children.link(new_collection)

    return new_collection
