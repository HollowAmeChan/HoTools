import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeTimingSnapshot:
    consumer: str
    tree_name: str
    tree_ref: object
    elapsed: float
    sample_count: int
    totals: dict
    node_totals: dict
    frame_level: bool


class OmniRuntimeTiming:
    """Aggregate runtime samples independently from their output consumers."""

    CONSOLE = "console"
    OVERLAY = "overlay"
    DEFAULT_CONSOLE_INTERVAL = 1.0
    OVERLAY_INTERVAL = 0.2
    _profiles = {}

    @staticmethod
    def is_enabled(tree):
        return bool(
            getattr(tree, "debug_runtime_timing", False)
            or getattr(tree, "show_runtime_timing", False)
        )

    @staticmethod
    def _profile_key(tree_name, tree_key):
        return str(tree_key) if tree_key is not None else f"name:{tree_name}"

    @staticmethod
    def _empty_bucket(now):
        return {
            "last_emit": now,
            "samples": 0,
            "stages": {},
            "nodes": {},
        }

    @classmethod
    def record(
        cls,
        tree_name,
        tree_key,
        stages,
        *,
        tree_ref=None,
        interval=None,
        frame_level=False,
        console_enabled=False,
        overlay_enabled=False,
        node_stages=None,
    ):
        if not stages or not (console_enabled or overlay_enabled):
            return

        now = time.perf_counter()
        key = cls._profile_key(tree_name, tree_key)
        profile = cls._profiles.setdefault(
            key,
            {
                "tree_name": tree_name,
                "tree_ref": tree_ref,
                "frame_level": bool(frame_level),
                "tree_pointer": cls._tree_pointer(tree_ref),
                "console_enabled": False,
                "overlay_enabled": False,
                cls.CONSOLE: cls._empty_bucket(now),
                cls.OVERLAY: cls._empty_bucket(now),
            },
        )
        profile["tree_name"] = tree_name
        profile["tree_ref"] = tree_ref
        profile["frame_level"] = bool(frame_level)
        profile["tree_pointer"] = cls._tree_pointer(tree_ref)
        try:
            profile["console_interval"] = max(float(interval), 0.05)
        except (TypeError, ValueError):
            profile["console_interval"] = cls.DEFAULT_CONSOLE_INTERVAL

        enabled_consumers = []
        if console_enabled:
            enabled_consumers.append(cls.CONSOLE)
        elif profile["console_enabled"]:
            profile[cls.CONSOLE] = cls._empty_bucket(now)
        if overlay_enabled:
            if not profile["overlay_enabled"]:
                profile[cls.OVERLAY]["last_emit"] = now - cls.OVERLAY_INTERVAL
            enabled_consumers.append(cls.OVERLAY)
        elif profile["overlay_enabled"]:
            profile[cls.OVERLAY] = cls._empty_bucket(now)
        profile["console_enabled"] = bool(console_enabled)
        profile["overlay_enabled"] = bool(overlay_enabled)

        node_stages = node_stages or {}
        for consumer in enabled_consumers:
            bucket = profile[consumer]
            bucket["samples"] += 1
            for stage, seconds in stages.items():
                seconds = float(seconds)
                bucket["stages"][stage] = bucket["stages"].get(stage, 0.0) + seconds
                if consumer == cls.OVERLAY:
                    node_name = node_stages.get(stage)
                    if node_name:
                        bucket["nodes"][node_name] = bucket["nodes"].get(node_name, 0.0) + seconds

    @staticmethod
    def _tree_pointer(tree_ref):
        if tree_ref is None:
            return None
        try:
            return int(tree_ref.as_pointer())
        except Exception:
            return id(tree_ref)

    @classmethod
    def flush(cls, force=False):
        now = time.perf_counter()
        snapshots = []

        for profile in cls._profiles.values():
            for consumer in (cls.CONSOLE, cls.OVERLAY):
                bucket = profile[consumer]
                if bucket["samples"] <= 0:
                    continue
                interval = (
                    profile.get("console_interval", cls.DEFAULT_CONSOLE_INTERVAL)
                    if consumer == cls.CONSOLE
                    else cls.OVERLAY_INTERVAL
                )
                elapsed = now - float(bucket["last_emit"])
                if not force and elapsed < interval:
                    continue

                snapshots.append(RuntimeTimingSnapshot(
                    consumer=consumer,
                    tree_name=profile["tree_name"],
                    tree_ref=profile["tree_ref"],
                    elapsed=elapsed,
                    sample_count=int(bucket["samples"]),
                    totals=dict(bucket["stages"]),
                    node_totals=dict(bucket["nodes"]),
                    frame_level=bool(profile["frame_level"]),
                ))
                profile[consumer] = cls._empty_bucket(now)

        return snapshots

    @classmethod
    def clear_tree(cls, tree, consumer=None):
        tree_pointer = cls._tree_pointer(tree)
        for key, profile in list(cls._profiles.items()):
            if profile.get("tree_pointer") != tree_pointer:
                continue
            if consumer in {cls.CONSOLE, cls.OVERLAY}:
                profile[consumer] = cls._empty_bucket(time.perf_counter())
                profile[f"{consumer}_enabled"] = False
            else:
                cls._profiles.pop(key, None)

    @classmethod
    def clear(cls):
        cls._profiles.clear()
