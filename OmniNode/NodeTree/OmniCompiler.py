# 该文件将 OmniNode 树编译成简单的运行时指令列表。
# 组节点被视为子树桥而不是普通的功能节点。

from .OmniDebug import OmniDebug
from . import OmniRuntimeState


class CompiledGraph:
    """Compiled result for a single OmniNode tree."""

    def __init__(self):
        self.instructions = []
        self.reg_count = 0
        self.input_regs = {}
        self.output_regs = {}
        self.tree_name = ""
        self.tree_ref = None
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
    def __init__(self, cache_key_input, fallback_input, outputs, node):
        self.cache_key_input = cache_key_input
        self.fallback_input = fallback_input
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


class OmniCompiler:
    GROUP_NODE_IDNAME = "HO_OmniNode_GroupNode"
    BATCH_GROUP_NODE_IDNAME = "HO_OmniNode_BatchGroupNode"
    GROUP_INPUTS_IDNAME = "HO_OmniNode_GroupNode_Inputs"
    GROUP_OUTPUTS_IDNAME = "HO_OmniNode_GroupNode_Outputs"
    CACHE_READ_NODE_IDNAME = "HO_OmniNode_CacheRead"
    CACHE_WRITE_NODE_IDNAME = "HO_OmniNode_CacheWrite"
    CACHE_DELETE_NODE_IDNAME = "HO_OmniNode_CacheDelete"
    CACHE_DUMP_NODE_IDNAME = "HO_OmniNode_CacheDump"
    FRAME_NODE_IDNAME = "NodeFrame"
    REROUTE_NODE_IDNAME = "NodeReroute"

    @staticmethod
    def _node_idname(node):
        return getattr(node, "bl_idname", "") or node.__class__.__name__

    @staticmethod
    def _socket_default_value(sock):
        try:
            return sock.default_value
        except Exception:
            return None

    @staticmethod
    def _set_node_bug_state(node, message):
        if hasattr(node, "set_bug_state"):
            node.set_bug_state(message)

    @staticmethod
    def _is_frame_node(node):
        return OmniCompiler._node_idname(node) == OmniCompiler.FRAME_NODE_IDNAME

    @staticmethod
    def _is_reroute_node(node):
        return OmniCompiler._node_idname(node) == OmniCompiler.REROUTE_NODE_IDNAME

    @staticmethod
    def topo_sort(nodes, links):
        """
        nodes: set[OmniNode]
        links: set[NodeLink]

        return: list[OmniNode]
        """
        in_degree = {node: 0 for node in nodes}
        adjacency = {node: [] for node in nodes}

        for link in links:
            src = link.from_node
            dst = link.to_node
            if src not in nodes or dst not in nodes:
                continue
            adjacency[src].append(dst)
            in_degree[dst] += 1

        queue = [node for node in nodes if in_degree[node] == 0]
        queue.sort(key=lambda n: n.name)

        result = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
            queue.sort(key=lambda n: n.name)

        if len(result) != len(nodes):
            cycle_nodes = [n for n in nodes if in_degree[n] > 0]
            for node in cycle_nodes:
                OmniCompiler._set_node_bug_state(node, "Cycle detected in node graph")
            raise RuntimeError("Cycle detected in OmniNodeTree")

        return result

    @staticmethod
    def compile(tree, debug=False):
        return OmniCompiler._compile_tree(tree, compiling_stack=[], debug=debug)

    @staticmethod
    def _compile_tree(tree, compiling_stack, debug=False):
        OmniRuntimeState.ensure_tree_runtime_uids(tree)

        graph = CompiledGraph()
        graph.tree_name = getattr(tree, "name", "")
        graph.tree_ref = tree
        graph.debug_enabled = debug

        OmniDebug.append_compile_trace(graph, f"Start compile tree '{graph.tree_name}'")

        if tree in compiling_stack:
            cycle_path = [getattr(t, "name", "<tree>") for t in compiling_stack + [tree]]
            raise RuntimeError("Cycle detected in OmniNode subtree: " + " -> ".join(cycle_path))

        compiling_stack = compiling_stack + [tree]

        output_nodes = [node for node in tree.nodes if getattr(node, "is_output_node", False)]

        visited = set()
        links = set()

        def dfs(node):
            if node in visited:
                return
            visited.add(node)

            if OmniCompiler._is_frame_node(node):
                return

            for input_socket in node.inputs:
                for link in input_socket.links:
                    links.add(link)
                    dfs(link.from_node)

        for node in output_nodes:
            dfs(node)

        topo = OmniCompiler.topo_sort(visited, links)
        OmniDebug.append_compile_trace(
            graph,
            "Reachable output nodes: " + ", ".join(sorted(OmniDebug.node_name(node) for node in output_nodes))
            if output_nodes else "Reachable output nodes: <none>",
        )
        OmniDebug.append_compile_trace(
            graph,
            "Topo order: " + ", ".join(OmniDebug.node_name(node) for node in topo)
            if topo else "Topo order: <empty>",
        )

        reg_map = {}
        reg_id = 0

        def new_reg():
            nonlocal reg_id
            reg = reg_id
            reg_id += 1
            return reg

        instructions = []

        def compile_single_input(sock):
            socket_links = sorted(
                sock.links,
                key=lambda link: (link.from_node.name, link.from_socket.identifier),
            )
            if socket_links:
                link = socket_links[0]
                key = (link.from_node.name, link.from_socket.identifier)
                reg = reg_map[key]
                OmniDebug.append_compile_trace(
                    graph,
                    f"Use r{reg} bridge {link.from_node.name}.{OmniDebug.socket_name(link.from_socket)} -> "
                    f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
                )
                return reg

            reg = new_reg()
            default_value = OmniCompiler._socket_default_value(sock)
            instructions.append(("CONST", reg, default_value))
            OmniDebug.append_compile_trace(
                graph,
                f"Emit CONST r{reg} = {OmniDebug.format_value(default_value)} for "
                f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
            )
            OmniDebug.add_register_bridge(
                graph,
                reg,
                OmniDebug.node_name(sock.node),
                OmniDebug.socket_name(sock),
                source=OmniDebug.format_value(default_value),
                note="CONST default",
            )
            return reg

        def compile_multi_input(sock, trace_kind="multi"):
            socket_links = sorted(
                sock.links,
                key=lambda link: (link.from_node.name, link.from_socket.identifier),
            )
            if not socket_links:
                reg = compile_single_input(sock)
                OmniDebug.append_compile_trace(
                    graph,
                    f"Use {trace_kind} default r{reg} for "
                    f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
                )
                return [reg]

            regs = []
            for link in socket_links:
                key = (link.from_node.name, link.from_socket.identifier)
                reg = reg_map[key]
                regs.append(reg)
                OmniDebug.append_compile_trace(
                    graph,
                    f"Use {trace_kind} bridge r{reg} {link.from_node.name}.{OmniDebug.socket_name(link.from_socket)} -> "
                    f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
                )
            return regs

        def compile_node_inputs(node):
            input_regs = []
            socket_is_multi = getattr(node, "_socket_is_multi", None) or {}

            for sock in node.inputs:
                is_multi = socket_is_multi.get(sock.identifier, False)
                if is_multi:
                    input_regs.append(compile_multi_input(sock, trace_kind="multi"))
                else:
                    input_regs.append(compile_single_input(sock))

            return input_regs

        def input_socket(node, identifier):
            try:
                return node.inputs.get(identifier)
            except Exception:
                return None

        def compile_optional_input(node, identifier):
            sock = input_socket(node, identifier)
            return compile_single_input(sock) if sock is not None else None

        for node in topo:
            node_idname = OmniCompiler._node_idname(node)

            if OmniCompiler._is_frame_node(node):
                OmniDebug.append_compile_trace(graph, f"Skip FRAME {node.name}")
                continue

            if OmniCompiler._is_reroute_node(node):
                input_sock = node.inputs[0] if len(node.inputs) > 0 else None
                input_reg = None
                if input_sock is not None:
                    input_reg = compile_single_input(input_sock)
                else:
                    input_reg = new_reg()
                    instructions.append(("CONST", input_reg, None))
                    OmniDebug.add_register_bridge(
                        graph,
                        input_reg,
                        node.name,
                        "<missing input>",
                        source="None",
                        note="reroute fallback",
                    )

                for sock in node.outputs:
                    reg_map[(node.name, sock.identifier)] = input_reg
                    OmniDebug.add_register_bridge(
                        graph,
                        input_reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source="reroute passthrough",
                        note="reroute output bridge",
                    )

                OmniDebug.append_compile_trace(
                    graph,
                    f"Pass REROUTE {node.name} -> r{input_reg}",
                )
                continue

            if node_idname == OmniCompiler.GROUP_INPUTS_IDNAME:
                for sock in node.outputs:
                    uid = sock.identifier
                    reg = graph.input_regs.get(uid)
                    if reg is None:
                        reg = new_reg()
                        graph.input_regs[uid] = reg
                    reg_map[(node.name, sock.identifier)] = reg
                    OmniDebug.append_compile_trace(
                        graph,
                        f"Map tree input {uid} -> r{reg} via {node.name}.{OmniDebug.socket_name(sock)}",
                    )
                    OmniDebug.add_register_bridge(
                        graph,
                        reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source=f"tree_input:{uid}",
                        note="group input bridge",
                    )
                continue

            if node_idname == OmniCompiler.GROUP_OUTPUTS_IDNAME:
                for sock in node.inputs:
                    socket_links = sorted(
                        sock.links,
                        key=lambda link: (link.from_node.name, link.from_socket.identifier),
                    )
                    if not socket_links:
                        continue
                    link = socket_links[0]
                    key = (link.from_node.name, link.from_socket.identifier)
                    graph.output_regs[sock.identifier] = reg_map[key]
                    OmniDebug.append_compile_trace(
                        graph,
                        f"Map tree output {sock.identifier} <- r{reg_map[key]} from "
                        f"{link.from_node.name}.{OmniDebug.socket_name(link.from_socket)}",
                    )
                continue

            if node_idname == OmniCompiler.GROUP_NODE_IDNAME:
                child_tree = getattr(node, "target_tree", None)
                if child_tree is None:
                    node.set_bug_state("Group node has no target tree")
                    raise RuntimeError(f"Group node '{node.name}' has no target tree")

                try:
                    compiled_subtree = OmniCompiler._compile_tree(child_tree, compiling_stack, debug=debug)
                except Exception as exc:
                    node.set_bug_state(exc)
                    raise

                input_regs = [compile_single_input(sock) for sock in node.inputs]

                output_regs = []
                for sock in node.outputs:
                    reg = new_reg()
                    reg_map[(node.name, sock.identifier)] = reg
                    output_regs.append(reg)
                    OmniDebug.add_register_bridge(
                        graph,
                        reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source=f"subtree:{compiled_subtree.tree_name}",
                        note="subtree output bridge",
                    )

                instructions.append(SubtreeCall(compiled_subtree, input_regs, output_regs, node))
                OmniDebug.append_compile_trace(
                    graph,
                    f"Emit SUBTREE {node.name} -> {compiled_subtree.tree_name} inputs={input_regs} outputs={output_regs}",
                )
                continue

            if node_idname == OmniCompiler.BATCH_GROUP_NODE_IDNAME:
                child_tree = getattr(node, "target_tree", None)
                if child_tree is None:
                    node.set_bug_state("Batch group node has no target tree")
                    raise RuntimeError(f"Batch group node '{node.name}' has no target tree")

                try:
                    compiled_subtree = OmniCompiler._compile_tree(child_tree, compiling_stack, debug=debug)
                except Exception as exc:
                    node.set_bug_state(exc)
                    raise

                batch_input_index = int(getattr(node, "batch_input_index", -1))
                if batch_input_index < 0 or batch_input_index >= len(node.inputs):
                    batch_input_index = -1
                input_regs = []

                for index, sock in enumerate(node.inputs):
                    if index == batch_input_index:
                        input_regs.append(compile_multi_input(sock, trace_kind="batch"))
                    else:
                        input_regs.append(compile_single_input(sock))

                if batch_input_index < 0:
                    node.set_bug_state("Batch group node has no batch input selected")
                    raise RuntimeError(f"Batch group node '{node.name}' has no batch input selected")

                output_regs = []
                for sock in node.outputs:
                    reg = new_reg()
                    reg_map[(node.name, sock.identifier)] = reg
                    output_regs.append(reg)
                    OmniDebug.add_register_bridge(
                        graph,
                        reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source=f"batch_subtree:{compiled_subtree.tree_name}",
                        note="batch subtree output bridge",
                    )

                instructions.append(
                    BatchSubtreeCall(
                        compiled_subtree,
                        input_regs,
                        output_regs,
                        node,
                        batch_input_index=batch_input_index,
                    )
                )
                OmniDebug.append_compile_trace(
                    graph,
                    f"Emit BATCH SUBTREE {node.name} -> {compiled_subtree.tree_name} "
                    f"batch_input_index={batch_input_index} inputs={input_regs} outputs={output_regs}",
                )
                continue

            if node_idname == OmniCompiler.CACHE_READ_NODE_IDNAME:
                cache_key_reg = compile_optional_input(node, "cache_key")
                fallback_reg = compile_optional_input(node, "fallback")

                output_regs = []
                for sock in node.outputs:
                    reg = new_reg()
                    reg_map[(node.name, sock.identifier)] = reg
                    output_regs.append(reg)
                    OmniDebug.add_register_bridge(
                        graph,
                        reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source="runtime_cache_read",
                        note="cache read output",
                    )

                instructions.append(
                    CacheReadCall(
                        cache_key_reg,
                        fallback_reg,
                        output_regs,
                        node,
                    )
                )
                OmniDebug.append_compile_trace(
                    graph,
                    f"Emit CACHE READ {node.name} key={cache_key_reg} fallback={fallback_reg} outputs={output_regs}",
                )
                continue

            if node_idname == OmniCompiler.CACHE_WRITE_NODE_IDNAME:
                cache_key_reg = compile_optional_input(node, "cache_key")
                value_reg = compile_optional_input(node, "value")
                enabled_reg = compile_optional_input(node, "enable")

                output_regs = []
                for sock in node.outputs:
                    reg = new_reg()
                    reg_map[(node.name, sock.identifier)] = reg
                    output_regs.append(reg)
                    OmniDebug.add_register_bridge(
                        graph,
                        reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source="runtime_cache_write",
                        note="cache write passthrough",
                    )

                instructions.append(
                    CacheWriteCall(
                        cache_key_reg,
                        value_reg,
                        enabled_reg,
                        output_regs,
                        node,
                    )
                )
                OmniDebug.append_compile_trace(
                    graph,
                    f"Emit CACHE WRITE {node.name} key={cache_key_reg} value={value_reg} enabled={enabled_reg} outputs={output_regs}",
                )
                continue

            if node_idname == OmniCompiler.CACHE_DELETE_NODE_IDNAME:
                trigger_reg = compile_optional_input(node, "trigger")
                cache_key_reg = compile_optional_input(node, "cache_key")
                delete_all_reg = compile_optional_input(node, "delete_all")
                enabled_reg = compile_optional_input(node, "enable")

                output_regs = []
                for sock in node.outputs:
                    reg = new_reg()
                    reg_map[(node.name, sock.identifier)] = reg
                    output_regs.append(reg)
                    OmniDebug.add_register_bridge(
                        graph,
                        reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source="runtime_cache_delete",
                        note="cache delete output",
                    )

                instructions.append(
                    CacheDeleteCall(
                        trigger_reg,
                        cache_key_reg,
                        delete_all_reg,
                        enabled_reg,
                        output_regs,
                        node,
                    )
                )
                OmniDebug.append_compile_trace(
                    graph,
                    f"Emit CACHE DELETE {node.name} trigger={trigger_reg} key={cache_key_reg} delete_all={delete_all_reg} enabled={enabled_reg} outputs={output_regs}",
                )
                continue

            if node_idname == OmniCompiler.CACHE_DUMP_NODE_IDNAME:
                trigger_reg = compile_single_input(node.inputs[0]) if len(node.inputs) > 0 else None
                label_reg = compile_single_input(node.inputs[1]) if len(node.inputs) > 1 else None

                output_regs = []
                for sock in node.outputs:
                    reg = new_reg()
                    reg_map[(node.name, sock.identifier)] = reg
                    output_regs.append(reg)
                    OmniDebug.add_register_bridge(
                        graph,
                        reg,
                        node.name,
                        OmniDebug.socket_name(sock),
                        source="runtime_cache_dump",
                        note="cache dump output",
                    )

                instructions.append(
                    CacheDumpCall(
                        trigger_reg,
                        label_reg,
                        output_regs,
                        node,
                        bool(getattr(node, "print_to_console", True)),
                    )
                )
                OmniDebug.append_compile_trace(
                    graph,
                    f"Emit CACHE DUMP {node.name} trigger={trigger_reg} label={label_reg} outputs={output_regs}",
                )
                continue

            func = getattr(node, "_func", None)
            if func is None:
                message = f"Unsupported OmniNode node type: {node_idname}"
                OmniCompiler._set_node_bug_state(node, message)
                raise RuntimeError(f"{message} ({node.name})")

            input_regs = compile_node_inputs(node)

            output_regs = []
            for sock in node.outputs:
                reg = new_reg()
                reg_map[(node.name, sock.identifier)] = reg
                output_regs.append(reg)
                OmniDebug.add_register_bridge(
                    graph,
                    reg,
                    node.name,
                    OmniDebug.socket_name(sock),
                    source=OmniDebug.func_name(func),
                    note="node output",
                )

            instructions.append(OpCall(func, input_regs, output_regs, node))
            graph.function_catalog.append({
                "func": OmniDebug.func_name(func),
                "node": node.name,
            })
            OmniDebug.append_compile_trace(
                graph,
                f"Emit CALL {OmniDebug.func_name(func)} @ {node.name} inputs={input_regs} outputs={output_regs}",
            )

        graph.instructions = instructions
        graph.reg_count = reg_id
        graph.node_order = [node.name for node in topo]
        OmniDebug.append_compile_trace(graph, f"Compile finished with {len(instructions)} instructions")
        return graph
