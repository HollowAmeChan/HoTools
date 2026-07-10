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


def _task(setup_type: str, sources, enabled: bool, backend: int):
    backend_name = ("auto", "python", "cpp")[max(0, min(2, int(backend)))]
    return [
        make_mc2_task_spec(
            setup_type,
            sources,
            enabled=enabled,
            backend=backend_name,
        )
    ]


_TASK_INPUT_INIT = {
    "backend": {
        "min_value": 0,
        "max_value": 2,
        "description": "0=Auto, 1=Python参考后端, 2=C++后端；backend 不改变 solver 身份",
    },
}


@omni(
    enable=True,
    bl_label="MC2 MeshCloth任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["代理网格", "启用", "后端"],
    input_init=_TASK_INPUT_INIT,
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2MeshClothTask(
    sources: list[typing.Any],
    enabled: bool = True,
    backend: int = 0,
) -> list[typing.Any]:
    return _task(MC2_SETUP_MESH_CLOTH, sources, enabled, backend)


@omni(
    enable=True,
    bl_label="MC2 BoneCloth任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "启用", "后端"],
    input_init=_TASK_INPUT_INIT,
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2BoneClothTask(
    sources: list[typing.Any],
    enabled: bool = True,
    backend: int = 0,
) -> list[typing.Any]:
    return _task(MC2_SETUP_BONE_CLOTH, sources, enabled, backend)


@omni(
    enable=True,
    bl_label="MC2 BoneSpring任务（框架）",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨链", "启用", "后端"],
    input_init=_TASK_INPUT_INIT,
    _OUTPUT_NAME=["MC2任务"],
)
def physicsMC2BoneSpringTask(
    sources: list[typing.Any],
    enabled: bool = True,
    backend: int = 0,
) -> list[typing.Any]:
    return _task(MC2_SETUP_BONE_SPRING, sources, enabled, backend)


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
