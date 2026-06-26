"""Select the active MC2 solver backend."""

from __future__ import annotations

from .. import solver


def normalize_backend_label(solver_backend: str | None) -> str:
    return "cpp" if str(solver_backend).lower() in {"cpp", "native", "native_core"} else "py"


def solver_for_backend(backend_label: str):
    return solver.solve_meshcloth_native_core if backend_label == "cpp" else solver.solve_meshcloth
