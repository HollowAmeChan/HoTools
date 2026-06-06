from .capi import oidn_ffi
import torch

def torch2c_ptr(tensor: torch.Tensor, ptr_type="void *"):
    return oidn_ffi.cast(ptr_type, tensor.data_ptr())
