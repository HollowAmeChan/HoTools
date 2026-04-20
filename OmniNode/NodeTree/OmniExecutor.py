from .OmniCompiler import CompiledGraph, OpCall, SubtreeCall


class OmniExecutor:
    COLOR_TERMINAL = {"displays_colors": False, "initialized": False}

    @staticmethod
    def _func_name(func):
        if func is None:
            return "<missing_func>"
        return getattr(func, "__name__", func.__class__.__name__)

    @staticmethod
    def _format_value(value):
        text = repr(value)
        if len(text) > 160:
            text = text[:157] + "..."
        return text

    @staticmethod
    def _init_terminal_colors():
        if OmniExecutor.COLOR_TERMINAL["initialized"]:
            return

        import os
        import sys

        can_paint = os.name in {"posix"}
        try:
            if hasattr(sys, "getwindowsversion"):
                if sys.getwindowsversion().major == 10:
                    can_paint = True
        except Exception:
            pass

        OmniExecutor.COLOR_TERMINAL["displays_colors"] = can_paint
        OmniExecutor.COLOR_TERMINAL["initialized"] = True

    @staticmethod
    def _str_color(text, color):
        OmniExecutor._init_terminal_colors()
        if OmniExecutor.COLOR_TERMINAL["displays_colors"]:
            return f"\033[1;{color}m{text}\033[0m"
        return str(text)

    @staticmethod
    def _section_label(text):
        return OmniExecutor._str_color(f"[{text}]", 96)

    @staticmethod
    def _tree_label(text):
        return OmniExecutor._str_color(f"<{text}>", 94)

    @staticmethod
    def _reg_label(reg):
        return OmniExecutor._str_color(f"r{reg}", 93)

    @staticmethod
    def _node_label(text):
        return OmniExecutor._str_color(text, 92)

    @staticmethod
    def _func_label(text):
        return OmniExecutor._str_color(text, 95)

    @staticmethod
    def _value_label(text):
        return OmniExecutor._str_color(str(text), 90)

    @staticmethod
    def _error_label(text):
        return OmniExecutor._str_color(f"ERROR: {text}", 91)

    @staticmethod
    def flatten_runtime(values):
        result = []
        for value in values:
            if isinstance(value, list):
                result.extend(value)
            else:
                result.append(value)
        return result

    @staticmethod
    def _execute(compiled: CompiledGraph, provided_inputs=None, debug=False, depth=0):
        registers = [None] * compiled.reg_count
        provided_inputs = provided_inputs or {}
        trace = []
        indent = "    " * depth

        def log(message):
            trace.append(f"{indent}{message}")

        log(f"{OmniExecutor._section_label('[Run]')} Tree: {OmniExecutor._tree_label(compiled.tree_name)}")
        for uid, reg in compiled.input_regs.items():
            if uid in provided_inputs:
                registers[reg] = provided_inputs[uid]
                log(
                    f"  {OmniExecutor._section_label('Input')} {OmniExecutor._value_label(uid)} -> "
                    f"{OmniExecutor._reg_label(reg)} = {OmniExecutor._value_label(OmniExecutor._format_value(registers[reg]))}"
                )

        for step_index, op in enumerate(compiled.instructions):
            if isinstance(op, tuple):
                _, reg, value = op
                registers[reg] = value
                log(
                    f"  {OmniExecutor._section_label(f'Step {step_index}')}: "
                    f"{OmniExecutor._func_label('CONST')} {OmniExecutor._reg_label(reg)} = "
                    f"{OmniExecutor._value_label(OmniExecutor._format_value(value))}"
                )
                continue

            if isinstance(op, OpCall):
                args = []
                arg_desc = []
                for inp in op.inputs:
                    if isinstance(inp, list):
                        values = [registers[r] for r in inp]
                        flat_values = OmniExecutor.flatten_runtime(values)
                        args.append(flat_values)
                        arg_desc.append(
                            "[" + ", ".join(
                                f"{OmniExecutor._reg_label(r)}={OmniExecutor._value_label(OmniExecutor._format_value(registers[r]))}"
                                for r in inp
                            ) + "]"
                        )
                    else:
                        args.append(registers[inp])
                        arg_desc.append(
                            f"{OmniExecutor._reg_label(inp)}={OmniExecutor._value_label(OmniExecutor._format_value(registers[inp]))}"
                        )

                try:
                    result = op.func(*args)
                except Exception as e:
                    op.node.is_bug = True
                    op.node.bug_text = str(e)
                    log(
                        f"  {OmniExecutor._section_label(f'Step {step_index}')}: "
                        f"{OmniExecutor._error_label('ERROR')} in {OmniExecutor._func_label(OmniExecutor._func_name(op.func))} "
                        f"@ {OmniExecutor._node_label(op.node.name)}: {OmniExecutor._error_label(e)}"
                    )
                    break

                if len(op.outputs) == 1:
                    registers[op.outputs[0]] = result
                    out_desc = (
                        f"{OmniExecutor._reg_label(op.outputs[0])}="
                        f"{OmniExecutor._value_label(OmniExecutor._format_value(result))}"
                    )
                else:
                    for i, reg in enumerate(op.outputs):
                        registers[reg] = result[i]
                    out_desc = ", ".join(
                        f"{OmniExecutor._reg_label(reg)}="
                        f"{OmniExecutor._value_label(OmniExecutor._format_value(registers[reg]))}"
                        for reg in op.outputs
                    )
                log(
                    f"  {OmniExecutor._section_label(f'Step {step_index}')}: "
                    f"{OmniExecutor._func_label('CALL')} {OmniExecutor._func_label(OmniExecutor._func_name(op.func))} "
                    f"@ {OmniExecutor._node_label(op.node.name)} "
                    f"args=({', '.join(arg_desc)}) -> {out_desc}"
                )
                continue

            if isinstance(op, SubtreeCall):
                subtree_inputs = {}
                ordered_input_uids = list(op.compiled_graph.input_regs.keys())
                for i, uid in enumerate(ordered_input_uids):
                    if i < len(op.inputs):
                        subtree_inputs[uid] = registers[op.inputs[i]]
                log(
                    f"  {OmniExecutor._section_label(f'Step {step_index}')}: "
                    f"{OmniExecutor._func_label('ENTER SUBTREE')} {OmniExecutor._node_label(op.node.name)} -> "
                    f"{OmniExecutor._tree_label(op.compiled_graph.tree_name)} "
                    f"inputs=({', '.join(f'{OmniExecutor._value_label(uid)}={OmniExecutor._value_label(OmniExecutor._format_value(value))}' for uid, value in subtree_inputs.items())})"
                )

                try:
                    subtree_outputs, subtree_trace = OmniExecutor._execute(
                        op.compiled_graph,
                        subtree_inputs,
                        debug=debug,
                        depth=depth + 1,
                    )
                except Exception as e:
                    op.node.is_bug = True
                    op.node.bug_text = str(e)
                    log(
                        f"  {OmniExecutor._section_label(f'Step {step_index}')}: "
                        f"{OmniExecutor._error_label('ERROR')} in subtree {OmniExecutor._node_label(op.node.name)}: "
                        f"{OmniExecutor._error_label(e)}"
                    )
                    break

                trace.extend(subtree_trace)
                ordered_output_uids = list(op.compiled_graph.output_regs.keys())
                for i, uid in enumerate(ordered_output_uids):
                    if i < len(op.outputs):
                        registers[op.outputs[i]] = subtree_outputs.get(uid)
                log(
                    f"  {OmniExecutor._section_label(f'Step {step_index}')}: "
                    f"{OmniExecutor._func_label('EXIT SUBTREE')} {OmniExecutor._node_label(op.node.name)} outputs=("
                    + ", ".join(
                        f"{OmniExecutor._reg_label(op.outputs[i])}="
                        f"{OmniExecutor._value_label(OmniExecutor._format_value(registers[op.outputs[i]]))}"
                        for i in range(min(len(op.outputs), len(ordered_output_uids)))
                    )
                    + ")"
                )

        result = {}
        for uid, reg in compiled.output_regs.items():
            result[uid] = registers[reg]
        log(
            f"  {OmniExecutor._section_label('Final Outputs')}: "
            + (
                ", ".join(
                    f"{OmniExecutor._value_label(uid)}={OmniExecutor._value_label(OmniExecutor._format_value(value))}"
                    for uid, value in result.items()
                )
                if result else OmniExecutor._value_label("<none>")
            )
        )
        return result, trace

    @staticmethod
    def run(compiled: CompiledGraph, debug=False):
        result, trace = OmniExecutor._execute(compiled, debug=debug)
        if debug:
            print("\n".join(trace))
        return result
