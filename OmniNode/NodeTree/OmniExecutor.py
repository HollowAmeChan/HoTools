from .OmniIR import (
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
from .OmniTracy import omni_zone, omni_frame_mark, tracy_enabled
import time


class RuntimeObserver:
    def __init__(self, debug=False, depth=0, trace=None, timing_collector=None):
        self.debug = bool(debug)
        self.depth = int(depth)
        self.trace = [] if trace is None else trace
        self.timing_start = None
        self.timing_stages = None
        # 若提供收集器，则顶层 step 明细并入该字典（帧链路报告），
        # 不再单独成一个报告块。子树仍走各自的独立报告。
        self.timing_collector = timing_collector
        # Tracy zone 句柄：仅在 Tracy 构建下非 None
        self._tracy_tree_zone = None   # 树级 zone（整棵树执行期间）
        self._tracy_step_zone = None   # 当前 step zone（step_begin→step_end）
        # 懒求值计数器（每帧重置，end_timing 时写入 timing_stages）
        self._lazy_nodes_run     = 0
        self._lazy_nodes_skipped = 0

    def child(self):
        # 子树 observer 不继承父级 zone 句柄，各自独立管理
        return RuntimeObserver(
            debug=self.debug,
            depth=self.depth + 1,
            trace=self.trace,
        )

    def log(self, message):
        if self.debug:
            self.trace.append(f"{'    ' * self.depth}{message}")

    def begin_tree(self, compiled):
        # Tracy：为整棵树的执行开一个顶级 zone
        if tracy_enabled():
            tree_name = getattr(compiled, "tree_name", "<tree>") or "<tree>"
            zone_name = f"OmniNode/Tree/{tree_name}"
            self._tracy_tree_zone = omni_zone(zone_name)
            self._tracy_tree_zone.__enter__()
        if not self.debug:
            return
        self.log(f"{OmniDebug.section_label('Run')} Tree: {OmniDebug.tree_label(compiled.tree_name)}")

    def input_value(self, uid, reg, value):
        if not self.debug:
            return
        self.log(
            f"  {OmniDebug.section_label('Input')} {OmniDebug.value_label(uid)} -> "
            f"{OmniDebug.reg_label(reg)} = {OmniDebug.value_label(OmniDebug.format_value(value))}"
        )

    def begin_timing(self, op):
        tree_ref = getattr(op, "tree_ref", None)
        if bool(getattr(tree_ref, "debug_runtime_timing", False)):
            self.timing_start = time.perf_counter()
            self.timing_stages = {}
            # 每帧重置懒求值计数器
            self._lazy_nodes_run     = 0
            self._lazy_nodes_skipped = 0

    def end_timing(self, compiled, op):
        tree_ref = getattr(op, "tree_ref", None)
        if self.timing_start is None or not bool(getattr(tree_ref, "debug_runtime_timing", False)):
            return

        try:
            interval = float(getattr(tree_ref, "debug_runtime_timing_interval", 1.0))
        except Exception:
            interval = 1.0

        stages = dict(self.timing_stages or {})

        # 把懒求值计数写入 stages（值为计数，后续报告特殊处理不当成毫秒）
        if self._lazy_nodes_run or self._lazy_nodes_skipped:
            stages["[lazy] nodes_run"]     = float(self._lazy_nodes_run)
            stages["[lazy] nodes_skipped"] = float(self._lazy_nodes_skipped)

        # 顶层有收集器时，step 明细并入帧链路报告（不再单独成块），
        # 且不写入 total，避免与帧链路的聚合项重复计数。
        if self.timing_collector is not None:
            for stage, seconds in stages.items():
                self.timing_collector[stage] = (
                    self.timing_collector.get(stage, 0.0) + float(seconds)
                )
            return

        stages["total"] = time.perf_counter() - self.timing_start
        OmniDebug.record_runtime_timing(
            getattr(op, "tree_name", compiled.tree_name),
            getattr(compiled, "runtime_timing_tree_key", None),
            stages,
            interval=interval,
        )

    def step_begin(self, step_index, op):
        # Tracy：为当前 step 开一个 zone
        if tracy_enabled():
            stage_name = OmniExecutor.timing_stage_name(step_index, op)
            zone_name = f"OmniNode/{stage_name}" if stage_name else f"OmniNode/step{step_index}"
            self._tracy_step_zone = omni_zone(zone_name)
            self._tracy_step_zone.__enter__()
        if self.timing_stages is None:
            return None, None
        return time.perf_counter(), OmniExecutor.timing_stage_name(step_index, op)

    def step_end(self, start_time, stage):
        # Tracy：关闭当前 step zone
        if self._tracy_step_zone is not None:
            self._tracy_step_zone.__exit__(None, None, None)
            self._tracy_step_zone = None
        if start_time is not None and stage:
            self.timing_stages[stage] = self.timing_stages.get(stage, 0.0) + (
                time.perf_counter() - start_time
            )

    def const(self, step_index, reg, value):
        if not self.debug:
            return
        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('CONST')} {OmniDebug.reg_label(reg)} = "
            f"{OmniDebug.value_label(OmniDebug.format_value(value))}"
        )

    def cache_read(self, step_index, op, cache_key, hit, value):
        if not self.debug:
            return

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

        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('CACHE READ')} {OmniDebug.node_label(op.node.name)} "
            f"key={OmniDebug.value_label(cache_key)} hit={OmniDebug.value_label(hit)} "
            f"-> {', '.join(out_desc)}"
        )

    def cache_write(self, step_index, op, cache_key, enabled, value):
        if not self.debug:
            return

        out_desc = ", ".join(
            f"{OmniDebug.reg_label(reg)}={OmniDebug.value_label(OmniDebug.format_value(value))}"
            for reg in op.outputs
        )
        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('CACHE WRITE')} {OmniDebug.node_label(op.node.name)} "
            f"key={OmniDebug.value_label(cache_key)} enabled={OmniDebug.value_label(enabled)} value="
            f"{OmniDebug.value_label(OmniDebug.format_value(value))} -> {out_desc}"
        )

    def cache_delete(self, step_index, op, registers, enabled, mode, deleted_count):
        if not self.debug:
            return

        out_desc = ", ".join(
            f"{OmniDebug.reg_label(reg)}={OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
            for reg in op.outputs
        )
        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('CACHE DELETE')} {OmniDebug.node_label(op.node.name)} "
            f"enabled={OmniDebug.value_label(enabled)} target={OmniDebug.value_label(mode)} "
            f"deleted={OmniDebug.value_label(deleted_count)} -> {out_desc}"
        )

    def cache_dump(self, step_index, op, registers, title, cache_count):
        if not self.debug:
            return

        out_desc = ", ".join(
            f"{OmniDebug.reg_label(reg)}={OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
            for reg in op.outputs
        )
        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('CACHE DUMP')} {OmniDebug.node_label(op.node.name)} "
            f"title={OmniDebug.value_label(title)} count={OmniDebug.value_label(cache_count)} -> {out_desc}"
        )

    def call(self, step_index, op, arg_desc, out_desc):
        if not self.debug:
            return

        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('CALL')} {OmniDebug.func_label(OmniDebug.func_name(op.func))} "
            f"@ {OmniDebug.node_label(op.node.name)} "
            f"args=({', '.join(arg_desc)}) -> {out_desc}"
        )

    def enter_subtree(self, step_index, op, subtree_inputs):
        if not self.debug:
            return

        input_desc = ", ".join(
            f"{OmniDebug.value_label(uid)}={OmniDebug.value_label(OmniDebug.format_value(value))}"
            for uid, value in subtree_inputs.items()
        )
        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('ENTER SUBTREE')} {OmniDebug.node_label(op.node.name)} -> "
            f"{OmniDebug.tree_label(op.compiled_graph.tree_name)} inputs=({input_desc})"
        )

    def exit_subtree(self, step_index, op, registers, ordered_output_uids):
        if not self.debug:
            return

        out_desc = ", ".join(
            f"{OmniDebug.reg_label(op.outputs[index])}="
            f"{OmniDebug.value_label(OmniDebug.format_value(registers[op.outputs[index]]))}"
            for index in range(min(len(op.outputs), len(ordered_output_uids)))
        )
        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('EXIT SUBTREE')} {OmniDebug.node_label(op.node.name)} "
            f"outputs=({out_desc})"
        )

    def enter_batch_subtree(self, step_index, op, batch_count):
        if not self.debug:
            return

        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('ENTER BATCH SUBTREE')} {OmniDebug.node_label(op.node.name)} -> "
            f"{OmniDebug.tree_label(op.compiled_graph.tree_name)} "
            f"batch_count={OmniDebug.value_label(batch_count)}"
        )

    def batch_item(self, batch_index, batch_uid, batch_value):
        if not self.debug:
            return

        self.log(
            f"    {OmniDebug.section_label(f'Batch {batch_index}')}: "
            f"{OmniDebug.value_label(batch_uid)}="
            f"{OmniDebug.value_label(OmniDebug.format_value(batch_value))}"
        )

    def exit_batch_subtree(self, step_index, op, registers, ordered_output_uids):
        if not self.debug:
            return

        out_desc = ", ".join(
            f"{OmniDebug.reg_label(op.outputs[index])}="
            f"{OmniDebug.value_label(OmniDebug.format_value(registers[op.outputs[index]]))}"
            for index in range(min(len(op.outputs), len(ordered_output_uids)))
        )
        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.func_label('EXIT BATCH SUBTREE')} {OmniDebug.node_label(op.node.name)} "
            f"outputs=({out_desc})"
        )

    def error(self, step_index, message):
        # Tracy：执行出错时 step_end 不会被调用，这里负责关闭残留的 step zone
        if self._tracy_step_zone is not None:
            self._tracy_step_zone.__exit__(None, None, None)
            self._tracy_step_zone = None
        if not self.debug:
            return

        self.log(
            f"  {OmniDebug.section_label(f'Step {step_index}')}: "
            f"{OmniDebug.error_label(message)}"
        )

    def final_outputs(self, result):
        # Tracy：关闭树级 zone
        if self._tracy_tree_zone is not None:
            self._tracy_tree_zone.__exit__(None, None, None)
            self._tracy_tree_zone = None
        if not self.debug:
            return

        self.log(
            f"  {OmniDebug.section_label('Final Outputs')}: "
            + (
                ", ".join(
                    f"{OmniDebug.value_label(uid)}={OmniDebug.value_label(OmniDebug.format_value(value))}"
                    for uid, value in result.items()
                )
                if result else OmniDebug.value_label("<none>")
            )
        )

    # ── 懒求值 debug 方法 ─────────────────────────────────────────────────────

    def log_skip(self, op):
        """节点被 skip：所有输入版本号与上帧相同。"""
        if not self.debug:
            return
        node_name = getattr(getattr(op, "node", None), "name", "<node>")
        self.log(f"  {OmniDebug.section_label('SKIP')}     {OmniDebug.node_label(node_name)} — inputs unchanged")

    def log_no_change(self, op, output_index):
        """节点执行后返回 OMNI_NO_CHANGE：输出版本号不递增。"""
        if not self.debug:
            return
        node_name = getattr(getattr(op, "node", None), "name", "<node>")
        self.log(f"  {OmniDebug.section_label('NO_CHG')}   {OmniDebug.node_label(node_name)}.output{output_index} — version not bumped")

    def log_subtree_skip(self, call):
        """SubtreeCall 整块被 skip。"""
        if not self.debug:
            return
        tree_name = getattr(getattr(call, "compiled_graph", None), "tree_name", "<subtree>")
        node_name = getattr(getattr(call, "node", None), "name", "<node>")
        self.log(f"  {OmniDebug.section_label('SKIP_ST')}  SubtreeCall({OmniDebug.node_label(node_name)}) -> {OmniDebug.tree_label(tree_name)} — inputs unchanged")


