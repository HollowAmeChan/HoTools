"""
OmniNode Tracy 性能桩封装。

Tracy 可用时（编译了 tracy_client 的 Blender 构建）自动激活；
普通 Blender 构建中 tracy_client 不存在，全部降级为空操作，
不产生任何额外开销。

使用方式
--------
from .OmniTracy import omni_zone, omni_frame_mark, tracy_enabled

# 上下文管理器方式（推荐）
with omni_zone("OmniNode/Run/my_tree"):
    ...

# 可以随时查询是否激活
if tracy_enabled():
    ...
"""

# ---------------------------------------------------------------------------
# Tracy 可用性检测
# ---------------------------------------------------------------------------

_TRACY_AVAILABLE = False
_ScopedZone = None
_frame_mark_fn = None

try:
    # tracy_client 需要从 D:\BlenderAdvance\tracy_src\python\ 编译安装
    # 普通 Blender 中 import 会失败，走 except 分支
    from tracy_client import ScopedZone as _ScopedZone  # type: ignore
    from tracy_client import frame_mark as _frame_mark_fn  # type: ignore
    # is_enabled() 返回 True 才说明 Tracy 实际运行中
    from tracy_client import is_enabled as _tracy_is_enabled  # type: ignore
    _TRACY_AVAILABLE = bool(_tracy_is_enabled())
except Exception:
    # 普通 Blender 构建 / tracy_client 未编译 —— 静默跳过
    pass


# ---------------------------------------------------------------------------
# 空操作上下文管理器（Tracy 不可用时使用）
# ---------------------------------------------------------------------------

class _NullZone:
    """Tracy 不可用时的零开销替代品。"""
    __slots__ = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False  # 不吞异常


# 单例，避免每次 zone() 调用都分配对象
_NULL_ZONE = _NullZone()


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def tracy_enabled() -> bool:
    """返回 Tracy profiler 是否已激活。"""
    return _TRACY_AVAILABLE


def omni_zone(name: str, color: int = 0):
    """
    返回一个 Tracy zone 上下文管理器。

    参数
    ----
    name  : zone 显示名称，建议格式 "OmniNode/<类型>/<树名或节点名>"
    color : Tracy 颜色值（0 = Tracy 默认色）

    Tracy 不可用时返回 _NullZone，with 语句开销极小（一次属性查找）。

    示例
    ----
    with omni_zone("OmniNode/Run/my_tree"):
        ...
    with omni_zone("OmniNode/OpCall/Mesh.set_position", color=0x00AAFF):
        ...
    """
    if not _TRACY_AVAILABLE or _ScopedZone is None:
        return _NULL_ZONE
    try:
        if color:
            return _ScopedZone(name=name, color=color)
        return _ScopedZone(name=name)
    except Exception:
        return _NULL_ZONE


def omni_frame_mark(name: str = "") -> None:
    """
    发送 Tracy 帧标记（frame_mark）。

    name 为空字符串时标记主帧；传入名称则标记命名帧序列。
    Tracy 不可用时为空操作。
    """
    if not _TRACY_AVAILABLE or _frame_mark_fn is None:
        return
    try:
        if name:
            _frame_mark_fn(name)
        else:
            _frame_mark_fn()
    except Exception:
        pass
