"""MC2 参数槽与 depth 曲线采样。"""

import numpy as np


def scalar_param(value) -> dict:
    return {"mode": "scalar", "value": float(value), "samples": None}


def sample_param(param: dict, depths: np.ndarray) -> np.ndarray:
    mode = str(param.get("mode", "scalar") if isinstance(param, dict) else "scalar")
    if mode == "scalar":
        value = float(param.get("value", 0.0)) if isinstance(param, dict) else float(param)
        return np.full(len(depths), value, dtype=np.float32)

    samples = param.get("samples") if isinstance(param, dict) else None
    if samples is None:
        value = float(param.get("value", 0.0)) if isinstance(param, dict) else 0.0
        return np.full(len(depths), value, dtype=np.float32)

    table = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
    if len(table) == 0:
        return np.zeros(len(depths), dtype=np.float32)
    if len(table) == 1:
        return np.full(len(depths), float(table[0]), dtype=np.float32)

    x = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0) * float(len(table) - 1)
    i0 = np.floor(x).astype(np.int32)
    i1 = np.minimum(i0 + 1, len(table) - 1)
    t = x - i0
    return np.ascontiguousarray(table[i0] * (1.0 - t) + table[i1] * t, dtype=np.float32)
