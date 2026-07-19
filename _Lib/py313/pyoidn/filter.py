"""Filter wrapper.

This module provides a minimal wrapper around OIDN filters.

Filters are created from a :class:`pyoidn.device.Device`, then configured by
setting images and parameters, and finally committed/executed.

Typical usage:

.. code-block:: python

        import numpy as np
        import pyoidn

        result = np.zeros_like(color, dtype=np.float32)
        with pyoidn.Device() as device:
                device.commit()
                with pyoidn.Filter(device, pyoidn.OIDN_FILTER_TYPE_RT) as flt:
                        flt.set_image(pyoidn.OIDN_IMAGE_COLOR, color, pyoidn.OIDN_FORMAT_FLOAT3)
                        flt.set_image(pyoidn.OIDN_IMAGE_OUTPUT, result, pyoidn.OIDN_FORMAT_FLOAT3)
                        flt.commit()
                        flt.execute()

        assert device.get_error() is None

Notes
-----
- Image inputs can be passed either as NumPy arrays (shared host memory) or as
    :class:`pyoidn.buffer.Buffer` instances (OIDN buffers).
- Error handling: check :meth:`pyoidn.device.Device.get_error` after operations.
- Refer to https://github.com/RenderKit/oidn?tab=readme-ov-file#filters for the OIDN property settings.
"""

from .capi import oidn_Capi
from .device import Device
from .buffer import Buffer
from .utils import c_str, np2c_ptr, TORCH_AVAILABLE
import numpy as np
from typing import Any

OIDN_FORMAT_UNDEFINED = 0

OIDN_FORMAT_FLOAT = 1
OIDN_FORMAT_FLOAT2 = OIDN_FORMAT_FLOAT + 1
OIDN_FORMAT_FLOAT3 = OIDN_FORMAT_FLOAT + 2
OIDN_FORMAT_FLOAT4 = OIDN_FORMAT_FLOAT + 3

OIDN_FORMAT_HALF = 257
OIDN_FORMAT_HALF2 = OIDN_FORMAT_HALF + 1
OIDN_FORMAT_HALF3 = OIDN_FORMAT_HALF + 2
OIDN_FORMAT_HALF4 = OIDN_FORMAT_HALF + 3

OIDN_QUALITY_DEFAULT = 0
OIDN_QUALITY_FAST = 4
OIDN_QUALITY_BALANCED = 5
OIDN_QUALITY_HIGH = 6

OIDN_IMAGE_COLOR = "color"
OIDN_IMAGE_ALBEDO = "albedo"
OIDN_IMAGE_NORMAL = "normal"
OIDN_IMAGE_OUTPUT = "output"

OIDN_FILTER_TYPE_RT = "RT"
OIDN_FILTER_TYPE_RT_LIGHTMAP = "RTLightmap"

__all__ = [
    "Filter",
    "OIDN_FORMAT_UNDEFINED",
    "OIDN_FORMAT_FLOAT",
    "OIDN_FORMAT_FLOAT2",
    "OIDN_FORMAT_FLOAT3",
    "OIDN_FORMAT_FLOAT4",
    "OIDN_FORMAT_HALF",
    "OIDN_FORMAT_HALF2",
    "OIDN_FORMAT_HALF3",
    "OIDN_FORMAT_HALF4",
    "OIDN_QUALITY_DEFAULT",
    "OIDN_QUALITY_FAST",
    "OIDN_QUALITY_BALANCED",
    "OIDN_QUALITY_HIGH",
    "OIDN_IMAGE_COLOR",
    "OIDN_IMAGE_ALBEDO",
    "OIDN_IMAGE_NORMAL",
    "OIDN_IMAGE_OUTPUT",
    "OIDN_FILTER_TYPE_RT",
    "OIDN_FILTER_TYPE_RT_LIGHTMAP",
]


