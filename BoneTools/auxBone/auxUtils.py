"""Compatibility import for the BoneTools-wide preview utilities."""

try:
    from ..previewUtils import AuxPreviewUtils
except ImportError:
    from previewUtils import AuxPreviewUtils


__all__ = ("AuxPreviewUtils",)
