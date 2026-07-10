"""统一 MC2 solver 的三种 setup task 节点和安全空模拟步。"""

import typing

from ....FunctionNodeCore import omni
from ... import _Color
from ..types import PhysicsWorldCache
from .names import (
    MC2_SETUP_BONE_CLOTH,
    MC2_SETUP_BONE_SPRING,
    MC2_SETUP_MESH_CLOTH,
)
from .solver import step_mc2
from .specs import make_mc2_task_spec


def _task(setup_type: str, sources, enabled: bool):
    return [
        make_mc2_task_spec(
            setup_type,
            sources,
            enabled=enabled,
        )
    ]


@omni(
    enable=True,
    bl_label="MC2 MeshCloth任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["代理网格", "启用"],
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2MeshClothTask(
    sources: list[typing.Any],
    enabled: bool = True,
) -> list[typing.Any]:
    return _task(MC2_SETUP_MESH_CLOTH, sources, enabled)


@omni(
    enable=True,
    bl_label="MC2 BoneCloth任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "启用"],
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2BoneClothTask(
    sources: list[typing.Any],
    enabled: bool = True,
) -> list[typing.Any]:
    return _task(MC2_SETUP_BONE_CLOTH, sources, enabled)


@omni(
    enable=True,
    bl_label="MC2 BoneSpring任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "启用"],
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2BoneSpringTask(
    sources: list[typing.Any],
    enabled: bool = True,
) -> list[typing.Any]:
    return _task(MC2_SETUP_BONE_SPRING, sources, enabled)


@omni(
    enable=True,
    bl_label="MC2模拟步（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "MC2任务", "启用"],
    _OUTPUT_NAME=["物理世界", "就绪", "状态"],
    mute_passthrough={"_OUTPUT0": "world"},
)
def physicsMC2Step(
    world: PhysicsWorldCache,
    mc2_tasks: list[typing.Any],
    enabled: bool = True,
) -> tuple[PhysicsWorldCache, bool, str]:
    return step_mc2(world, mc2_tasks, enabled=enabled)