class Filter:
    """OIDN filter.

    :param device: The owning :class:`pyoidn.device.Device`.
    :param filter_type:
        Filter type string (e.g. ``OIDN_FILTER_TYPE_RT``). See OIDN docs for supported
        filter types.
    """

    def __init__(self, device: Device, filter_type: str = OIDN_FILTER_TYPE_RT) -> None:
        """Create a filter."""
        self._device = device
        self._filter = oidn_Capi.oidnNewFilter(device._device, c_str(filter_type))

    def set_image(
        self,
        name: str,
        data: Any,
        data_format: int,
        width: int = -1,
        height: int = -1,
        byte_offset: int = 0,
        pixel_byte_stride: int = 0,
        row_byte_stride: int = 0,
    ) -> None:
        """Set an input/output image.

        When ``data`` is a NumPy array, this calls OIDN's shared-image API
        (``oidnSetSharedFilterImage``). When ``data`` is a :class:`pyoidn.buffer.Buffer`,
        it uses the buffer-based API (``oidnSetFilterImage``).

        :param name:
            Image slot name. Common values are:
            ``OIDN_IMAGE_COLOR``, ``OIDN_IMAGE_ALBEDO``, ``OIDN_IMAGE_NORMAL``,
            ``OIDN_IMAGE_OUTPUT``.
        :param data:
            NumPy array (host memory), :class:`pyoidn.buffer.Buffer` or
            ``torch.Tensor`` (if PyTorch is available). The array/tensor must be contiguous.
        :param data_format:
            One of ``OIDN_FORMAT_*`` (e.g. ``OIDN_FORMAT_FLOAT3``).
        :param width:
            Image width. If ``data`` is a NumPy array and this is negative, width is
            derived from ``data.shape[1]``.
        :param height:
            Image height. If ``data`` is a NumPy array and this is negative, height is
            derived from ``data.shape[0]``.
        :param byte_offset: Byte offset into the buffer/pointer.
        :param pixel_byte_stride:
            Bytes between consecutive pixels. Use 0 to let OIDN assume tightly packed
            pixels.
        :param row_byte_stride:
            Bytes between consecutive rows. Use 0 to let OIDN assume tightly packed
            rows.
        """
        if isinstance(data, Buffer):
            oidn_Capi.oidnSetFilterImage(
                self._filter,
                c_str(name),
                data._buffer,
                data_format,
                width,
                height,
                byte_offset,
                pixel_byte_stride,
                row_byte_stride,
            )
        elif isinstance(data, np.ndarray):
            oidn_Capi.oidnSetSharedFilterImage(
                self._filter,
                c_str(name),
                np2c_ptr(data),
                data_format,
                data.shape[1] if width < 0 else width,
                data.shape[0] if height < 0 else height,
                byte_offset,
                pixel_byte_stride,
                row_byte_stride,
            )
        elif TORCH_AVAILABLE:
            import torch
            from .torch_utils import torch2c_ptr

            if isinstance(data, torch.Tensor):
                oidn_Capi.oidnSetSharedFilterImage(
                    self._filter,
                    c_str(name),
                    torch2c_ptr(data),
                    data_format,
                    data.shape[1] if width < 0 else width,
                    data.shape[0] if height < 0 else height,
                    byte_offset,
                    pixel_byte_stride,
                    row_byte_stride,
                )
        else:
            raise TypeError(f"Unsupported image type: {type(data)}")

    def unset_image(self, name: str):
        """Unset an input/output image.

        :param name: Image slot name.
        """
        oidn_Capi.oidnUnsetFilterImage(self._filter, c_str(name))

    def get_bool(self, name: str) -> bool:
        """Get a boolean filter parameter."""
        return bool(oidn_Capi.oidnGetFilterBool(self._filter, c_str(name)))

    def set_bool(self, name: str, value: bool):
        """Set a boolean filter parameter."""
        oidn_Capi.oidnSetFilterBool(self._filter, c_str(name), value)

    def get_int(self, name: str) -> int:
        """Get an integer filter parameter."""
        return oidn_Capi.oidnGetFilterInt(self._filter, c_str(name))

    def set_int(self, name: str, value: int):
        """Set an integer filter parameter."""
        oidn_Capi.oidnSetFilterInt(self._filter, c_str(name), value)

    def get_float(self, name: str) -> float:
        """Get a float filter parameter."""
        return oidn_Capi.oidnGetFilterFloat(self._filter, c_str(name))

    def set_float(self, name: str, value: float):
        """Set a float filter parameter."""
        oidn_Capi.oidnSetFilterFloat(self._filter, c_str(name), value)

    def set_value(self, k: str, value):
        """Convenience setter that dispatches based on Python type."""
        if isinstance(value, int):
            self.set_int(k, value)
        elif isinstance(value, bool):
            self.set_bool(k, value)
        elif isinstance(value, float):
            self.set_float(k, value)
        else:
            raise TypeError("Unsupported value type: {}".format(type(value)))

    def set_quality(self, quality: int):
        """Set the filter quality level.

        :param quality: One of ``OIDN_QUALITY_*``.
        """
        self.set_int("quality", quality)

    def commit(self):
        """Commit filter parameters and images."""
        oidn_Capi.oidnCommitFilter(self._filter)

    def execute(self):
        """Execute the filter synchronously."""
        oidn_Capi.oidnExecuteFilter(self._filter)

    def execute_async(self):
        """Execute the filter asynchronously.

        Synchronize via :meth:`pyoidn.device.Device.wait`.
        """
        oidn_Capi.oidnExecuteFilterAsync(self._filter)

    def release(self):
        """Release the underlying OIDN filter handle."""
        oidn_Capi.oidnReleaseFilter(self._filter)

    def __enter__(self) -> "Filter":
        """Enter a context manager.

        :return: This filter.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Exit a context manager and release the filter."""
        self.release()
        return self
