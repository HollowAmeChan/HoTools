from .OmniCompiler import CompiledGraph, OpCall, SubtreeCall


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
    def _execute(compiled: CompiledGraph, provided_inputs=None):
        registers = [None] * compiled.reg_count
        provided_inputs = provided_inputs or {}

        for uid, reg in compiled.input_regs.items():
            if uid in provided_inputs:
                registers[reg] = provided_inputs[uid]

        for op in compiled.instructions:
            if isinstance(op, tuple):
                _, reg, value = op
                registers[reg] = value
                continue

            if isinstance(op, OpCall):
                args = []
                for inp in op.inputs:
                    if isinstance(inp, list):
                        values = [registers[r] for r in inp]
                        args.append(OmniExecutor.flatten_runtime(values))
                    else:
                        args.append(registers[inp])

                try:
                    result = op.func(*args)
                except Exception as e:
                    op.node.is_bug = True
                    op.node.bug_text = str(e)
                    break

                if len(op.outputs) == 1:
                    registers[op.outputs[0]] = result
                else:
                    for i, reg in enumerate(op.outputs):
                        registers[reg] = result[i]
                continue

            if isinstance(op, SubtreeCall):
                subtree_inputs = {}
                ordered_input_uids = list(op.compiled_graph.input_regs.keys())
                for i, uid in enumerate(ordered_input_uids):
                    if i < len(op.inputs):
                        subtree_inputs[uid] = registers[op.inputs[i]]

                try:
                    subtree_outputs = OmniExecutor._execute(op.compiled_graph, subtree_inputs)
                except Exception as e:
                    op.node.is_bug = True
                    op.node.bug_text = str(e)
                    break

                ordered_output_uids = list(op.compiled_graph.output_regs.keys())
                for i, uid in enumerate(ordered_output_uids):
                    if i < len(op.outputs):
                        registers[op.outputs[i]] = subtree_outputs.get(uid)

        result = {}
        for uid, reg in compiled.output_regs.items():
            result[uid] = registers[reg]
        return result

    @staticmethod
    def run(compiled: CompiledGraph):
        OmniExecutor._execute(compiled)
