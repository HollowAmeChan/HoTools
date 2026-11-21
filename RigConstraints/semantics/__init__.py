"""Versioned ordinary constraint semantics, independent of UI and backends."""

from .translate import translate
from .aim import inspect_aim_pair

__all__ = ["translate", "inspect_aim_pair"]
