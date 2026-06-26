"""MC2 solver backend adapters."""

from .selector import normalize_backend_label, solver_for_backend

__all__ = [
    "normalize_backend_label",
    "solver_for_backend",
]
