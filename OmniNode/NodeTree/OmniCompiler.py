# 该文件将 OmniNode 树编译成简单的运行时指令列表。
# 组节点被视为子树桥而不是普通的功能节点。

from .OmniDebug import OmniDebug


class CompiledGraph:
    """Compiled result for a single OmniNode tree."""

    def __init__(self):
        self.instructions = []
        self.reg_count = 0
        self.input_regs = {}
        self.output_regs = {}
        self.tree_name = ""
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


class OmniCompiler:
    GROUP_NODE_IDNAME = "HO_OmniNode_GroupNode"
    GROUP_INPUTS_IDNAME = "HO_OmniNode_GroupNode_Inputs"
    GROUP_OUTPUTS_IDNAME = "HO_OmniNode_GroupNode_Outputs"

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
                node.set_bug_state("Cycle detected in node graph")
            raise RuntimeError("Cycle detected in OmniNodeTree")

        return result

    @staticmethod
    def compile(tree, debug=False):
        return OmniCompiler._compile_tree(tree, compiling_stack=[], debug=debug)

    @staticmethod
    def _compile_tree(tree, compiling_stack, debug=False):
        graph = CompiledGraph()
        graph.tree_name = getattr(tree, "name", "")
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
            instructions.append(("CONST", reg, sock.default_value))
            OmniDebug.append_compile_trace(
                graph,
                f"Emit CONST r{reg} = {OmniDebug.format_value(sock.default_value)} for "
                f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
            )
            OmniDebug.add_register_bridge(
                graph,
                reg,
                OmniDebug.node_name(sock.node),
                OmniDebug.socket_name(sock),
                source=OmniDebug.format_value(sock.default_value),
                note="CONST default",
            )
            return reg

        def compile_node_inputs(node):
            input_regs = []
            socket_is_multi = getattr(node, "_socket_is_multi", None) or {}

            for sock in node.inputs:
                is_multi = socket_is_multi.get(sock.identifier, False)
                socket_links = sorted(
                    sock.links,
                    key=lambda link: (link.from_node.name, link.from_socket.identifier),
                )
                if is_multi:
                    regs = []
                    for link in socket_links:
                        key = (link.from_node.name, link.from_socket.identifier)
                        reg = reg_map[key]
                        regs.append(reg)
                        OmniDebug.append_compile_trace(
                            graph,
                            f"Use multi bridge r{reg} {link.from_node.name}.{OmniDebug.socket_name(link.from_socket)} -> "
                            f"{OmniDebug.node_name(node)}.{OmniDebug.socket_name(sock)}",
                        )
                    input_regs.append(regs)
                else:
                    input_regs.append(compile_single_input(sock))

            return input_regs

        for node in topo:
            node_idname = getattr(node, "bl_idname", "")

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
                        f"Bind tree input {uid} -> r{reg} via {node.name}.{OmniDebug.socket_name(sock)}",
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
                        f"Bind tree output {sock.identifier} <- r{reg_map[key]} from "
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

            func = getattr(node, "_func", None)
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
