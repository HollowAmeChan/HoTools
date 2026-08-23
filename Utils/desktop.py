"""Cross-platform desktop operations delegated through Blender APIs."""

from __future__ import annotations

from os import PathLike
from typing import Callable


def copy_text(window_manager, text: str) -> None:
    """Write text through Blender's cross-platform clipboard property."""

    window_manager.clipboard = text


def open_path(
    filepath: str | PathLike[str],
    opener: Callable[..., set[str]],
) -> set[str]:
    """Open a path through Blender's platform-neutral path operator."""

    return opener(filepath=str(filepath))


__all__ = ["copy_text", "open_path"]
