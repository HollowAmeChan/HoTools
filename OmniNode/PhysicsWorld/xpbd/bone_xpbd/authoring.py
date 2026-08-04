"""Bone XPBD 对象到任务的显式装配。"""

from __future__ import annotations

from .object_spec import BoneXpbdObjectSpec
from .specs import BoneXpbdTaskSpec, build_bone_xpbd_task_specs


def make_bone_xpbd_tasks(bone_objects, **parameters) -> tuple[BoneXpbdTaskSpec, ...]:
    pending = [bone_objects]
    tasks = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        if not isinstance(value, BoneXpbdObjectSpec):
            raise TypeError("Bone XPBD 任务只接受 Bone XPBD对象输出")
        tasks.append(BoneXpbdTaskSpec(value, **parameters))
    return build_bone_xpbd_task_specs(tasks)


__all__ = ["make_bone_xpbd_tasks"]
