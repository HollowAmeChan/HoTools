import os
import sys


class OmniDebug:
    COLOR_TERMINAL = {"displays_colors": False, "initialized": False}

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

        for op in graph.instructions:
            if isinstance(op, subtree_call_type):
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
    def make_runtime_logger(depth):
        trace = []
        indent = "    " * depth

        def log(message):
            trace.append(f"{indent}{message}")

        return trace, log
