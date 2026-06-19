"""MC2 参数槽与 depth 曲线采样。"""

import numpy as np

from .....PropertyCurve import resolve_float_curve


_CACHE_BUCKET_LIMIT = 256


def _freeze_cache_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        return ("ndarray", str(array.dtype), tuple(array.shape), bytes(array.reshape(-1).tobytes()))
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze_cache_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_cache_value(item) for item in value)
    try:
        return _freeze_cache_value(value.to_payload())
    except Exception:
        return (type(value).__name__, id(value))


def _cache_bucket(cache: dict | None, name: str) -> dict | None:
    if not isinstance(cache, dict):
        return None
    bucket = cache.setdefault(str(name), {})
    if not isinstance(bucket, dict):
        bucket = {}
        cache[str(name)] = bucket
    if len(bucket) > _CACHE_BUCKET_LIMIT:
        bucket.clear()
    return bucket


def _remember(bucket: dict | None, key, factory):
    if bucket is None:
        return factory()
    if key in bucket:
        return bucket[key]
    value = factory()
    if len(bucket) > _CACHE_BUCKET_LIMIT:
        bucket.clear()
    bucket[key] = value
    return value


def _curve_value_at(curve, position: float) -> float:
    try:
        return float(curve.sample(position))
    except Exception:
        return float(getattr(curve, "value", 0.0))


def _is_float_curve_value(value) -> bool:
    if isinstance(value, dict):
        return str(value.get("kind", "")).lower() == "float_curve"
    return callable(getattr(value, "sample_positions", None)) and callable(getattr(value, "to_payload", None))


def scalar_param(value) -> dict:
    numeric = float(value)
    return {"mode": "scalar", "value": numeric, "samples": None, "cache_key": ("scalar", numeric)}


def _clamp_value(value, minimum=None, maximum=None) -> float:
    result = float(value)
    if minimum is not None:
        result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result


def float_curve_param(value, sample_count: int = 65) -> dict:
    curve = resolve_float_curve(value)
    sample_count = max(2, int(sample_count))
    samples = np.ascontiguousarray(
        curve.sample_many(sample_count),
        dtype=np.float32,
    )
    return {
        "mode": "curve",
        "value": _curve_value_at(curve, 0.0),
        "samples": samples,
        "payload": curve.to_payload(),
        "curve": curve,
        "sample_count": int(sample_count),
    }


def float_curve_param_cached(cache: dict | None, slot: str, value, sample_count: int = 65) -> dict:
    curve = resolve_float_curve(value)
    sample_count = max(2, int(sample_count))
    payload = curve.to_payload()
    key = ("float_curve", str(slot), _freeze_cache_value(payload), int(sample_count))

    def factory():
        samples = np.ascontiguousarray(curve.sample_many(sample_count), dtype=np.float32)
        return {
            "mode": "curve",
            "value": _curve_value_at(curve, 0.0),
            "samples": samples,
            "payload": payload,
            "curve": curve,
            "sample_count": int(sample_count),
            "cache_key": key,
        }

    return _remember(_cache_bucket(cache, "params"), key, factory)


def float_param(value, minimum=None, maximum=None, sample_count: int = 65) -> dict:
    if _is_float_curve_value(value):
        param = float_curve_param(value, sample_count=sample_count)
    else:
        param = scalar_param(value)

    if minimum is None and maximum is None:
        return param
    return clamp_param(param, minimum=minimum, maximum=maximum)


def float_param_cached(cache: dict | None, slot: str, value, minimum=None, maximum=None, sample_count: int = 65) -> dict:
    if not _is_float_curve_value(value):
        return clamp_param(scalar_param(value), minimum=minimum, maximum=maximum)
    param = float_curve_param_cached(cache, slot, value, sample_count=sample_count)
    return clamp_param(param, minimum=minimum, maximum=maximum)


def curve_value_param(value, curve, minimum=None, maximum=None, sample_count: int = 65) -> dict:
    base_value = _clamp_value(value, minimum=minimum, maximum=maximum)
    if not _is_float_curve_value(curve):
        return clamp_param(scalar_param(base_value), minimum=minimum, maximum=maximum)

    curve_value = resolve_float_curve(curve)
    sample_count = max(2, int(sample_count))
    curve_samples = np.ascontiguousarray(
        curve_value.sample_many(sample_count),
        dtype=np.float32,
    )
    samples = np.ascontiguousarray(base_value * curve_samples, dtype=np.float32)
    first_curve_value = _curve_value_at(curve_value, 0.0)
    param = {
        "mode": "curve_value",
        "value": base_value * first_curve_value,
        "base_value": base_value,
        "curve_value": first_curve_value,
        "samples": samples,
        "curve_samples": curve_samples,
        "payload": curve_value.to_payload(),
        "curve": curve_value,
        "sample_count": int(sample_count),
    }
    return clamp_param(param, minimum=minimum, maximum=maximum)


