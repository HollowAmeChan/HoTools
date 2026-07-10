"""MC2 未来结果流的只读辅助函数。"""

from __future__ import annotations

from .names import (
    MC2_BONE_RESULT_CHANNEL,
    MC2_MESH_RESULT_CHANNEL,
    MC2_STATS_CHANNEL,
)


def iter_mc2_results(world, channel: str | None = None):
    """只读取已有结果；框架阶段不会自行创建或发布结果。"""
    channels = (
        (str(channel),)
        if channel
        else (MC2_MESH_RESULT_CHANNEL, MC2_BONE_RESULT_CHANNEL, MC2_STATS_CHANNEL)
    )
    iterator = getattr(world, "iter_results", None)
    if not callable(iterator):
        return iter(())

    def _iter():
        for result_channel in channels:
            yield from iterator(result_channel)

    return _iter()
