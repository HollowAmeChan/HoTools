"""Lazy import boundaries for optional HoTools binary dependencies."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable

from .runtime_platform import (
    RuntimeTarget,
    configure_runtime_paths,
    resolve_runtime_target,
)


Importer = Callable[[str], Any]


class OptionalDependencyError(RuntimeError):
    """Expected dependency import failure qualified by runtime target."""

    def __init__(
        self,
        dependency: str,
        module_name: str,
        target: RuntimeTarget,
        cause: BaseException,
    ) -> None:
        self.dependency = dependency
        self.module_name = module_name
        self.target = target
        self.cause = cause
        super().__init__(
            f"Dependency {dependency} ({module_name}) is unavailable for "
            f"{target.abi} on {target.platform_id}; expected under "
            f"{target.dependency_dir}: {cause}"
        )


def current_runtime_target() -> RuntimeTarget:
    """Resolve the target for this HoTools checkout and interpreter."""

    addon_root = Path(__file__).resolve().parents[1]
    return resolve_runtime_target(addon_root)


class LazyOptionalModule:
    """Module proxy that imports once on first actual use."""

    def __init__(
        self,
        module_name: str,
        dependency: str,
        target: RuntimeTarget,
        importer: Importer = importlib.import_module,
    ) -> None:
        self.module_name = module_name
        self.dependency = dependency
        self.target = target
        self._importer = importer
        self._module: Any | None = None
        self._error: OptionalDependencyError | None = None

    def require(self) -> Any:
        """Return the module or raise a stable qualified error."""

        if self._module is not None:
            return self._module
        if self._error is not None:
            raise self._error
        try:
            self._module = self._importer(self.module_name)
        except (ImportError, OSError) as exc:
            self._error = OptionalDependencyError(
                self.dependency,
                self.module_name,
                self.target,
                exc,
            )
            raise self._error from exc
        return self._module

    def is_available(self) -> bool:
        """Return false only for an expected dependency load failure."""

        try:
            self.require()
        except OptionalDependencyError:
            return False
        return True

    def __getattr__(self, name: str) -> Any:
        return getattr(self.require(), name)


def optional_module(
    module_name: str,
    dependency: str,
    target: RuntimeTarget | None = None,
) -> LazyOptionalModule:
    """Create a lazy module proxy for the current or supplied target."""

    resolved_target = target or current_runtime_target()
    return LazyOptionalModule(module_name, dependency, resolved_target)


def import_native_module(
    module_name: str,
    target: RuntimeTarget | None = None,
    override_env: str = "HOTOOLS_NATIVE_TEST_DIR",
) -> ModuleType:
    """Import a native module using test override or target runtime paths."""

    resolved_target = target or current_runtime_target()
    override = os.environ.get(override_env)
    if override:
        override_path = str(Path(override))
        if override_path not in sys.path:
            sys.path.insert(0, override_path)
    else:
        configure_runtime_paths(resolved_target)
    return LazyOptionalModule(
        module_name,
        module_name,
        resolved_target,
    ).require()


__all__ = [
    "LazyOptionalModule",
    "OptionalDependencyError",
    "current_runtime_target",
    "import_native_module",
    "optional_module",
]
