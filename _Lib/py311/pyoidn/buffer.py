"""Buffer wrapper.

This module provides a thin Python wrapper around OIDN's buffer API.

Buffers are owned by a :class:`pyoidn.device.Device` and can be used with
filters via ``oidnSetFilterImage`` (buffer-based images) or manually read/written
from host memory.

Typical usage:

.. code-block:: python

    import pyoidn
    import numpy as np

    data = np.zeros((64, 64, 3), dtype=np.float32)
    with pyoidn.Device() as device:
        device.commit()

        buf = pyoidn.Buffer(device, data.nbytes, storage=pyoidn.OIDN_STORAGE_HOST)
        buf.write(0, data.nbytes, data)
        # ... use buf with Filter.set_image(...)
        buf.release()

Notes
-----
- This wrapper mirrors OIDN's lifecycle: allocate -> use -> :meth:`Buffer.release`.
- ``read*``/``write*`` take *host* buffers (e.g., ``bytes``, ``bytearray``,
  ``memoryview``, NumPy arrays).
- Refer to https://github.com/RenderKit/oidn?tab=readme-ov-file#buffers for the OIDN buffer functions.
"""

from __future__ import annotations

from typing import Optional, Any

from .capi import oidn_Capi, oidn_ffi
from .device import Device
from .utils import require_torch
import numpy as np

OIDN_STORAGE_UNDEFINED = 0
OIDN_STORAGE_HOST = 1
OIDN_STORAGE_DEVICE = 2
OIDN_STORAGE_MANAGED = 3

__all__ = [
    "Buffer",
    "OIDN_STORAGE_UNDEFINED",
    "OIDN_STORAGE_HOST",
    "OIDN_STORAGE_DEVICE",
    "OIDN_STORAGE_MANAGED",
]


def _from_buffer(obj, require_writable: bool):
    """Create a CFFI view for an object supporting the buffer protocol."""
    try:
        return oidn_ffi.from_buffer(obj, require_writable=require_writable)
    except TypeError:
        return oidn_ffi.from_buffer(obj, require_writable)


