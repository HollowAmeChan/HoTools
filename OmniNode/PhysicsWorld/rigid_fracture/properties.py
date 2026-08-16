"""Persistent Source and Piece properties for explicit rigid-fracture assets."""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class PG_Hotools_RigidFracture(PropertyGroup):
    """Source object fracture asset configuration."""

    enabled: BoolProperty(
        name="启用刚体破碎",
        description="排除本体，并将链接集合中的受管碎块加入刚体模拟",
        default=False,
    )
    asset_id: StringProperty(name="资产 ID", default="")
    schema_version: IntProperty(name="Schema", default=1, min=1, options={"HIDDEN"})
    modifier_name: StringProperty(name="几何节点修改器", default="")
    piece_id_attribute: StringProperty(name="碎块 ID 属性", default="hotools_piece_id")
    split_mode: EnumProperty(
        name="拆分方式",
        items=(("CONNECTED_COMPONENT", "连通块", "按 evaluated mesh 的不连通面岛拆成独立物体"),),
        default="CONNECTED_COMPONENT",
    )
    product_collection: PointerProperty(name="产物集合", type=bpy.types.Collection)
    product_revision: IntProperty(name="产物版本", default=0, min=0)
    product_status: EnumProperty(
        name="产物状态",
        items=(
            ("EMPTY", "未生成", "尚无可模拟碎块"),
            ("READY", "可用", "产物与当前 manifest 一致"),
            ("OUTDATED", "需刷新", "生成器或本体已更改"),
            ("ERROR", "错误", "上次刷新失败"),
        ),
        default="EMPTY",
    )
    product_fingerprint: StringProperty(name="产物指纹", default="", options={"HIDDEN"})
    last_error: StringProperty(name="诊断", default="")
    piece_body_type: EnumProperty(
        name="新碎块类型",
        items=(
            ("DYNAMIC", "动态", "新碎块作为动态刚体"),
            ("STATIC", "静态", "新碎块作为静态刚体"),
        ),
        default="DYNAMIC",
    )
    piece_mass: FloatProperty(name="新碎块质量", default=1.0, min=0.001, soft_max=1000.0)
    piece_friction: FloatProperty(name="新碎块摩擦", default=0.5, min=0.0, max=1.0)
    piece_restitution: FloatProperty(name="新碎块弹性", default=0.0, min=0.0, max=1.0)
    piece_start_deactivated: BoolProperty(
        name="新碎块初始停用",
        description="新动态碎块等待碰撞或显式命令唤醒",
        default=True,
    )
    piece_breakable: BoolProperty(name="新碎块可破碎", default=True)


class PG_Hotools_RigidFracturePiece(PropertyGroup):
    """Managed identity; physical parameters remain on hotools_rigid_body."""

    managed: BoolProperty(name="受管碎块", default=False)
    owner_asset_id: StringProperty(name="Owner Asset ID", default="")
    piece_id: StringProperty(name="Piece ID", default="")
    product_revision: IntProperty(name="Product Revision", default=0, min=0)
    breakable: BoolProperty(name="可破碎", default=True)


RIGID_FRACTURE_BLENDER_PROPERTIES = {
    "classes": (PG_Hotools_RigidFracture, PG_Hotools_RigidFracturePiece),
    "bindings": (
        {
            "owner": bpy.types.Object,
            "name": "hotools_rigid_fracture",
            "property": "pointer",
            "type": PG_Hotools_RigidFracture,
        },
        {
            "owner": bpy.types.Object,
            "name": "hotools_rigid_fracture_piece",
            "property": "pointer",
            "type": PG_Hotools_RigidFracturePiece,
        },
    ),
}


__all__ = [
    "PG_Hotools_RigidFracture",
    "PG_Hotools_RigidFracturePiece",
    "RIGID_FRACTURE_BLENDER_PROPERTIES",
]
