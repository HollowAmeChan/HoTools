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
    """Aggregate console timing and schedule direct node-overlay samples."""

    CONSOLE = "console"
    OVERLAY = "overlay"
    DEFAULT_CONSOLE_INTERVAL = 1.0
    DEFAULT_OVERLAY_SAMPLE_INTERVAL = 3.0
    _profiles = {}
    _overlay_last_sample = {}

    @staticmethod
    def is_enabled(tree):
        return bool(
            getattr(tree, "debug_runtime_timing", False)
            or getattr(tree, "show_runtime_timing", False)
        )

    @classmethod
    def take_overlay_sample(cls, tree, now=None, gate=None):
        # PERFORMANCE CONTRACT: this is the only wall-clock gate for overlay
        # sampling. A root run shares gate with all child observers, so even a
        # heavily reused subtree cannot cause additional clock reads.
        if tree is None or not bool(getattr(tree, "show_runtime_timing", False)):
            return False
        try:
            interval = max(
                float(getattr(
                    tree,
                    "runtime_timing_sample_interval",
                    cls.DEFAULT_OVERLAY_SAMPLE_INTERVAL,
                )),
                0.05,
            )
        except (TypeError, ValueError):
            interval = cls.DEFAULT_OVERLAY_SAMPLE_INTERVAL

        if now is None and gate is not None:
            now = gate.get("now")
        if now is None:
            now = time.perf_counter()
            if gate is not None:
                gate["now"] = now
        else:
            now = float(now)
        key = cls._tree_pointer(tree)
        last_sample = cls._overlay_last_sample.get(key)
        if last_sample is not None and now - last_sample < interval:
            return False
        cls._overlay_last_sample[key] = now
        return True

    @classmethod
    def reset_overlay_schedule(cls, tree):
        cls._overlay_last_sample.pop(cls._tree_pointer(tree), None)

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
        overlay_sampled=False,
        node_stages=None,
    ):
        if not stages or not (console_enabled or overlay_sampled):
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

        if console_enabled:
            bucket = profile[cls.CONSOLE]
            bucket["samples"] += 1
            for stage, seconds in stages.items():
                seconds = float(seconds)
                bucket["stages"][stage] = bucket["stages"].get(stage, 0.0) + seconds
        elif profile["console_enabled"]:
            profile[cls.CONSOLE] = cls._empty_bucket(now)
        profile["console_enabled"] = bool(console_enabled)

        if overlay_sampled:
            bucket = cls._empty_bucket(now)
            bucket["samples"] = 1
            node_stages = node_stages or {}
            for stage, seconds in stages.items():
                seconds = float(seconds)
                bucket["stages"][stage] = seconds
                node_name = node_stages.get(stage)
                if node_name:
                    bucket["nodes"][node_name] = bucket["nodes"].get(node_name, 0.0) + seconds
            profile[cls.OVERLAY] = bucket

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
                interval = profile.get("console_interval", cls.DEFAULT_CONSOLE_INTERVAL)
                elapsed = now - float(bucket["last_emit"])
                if consumer == cls.CONSOLE and not force and elapsed < interval:
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
                if consumer == cls.CONSOLE:
                    profile["console_enabled"] = False
            else:
                cls._profiles.pop(key, None)
        if consumer in {None, cls.OVERLAY}:
            cls.reset_overlay_schedule(tree)

    @classmethod
    def clear(cls):
        cls._profiles.clear()
        cls._overlay_last_sample.clear()
