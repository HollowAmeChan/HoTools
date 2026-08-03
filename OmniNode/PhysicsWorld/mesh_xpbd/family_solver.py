"""单一 XPBD 模拟步对 Mesh/Bone 显式域任务的调度。"""

from __future__ import annotations

import time

from ..bone_xpbd.names import (
    BONE_XPBD_SLOT_KIND,
    BONE_XPBD_SOLVER_ID,
    BONE_XPBD_STATS_CHANNEL,
)
from ..bone_xpbd.results import clear_bone_xpbd_writeback_results
from ..bone_xpbd.solver import step_bone_xpbd
from ..bone_xpbd.specs import BoneXpbdTaskSpec, build_bone_xpbd_task_specs
from ..types import PhysicsWorldCache
from .names import (
    MESH_XPBD_SLOT_KIND,
    MESH_XPBD_SOLVER_ID,
    MESH_XPBD_STATS_CHANNEL,
)
from .results import clear_mesh_xpbd_writeback_results
from .solver import step_mesh_xpbd
from .specs import MeshXpbdTaskSpec, build_mesh_xpbd_task_specs


_FAMILY_FAILURE_WRITER_ID = "xpbd_family.step.failure"


def _flatten_tasks(values) -> tuple[object, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if type(value) is float and value == 0.0:
            continue
        result.append(value)
    return tuple(result)


def split_xpbd_tasks(values):
    """在任何 solver mutation 前完成强类型分域和各域重复校验。"""

    mesh_tasks = []
    bone_tasks = []
    invalid = []
    for value in _flatten_tasks(values):
        if isinstance(value, MeshXpbdTaskSpec):
            mesh_tasks.append(value)
        elif isinstance(value, BoneXpbdTaskSpec):
            bone_tasks.append(value)
        else:
            invalid.append(type(value).__name__)
    if invalid:
        raise TypeError(
            "XPBD模拟步只接受XPBD网格任务或Bone XPBD任务，"
            f"收到: {', '.join(invalid)}"
        )
    return (
        build_mesh_xpbd_task_specs(mesh_tasks),
        build_bone_xpbd_task_specs(bone_tasks),
    )


def _discard_xpbd_family_state(world) -> None:
    world.acquire_write(_FAMILY_FAILURE_WRITER_ID)
    try:
        clear_mesh_xpbd_writeback_results(world)
        clear_bone_xpbd_writeback_results(world)
        world.clear_results(MESH_XPBD_STATS_CHANNEL, solver=MESH_XPBD_SOLVER_ID)
        world.clear_results(BONE_XPBD_STATS_CHANNEL, solver=BONE_XPBD_SOLVER_ID)
        removed = False
        for slot_id, slot in list(world.solver_slots.items()):
            if slot.kind not in {MESH_XPBD_SLOT_KIND, BONE_XPBD_SLOT_KIND}:
                continue
            world.solver_slots.pop(slot_id, None)
            slot.dispose("xpbd_family_step_failed")
            removed = True
        if removed:
            world.replace_required = True
    finally:
        world.release_write(_FAMILY_FAILURE_WRITER_ID)


def step_xpbd_tasks(
    world: PhysicsWorldCache,
    task_values,
    *,
    debug_capture: bool = False,
) -> tuple[int, float]:
    """推进两种 XPBD 域；空域也执行，以清理上一次活动 slot。"""

    if not isinstance(world, PhysicsWorldCache):
        return 0, 0.0
    started = time.perf_counter()
    try:
        mesh_tasks, bone_tasks = split_xpbd_tasks(task_values)
        mesh_count, _mesh_ms = step_mesh_xpbd(
            world,
            mesh_tasks,
            debug_capture=debug_capture,
        )
        bone_count, _bone_ms = step_bone_xpbd(
            world,
            bone_tasks,
            debug_capture=debug_capture,
        )
        return mesh_count + bone_count, (time.perf_counter() - started) * 1000.0
    except Exception:
        _discard_xpbd_family_state(world)
        raise


__all__ = ["split_xpbd_tasks", "step_xpbd_tasks"]