class OmniExecutor:
    @staticmethod
    def ensure_compiled_graph_enabled(compiled):
        tree_ref = getattr(compiled, "tree_ref", None)
        if tree_ref is not None and not bool(getattr(tree_ref, "is_execution_enabled", True)):
            tree_name = getattr(tree_ref, "name", None) or getattr(compiled, "tree_name", "<tree>")
            raise RuntimeError(f"OmniNodeTree '{tree_name}' is disabled")

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
    def _write_reg(graph, reg, value):
        """
        写入寄存器并维护版本号。
        - value is OMNI_NO_CHANGE → 版本不递增，reg_values 不修改
        - value is not 旧值（身份比较） → 版本 +1，reg_values 更新
        - value is 旧值 → 不递增（幂等写入）
        """
        from .OmniIR import OMNI_NO_CHANGE as _NO_CHG
        if value is _NO_CHG:
            return False   # 调用方据此决定是否 log_no_change
        old = graph.reg_values[reg]
        if old is not value:
            graph.reg_values[reg]    = value
            graph.reg_versions[reg] += 1
        return True

    @staticmethod
    def _should_skip_opcall(op, graph) -> bool:
        """
        判断 OpCall 是否可以跳过。
        热路径：零内存分配，C 层批量版本比较。
        """
        if op.has_always_run:
            return False
        snap = op.last_snapshot
        if snap is None or snap[0] == -1:
            return False
        buf   = op.version_buffer
        ins   = op.flat_inputs
        vers  = graph.reg_versions
        for i in range(len(ins)):
            buf[i] = vers[ins[i]]
        return buf == snap

    @staticmethod
    def _record_snapshot(op):
        """执行完毕后把 version_buffer 内容 memcpy 到 last_snapshot。"""
        op.last_snapshot[:] = op.version_buffer

    @staticmethod
    def _should_skip_subtree(call, parent_graph) -> bool:
        """
        SubtreeCall 整块跳过判断（基于父树寄存器，始终安全）。
        子树内部是否允许逐节点 skip 由 inner_lazy_eval 控制。
        """
        snap = call.last_snapshot
        if snap is None or snap[0] == -1:
            return False
        if getattr(call.compiled_graph, "has_always_run_node", False):
            return False
        buf  = call.version_buffer
        ins  = call.flat_inputs
        vers = parent_graph.reg_versions
        for i in range(len(ins)):
            buf[i] = vers[ins[i]]
        return buf == snap

    @staticmethod
    def cache_key_input_value(registers, reg):
        if reg is None:
            return ""
        value = registers[reg]
        return "" if value is None else str(value)

    @staticmethod
    def build_subtree_inputs(registers, op):
        subtree_inputs = {}
        ordered_input_uids = list(op.compiled_graph.input_regs.keys())
        for index, uid in enumerate(ordered_input_uids):
            if index < len(op.inputs):
                subtree_inputs[uid] = registers[op.inputs[index]]
        return subtree_inputs

    @staticmethod
    def build_call_args(registers, op, observer):
        args = []
        arg_desc = [] if observer.debug else None

        for inp in op.inputs:
            if isinstance(inp, list):
                values = [registers[reg] for reg in inp]
                args.append(OmniExecutor.flatten_runtime(values))
                if arg_desc is not None:
                    arg_desc.append(
                        "[" + ", ".join(
                            f"{OmniDebug.reg_label(reg)}="
                            f"{OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                            for reg in inp
                        ) + "]"
                    )
            else:
                args.append(registers[inp])
                if arg_desc is not None:
                    arg_desc.append(
                        f"{OmniDebug.reg_label(inp)}="
                        f"{OmniDebug.value_label(OmniDebug.format_value(registers[inp]))}"
                    )

        return args, arg_desc

    @staticmethod
    def assign_call_outputs(registers, op, result, observer):
        if len(op.outputs) == 1:
            registers[op.outputs[0]] = result
            if not observer.debug:
                return None
            return (
                f"{OmniDebug.reg_label(op.outputs[0])}="
                f"{OmniDebug.value_label(OmniDebug.format_value(result))}"
            )

        for index, reg in enumerate(op.outputs):
            registers[reg] = result[index]

        if not observer.debug:
            return None
        return ", ".join(
            f"{OmniDebug.reg_label(reg)}="
            f"{OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
            for reg in op.outputs
        )

    @staticmethod
    def _execute(
        compiled: CompiledGraph,
        provided_inputs=None,
        debug=False,
        depth=0,
        runtime_context=None,
        observer=None,
        timing_collector=None,
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
                    observer=observer,
                    timing_collector=timing_collector,
                )
            except Exception:
                runtime_context.mark_failed()
                raise
            finally:
                OmniRuntimeState.finish_run(runtime_context)

        if observer is None:
            observer = RuntimeObserver(debug=debug, depth=depth, timing_collector=timing_collector)

        return OmniExecutor._execute_core(compiled, provided_inputs, runtime_context, observer)

    @staticmethod
    def _execute_core(compiled, provided_inputs, runtime_context, observer):
        OmniExecutor.ensure_compiled_graph_enabled(compiled)

        # 持久化寄存器：首次执行时分配，后续帧复用（懒求值的基础）
        compiled.ensure_reg_arrays()
        registers = compiled.reg_values   # 别名，写 registers[reg] 即写持久化数组
        provided_inputs = provided_inputs or {}

        observer.begin_tree(compiled)
        for uid, reg in compiled.input_regs.items():
            if uid in provided_inputs:
                OmniExecutor._write_reg(compiled, reg, provided_inputs[uid])
                observer.input_value(uid, reg, registers[reg])

        for step_index, op in enumerate(compiled.instructions):
            if isinstance(op, RuntimeTimingBeginCall):
                observer.begin_timing(op)
                continue

            if isinstance(op, RuntimeTimingEndCall):
                observer.end_timing(compiled, op)
                continue

            step_start, stage = observer.step_begin(step_index, op)

            if isinstance(op, tuple):
                _, reg, value = op
                registers[reg] = value
                observer.const(step_index, reg, value)
                observer.step_end(step_start, stage)
                continue

            if isinstance(op, CacheReadCall):
                key_value = OmniExecutor.cache_key_input_value(registers, getattr(op, "cache_key_input", None))
                cache_key = OmniRuntimeState.cache_key_for_node(op.node, key_value)

                try:
                    hit, value = OmniRuntimeState.read_cache(runtime_context, cache_key)
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    observer.error(step_index, f"ERROR in cache read @ {op.node.name}: {exc}")
                    break

                if len(op.outputs) > 0:
                    registers[op.outputs[0]] = value
                if len(op.outputs) > 1:
                    registers[op.outputs[1]] = hit

                observer.cache_read(step_index, op, cache_key, hit, value)
                observer.step_end(step_start, stage)
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
                        observer.error(step_index, f"ERROR in cache write @ {op.node.name}: {exc}")
                        break

                output_value = OmniRuntimeState.cache_visible_value(value)
                for reg in op.outputs:
                    registers[reg] = output_value

                observer.cache_write(step_index, op, cache_key, enabled, output_value)
                observer.step_end(step_start, stage)
                continue

            if isinstance(op, CacheDeleteCall):
                trigger_value = registers[op.trigger_input] if op.trigger_input is not None else None
                enabled = bool(registers[op.enabled_input]) if op.enabled_input is not None else False
                cache_key = OmniExecutor.cache_key_input_value(
                    registers,
                    getattr(op, "cache_key_input", None),
                ).strip()
                delete_all = (
                    bool(registers[op.delete_all_input])
                    if getattr(op, "delete_all_input", None) is not None else False
                )
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
                    observer.error(step_index, f"ERROR in cache delete @ {op.node.name}: {exc}")
                    break

                output_values = [trigger_value, deleted_count, enabled and (delete_all or bool(cache_key))]
                for index, reg in enumerate(op.outputs):
                    registers[reg] = output_values[index] if index < len(output_values) else None

                mode = "all" if delete_all else (cache_key or "<empty>")
                observer.cache_delete(step_index, op, registers, enabled, mode, deleted_count)
                observer.step_end(step_start, stage)
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
                    observer.error(step_index, f"ERROR in cache dump @ {op.node.name}: {exc}")
                    break

                if getattr(op, "print_to_console", True):
                    print(text)

                output_values = [trigger_value, text, len(cache_values)]
                for index, reg in enumerate(op.outputs):
                    registers[reg] = output_values[index] if index < len(output_values) else None

                observer.cache_dump(step_index, op, registers, title, len(cache_values))
                observer.step_end(step_start, stage)
                continue

            if isinstance(op, OpCall):
                # ── 懒求值 skip 判定 ───────────────────────────────────────────
                if OmniExecutor._should_skip_opcall(op, compiled):
                    observer.log_skip(op)
                    # 计入 skip 专用 stage（与执行路径的 stage 区分）
                    skip_stage = (stage + ":SKIP") if stage else stage
                    observer.step_end(step_start, skip_stage)
                    observer._lazy_nodes_skipped += 1
                    continue

                observer._lazy_nodes_run += 1

                args, arg_desc = OmniExecutor.build_call_args(registers, op, observer)

                try:
                    result = op.func(*args)
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    observer.error(
                        step_index,
                        f"ERROR in {OmniDebug.func_name(op.func)} @ {op.node.name}: {exc}",
                    )
                    break

                # ── 写回输出寄存器（处理 OMNI_NO_CHANGE）─────────────────────
                if len(op.outputs) == 1:
                    changed = OmniExecutor._write_reg(compiled, op.outputs[0], result)
                    if not changed:
                        observer.log_no_change(op, 0)
                    out_desc = (
                        f"{OmniDebug.reg_label(op.outputs[0])}="
                        f"{OmniDebug.value_label(OmniDebug.format_value(registers[op.outputs[0]]))}"
                        if observer.debug else None
                    )
                else:
                    out_parts = []
                    results = result if isinstance(result, tuple) else (result,)
                    for index, reg in enumerate(op.outputs):
                        val = results[index] if index < len(results) else None
                        changed = OmniExecutor._write_reg(compiled, reg, val)
                        if not changed:
                            observer.log_no_change(op, index)
                        if observer.debug:
                            out_parts.append(
                                f"{OmniDebug.reg_label(reg)}="
                                f"{OmniDebug.value_label(OmniDebug.format_value(registers[reg]))}"
                            )
                    out_desc = ", ".join(out_parts) if observer.debug else None

                # 记录版本快照，供下帧 skip 判定使用
                OmniExecutor._record_snapshot(op)

                observer.call(step_index, op, arg_desc or [], out_desc or "")
                observer.step_end(step_start, stage)
                continue

            if isinstance(op, SubtreeCall):
                # ── SubtreeCall 外层 skip（基于父树寄存器，始终安全）──────────
                if OmniExecutor._should_skip_subtree(op, compiled):
                    observer.log_subtree_skip(op)
                    OmniExecutor._record_snapshot(op)
                    observer.step_end(step_start, stage)
                    continue

                subtree_inputs = OmniExecutor.build_subtree_inputs(registers, op)
                observer.enter_subtree(step_index, op, subtree_inputs)

                try:
                    subtree_outputs, _ = OmniExecutor._execute(
                        op.compiled_graph,
                        subtree_inputs,
                        debug=observer.debug,
                        depth=observer.depth + 1,
                        runtime_context=runtime_context.descend_group(
                            op.node,
                            getattr(op.compiled_graph, "tree_ref", None),
                        ),
                        observer=observer.child(),
                    )
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    observer.error(step_index, f"ERROR in subtree {op.node.name}: {exc}")
                    break

                ordered_output_uids = list(op.compiled_graph.output_regs.keys())
                for index, uid in enumerate(ordered_output_uids):
                    if index < len(op.outputs):
                        val = subtree_outputs.get(uid)
                        OmniExecutor._write_reg(compiled, op.outputs[index], val)

                # 记录快照供下帧 skip 判定
                OmniExecutor._record_snapshot(op)

                observer.exit_subtree(step_index, op, registers, ordered_output_uids)
                observer.step_end(step_start, stage)
                continue

            if isinstance(op, BatchSubtreeCall):
                ordered_input_uids = list(op.compiled_graph.input_regs.keys())
                ordered_output_uids = list(op.compiled_graph.output_regs.keys())

                if op.batch_input_index >= len(op.inputs):
                    runtime_context.mark_failed()
                    op.node.set_bug_state("Batch input index out of range")
                    observer.error(step_index, f"ERROR invalid batch input index on {op.node.name}")
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
                observer.enter_batch_subtree(step_index, op, len(batch_values))

                try:
                    batch_uid = ordered_input_uids[op.batch_input_index]
                    identity_counts = {}
                    for batch_index, batch_value in enumerate(batch_values):
                        subtree_inputs = dict(base_inputs)
                        subtree_inputs[batch_uid] = batch_value
                        observer.batch_item(batch_index, batch_uid, batch_value)
                        item_identity = OmniRuntimeState.batch_item_identity(
                            batch_value
                        )
                        identity_occurrence = identity_counts.get(item_identity, 0)
                        identity_counts[item_identity] = identity_occurrence + 1

                        subtree_outputs, _ = OmniExecutor._execute(
                            op.compiled_graph,
                            subtree_inputs,
                            debug=observer.debug,
                            depth=observer.depth + 1,
                            runtime_context=runtime_context.descend_batch_item(
                                op.node,
                                getattr(op.compiled_graph, "tree_ref", None),
                                batch_index,
                                batch_value,
                                item_identity,
                                identity_occurrence,
                            ),
                            observer=observer.child(),
                        )

                        for uid in ordered_output_uids:
                            collected_outputs[uid].append(subtree_outputs.get(uid))
                except Exception as exc:
                    runtime_context.mark_failed()
                    op.node.set_bug_state(exc)
                    observer.error(step_index, f"ERROR in batch subtree {op.node.name}: {exc}")
                    break

                for index, uid in enumerate(ordered_output_uids):
                    if index < len(op.outputs):
                        registers[op.outputs[index]] = collected_outputs.get(uid, [])

                observer.exit_batch_subtree(step_index, op, registers, ordered_output_uids)
                observer.step_end(step_start, stage)

        result = {}
        for uid, reg in compiled.output_regs.items():
            result[uid] = registers[reg]

        observer.final_outputs(result)
        return result, observer.trace

    @staticmethod
    def run(compiled: CompiledGraph, debug=False, phases=None):
        t = time.perf_counter()
        runtime_context = OmniRuntimeState.begin_run(getattr(compiled, "tree_ref", None))
        if phases is not None:
            phases["[run] begin_run"] = time.perf_counter() - t
        try:
            # phases 作为收集器传入：顶层 step 明细直接并入帧链路报告，
            # 不再单独成块。step_loop 不作为聚合项写入，避免与各 step 重复计数。
            result, trace = OmniExecutor._execute(
                compiled,
                debug=debug,
                runtime_context=runtime_context,
                timing_collector=phases,
            )
        except Exception:
            runtime_context.mark_failed()
            raise
        finally:
            t = time.perf_counter()
            OmniRuntimeState.finish_run(runtime_context, phases=phases)
            if phases is not None:
                # finish_run 已写入三个子段；这里用 [finish] other 补齐
                # 未插桩的部分（失败路径、循环/字典清理开销），
                # 使 finish_run 被完整分解，且不与子段重复计数。
                finish_total = time.perf_counter() - t
                measured = (
                    phases.get("[finish] committed_ids", 0.0)
                    + phases.get("[finish] snapshot", 0.0)
                    + phases.get("[finish] dispose", 0.0)
                )
                other = finish_total - measured
                if other > 0.0:
                    phases["[finish] other"] = phases.get("[finish] other", 0.0) + other
        if debug:
            print("\n".join(trace))
        return result
