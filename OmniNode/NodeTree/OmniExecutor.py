# 此文件为用于omninode的编译与运行，以及与cache交互
from .OmniNode import OmniNode
from.OmniCompiler import OpCall,CompiledGraph

class OmniExecutor:

    @staticmethod
    def flatten_runtime(values):
        """只能在运行时展平list，但是这样也比较脏，参数有处理的传入了func，debug难看"""
        result = []
        for v in values:
            if isinstance(v, list):
                result.extend(v)
            else:
                result.append(v)
        return result

    @staticmethod
    def run(compiled:CompiledGraph):
        registers = [None] * compiled.reg_count #寄存器cache，用于存储临时数据

        for op in compiled.instructions:

            if isinstance(op, tuple):  # CONST
                _, r, v = op
                registers[r] = v
                continue

            if isinstance(op, OpCall):

                args = []
                for inp in op.inputs:
                    # multi-input（list of regs）
                    if isinstance(inp, list):
                        values = [registers[r] for r in inp]
                        args.append(OmniExecutor.flatten_runtime(values))#此处flatten会导致debug很难看
                    # single
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
                    for i, r in enumerate(op.outputs):
                        registers[r] = result[i]