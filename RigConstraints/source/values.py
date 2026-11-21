"""JSON values shared by raw RNA parameter and reference capture."""

from collections.abc import Mapping
from typing import Any

_UNSERIALIZABLE = object()


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            value = to_dict()
        except (AttributeError, TypeError, RuntimeError):
            return _UNSERIALIZABLE

    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            converted = json_value(item)
            if converted is not _UNSERIALIZABLE:
                result[str(key)] = converted
        return result
    if isinstance(value, (bytes, bytearray)):
        return _UNSERIALIZABLE
    try:
        iterator = iter(value)
    except TypeError:
        return _UNSERIALIZABLE

    result = []
    for item in iterator:
        converted = json_value(item)
        if converted is _UNSERIALIZABLE:
            return _UNSERIALIZABLE
        result.append(converted)
    return result
