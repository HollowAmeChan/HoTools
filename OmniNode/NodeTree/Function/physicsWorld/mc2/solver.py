"""统一 MC2 模拟步的框架占位实现。"""

from __future__ import annotations

from .parameters import (
    MC2SolverSettingsSpec,
    make_mc2_effective_parameters,
    make_mc2_solver_settings,
)
from .specs import build_mc2_task_specs


MC2_FRAMEWORK_STATUS = (
    "MC2 Physics World 框架已就绪；MeshCloth、BoneCloth、BoneSpring 后端尚未接入"
)


def step_mc2(
    world,
    tasks=None,
    *,
    settings: MC2SolverSettingsSpec | None = None,
    enabled: bool = True,
) -> tuple[object, bool, str]:
    """安全空运行：不创建 slot、不发布结果、不调用任何旧 MC2 backend。"""
    specs = build_mc2_task_specs(tasks)
    if settings is None:
        settings = make_mc2_solver_settings()
    if not isinstance(settings, MC2SolverSettingsSpec):
        raise TypeError("settings 必须是 MC2SolverSettingsSpec")
    # 现在只冻结未来 solver 会接收的输入；不创建任何运行状态。
    effective_parameters = tuple(
        make_mc2_effective_parameters(spec.profile, settings, spec.setup_options)
        for spec in specs
        if spec.enabled and spec.sources
    )
    if not enabled:
        return world, False, "MC2 模拟步已禁用"
    active_count = len(effective_parameters)
    status = f"{MC2_FRAMEWORK_STATUS}（有效任务 {active_count}）"
    return world, False, status
