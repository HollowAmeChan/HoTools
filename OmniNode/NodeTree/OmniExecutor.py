from .OmniCompiler import (
    CompiledGraph,
    OpCall,
    SubtreeCall,
    BatchSubtreeCall,
    CacheReadCall,
    CacheWriteCall,
    CacheDeleteCall,
    CacheDumpCall,
    RuntimeTimingBeginCall,
    RuntimeTimingEndCall,
)
from .OmniDebug import OmniDebug
from . import OmniRuntimeState
import time


class OmniExecutor:
    @staticmethod
    def make_runtime_logger(debug, depth):
        if debug:
            return OmniDebug.make_runtime_logger(depth)

        def log(_message):
            return None

        return [], log

    @staticmethod
    def timing_token(value, fallback):
        text = str(value if value not in {None, ""} else fallback)
        text = "_".join(text.split())
        return text.replace(":", ".")

    @staticmethod
    def timing_stage_name(step_index, op):
        if isinstance(op, RuntimeTimingBeginCall):
            return None
        if isinstance(op, RuntimeTimingEndCall):
            return None
        if isinstance(op, tuple):
            return f"step{step_index}:CONST"
        if isinstance(op, OpCall):
            node_name = OmniExecutor.timing_token(getattr(getattr(op, "node", None), "name", None), "<node>")
            func_name = OmniExecutor.timing_token(OmniDebug.func_name(getattr(op, "func", None)), "<func>")
            return f"step{step_index}:{node_name}:{func_name}"
        if isinstance(op, SubtreeCall):
            node_name = OmniExecutor.timing_token(getattr(getattr(op, "node", None), "name", None), "<subtree>")
            tree_name = OmniExecutor.timing_token(getattr(getattr(op, "compiled_graph", None), "tree_name", None), "<tree>")
            return f"step{step_index}:{node_name}:SUBTREE:{tree_name}"
        if isinstance(op, BatchSubtreeCall):
            node_name = OmniExecutor.timing_token(getattr(getattr(op, "node", None), "name", None), "<batch>")
            tree_name = OmniExecutor.timing_token(getattr(getattr(op, "compiled_graph", None), "tree_name", None), "<tree>")
            return f"step{step_index}:{node_name}:BATCH:{tree_name}"
        if isinstance(op, CacheReadCall):
            node_name = OmniExecutor.timing_token(getattr(getattr(op, "node", None), "name", None), "<cache>")
            return f"step{step_index}:{node_name}:CACHE_READ"
        if isinstance(op, CacheWriteCall):
            node_name = OmniExecutor.timing_token(getattr(getattr(op, "node", None), "name", None), "<cache>")
            return f"step{step_index}:{node_name}:CACHE_WRITE"
        if isinstance(op, CacheDeleteCall):
            node_name = OmniExecutor.timing_token(getattr(getattr(op, "node", None), "name", None), "<cache>")
            return f"step{step_index}:{node_name}:CACHE_DELETE"
        if isinstance(op, CacheDumpCall):
            node_name = OmniExecutor.timing_token(getattr(getattr(op, "node", None), "name", None), "<cache>")
            return f"step{step_index}:{node_name}:CACHE_DUMP"
        return f"step{step_index}:{op.__class__.__name__}"

    @staticmethod
    def add_timing_stage(timing_stages, stage, seconds):
        if timing_stages is not None and stage:
            timing_stages[stage] = timing_stages.get(stage, 0.0) + float(seconds)

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
    def format_cache_snapshot(values):
        if not values:
            return "<empty>"

        lines = []
        for key in sorted(values.keys(), key=str):
            lines.append(f"{key}: {OmniDebug.format_value(values[key])}")
        return "\n".join(lines)

    @staticmethod
    def cache_key_input_value(registers, reg):
        if reg is None:
            return ""
        value = registers[reg]
        return "" if value is None else str(value)

    @staticmethod
    def _record_timing_end(compiled, op, timing_start, timing_stages):
        tree_ref = getattr(op, "tree_ref", None)
        if timing_start is None or not bool(getattr(tree_ref, "debug_runtime_timing", False)):
            return

        try:
            interval = float(getattr(tree_ref, "debug_runtime_timing_interval", 1.0))
        except Exception:
            interval = 1.0
        tree_key = getattr(compiled, "runtime_timing_tree_key", None)
        timing_stages = dict(timing_stages or {})
        timing_stages["total"] = time.perf_counter() - timing_start
        OmniDebug.record_runtime_timing(
            getattr(op, "tree_name", compiled.tree_name),
            tree_key,
            timing_stages,
            interval=interval,
        )

    @staticmethod
    def _execute_fast(
        compiled: CompiledGraph,
        provided_inputs=None,
        depth=0,
        runtime_context=None,
    ):
        registers = [None] * compiled.reg_count
        provided_inputs = provided_inputs or {}
        timing_start = None
        timing_stages = None

        for uid, reg in compiled.input_regs.items():
            if uid in provided_inputs:
                registers[reg] = provided_inputs[uid]

        for step_index, op in enumerate(compiled.instructions):
            if isinstance(op, RuntimeTimingBeginCall):
                tree_ref = getattr(op, "tree_ref", None)
                if bool(getattr(tree_ref, "debug_runtime_timing", False)):
                    timing_start = time.perf_counter()
                    timing_stages = {}
                continue

            if isinstance(op, RuntimeTimingEndCall):
                OmniExecutor._record_timing_end(compiled, op, timing_start, timing_stages)
                continue

            op_timing_start = time.perf_counter() if timing_stages is not None else None
            op_timing_stage = OmniExecutor.timing_stage_name(step_index, op) if timing_stages is not None else None

            if isinstance(op, tuple):
                _, reg, value = op
                registers[reg] = value
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)
                continue

            if isinstance(op, CacheReadCall):
                key_value = OmniExecutor.cache_key_input_value(registers, getattr(op, "cache_key_input", None))
                cache_key = OmniRuntimeState.cache_key_for_node(op.node, key_value)

                try:
                    hit, value = OmniRuntimeState.read_cache(runtime_context, cache_key)
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    break

                if len(op.outputs) > 0:
                    registers[op.outputs[0]] = value
                if len(op.outputs) > 1:
                    registers[op.outputs[1]] = hit
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)
                continue

            if isinstance(op, CacheWriteCall):
                value = registers[op.value_input] if op.value_input is not None else None
                enabled = bool(registers[op.enabled_input]) if op.enabled_input is not None else True
                key_value = OmniExecutor.cache_key_input_value(registers, getattr(op, "cache_key_input", None))
                cache_key = OmniRuntimeState.cache_key_for_node(op.node, key_value)

                if enabled:
                    try:
                        OmniRuntimeState.write_cache(runtime_context, cache_key, value)
                    except Exception as exc:
                        runtime_context.mark_failed()
                        op.node.set_bug_state(exc)
                        break

                for reg in op.outputs:
                    registers[reg] = value
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)
                continue

            if isinstance(op, CacheDeleteCall):
                trigger_value = registers[op.trigger_input] if op.trigger_input is not None else None
                enabled = bool(registers[op.enabled_input]) if op.enabled_input is not None else False
                cache_key = OmniExecutor.cache_key_input_value(registers, getattr(op, "cache_key_input", None)).strip()
                delete_all = bool(registers[op.delete_all_input]) if getattr(op, "delete_all_input", None) is not None else False
                deleted_count = 0

                try:
                    if enabled:
                        if delete_all:
                            deleted_count = OmniRuntimeState.clear_namespace(runtime_context)
                        elif cache_key:
                            deleted_count = OmniRuntimeState.delete_cache(runtime_context, cache_key)
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    break

                output_values = [trigger_value, deleted_count, enabled and (delete_all or bool(cache_key))]
                for index, reg in enumerate(op.outputs):
                    registers[reg] = output_values[index] if index < len(output_values) else None
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)
                continue

            if isinstance(op, CacheDumpCall):
                trigger_value = registers[op.trigger_input] if op.trigger_input is not None else None
                label_value = registers[op.label_input] if getattr(op, "label_input", None) is not None else ""
                label = str(label_value).strip() if label_value is not None else ""
                title = label or op.node.name

                try:
                    cache_values = OmniRuntimeState.snapshot_cache(runtime_context)
                    body = OmniExecutor.format_cache_snapshot(cache_values)
                    text = f"[OmniNode Cache] {title} ({len(cache_values)} item(s))\n{body}"
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    break

                if getattr(op, "print_to_console", True):
                    print(text)

                output_values = [trigger_value, text, len(cache_values)]
                for index, reg in enumerate(op.outputs):
                    registers[reg] = output_values[index] if index < len(output_values) else None
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)
                continue

            if isinstance(op, OpCall):
                args = []
                for inp in op.inputs:
                    if isinstance(inp, list):
                        args.append(OmniExecutor.flatten_runtime([registers[reg] for reg in inp]))
                    else:
                        args.append(registers[inp])

                try:
                    result = op.func(*args)
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    break

                if len(op.outputs) == 1:
                    registers[op.outputs[0]] = result
                else:
                    for index, reg in enumerate(op.outputs):
                        registers[reg] = result[index]
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)
                continue

            if isinstance(op, SubtreeCall):
                subtree_inputs = {}
                ordered_input_uids = list(op.compiled_graph.input_regs.keys())
                for index, uid in enumerate(ordered_input_uids):
                    if index < len(op.inputs):
                        subtree_inputs[uid] = registers[op.inputs[index]]

                try:
                    subtree_outputs, _ = OmniExecutor._execute_fast(
                        op.compiled_graph,
                        subtree_inputs,
                        depth=depth + 1,
                        runtime_context=runtime_context.descend_group(
                            op.node,
                            getattr(op.compiled_graph, "tree_ref", None),
                        ),
                    )
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    break

                ordered_output_uids = list(op.compiled_graph.output_regs.keys())
                for index, uid in enumerate(ordered_output_uids):
                    if index < len(op.outputs):
                        registers[op.outputs[index]] = subtree_outputs.get(uid)
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)
                continue

            if isinstance(op, BatchSubtreeCall):
                ordered_input_uids = list(op.compiled_graph.input_regs.keys())
                ordered_output_uids = list(op.compiled_graph.output_regs.keys())

                if op.batch_input_index >= len(op.inputs):
                    runtime_context.mark_failed()
                    op.node.set_bug_state("Batch input index out of range")
                    break

                batch_regs = op.inputs[op.batch_input_index]
                if not isinstance(batch_regs, list):
                    batch_regs = [batch_regs]

                batch_values = OmniExecutor.flatten_runtime([registers[reg] for reg in batch_regs])

                base_inputs = {}
                for index, uid in enumerate(ordered_input_uids):
                    if index >= len(op.inputs) or index == op.batch_input_index:
                        continue
                    base_inputs[uid] = registers[op.inputs[index]]

                collected_outputs = {uid: [] for uid in ordered_output_uids}
                try:
                    batch_uid = ordered_input_uids[op.batch_input_index]
                    for batch_index, batch_value in enumerate(batch_values):
                        subtree_inputs = dict(base_inputs)
                        subtree_inputs[batch_uid] = batch_value

                        subtree_outputs, _ = OmniExecutor._execute_fast(
                            op.compiled_graph,
                            subtree_inputs,
                            depth=depth + 1,
                            runtime_context=runtime_context.descend_batch_item(
                                op.node,
                                getattr(op.compiled_graph, "tree_ref", None),
                                batch_index,
                            ),
                        )

                        for uid in ordered_output_uids:
                            collected_outputs[uid].append(subtree_outputs.get(uid))
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    break

                for index, uid in enumerate(ordered_output_uids):
                    if index < len(op.outputs):
                        registers[op.outputs[index]] = collected_outputs.get(uid, [])
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(timing_stages, op_timing_stage, time.perf_counter() - op_timing_start)

        result = {}
        for uid, reg in compiled.output_regs.items():
            result[uid] = registers[reg]

        return result, []

    @staticmethod
    def _execute(
        compiled: CompiledGraph,
        provided_inputs=None,
        debug=False,
        depth=0,
        runtime_context=None,
    ):
        if runtime_context is None:
            runtime_context = OmniRuntimeState.begin_run(getattr(compiled, "tree_ref", None))
            try:
                return OmniExecutor._execute(
                    compiled,
                    provided_inputs=provided_inputs,
                    debug=debug,
                    depth=depth,
                    runtime_context=runtime_context,
                )
            except Exception:
                runtime_context.mark_failed()
                raise
            finally:
                OmniRuntimeState.finish_run(runtime_context)

        if not debug:
            return OmniExecutor._execute_fast(
                compiled,
                provided_inputs=provided_inputs,
                depth=depth,
                runtime_context=runtime_context,
            )

        registers = [None] * compiled.reg_count
        provided_inputs = provided_inputs or {}
        trace, log = OmniExecutor.make_runtime_logger(debug, depth)
        timing_start = None
        timing_stages = None

        log(f"{OmniDebug.section_label('Run')} Tree: {OmniDebug.tree_label(compiled.tree_name)}")
        for uid, reg in compiled.input_regs.items():
            if uid in provided_inputs:
                registers[reg] = provided_inputs[uid]
                log(
                    f"  {OmniDebug.section_label('Input')} {OmniDebug.value_label(uid)} -> "
                    f"{OmniDebug.reg_label(reg)} = {OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                )

        for step_index, op in enumerate(compiled.instructions):
            if isinstance(op, RuntimeTimingBeginCall):
                tree_ref = getattr(op, "tree_ref", None)
                if bool(getattr(tree_ref, "debug_runtime_timing", False)):
                    timing_start = time.perf_counter()
                    timing_stages = {}
                continue

            if isinstance(op, RuntimeTimingEndCall):
                tree_ref = getattr(op, "tree_ref", None)
                if timing_start is not None and bool(getattr(tree_ref, "debug_runtime_timing", False)):
                    try:
                        interval = float(getattr(tree_ref, "debug_runtime_timing_interval", 1.0))
                    except Exception:
                        interval = 1.0
                    tree_key = getattr(compiled, "runtime_timing_tree_key", None)
                    timing_stages = dict(timing_stages or {})
                    timing_stages["total"] = time.perf_counter() - timing_start
                    OmniDebug.record_runtime_timing(
                        getattr(op, "tree_name", compiled.tree_name),
                        tree_key,
                        timing_stages,
                        interval=interval,
                    )
                continue

            op_timing_start = time.perf_counter() if timing_stages is not None else None
            op_timing_stage = OmniExecutor.timing_stage_name(step_index, op) if timing_stages is not None else None

            if isinstance(op, tuple):
                _, reg, value = op
                registers[reg] = value
                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('CONST')} {OmniDebug.reg_label(reg)} = "
                    f"{OmniDebug.value_label(OmniDebug.format_value(value))}"
                )
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
                    )
                continue

            if isinstance(op, CacheReadCall):
                key_value = OmniExecutor.cache_key_input_value(registers, getattr(op, "cache_key_input", None))
                cache_key = OmniRuntimeState.cache_key_for_node(op.node, key_value)

                try:
                    hit, value = OmniRuntimeState.read_cache(runtime_context, cache_key)
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    log(
                        f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                        f"{OmniDebug.error_label('ERROR')} in cache read "
                        f"@ {OmniDebug.node_label(op.node.name)}: {OmniDebug.error_label(exc)}"
                    )
                    break

                if len(op.outputs) > 0:
                    registers[op.outputs[0]] = value
                if len(op.outputs) > 1:
                    registers[op.outputs[1]] = hit

                out_desc = []
                if len(op.outputs) > 0:
                    out_desc.append(
                        f"{OmniDebug.reg_label(op.outputs[0])}="
                        f"{OmniDebug.value_label(OmniDebug.format_value(value))}"
                    )
                if len(op.outputs) > 1:
                    out_desc.append(
                        f"{OmniDebug.reg_label(op.outputs[1])}="
                        f"{OmniDebug.value_label(OmniDebug.format_value(hit))}"
                    )

                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('CACHE READ')} {OmniDebug.node_label(op.node.name)} "
                    f"key={OmniDebug.value_label(cache_key)} hit={OmniDebug.value_label(hit)} "
                    f"-> {', '.join(out_desc)}"
                )
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
                    )
                continue

            if isinstance(op, CacheWriteCall):
                value = registers[op.value_input] if op.value_input is not None else None
                enabled = bool(registers[op.enabled_input]) if op.enabled_input is not None else True
                key_value = OmniExecutor.cache_key_input_value(registers, getattr(op, "cache_key_input", None))
                cache_key = OmniRuntimeState.cache_key_for_node(op.node, key_value)

                if enabled:
                    try:
                        OmniRuntimeState.write_cache(runtime_context, cache_key, value)
                    except Exception as exc:
                        runtime_context.mark_failed()
                        op.node.set_bug_state(exc)
                        log(
                            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                            f"{OmniDebug.error_label('ERROR')} in cache write "
                            f"@ {OmniDebug.node_label(op.node.name)}: {OmniDebug.error_label(exc)}"
                        )
                        break

                for reg in op.outputs:
                    registers[reg] = value

                out_desc = ", ".join(
                    f"{OmniDebug.reg_label(reg)}={OmniDebug.value_label(OmniDebug.format_value(value))}"
                    for reg in op.outputs
                )
                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('CACHE WRITE')} {OmniDebug.node_label(op.node.name)} "
                    f"key={OmniDebug.value_label(cache_key)} enabled={OmniDebug.value_label(enabled)} value="
                    f"{OmniDebug.value_label(OmniDebug.format_value(value))} -> {out_desc}"
                )
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
                    )
                continue

            if isinstance(op, CacheDeleteCall):
                trigger_value = registers[op.trigger_input] if op.trigger_input is not None else None
                enabled = bool(registers[op.enabled_input]) if op.enabled_input is not None else False
                cache_key = OmniExecutor.cache_key_input_value(registers, getattr(op, "cache_key_input", None)).strip()
                delete_all = bool(registers[op.delete_all_input]) if getattr(op, "delete_all_input", None) is not None else False
                deleted_count = 0

                try:
                    if enabled:
                        if delete_all:
                            deleted_count = OmniRuntimeState.clear_namespace(runtime_context)
                        elif cache_key:
                            deleted_count = OmniRuntimeState.delete_cache(runtime_context, cache_key)
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    log(
                        f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                        f"{OmniDebug.error_label('ERROR')} in cache delete "
                        f"@ {OmniDebug.node_label(op.node.name)}: {OmniDebug.error_label(exc)}"
                    )
                    break

                output_values = [trigger_value, deleted_count, enabled and (delete_all or bool(cache_key))]
                for index, reg in enumerate(op.outputs):
                    registers[reg] = output_values[index] if index < len(output_values) else None

                out_desc = ", ".join(
                    f"{OmniDebug.reg_label(reg)}={OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                    for reg in op.outputs
                )
                mode = "all" if delete_all else (cache_key or "<empty>")
                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('CACHE DELETE')} {OmniDebug.node_label(op.node.name)} "
                    f"enabled={OmniDebug.value_label(enabled)} target={OmniDebug.value_label(mode)} "
                    f"deleted={OmniDebug.value_label(deleted_count)} -> {out_desc}"
                )
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
                    )
                continue

            if isinstance(op, CacheDumpCall):
                trigger_value = registers[op.trigger_input] if op.trigger_input is not None else None
                label_value = registers[op.label_input] if getattr(op, "label_input", None) is not None else ""
                label = str(label_value).strip() if label_value is not None else ""
                title = label or op.node.name

                try:
                    cache_values = OmniRuntimeState.snapshot_cache(runtime_context)
                    body = OmniExecutor.format_cache_snapshot(cache_values)
                    text = f"[OmniNode Cache] {title} ({len(cache_values)} item(s))\n{body}"
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    log(
                        f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                        f"{OmniDebug.error_label('ERROR')} in cache dump "
                        f"@ {OmniDebug.node_label(op.node.name)}: {OmniDebug.error_label(exc)}"
                    )
                    break

                if getattr(op, "print_to_console", True):
                    print(text)

                output_values = [trigger_value, text, len(cache_values)]
                for index, reg in enumerate(op.outputs):
                    registers[reg] = output_values[index] if index < len(output_values) else None

                out_desc = ", ".join(
                    f"{OmniDebug.reg_label(reg)}={OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                    for reg in op.outputs
                )
                log(
                    f"  {OmniDebug.section_label(f'Step {step_index}')}: "
                    f"{OmniDebug.func_label('CACHE DUMP')} {OmniDebug.node_label(op.node.name)} "
                    f"title={OmniDebug.value_label(title)} count={OmniDebug.value_label(len(cache_values))} -> {out_desc}"
                )
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
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
                    runtime_context.mark_failed()
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
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
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
                        runtime_context=runtime_context.descend_group(
                            op.node,
                            getattr(op.compiled_graph, "tree_ref", None),
                        ),
                    )
                except Exception as exc:
                    runtime_context.mark_failed()
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
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
                    )
                continue

            if isinstance(op, BatchSubtreeCall):
                ordered_input_uids = list(op.compiled_graph.input_regs.keys())
                ordered_output_uids = list(op.compiled_graph.output_regs.keys())

                if op.batch_input_index >= len(op.inputs):
                    runtime_context.mark_failed()
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
                            runtime_context=runtime_context.descend_batch_item(
                                op.node,
                                getattr(op.compiled_graph, "tree_ref", None),
                                batch_index,
                            ),
                        )
                        trace.extend(subtree_trace)

                        for uid in ordered_output_uids:
                            collected_outputs[uid].append(subtree_outputs.get(uid))
                except Exception as exc:
                    runtime_context.mark_failed()
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
                if op_timing_start is not None:
                    OmniExecutor.add_timing_stage(
                        timing_stages,
                        op_timing_stage,
                        time.perf_counter() - op_timing_start,
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
        runtime_context = OmniRuntimeState.begin_run(getattr(compiled, "tree_ref", None))
        try:
            result, trace = OmniExecutor._execute(compiled, debug=debug, runtime_context=runtime_context)
        except Exception:
            runtime_context.mark_failed()
            raise
        finally:
            OmniRuntimeState.finish_run(runtime_context)
        if debug:
            print("\n".join(trace))
        return result