def curve_value_param_cached(
    cache: dict | None,
    slot: str,
    value,
    curve,
    minimum=None,
    maximum=None,
    sample_count: int = 65,
) -> dict:
    base_value = _clamp_value(value, minimum=minimum, maximum=maximum)
    if not _is_float_curve_value(curve):
        return clamp_param(scalar_param(base_value), minimum=minimum, maximum=maximum)

    curve_value = resolve_float_curve(curve)
    sample_count = max(2, int(sample_count))
    payload = curve_value.to_payload()
    key = (
        "curve_value",
        str(slot),
        float(base_value),
        _freeze_cache_value(payload),
        minimum,
        maximum,
        int(sample_count),
    )

    def factory():
        curve_samples = np.ascontiguousarray(curve_value.sample_many(sample_count), dtype=np.float32)
        samples = np.ascontiguousarray(base_value * curve_samples, dtype=np.float32)
        first_curve_value = _curve_value_at(curve_value, 0.0)
        param = {
            "mode": "curve_value",
            "value": base_value * first_curve_value,
            "base_value": base_value,
            "curve_value": first_curve_value,
            "samples": samples,
            "curve_samples": curve_samples,
            "payload": payload,
            "curve": curve_value,
            "sample_count": int(sample_count),
            "cache_key": key,
        }
        return clamp_param(param, minimum=minimum, maximum=maximum)

    return _remember(_cache_bucket(cache, "params"), key, factory)


def clamp_param(param: dict, minimum=None, maximum=None) -> dict:
    result = dict(param)
    result["minimum"] = minimum
    result["maximum"] = maximum
    if minimum is not None or maximum is not None:
        value = float(result.get("value", 0.0))
        if minimum is not None:
            value = max(float(minimum), value)
        if maximum is not None:
            value = min(float(maximum), value)
        result["value"] = value

    samples = result.get("samples")
    if samples is not None:
        array = np.ascontiguousarray(samples, dtype=np.float32)
        if minimum is not None:
            array = np.maximum(array, float(minimum))
        if maximum is not None:
            array = np.minimum(array, float(maximum))
        result["samples"] = np.ascontiguousarray(array, dtype=np.float32)
    result["cache_key"] = (
        "clamp",
        _freeze_cache_value(result.get("cache_key")),
        minimum,
        maximum,
        float(result.get("value", 0.0)),
    )
    return result


def param_scalar_value(param: dict, fallback=0.0) -> float:
    try:
        return float(param.get("value", fallback))
    except Exception:
        return float(fallback)


def param_has_positive(param: dict, epsilon: float = 0.0) -> bool:
    if not isinstance(param, dict):
        try:
            return float(param) > float(epsilon)
        except Exception:
            return False
    samples = param.get("samples")
    if samples is not None:
        array = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
        return bool(np.any(array > float(epsilon)))
    return param_scalar_value(param, 0.0) > float(epsilon)


def sample_param(param: dict, depths: np.ndarray) -> np.ndarray:
    mode = str(param.get("mode", "scalar") if isinstance(param, dict) else "scalar")
    if mode == "scalar":
        value = float(param.get("value", 0.0)) if isinstance(param, dict) else float(param)
        return np.full(len(depths), value, dtype=np.float32)

    if mode == "curve":
        curve = param.get("curve") if isinstance(param, dict) else None
        if curve is not None:
            positions = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
            values = np.ascontiguousarray(
                np.asarray(curve.sample_positions(positions), dtype=np.float32),
                dtype=np.float32,
            )
            minimum = param.get("minimum")
            maximum = param.get("maximum")
            if minimum is not None:
                values = np.maximum(values, float(minimum))
            if maximum is not None:
                values = np.minimum(values, float(maximum))
            return np.ascontiguousarray(values, dtype=np.float32)

    if mode == "curve_value":
        curve = param.get("curve") if isinstance(param, dict) else None
        if curve is not None:
            positions = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
            base_value = float(param.get("base_value", 0.0))
            curve_values = np.ascontiguousarray(
                np.asarray(curve.sample_positions(positions), dtype=np.float32),
                dtype=np.float32,
            )
            values = np.ascontiguousarray(base_value * curve_values, dtype=np.float32)
            minimum = param.get("minimum")
            maximum = param.get("maximum")
            if minimum is not None:
                values = np.maximum(values, float(minimum))
            if maximum is not None:
                values = np.minimum(values, float(maximum))
            return np.ascontiguousarray(values, dtype=np.float32)

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


def sample_param_cached(cache: dict | None, slot: str, param: dict, depths: np.ndarray) -> np.ndarray:
    depths_array = np.ascontiguousarray(depths, dtype=np.float32)
    param_key = param.get("cache_key") if isinstance(param, dict) else ("raw", _freeze_cache_value(param))
    key = (
        "sample",
        str(slot),
        _freeze_cache_value(param_key),
        str(depths_array.dtype),
        tuple(depths_array.shape),
        bytes(depths_array.reshape(-1).tobytes()),
    )
    return _remember(
        _cache_bucket(cache, "samples"),
        key,
        lambda: sample_param(param, depths_array),
    )
