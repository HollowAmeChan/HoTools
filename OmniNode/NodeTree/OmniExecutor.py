from .OmniCompiler import CompiledGraph, OpCall, SubtreeCall
from .OmniDebug import OmniDebug


class OmniExecutor:

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
        trace, log = OmniDebug.make_runtime_logger(depth)

        log(f"{OmniDebug.section_label('Run')} Tree: {OmniDebug.tree_label(compiled.tree_name)}")
        for uid, reg in compiled.input_regs.items():
            if uid in provided_inputs:
                registers[reg] = provided_inputs[uid]
                log(
                    f"  {OmniDebug.section_label('Input')} {OmniDebug.value_label(uid)} -> "
                    f"{OmniDebug.reg_label(reg)} = {OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                )

        for step_index, op in enumerate(compiled.instructions):
            if isinstance(op, tuple):
                _, reg, value = op
                registers[reg] = value
                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('CONST')} {OmniDebug.reg_label(reg)} = "
                    f"{OmniDebug.value_label(OmniDebug.format_value(value))}"
                )
                continue

            if isinstance(op, OpCall):
                args = []
                arg_desc = []
                for inp in op.inputs:
                    if isinstance(inp, list):
                        values = [registers[reg] for reg in inp]
                        flat_values = OmniExecutor.flatten_runtime(values)
                        args.append(flat_values)
                        arg_desc.append(
                            "[" + ", ".join(
                                f"{OmniDebug.reg_label(reg)}={OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                                for reg in inp
                            ) + "]"
                        )
                    else:
                        args.append(registers[inp])
                        arg_desc.append(
                            f"{OmniDebug.reg_label(inp)}={OmniDebug.value_label(OmniDebug.format_value(registers[inp]))}"
                        )

                try:
                    result = op.func(*args)
                except Exception as exc:
                    op.node.set_bug_state(exc)
                    log(
                        f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                        f"{OmniDebug.error_label('ERROR')} in {OmniDebug.func_label(OmniDebug.func_name(op.func))} "
                        f"@ {OmniDebug.node_label(op.node.name)}: {OmniDebug.error_label(exc)}"
                    )
                    break

                if len(op.outputs) == 1:
                    registers[op.outputs[0]] = result
                    out_desc = (
                        f"{OmniDebug.reg_label(op.outputs[0])}="
                        f"{OmniDebug.value_label(OmniDebug.format_value(result))}"
                    )
                else:
                    for i, reg in enumerate(op.outputs):
                        registers[reg] = result[i]
                    out_desc = ", ".join(
                        f"{OmniDebug.reg_label(reg)}="
                        f"{OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                        for reg in op.outputs
                    )

                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('CALL')} {OmniDebug.func_label(OmniDebug.func_name(op.func))} "
                    f"@ {OmniDebug.node_label(op.node.name)} "
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
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('ENTER SUBTREE')} {OmniDebug.node_label(op.node.name)} -> "
                    f"{OmniDebug.tree_label(op.compiled_graph.tree_name)} "
                    f"inputs=({', '.join(f'{OmniDebug.value_label(uid)}={OmniDebug.value_label(OmniDebug.format_value(value))}' for uid, value in subtree_inputs.items())})"
                )

                try:
                    subtree_outputs, subtree_trace = OmniExecutor._execute(
                        op.compiled_graph,
                        subtree_inputs,
                        debug=debug,
                        depth=depth + 1,
                    )
                except Exception as exc:
                    op.node.set_bug_state(exc)
                    log(
                        f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                        f"{OmniDebug.error_label('ERROR')} in subtree {OmniDebug.node_label(op.node.name)}: "
                        f"{OmniDebug.error_label(exc)}"
                    )
                    break

                trace.extend(subtree_trace)
                ordered_output_uids = list(op.compiled_graph.output_regs.keys())
                for i, uid in enumerate(ordered_output_uids):
                    if i < len(op.outputs):
                        registers[op.outputs[i]] = subtree_outputs.get(uid)

                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('EXIT SUBTREE')} {OmniDebug.node_label(op.node.name)} outputs=("
                    + ", ".join(
                        f"{OmniDebug.reg_label(op.outputs[i])}="
                        f"{OmniDebug.value_label(OmniDebug.format_value(registers[op.outputs[i]]))}"
                        for i in range(min(len(op.outputs), len(ordered_output_uids)))
                    )
                    + ")"
                )

        result = {}
        for uid, reg in compiled.output_regs.items():
            result[uid] = registers[reg]

        log(
            f"  {OmniDebug.section_label('Final Outputs')}: "
            + (
                ", ".join(
                    f"{OmniDebug.value_label(uid)}={OmniDebug.value_label(OmniDebug.format_value(value))}"
                    for uid, value in result.items()
                )
                if result else OmniDebug.value_label("<none>")
            )
        )
        return result, trace

    @staticmethod
    def run(compiled: CompiledGraph, debug=False):
        result, trace = OmniExecutor._execute(compiled, debug=debug)
        if debug:
            print("\n".join(trace))
        return result
