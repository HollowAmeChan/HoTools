"""简单布料 Blender owner 与受管资源的公共准备边界。"""

from __future__ import annotations

from dataclasses import dataclass

import bpy

from ..utils.blender_scene import is_live_blender_id, resolve_object_scene
from .base_pose import (
    ensure_base_pose_proxy,
    ensure_generated_base_pose_proxy,
    mesh_topology_signature,
    validate_base_pose_proxy,
)
from .output import ensure_gn_offset_output


@dataclass(frozen=True, slots=True)
class SimpleClothRuntimeResources:
    source_object: bpy.types.Object
    scene: bpy.types.Scene
    base_pose_proxy: bpy.types.Object | None
    base_pose_created: bool
    gn_output_ready: bool


def _require_mesh_object(source_object) -> None:
    if (
        not is_live_blender_id(source_object)
        or not isinstance(source_object, bpy.types.Object)
        or source_object.type != "MESH"
        or not is_live_blender_id(source_object.data)
    ):
        raise ValueError("简单布料资源只能绑定到有效 Mesh 对象")
    if int(getattr(source_object.data, "users", 0) or 0) != 1:
        raise ValueError(
            "简单布料 source Mesh 必须是单用户数据；公共GN offset不能写入共享Mesh"
        )


def flatten_simple_cloth_objects(values) -> tuple[bpy.types.Object, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        _require_mesh_object(value)
        result.append(value)
    return tuple(result)


def ensure_simple_cloth_resources(
    source_object: bpy.types.Object,
    *,
    scene: bpy.types.Scene | None = None,
    require_base_pose: bool = False,
    base_pose_proxy: bpy.types.Object | None = None,
    persist_base_pose_reference: bool = False,
) -> SimpleClothRuntimeResources:
    """在对象/适配层准备 Blender 资源；solver step 不得调用。"""
    _require_mesh_object(source_object)
    target_scene = resolve_object_scene(
        source_object,
        scene,
        purpose="简单布料 Source",
    )
    ensure_gn_offset_output(source_object)

    base_obj = None
    created = False
    if require_base_pose:
        expected = mesh_topology_signature(source_object)
        if persist_base_pose_reference:
            base_obj = ensure_base_pose_proxy(
                source_object,
                target_scene,
                expected_mesh_topology_signature=expected,
            )
            properties = getattr(source_object, "hotools_mesh_collision", None)
            if properties is None:
                raise ValueError("简单布料属性没有注册到 source 对象")
            properties.mc2_base_pose_proxy = base_obj
        elif base_pose_proxy is None:
            base_obj, created = ensure_generated_base_pose_proxy(
                source_object,
                target_scene,
                expected,
            )
        else:
            validate_base_pose_proxy(source_object, base_pose_proxy, expected)
            base_obj = base_pose_proxy

    return SimpleClothRuntimeResources(
        source_object=source_object,
        scene=target_scene,
        base_pose_proxy=base_obj,
        base_pose_created=created,
        gn_output_ready=True,
    )


def prepare_simple_cloth_panel_objects(
    values,
    *,
    require_base_pose: bool = False,
) -> tuple[SimpleClothRuntimeResources, ...]:
    resources = []
    for source_object in flatten_simple_cloth_objects(values):
        properties = getattr(source_object, "hotools_mesh_collision", None)
        if properties is None:
            raise ValueError("Mesh Object 没有注册 hotools_mesh_collision 属性")
        if not bool(getattr(properties, "enabled", False)):
            continue
        resources.append(ensure_simple_cloth_resources(
            source_object,
            require_base_pose=require_base_pose,
            base_pose_proxy=getattr(properties, "mc2_base_pose_proxy", None),
            persist_base_pose_reference=require_base_pose,
        ))
    return tuple(resources)


def prepare_simple_cloth_custom_objects(
    values,
    *,
    require_base_pose: bool = False,
    base_pose_proxy: bpy.types.Object | None = None,
) -> tuple[SimpleClothRuntimeResources, ...]:
    return tuple(
        ensure_simple_cloth_resources(
            source_object,
            require_base_pose=require_base_pose,
            base_pose_proxy=base_pose_proxy,
            persist_base_pose_reference=False,
        )
        for source_object in flatten_simple_cloth_objects(values)
    )


__all__ = [
    "SimpleClothRuntimeResources",
    "ensure_simple_cloth_resources",
    "flatten_simple_cloth_objects",
    "prepare_simple_cloth_custom_objects",
    "prepare_simple_cloth_panel_objects",
]
