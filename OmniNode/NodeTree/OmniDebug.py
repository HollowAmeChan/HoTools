import os
import sys
import time


class OmniDebug:
    COLOR_TERMINAL = {"displays_colors": False, "initialized": False}
    RUNTIME_TIMING_PRINT_INTERVAL = 1.0
    RUNTIME_TIMING_MAX_STAGES = 12
    _runtime_timing_profiles = {}

    @staticmethod
    def node_name(node):
        return getattr(node, "name", "<node>")

    @staticmethod
    def socket_name(sock):
        return getattr(sock, "identifier", getattr(sock, "name", "<socket>"))

    @staticmethod
    def func_name(func):
        if func is None:
            return "<missing_func>"
        return getattr(func, "__name__", func.__class__.__name__)

    @staticmethod
    def format_value(value):
        text = repr(value)
        if len(text) > 160:
            text = text[:157] + "..."
        return text

    @staticmethod
    def append_compile_trace(graph, message):
        graph.compile_trace.append(message)

    @staticmethod
    def add_register_bridge(graph, reg, owner_node, owner_socket, source=None, note=""):
        graph.register_bridges.append({
            "reg": reg,
            "owner_node": owner_node,
            "owner_socket": owner_socket,
            "source": source,
            "note": note,
        })

    @staticmethod
    def init_terminal_colors():
        if OmniDebug.COLOR_TERMINAL["initialized"]:
            return

        can_paint = os.name in {"posix"}
        try:
            if hasattr(sys, "getwindowsversion") and sys.getwindowsversion().major == 10:
                can_paint = True
        except Exception:
            pass

        OmniDebug.COLOR_TERMINAL["displays_colors"] = can_paint
        OmniDebug.COLOR_TERMINAL["initialized"] = True

    @staticmethod
    def str_color(text, color):
        OmniDebug.init_terminal_colors()
        if OmniDebug.COLOR_TERMINAL["displays_colors"]:
            return f"\033[1;{color}m{text}\033[0m"
        return str(text)

    @staticmethod
    def section_label(text):
        return OmniDebug.str_color(f"[{text}]", 96)

    @staticmethod
    def tree_label(text):
        return OmniDebug.str_color(f"<{text}>", 94)

    @staticmethod
    def reg_label(reg):
        return OmniDebug.str_color(f"r{reg}", 93)

    @staticmethod
    def node_label(text):
        return OmniDebug.str_color(text, 92)

    @staticmethod
    def func_label(text):
        return OmniDebug.str_color(text, 95)

    @staticmethod
    def value_label(text):
        return OmniDebug.str_color(str(text), 90)

    @staticmethod
    def error_label(text):
        return OmniDebug.str_color(f"ERROR: {text}", 91)

    @staticmethod
    def format_compile_report(graph, subtree_call_type, depth=0):
        indent = "    " * depth
        lines = [
            f"{indent}{OmniDebug.section_label('Compile')} Tree: {OmniDebug.tree_label(graph.tree_name)}",
            f"{indent}  {OmniDebug.section_label('Registers')}: {OmniDebug.value_label(graph.reg_count)}",
            f"{indent}  {OmniDebug.section_label('Topo Order')}: "
            + (
                ", ".join(OmniDebug.node_label(node_name) for node_name in graph.node_order)
                if graph.node_order else OmniDebug.value_label("<empty>")
            ),
        ]

        if graph.input_regs:
            lines.append(f"{indent}  {OmniDebug.section_label('Tree Inputs')}:")
            for uid, reg in graph.input_regs.items():
                lines.append(f"{indent}    {OmniDebug.value_label(uid)} -> {OmniDebug.reg_label(reg)}")

        if graph.output_regs:
            lines.append(f"{indent}  {OmniDebug.section_label('Tree Outputs')}:")
            for uid, reg in graph.output_regs.items():
                lines.append(f"{indent}    {OmniDebug.value_label(uid)} <- {OmniDebug.reg_label(reg)}")

        if graph.register_bridges:
            lines.append(f"{indent}  {OmniDebug.section_label('Register Bridges')}:")
            for bridge in graph.register_bridges:
                source = bridge["source"] or "<none>"
                note = f" ({bridge['note']})" if bridge["note"] else ""
                lines.append(
                    f"{indent}    {OmniDebug.reg_label(bridge['reg'])} :: "
                    f"{OmniDebug.node_label(bridge['owner_node'])}.{OmniDebug.value_label(bridge['owner_socket'])} <- "
                    f"{OmniDebug.value_label(source + note)}"
                )

        if graph.function_catalog:
            lines.append(f"{indent}  {OmniDebug.section_label('Runtime Functions')}:")
            for item in graph.function_catalog:
                lines.append(
                    f"{indent}    {OmniDebug.func_label(item['func'])} @ {OmniDebug.node_label(item['node'])}"
                )

        if graph.compile_trace:
            lines.append(f"{indent}  {OmniDebug.section_label('Compile Trace')}:")
            for entry in graph.compile_trace:
                lines.append(f"{indent}    {OmniDebug.value_label(entry)}")

        subtree_types = subtree_call_type
        if not isinstance(subtree_types, tuple):
            subtree_types = (subtree_types,)

        for op in graph.instructions:
            if isinstance(op, subtree_types):
                lines.extend(OmniDebug.format_compile_report(op.compiled_graph, subtree_call_type, depth + 1))

        return lines

    @staticmethod
    def format_runtime_header(tree_name):
        return [
            "",
            "=" * 72,
            f"OMNI DEBUG COMPILE  |  Tree: {tree_name}",
            "=" * 72,
        ]

    @staticmethod
    def format_runtime_separator(tree_name):
        return [
            "-" * 72,
            f"OMNI DEBUG RUNTIME  |  Tree: {tree_name}",
            "-" * 72,
        ]

    @staticmethod
    def format_runtime_timing_report(tree_name, elapsed, sample_count, totals, frame_level=False):
        sample_count = max(int(sample_count), 1)
        frame_ms = elapsed / sample_count * 1000.0           # 每帧真实墙钟间隔
        hz = sample_count / max(elapsed, 0.000001)
        handler_ms = totals.get("total", 0.0) / sample_count * 1000.0  # handler 内部耗时

        header = "Frame" if frame_level else "Tree"
        lines = [
            "",
            "-" * 72,
            f"OMNI DEBUG TIMING   |  {header}: {tree_name}",
            "-" * 72,
        ]

        if frame_level:
            # 帧级报告：区分 handler 内部 vs 引擎/重绘（handler 外）。
            engine_ms = max(frame_ms - handler_ms, 0.0)
            lines.append(
                f"  {OmniDebug.section_label('Summary')}: "
                f"samples={OmniDebug.value_label(sample_count)}  "
                f"fps={OmniDebug.value_label(f'{hz:.1f}')}  "
                f"frame={OmniDebug.func_label(f'{frame_ms:.2f}ms')}"
            )
            lines.append(
                f"    {OmniDebug.value_label('handler')} = {OmniDebug.func_label(f'{handler_ms:.2f}ms')}"
                f"  ({OmniDebug.value_label(f'{handler_ms / max(frame_ms, 1e-6) * 100:.0f}%')})"
            )
            lines.append(
                f"    {OmniDebug.value_label('engine/redraw')} = {OmniDebug.func_label(f'{engine_ms:.2f}ms')}"
                f"  ({OmniDebug.value_label(f'{engine_ms / max(frame_ms, 1e-6) * 100:.0f}%')})"
            )
        else:
            lines.append(
                f"  {OmniDebug.section_label('Summary')}: "
                f"interval={OmniDebug.value_label(f'{elapsed * 1000.0:.1f}ms')}  "
                f"samples={OmniDebug.value_label(sample_count)}  "
                f"hz={OmniDebug.value_label(f'{hz:.2f}')}  "
                f"total={OmniDebug.func_label(f'{handler_ms:.3f}ms')}"
            )

        step_stages = [stage for stage in totals if stage != "total"]
        step_stages.sort(key=lambda stage: totals[stage], reverse=True)
        max_stages = max(int(OmniDebug.RUNTIME_TIMING_MAX_STAGES), 1)
        shown_steps = step_stages[:max_stages]
        hidden_steps = step_stages[max_stages:]

        if shown_steps:
            label = "Breakdown" if frame_level else "Slow Steps"
            lines.append(f"  {OmniDebug.section_label(label)}:")
            for index, stage in enumerate(shown_steps, start=1):
                avg_ms = totals[stage] / sample_count * 1000.0
                pct = avg_ms / max(handler_ms, 1e-6) * 100.0
                lines.append(
                    f"    {OmniDebug.value_label(f'{index:02d}.')} "
                    f"{OmniDebug.func_label(stage)} = {OmniDebug.value_label(f'{avg_ms:.3f}ms')}"
                    f"  ({OmniDebug.value_label(f'{pct:.0f}%')})"
                )

        if hidden_steps:
            other_total = sum(totals[stage] for stage in hidden_steps)
            other_ms = other_total / sample_count * 1000.0
            lines.append(
                f"    {OmniDebug.value_label('..')} "
                f"{OmniDebug.func_label('other_steps')} = {OmniDebug.value_label(f'{other_ms:.3f}ms')}"
            )

        return lines

    @staticmethod
    def make_runtime_logger(depth):
        trace = []
        indent = "    " * depth

        def log(message):
            trace.append(f"{indent}{message}")

        return trace, log

    @staticmethod
    def runtime_timing_key(tree_name, tree_pointer=None):
        if tree_pointer is not None:
            return f"tree:{tree_pointer}"
        return f"name:{tree_name}"

    @classmethod
    def record_runtime_timing(cls, tree_name, tree_key, stages, interval=None, frame_level=False):
        if not stages:
            return

        now = time.perf_counter()
        if tree_key is None:
            key = cls.runtime_timing_key(tree_name)
        elif isinstance(tree_key, int):
            key = cls.runtime_timing_key(tree_name, tree_key)
        else:
            key = str(tree_key)

        profile = cls._runtime_timing_profiles.setdefault(
            key,
            {
                "last_print": now,
                "samples": 0,
                "stages": {},
                "tree_name": tree_name,
                "interval": cls.RUNTIME_TIMING_PRINT_INTERVAL,
                "frame_level": bool(frame_level),
            },
        )
        profile["tree_name"] = tree_name
        profile["frame_level"] = bool(frame_level)
        if interval is not None:
            try:
                profile["interval"] = max(float(interval), 0.05)
            except Exception:
                profile["interval"] = cls.RUNTIME_TIMING_PRINT_INTERVAL
        profile["samples"] += 1

        totals = profile["stages"]
        for stage, seconds in stages.items():
            totals[stage] = totals.get(stage, 0.0) + float(seconds)

    @classmethod
    def flush_runtime_timing(cls, force=False):
        now = time.perf_counter()

        for key, profile in list(cls._runtime_timing_profiles.items()):
            elapsed = now - float(profile["last_print"])
            interval = max(float(profile.get("interval", cls.RUNTIME_TIMING_PRINT_INTERVAL)), 0.05)
            if not force and elapsed < interval:
                continue

            sample_count = int(profile["samples"])
            if sample_count <= 0:
                continue
            totals = profile["stages"]
            tree_name = profile.get("tree_name", key)
            frame_level = bool(profile.get("frame_level", False))
            print("\n".join(cls.format_runtime_timing_report(
                tree_name, elapsed, sample_count, totals, frame_level=frame_level
            )))

            cls._runtime_timing_profiles[key] = {
                "last_print": now,
                "samples": 0,
                "stages": {},
                "tree_name": tree_name,
                "interval": interval,
                "frame_level": frame_level,
            }

    @classmethod
    def publish_runtime_timing(cls, tree_name, tree_key, stages, interval=None):
        cls.record_runtime_timing(tree_name, tree_key, stages, interval=interval)
        cls.flush_runtime_timing()
