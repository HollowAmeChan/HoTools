"""Persistent ordinary constraint-group properties and their RNA dependencies."""

from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup


class PG_RigConstraintMember(PropertyGroup):
    constraintName: StringProperty(name="约束名称", default="")
    constraintType: StringProperty(name="预期约束类型", default="")
    role: StringProperty(name="成员角色", default="")
    order: IntProperty(name="组内顺序", default=0, min=0)


class PG_RigConstraintGroup(PropertyGroup):
    groupId: StringProperty(name="语义组 ID", default="")
    semanticType: StringProperty(name="语义类型", default="")
    semanticVersion: IntProperty(name="语义版本", default=1, min=1)
    generatorId: StringProperty(name="生成来源", default="")
    evidence: StringProperty(name="登记来源", default="GENERATED")
    ownsBone: BoolProperty(name="拥有生成骨", default=False,
                          description="仅生成器实际创建的骨可随辅助关系删除；接纳现有骨默认保留")
    members: CollectionProperty(name="成员约束", type=PG_RigConstraintMember)


# Register before PG_Hotools_BoneProps; unregister in reverse dependency order.
PROPERTY_CLASSES = (PG_RigConstraintMember, PG_RigConstraintGroup)