class Buffer:
    """OIDN buffer wrapper.

    Mirrors the functions in `OIDN_FUNCTION_BUFFER`.

    Notes:
    - This is a thin wrapper; call `release()` when done.
    - `read*`/`write*` operate on host memory pointers.
    """

    def __init__(
        self,
        device: Device,
        byte_size: int,
        storage: Optional[int] = None,
    ) -> None:
        """Create a new OIDN buffer.

        :param device: The :class:`pyoidn.device.Device` that owns this buffer.
        :param byte_size: Buffer size in bytes.
        :param storage:
            Optional storage type, one of ``OIDN_STORAGE_*``.
            If omitted, OIDN chooses a default.
        :raises ValueError: If ``byte_size`` is negative.
        """
        if byte_size < 0:
            raise ValueError("byte_size must be >= 0")

        self._device = device
        if storage is None:
            self._buffer = oidn_Capi.oidnNewBuffer(device._device, int(byte_size))
        else:
            self._buffer = oidn_Capi.oidnNewBufferWithStorage(
                device._device, int(byte_size), int(storage)
            )

    @classmethod
    def shared(cls, device: Device, dev_ptr, byte_size: int) -> "Buffer":
        """Create a shared buffer from an existing pointer.

        This wraps an external allocation as an OIDN buffer without copying.

        :param device: The :class:`pyoidn.device.Device` that owns this buffer.
        :param dev_ptr:
            A pointer to existing memory. Can be an integer address or a cffi
            pointer compatible with ``void*``.
        :param byte_size: Buffer size in bytes.
        :raises ValueError: If ``byte_size`` is negative.
        """
        if byte_size < 0:
            raise ValueError("byte_size must be >= 0")

        self = cls.__new__(cls)
        self._device = device

        if isinstance(dev_ptr, int):
            dev_ptr = oidn_ffi.cast("void*", dev_ptr)
        self._buffer = oidn_Capi.oidnNewSharedBuffer(
            device._device, dev_ptr, int(byte_size)
        )
        return self

    @classmethod
    def shared_from_numpy(cls, device: Device, array: np.ndarray) -> "Buffer":
        """Create a shared buffer from a NumPy array.

        This wraps the NumPy array's memory as an OIDN buffer without copying.

        :param device: The :class:`pyoidn.device.Device` that owns this buffer.
        :param array: A NumPy array in host memory.
        :raises ValueError: If the array is not contiguous.
        """
        if not array.flags["C_CONTIGUOUS"] and not array.flags["F_CONTIGUOUS"]:
            raise ValueError("NumPy array must be contiguous")

        self = cls.__new__(cls)
        self._device = device

        ptr = oidn_ffi.cast("void*", oidn_ffi.from_buffer(array))
        byte_size = array.nbytes
        self._buffer = oidn_Capi.oidnNewSharedBuffer(
            device._device, ptr, int(byte_size)
        )
        return self

    @classmethod
    def shared_from_torch(cls, device: Device, tensor: Any) -> "Buffer":
        """Create a shared buffer from a PyTorch tensor.

        This wraps the tensor's memory as an OIDN buffer without copying.

        :param device: The :class:`pyoidn.device.Device` that owns this buffer.
        :param tensor: A PyTorch tensor in host or device memory.
        :raises ImportError: If PyTorch is not available.
        :raises ValueError: If the tensor is not contiguous.
        """
        require_torch()
        import torch

        if not tensor.is_contiguous():
            raise ValueError("PyTorch tensor must be contiguous")

        self = cls.__new__(cls)
        self._device = device

        from .torch_utils import torch2c_ptr

        ptr = torch2c_ptr(tensor)
        byte_size = tensor.numel() * tensor.element_size()
        self._buffer = oidn_Capi.oidnNewSharedBuffer(
            device._device, ptr, int(byte_size)
        )
        return self

    def release(self):
        """Release the underlying OIDN buffer handle.

        This method is idempotent.
        """
        if getattr(self, "_buffer", None) is None:
            return
        oidn_Capi.oidnReleaseBuffer(self._buffer)
        self._buffer = None

    @property
    def size(self) -> int:
        """Return the buffer size in bytes."""
        return int(oidn_Capi.oidnGetBufferSize(self._buffer))

    @property
    def storage(self) -> int:
        """Return the storage type (one of ``OIDN_STORAGE_*``)."""
        return int(oidn_Capi.oidnGetBufferStorage(self._buffer))

    def get_data(self):
        """Return the raw pointer returned by ``oidnGetBufferData``.

        :return: A cffi pointer.
        """
        return oidn_Capi.oidnGetBufferData(self._buffer)

    def read(self, byte_offset: int, byte_size: int, dst) -> None:
        """Read from this buffer into a writable host buffer.

        :param byte_offset: Offset in bytes.
        :param byte_size: Number of bytes to read.
        :param dst:
            Destination host buffer. Must be writable and support the buffer protocol
            (e.g., ``bytearray``, writable ``memoryview``, NumPy array).
        :raises ValueError: If ``byte_offset`` or ``byte_size`` is negative.
        """
        if byte_offset < 0 or byte_size < 0:
            raise ValueError("byte_offset/byte_size must be >= 0")

        dst_mv = dst if isinstance(dst, memoryview) else memoryview(dst)
        dst_ptr = oidn_ffi.cast("void*", _from_buffer(dst_mv, require_writable=True))
        oidn_Capi.oidnReadBuffer(
            self._buffer, int(byte_offset), int(byte_size), dst_ptr
        )

    def read_async(self, byte_offset: int, byte_size: int, dst) -> None:
        """Asynchronous version of :meth:`read`.

        You must synchronize via :meth:`pyoidn.device.Device.wait` before reading
        the destination.

        :param byte_offset: Offset in bytes.
        :param byte_size: Number of bytes to read.
        :param dst: Destination host buffer (writable).
        :raises ValueError: If ``byte_offset`` or ``byte_size`` is negative.
        """
        if byte_offset < 0 or byte_size < 0:
            raise ValueError("byte_offset/byte_size must be >= 0")

        dst_mv = dst if isinstance(dst, memoryview) else memoryview(dst)
        dst_ptr = oidn_ffi.cast("void*", _from_buffer(dst_mv, require_writable=True))
        oidn_Capi.oidnReadBufferAsync(
            self._buffer, int(byte_offset), int(byte_size), dst_ptr
        )

    def write(self, byte_offset: int, byte_size: int, src) -> None:
        """Write into this buffer from a host buffer.

        :param byte_offset: Offset in bytes.
        :param byte_size: Number of bytes to write.
        :param src:
            Source host buffer. Must support the buffer protocol
            (e.g., ``bytes``, ``bytearray``, ``memoryview``, NumPy array).
        :raises ValueError: If ``byte_offset`` or ``byte_size`` is negative.
        """
        if byte_offset < 0 or byte_size < 0:
            raise ValueError("byte_offset/byte_size must be >= 0")

        src_mv = src if isinstance(src, memoryview) else memoryview(src)
        src_ptr = oidn_ffi.cast(
            "const void*", _from_buffer(src_mv, require_writable=False)
        )
        oidn_Capi.oidnWriteBuffer(
            self._buffer, int(byte_offset), int(byte_size), src_ptr
        )

    def write_async(self, byte_offset: int, byte_size: int, src) -> None:
        """Asynchronous version of :meth:`write`.

        You must synchronize via :meth:`pyoidn.device.Device.wait` before using
        the written data.

        :param byte_offset: Offset in bytes.
        :param byte_size: Number of bytes to write.
        :param src: Source host buffer.
        :raises ValueError: If ``byte_offset`` or ``byte_size`` is negative.
        """
        if byte_offset < 0 or byte_size < 0:
            raise ValueError("byte_offset/byte_size must be >= 0")

        src_mv = src if isinstance(src, memoryview) else memoryview(src)
        src_ptr = oidn_ffi.cast(
            "const void*", _from_buffer(src_mv, require_writable=False)
        )
        oidn_Capi.oidnWriteBufferAsync(
            self._buffer, int(byte_offset), int(byte_size), src_ptr
        )

    def __enter__(self) -> "Buffer":
        """Enter a context manager.

        :return: This buffer.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Exit a context manager and release the buffer."""
        self.release()
        return False
