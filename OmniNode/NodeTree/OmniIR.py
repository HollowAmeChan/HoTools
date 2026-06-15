class CompiledGraph:
    """Compiled result for a single OmniNode tree."""

    def __init__(self):
        self.instructions = []
        self.reg_count = 0
        self.input_regs = {}
        self.output_regs = {}
        self.tree_name = ""
        self.tree_ref = None
        self.runtime_timing_tree_key = None
        self.node_order = []
        self.compile_trace = []
        self.register_bridges = []
        self.function_catalog = []
        self.debug_enabled = False


class OpCall:
    def __init__(self, func, inputs, outputs, node):
        self.func = func
        self.inputs = inputs
        self.outputs = outputs
        self.node = node


class SubtreeCall:
    def __init__(self, compiled_graph, inputs, outputs, node):
        self.compiled_graph = compiled_graph
        self.inputs = inputs
        self.outputs = outputs
        self.node = node


class BatchSubtreeCall:
    def __init__(self, compiled_graph, inputs, outputs, node, batch_input_index):
        self.compiled_graph = compiled_graph
        self.inputs = inputs
        self.outputs = outputs
        self.node = node
        self.batch_input_index = batch_input_index


class CacheReadCall:
    def __init__(self, cache_key_input, outputs, node):
        self.cache_key_input = cache_key_input
        self.outputs = outputs
        self.node = node


class CacheWriteCall:
    def __init__(self, cache_key_input, value_input, enabled_input, outputs, node):
        self.cache_key_input = cache_key_input
        self.value_input = value_input
        self.enabled_input = enabled_input
        self.outputs = outputs
        self.node = node


class CacheDeleteCall:
    def __init__(self, trigger_input, cache_key_input, delete_all_input, enabled_input, outputs, node):
        self.trigger_input = trigger_input
        self.cache_key_input = cache_key_input
        self.delete_all_input = delete_all_input
        self.enabled_input = enabled_input
        self.outputs = outputs
        self.node = node


class CacheDumpCall:
    def __init__(self, trigger_input, label_input, outputs, node, print_to_console):
        self.trigger_input = trigger_input
        self.label_input = label_input
        self.outputs = outputs
        self.node = node
        self.print_to_console = print_to_console


class RuntimeTimingBeginCall:
    def __init__(self, tree_name, tree_ref):
        self.tree_name = tree_name
        self.tree_ref = tree_ref


class RuntimeTimingEndCall:
    def __init__(self, tree_name, tree_ref):
        self.tree_name = tree_name
        self.tree_ref = tree_ref
