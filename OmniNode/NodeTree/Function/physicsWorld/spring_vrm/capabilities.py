"""SpringBone solver 私有能力与更新频率。

Bone collision schema 已提升到 physicsWorld.collision；本模块只兼容重导出共享
能力，并保留 SpringBone 自己的更新频率声明。
"""

from __future__ import annotations

from ..collision.capabilities import (
    BONE_COLLISION_CAPABILITY,
    BONE_COLLISION_CAPABILITY_ID,
    audit_bone_collision_property_group,
    bone_collision_capability_field_names,
    bone_collision_capability_fields,
)
from .names import SPRING_VRM_CHAIN_OBJECT_TAG


# SpringBone 不再拥有共享 collision capability。
SPRING_VRM_CAPABILITIES = {}


SPRING_VRM_UPDATE_FREQUENCY_TABLE = [
    {
        "data": "帧 / dt",
        "source": "PhysicsWorldCache.frame_context",
        "policy": "every_frame",
    },
    {
        "data": "骨链根骨骼 / 骨骼列表",
        "source": f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        "policy": "implicit_object_dirty",
    },
    {
        "data": "刚度 / 阻尼 / 重力",
        "source": f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        "policy": "implicit_object_dirty",
    },
    {
        "data": "姿态 head / tail / 父级目标姿态",
        "source": "PoseBone 每帧输入",
        "policy": "every_frame",
    },
    {
        "data": "当前尾端 / 上一帧尾端",
        "source": "slot.data.frame_state",
        "policy": "every_frame_mutate_in_place",
    },
    {
        "data": "初始轴向 / 旋转 / 缩放",
        "source": "slot.data.native_context 静态数组",
        "policy": "restart_only",
    },
    {
        "data": "父级索引 / 连接骨骼标记",
        "source": "骨架拓扑",
        "policy": "topology_dirty",
    },
    {
        "data": "bone_collision.pin",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "restart_only",
    },
    {
        "data": "bone_collision.radius -> hit_radii",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "dirty_only_or_restart_only",
    },
    {
        "data": "bone_collision.collided_by_groups",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "dirty_only_or_restart_only",
    },
    {
        "data": "bone_collision.collision_type/length/offset/primary_collision_group",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "override_version_or_world_collider_snapshot_frame",
    },
    {
        "data": "物体 / 骨骼碰撞体",
        "source": "PhysicsWorldCache.collider_snapshot",
        "policy": "every_frame_by_world_begin",
    },
    {
        "data": "碰撞体数组（SpringBone context API）",
        "source": "solver slot 懒构建碰撞体数组缓存",
        "policy": "lazy_on_access",
    },
    {
        "data": "写回计划 / basis foreach 缓冲区",
        "source": "slot.data.writeback_plan",
        "policy": "topology_dirty_or_restart_only_allocation",
    },
]


__all__ = [
    "BONE_COLLISION_CAPABILITY",
    "BONE_COLLISION_CAPABILITY_ID",
    "SPRING_VRM_CAPABILITIES",
    "SPRING_VRM_UPDATE_FREQUENCY_TABLE",
    "audit_bone_collision_property_group",
    "bone_collision_capability_field_names",
    "bone_collision_capability_fields",
]
