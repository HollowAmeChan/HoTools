from .OmniCompiler import CompiledGraph, OmniCompiler, OpCall, SubtreeCall, BatchSubtreeCall
from .OmniDebug import OmniDebug
from . import OmniMenuBind


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
    def _execute(compiled: CompiledGraph, provided_inputs=None, debug=False, depth=0, batch_bind_context=None):
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
                node_idname = getattr(op.node, "bl_idname", "")
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

                if node_idname == OmniCompiler.BIND_NODE_IDNAME:
                    if batch_bind_context is not None:
                        OmniMenuBind.capture_batch_bind_node_runtime_context(
                            batch_bind_context["tree"],
                            batch_bind_context["batch_owner_node"],
                            op.node,
                            args,
                            getattr(op, "processor_graph", None),
                            bind_path=batch_bind_context.get("bind_path"),
                            instance_meta={
                                "iteration_index": batch_bind_context.get("iteration_index", -1),
                                "batch_value": batch_bind_context.get("batch_value"),
                            },
                        )
                    else:
                        OmniMenuBind.capture_bind_node_runtime_context(
                            getattr(compiled, "tree_ref", None),
                            op.node,
                            args,
                            getattr(op, "processor_graph", None),
                        )

                try:
                    if node_idname == OmniCompiler.BIND_NODE_IDNAME:
                        value = OmniMenuBind.get_parameter_value_from_args(op.node, args)
                        result = OmniMenuBind.execute_bind_node_update(
                            op.node,
                            args,
                            value,
                            getattr(op, "processor_graph", None),
                        )
                    else:
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
                        batch_bind_context=(
                            {
                                **batch_bind_context,
                                "bind_path": list(batch_bind_context.get("bind_path") or [])
                                + [getattr(op.compiled_graph, "tree_name", "") or getattr(op.node, "name", "")]
                            }
                            if batch_bind_context is not None else None
                        ),
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
                continue

            if isinstance(op, BatchSubtreeCall):
                ordered_input_uids = list(op.compiled_graph.input_regs.keys())
                ordered_output_uids = list(op.compiled_graph.output_regs.keys())

                if op.batch_input_index >= len(op.inputs):
                    op.node.set_bug_state("Batch input index out of range")
                    log(
                        f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                        f"{OmniDebug.error_label('ERROR')} invalid batch input index on "
                        f"{OmniDebug.node_label(op.node.name)}"
                    )
                    break

                batch_regs = op.inputs[op.batch_input_index]
                if not isinstance(batch_regs, list):
                    batch_regs = [batch_regs]

                batch_values = OmniExecutor.flatten_runtime([registers[reg] for reg in batch_regs])

                base_inputs = {}
                for i, uid in enumerate(ordered_input_uids):
                    if i >= len(op.inputs) or i == op.batch_input_index:
                        continue
                    base_inputs[uid] = registers[op.inputs[i]]

                collected_outputs = {uid: [] for uid in ordered_output_uids}

                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('ENTER BATCH SUBTREE')} {OmniDebug.node_label(op.node.name)} -> "
                    f"{OmniDebug.tree_label(op.compiled_graph.tree_name)} "
                    f"batch_count={OmniDebug.value_label(len(batch_values))}"
                )

                try:
                    batch_uid = ordered_input_uids[op.batch_input_index]
                    for batch_index, batch_value in enumerate(batch_values):
                        subtree_inputs = dict(base_inputs)
                        subtree_inputs[batch_uid] = batch_value

                        log(
                            f"    {OmniDebug.section_label(f'Batch {batch_index}')}: "
                            f"{OmniDebug.value_label(batch_uid)}="
                            f"{OmniDebug.value_label(OmniDebug.format_value(batch_value))}"
                        )

                        subtree_outputs, subtree_trace = OmniExecutor._execute(
                            op.compiled_graph,
                            subtree_inputs,
                            debug=debug,
                            depth=depth + 1,
                            batch_bind_context={
                                "tree": getattr(compiled, "tree_ref", None),
                                "batch_owner_node": op.node,
                                "bind_path": [],
                                "iteration_index": batch_index,
                                "batch_value": batch_value,
                            },
                        )
                        trace.extend(subtree_trace)

                        for uid in ordered_output_uids:
                            collected_outputs[uid].append(subtree_outputs.get(uid))
                except Exception as exc:
                    op.node.set_bug_state(exc)
                    log(
                        f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                        f"{OmniDebug.error_label('ERROR')} in batch subtree {OmniDebug.node_label(op.node.name)}: "
                        f"{OmniDebug.error_label(exc)}"
                    )
                    break

                for i, uid in enumerate(ordered_output_uids):
                    if i < len(op.outputs):
                        registers[op.outputs[i]] = collected_outputs.get(uid, [])

                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('EXIT BATCH SUBTREE')} {OmniDebug.node_label(op.node.name)} outputs=("
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
