"""Rigid/Jolt 解算器声明。"""

from __future__ import annotations

from ..declarations import RIGID_SOLVER_DECLARATION


def rigid_declaration_debug_dict() -> dict:
    return {
        "declaration": dict(RIGID_SOLVER_DECLARATION),
    }
