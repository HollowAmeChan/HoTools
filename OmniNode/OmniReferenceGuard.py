"""OmniNode 持久引用门禁。

Runtime cache owner 可以实现 ``omni_cache_refresh_references(reason)``，在
Blender 重建宿主数据引用的生命周期边界重新绑定 bpy 引用。架构层只负责
发现并调用协议，不认识 PhysicsWorld 等业务域的内部结构。
"""

from __future__ import annotations

from dataclasses import dataclass

import bpy

from .OmniRuntimeState import iter_committed_cache_values


@dataclass(frozen=True)
class ReferenceRefreshFailure:
    owner_type: str
    error: str


@dataclass(frozen=True)
class ReferenceRefreshReport:
    owner_count: int
    refreshed_count: int
    failures: tuple[ReferenceRefreshFailure, ...]

    @property
    def failed_count(self) -> int:
        return len(self.failures)


def is_bpy_reference_valid(value) -> bool:
    """检查 bpy 数据引用是否仍指向可访问的宿主对象。"""
    if value is None:
        return False
    try:
        _ = value.name
        value.as_pointer()
        return True
    except ReferenceError:
        return False
    except Exception:
        return False


def resolve_bpy_object_reference(
    object_pointer: int,
    data_pointer: int = 0,
    *,
    object_type: str | None = None,
):
    """通过 Object 与可选 data 双指针重新解析当前会话中的活体引用。"""
    object_pointer = int(object_pointer or 0)
    data_pointer = int(data_pointer or 0)
    expected_type = str(object_type or "").strip()
    if object_pointer <= 0:
        return None

    try:
        objects = tuple(bpy.data.objects)
    except Exception:
        return None

    for obj in objects:
        try:
            if expected_type and obj.type != expected_type:
                continue
            if int(obj.as_pointer()) != object_pointer:
                continue
            if data_pointer > 0:
                data = getattr(obj, "data", None)
                if data is None or int(data.as_pointer()) != data_pointer:
                    continue
            return obj
        except Exception:
            continue
    return None


def _iter_refreshable_owners(value, seen: set[int]):
    if value is None or isinstance(value, (str, bool, int, float)):
        return

    value_id = id(value)
    if value_id in seen:
        return
    seen.add(value_id)

    refresh = getattr(value, "omni_cache_refresh_references", None)
    if callable(refresh):
        yield value, refresh
        return

    if isinstance(value, dict):
        for item in tuple(value.values()):
            yield from _iter_refreshable_owners(item, seen)
        return

    if isinstance(value, (list, tuple, set)):
        for item in tuple(value):
            yield from _iter_refreshable_owners(item, seen)


def refresh_persistent_references(reason: str) -> ReferenceRefreshReport:
    """刷新全部 committed runtime cache owner 持有的 bpy 引用。"""
    normalized_reason = str(reason or "unknown")
    seen: set[int] = set()
    owners = []
    for value in tuple(iter_committed_cache_values()):
        owners.extend(_iter_refreshable_owners(value, seen))

    refreshed_count = 0
    failures = []
    for owner, refresh in owners:
        try:
            refresh(normalized_reason)
            refreshed_count += 1
        except Exception as exc:
            failure = ReferenceRefreshFailure(type(owner).__name__, str(exc))
            failures.append(failure)
            print(
                f"[OmniNode Reference Guard] {failure.owner_type} 刷新失败："
                f"{failure.error}"
            )

    return ReferenceRefreshReport(
        owner_count=len(owners),
        refreshed_count=refreshed_count,
        failures=tuple(failures),
    )
