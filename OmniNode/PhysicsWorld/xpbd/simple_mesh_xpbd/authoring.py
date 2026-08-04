"""Mesh XPBD 对象快照到独立 source task 的组装边界。"""

from __future__ import annotations

from .object_spec import MeshXpbdObjectSpec
from .specs import MeshXpbdTaskSpec, build_mesh_xpbd_task_specs


def _flatten_object_specs(values) -> tuple[MeshXpbdObjectSpec, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, MeshXpbdObjectSpec):
            raise TypeError(
                "XPBD网格任务只接受XPBD网格对象或XPBD网格自定义对象的输出"
            )
        result.append(value)
    return tuple(result)


def make_mesh_xpbd_tasks(
    mesh_objects,
    *,
    collision_enabled: bool = False,
    collision_radius: float = 0.05,
    damping: float = 0.02,
    stretch_compliance: float = 0.0,
    bend_compliance: float = 0.001,
    iterations: int = 6,
    gravity_direction=(0.0, 0.0, -1.0),
    gravity_power: float = 9.8,
) -> tuple[MeshXpbdTaskSpec, ...]:
    """把对象字段与任务级数值参数组合成每 source 一个 runtime task。"""

    tasks = []
    for mesh_object in _flatten_object_specs(mesh_objects):
        properties = mesh_object.properties
        tasks.append(MeshXpbdTaskSpec(
            source_object=mesh_object.source_object,
            enabled=True,
            pin_enabled=properties.pin_enabled,
            pin_vertex_group=properties.pin_vertex_group,
            collision_enabled=collision_enabled,
            collision_radius=collision_radius,
            radius_vertex_group=properties.radius_vertex_group,
            collided_by_groups=properties.collided_by_groups,
            damping=damping,
            stretch_compliance=stretch_compliance,
            bend_compliance=bend_compliance,
            iterations=iterations,
            gravity_direction=gravity_direction,
            gravity_power=gravity_power,
        ))
    return build_mesh_xpbd_task_specs(tasks)


__all__ = ["make_mesh_xpbd_tasks"]
