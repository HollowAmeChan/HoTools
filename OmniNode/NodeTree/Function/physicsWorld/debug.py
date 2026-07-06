"""
physicsWorld.debug — PhysicsWorldCache 调试输出工具

提供：
  snapshot_to_text     — 把 debug snapshot dict 转成可读文本
  result_items_to_text — 把 result stream item list 转成可读文本
  validate_world       — 校验 world 状态，返回问题列表
  print_world_summary  — 直接打印简洁的 world 摘要到控制台
"""

from __future__ import annotations

from .types import PhysicsWorldCache


# ---------------------------------------------------------------------------
# snapshot → 可读文本
# ---------------------------------------------------------------------------

def snapshot_to_text(snapshot: dict, indent: int = 0) -> str:
    """
    把 omni_cache_debug_snapshot() 返回的 dict 转成多行可读文本。

    indent 为当前缩进层级（内部递归用），外部调用传 0 即可。
    """
    if not isinstance(snapshot, dict):
        return str(snapshot)

    prefix = "  " * indent
    lines = []

    # 顶层字段优先顺序
    ordered_keys = [
        "kind", "schema", "generation", "replace_required", "valid",
        "frame", "previous_frame", "continuous", "same_frame", "restart_required",
        "dt", "time_scale", "substeps",
        "objects", "collider_sources", "colliders",
        "exchange_channels", "exchange_item_count",
        "result_channels", "result_item_count",
        "solver_slots", "backend_resources", "backend_resource_details",
    ]
    shown = set()

    for key in ordered_keys:
        if key not in snapshot:
            continue
        shown.add(key)
        value = snapshot[key]
        if key == "solver_slots" and isinstance(value, dict):
            lines.append(f"{prefix}{key}: ({len(value)} 个 slot)")
            for slot_id, slot_snap in value.items():
                lines.append(f"{prefix}  [{slot_id}]")
                if isinstance(slot_snap, dict):
                    for sk, sv in slot_snap.items():
                        lines.append(f"{prefix}    {sk}: {sv}")
                else:
                    lines.append(f"{prefix}    {slot_snap}")
        elif key == "backend_resources" and isinstance(value, list):
            lines.append(f"{prefix}{key}: {value}")
        elif key == "backend_resource_details" and isinstance(value, dict):
            lines.append(f"{prefix}{key}: ({len(value)} 个 backend)")
            for backend_name, backend_snap in value.items():
                lines.append(f"{prefix}  [{backend_name}]")
                if isinstance(backend_snap, dict):
                    for bk, bv in backend_snap.items():
                        lines.append(f"{prefix}    {bk}: {bv}")
                else:
                    lines.append(f"{prefix}    {backend_snap}")
        else:
            lines.append(f"{prefix}{key}: {value}")

    # 其余未列出的字段补充到末尾
    for key, value in snapshot.items():
        if key in shown:
            continue
        lines.append(f"{prefix}{key}: {value}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# result stream → 可读文本
# ---------------------------------------------------------------------------

def _format_result_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        if len(value) > 8:
            head = ", ".join(_format_result_value(v) for v in value[:8])
            return f"({head}, ... +{len(value) - 8})"
        return "(" + ", ".join(_format_result_value(v) for v in value) + ")"
    if isinstance(value, dict):
        keys = list(value.keys())
        shown = ", ".join(str(k) for k in keys[:8])
        suffix = f", ... +{len(keys) - 8}" if len(keys) > 8 else ""
        return "{" + shown + suffix + "}"
    return str(value)


def result_items_to_text(items: list[dict], max_items: int = 20) -> str:
    """
    把 world result stream item list 转成多行文本。

    result item 必须是纯 dict/tuple 数据；此函数只做展示，不回读 solver slot
    或 backend handle。
    """
    if not items:
        return "<empty result stream>"

    lines: list[str] = []
    visible_items = items[:max(0, int(max_items))]
    header_keys = {"channel", "solver", "frame", "generation"}

    for index, item in enumerate(visible_items):
        if not isinstance(item, dict):
            lines.append(f"[{index}] {item}")
            continue
        channel = item.get("channel", "<none>")
        solver = item.get("solver", "<none>")
        frame = item.get("frame", "<none>")
        generation = item.get("generation", "<none>")
        lines.append(f"[{index}] channel={channel} solver={solver} frame={frame} generation={generation}")
        for key in sorted(k for k in item.keys() if k not in header_keys):
            lines.append(f"  {key}: {_format_result_value(item.get(key))}")

    if len(items) > len(visible_items):
        lines.append(f"... +{len(items) - len(visible_items)} items")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 校验 world 状态
# ---------------------------------------------------------------------------

def validate_world(world: PhysicsWorldCache) -> list[str]:
    """
    校验 world 状态，返回问题描述字符串列表。
    空列表表示无问题。

    供 Physics World Validate 节点和 debug 节点使用。
    """
    problems: list[str] = []

    if not isinstance(world, PhysicsWorldCache):
        problems.append(f"world 不是 PhysicsWorldCache，实际类型：{type(world).__name__}")
        return problems

    fc = world.frame_context

    if not world.valid:
        problems.append("world.valid=False（上帧脏帧，当帧应已重建）")

    if world.generation == 0:
        problems.append("world.generation=0（world 尚未被 Physics World Begin 初始化）")

    if fc.dt <= 0.0:
        problems.append(f"frame_context.dt={fc.dt}（场景帧率可能为0或未设置）")

    if fc.substeps < 1:
        problems.append(f"frame_context.substeps={fc.substeps}（应≥1）")

    colliders = world.collider_snapshot.get("colliders") or []
    invalid_count = world.collider_snapshot.get("invalid_count", 0)
    if invalid_count > 0:
        problems.append(f"collider_snapshot 中有 {invalid_count} 个引用失效的对象（object scope 可能包含已删除对象）")

    if world._current_writer is not None:
        problems.append(f"world._current_writer={world._current_writer!r}（写入锁未释放，可能存在分叉写入）")

    return problems


# ---------------------------------------------------------------------------
# 控制台打印摘要
# ---------------------------------------------------------------------------

def print_world_summary(world: PhysicsWorldCache, label: str = "") -> None:
    """
    向控制台打印简洁的 world 帧摘要，供开发期调试使用。
    """
    if not isinstance(world, PhysicsWorldCache):
        print(f"[PhysicsWorld{f':{label}' if label else ''}] world 无效（{type(world).__name__}）")
        return

    fc = world.frame_context
    colliders = len(world.collider_snapshot.get("colliders") or [])
    sources = world.collider_snapshot.get("source_count", 0)
    invalid = world.collider_snapshot.get("invalid_count", 0)
    tag = f":{label}" if label else ""

    print(
        f"[PhysicsWorld{tag}] "
        f"gen={world.generation} frame={fc.frame} prev={fc.previous_frame} "
        f"cont={fc.continuous} same={fc.same_frame} restart={fc.restart_required} "
        f"dt={fc.dt:.4f} sources={sources} colliders={colliders} invalid={invalid} "
        f"slots={len(world.solver_slots)} replace={world.replace_required} valid={world.valid}"
    )

    problems = validate_world(world)
    for p in problems:
        print(f"  ⚠ {p}")
