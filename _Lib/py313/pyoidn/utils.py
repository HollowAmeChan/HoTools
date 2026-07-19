from .capi import oidn_ffi
import numpy as np

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


def require_torch():
    if not TORCH_AVAILABLE:
        raise ImportError(
            "This feature requires 'torch'. "
            "Please install it via `pip install pyoidn[torch]`"
        )


def c_str(py_str):
    return bytes(py_str, "ascii")


def np2c_ptr(np_array: np.ndarray, ptr_type="void *"):
    return oidn_ffi.cast(ptr_type, oidn_ffi.from_buffer(np_array))
