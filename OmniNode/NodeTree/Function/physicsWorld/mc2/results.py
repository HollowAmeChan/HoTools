"""MC2 未来结果流的只读辅助函数。"""

from __future__ import annotations

from ..names import BONE_TRANSFORM_CHANNEL, GN_ATTRIBUTE_CHANNEL
from .names import MC2_SOLVER_ID, MC2_STATS_CHANNEL


def iter_mc2_results(world, channel: str | None = None):
    """只读取已有结果；框架阶段不会自行创建或发布结果。"""
    channels = (
        (str(channel),)
        if channel
        else (GN_ATTRIBUTE_CHANNEL, BONE_TRANSFORM_CHANNEL, MC2_STATS_CHANNEL)
    )
    consume = getattr(world, "consume_results", None)
    if not callable(consume):
        return iter(())

    def _iter():
        for result_channel in channels:
            yield from consume(result_channel, solver=MC2_SOLVER_ID)

    return _iter()
