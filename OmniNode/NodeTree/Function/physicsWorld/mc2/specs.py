"""三种 MC2 setup 共用的稳定任务规格。"""

from __future__ import annotations

from dataclasses import dataclass

from .names import (
    MC2_BACKEND_AUTO,
    MC2_BACKENDS,
    MC2_SETUP_TYPES,
)


def normalize_mc2_setup_type(value: object) -> str:
    setup_type = str(value or "").strip().lower()
    if setup_type not in MC2_SETUP_TYPES:
        raise ValueError(f"未知 MC2 setup_type: {value!r}")
    return setup_type


def normalize_mc2_backend(value: object) -> str:
    backend = str(value or MC2_BACKEND_AUTO).strip().lower()
    if backend not in MC2_BACKENDS:
        raise ValueError(f"未知 MC2 backend: {value!r}")
    return backend


def _normalize_sources(values) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (list, tuple, set)):
        return tuple(value for value in values if value is not None)
    return (values,)


@dataclass(frozen=True)
class MC2TaskSpec:
    """MC2 step 的统一输入；setup adapter 只负责生成本规格。"""

    setup_type: str
    sources: tuple[object, ...]
    enabled: bool = True
    backend: str = MC2_BACKEND_AUTO
    implementation_version: int = 0

    def debug_dict(self) -> dict:
        return {
            "setup_type": self.setup_type,
            "source_count": len(self.sources),
            "enabled": self.enabled,
            "backend": self.backend,
            "implementation_version": self.implementation_version,
        }


def make_mc2_task_spec(
    setup_type: object,
    sources,
    *,
    enabled: bool = True,
    backend: object = MC2_BACKEND_AUTO,
) -> MC2TaskSpec:
    return MC2TaskSpec(
        setup_type=normalize_mc2_setup_type(setup_type),
        sources=_normalize_sources(sources),
        enabled=bool(enabled),
        backend=normalize_mc2_backend(backend),
    )


def build_mc2_task_specs(values) -> tuple[MC2TaskSpec, ...]:
    if values is None:
        return ()
    pending = values if isinstance(values, (list, tuple, set)) else (values,)
    return tuple(value for value in pending if isinstance(value, MC2TaskSpec))
