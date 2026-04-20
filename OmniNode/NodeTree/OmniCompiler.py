# This file compiles OmniNode trees into a simple runtime instruction list.
# Group nodes are treated as subtree bridges instead of normal function nodes.


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
    COLOR_TERMINAL = {"displays_colors": False, "initialized": False}

    @staticmethod
    def _node_name(node):
        return getattr(node, "name", "<node>")

    @staticmethod
    def _socket_name(sock):
        return getattr(sock, "identifier", getattr(sock, "name", "<socket>"))

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
    def _append_trace(graph, message):
        graph.compile_trace.append(message)

    @staticmethod
    def _init_terminal_colors():
        if OmniCompiler.COLOR_TERMINAL["initialized"]:
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

        OmniCompiler.COLOR_TERMINAL["displays_colors"] = can_paint
        OmniCompiler.COLOR_TERMINAL["initialized"] = True

    @staticmethod
    def _str_color(text, color):
        OmniCompiler._init_terminal_colors()
        if OmniCompiler.COLOR_TERMINAL["displays_colors"]:
            return f"\033[1;{color}m{text}\033[0m"
        return str(text)

    @staticmethod
    def _section_label(text):
        return OmniCompiler._str_color(f"[{text}]", 96)

    @staticmethod
    def _tree_label(text):
        return OmniCompiler._str_color(f"<{text}>", 94)

    @staticmethod
    def _reg_label(reg):
        return OmniCompiler._str_color(f"r{reg}", 93)

    @staticmethod
    def _node_label(text):
        return OmniCompiler._str_color(text, 92)

    @staticmethod
    def _func_label(text):
        return OmniCompiler._str_color(text, 95)

    @staticmethod
    def _value_label(text):
        return OmniCompiler._str_color(str(text), 90)

    @staticmethod
    def _error_label(text):
        return OmniCompiler._str_color(f"ERROR: {text}", 91)

    @staticmethod
    def _add_register_bridge(graph, reg, owner_node, owner_socket, source=None, note=""):
        graph.register_bridges.append({
            "reg": reg,
            "owner_node": owner_node,
            "owner_socket": owner_socket,
            "source": source,
            "note": note,
        })

    @staticmethod
    def _format_compile_report(graph, depth=0):
        indent = "    " * depth
        lines = [
            f"{indent}{OmniCompiler._section_label('[Compile]')} Tree: {OmniCompiler._tree_label(graph.tree_name)}",
            f"{indent}  {OmniCompiler._section_label('Registers')}: {OmniCompiler._value_label(graph.reg_count)}",
            f"{indent}  {OmniCompiler._section_label('Topo Order')}: "
            + (
                ", ".join(OmniCompiler._node_label(node_name) for node_name in graph.node_order)
                if graph.node_order else OmniCompiler._value_label('<empty>')
            ),
        ]

        if graph.input_regs:
            lines.append(f"{indent}  {OmniCompiler._section_label('Tree Inputs')}:")
            for uid, reg in graph.input_regs.items():
                lines.append(
                    f"{indent}    {OmniCompiler._value_label(uid)} -> {OmniCompiler._reg_label(reg)}"
                )

        if graph.output_regs:
            lines.append(f"{indent}  {OmniCompiler._section_label('Tree Outputs')}:")
            for uid, reg in graph.output_regs.items():
                lines.append(
                    f"{indent}    {OmniCompiler._value_label(uid)} <- {OmniCompiler._reg_label(reg)}"
                )

        if graph.register_bridges:
            lines.append(f"{indent}  {OmniCompiler._section_label('Register Bridges')}:")
            for bridge in graph.register_bridges:
                source = bridge["source"] or "<none>"
                note = f" ({bridge['note']})" if bridge["note"] else ""
                lines.append(
                    f"{indent}    {OmniCompiler._reg_label(bridge['reg'])} :: "
                    f"{OmniCompiler._node_label(bridge['owner_node'])}.{OmniCompiler._value_label(bridge['owner_socket'])} <- "
                    f"{OmniCompiler._value_label(source + note)}"
                )

        if graph.function_catalog:
            lines.append(f"{indent}  {OmniCompiler._section_label('Runtime Functions')}:")
            for item in graph.function_catalog:
                lines.append(
                    f"{indent}    {OmniCompiler._func_label(item['func'])} @ {OmniCompiler._node_label(item['node'])}"
                )

        if graph.compile_trace:
            lines.append(f"{indent}  {OmniCompiler._section_label('Compile Trace')}:")
            for entry in graph.compile_trace:
                lines.append(f"{indent}    {OmniCompiler._value_label(entry)}")

        for op in graph.instructions:
            if isinstance(op, SubtreeCall):
                lines.extend(OmniCompiler._format_compile_report(op.compiled_graph, depth + 1))

        return lines

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
            for n in cycle_nodes:
                n.is_bug = True
                n.bug_text = "Cycle detected in node graph"
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

        OmniCompiler._append_trace(graph, f"Start compile tree '{graph.tree_name}'")

        if tree in compiling_stack:
            cycle_path = [getattr(t, "name", "<tree>") for t in compiling_stack + [tree]]
            raise RuntimeError("Cycle detected in OmniNode subtree: " + " -> ".join(cycle_path))

        compiling_stack = compiling_stack + [tree]

        output_nodes = [n for n in tree.nodes if getattr(n, "is_output_node", False)]

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
        OmniCompiler._append_trace(
            graph,
            "Reachable output nodes: " + ", ".join(sorted(OmniCompiler._node_name(n) for n in output_nodes)) if output_nodes else "Reachable output nodes: <none>"
        )
        OmniCompiler._append_trace(
            graph,
            "Topo order: " + ", ".join(OmniCompiler._node_name(n) for n in topo) if topo else "Topo order: <empty>"
        )

        reg_map = {}
        reg_id = 0

        def new_reg():
            nonlocal reg_id
            r = reg_id
            reg_id += 1
            return r

        instructions = []

        def compile_single_input(sock):
            socket_links = sorted(
                sock.links,
                key=lambda l: (l.from_node.name, l.from_socket.identifier)
            )
            if socket_links:
                link = socket_links[0]
                key = (link.from_node.name, link.from_socket.identifier)
                reg = reg_map[key]
                OmniCompiler._append_trace(
                    graph,
                    f"Use r{reg} bridge {link.from_node.name}.{OmniCompiler._socket_name(link.from_socket)} -> {OmniCompiler._node_name(sock.node)}.{OmniCompiler._socket_name(sock)}"
                )
                return reg

            r = new_reg()
            instructions.append(("CONST", r, sock.default_value))
            OmniCompiler._append_trace(
                graph,
                f"Emit CONST r{r} = {OmniCompiler._format_value(sock.default_value)} for {OmniCompiler._node_name(sock.node)}.{OmniCompiler._socket_name(sock)}"
            )
            OmniCompiler._add_register_bridge(
                graph,
                r,
                OmniCompiler._node_name(sock.node),
                OmniCompiler._socket_name(sock),
                source=OmniCompiler._format_value(sock.default_value),
                note="CONST default",
            )
            return r

        def compile_node_inputs(node):
            input_regs = []
            socket_is_multi = getattr(node, "_socket_is_multi", None) or {}

            for sock in node.inputs:
                is_multi = socket_is_multi.get(sock.identifier, False)
                socket_links = sorted(
                    sock.links,
                    key=lambda l: (l.from_node.name, l.from_socket.identifier)
                )
                if is_multi:
                    regs = []
                    for link in socket_links:
                        key = (link.from_node.name, link.from_socket.identifier)
                        reg = reg_map[key]
                        regs.append(reg)
                        OmniCompiler._append_trace(
                            graph,
                            f"Use multi bridge r{reg} {link.from_node.name}.{OmniCompiler._socket_name(link.from_socket)} -> {OmniCompiler._node_name(node)}.{OmniCompiler._socket_name(sock)}"
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
                    r = graph.input_regs.get(uid)
                    if r is None:
                        r = new_reg()
                        graph.input_regs[uid] = r
                    reg_map[(node.name, sock.identifier)] = r
                    OmniCompiler._append_trace(
                        graph,
                        f"Bind tree input {uid} -> r{r} via {node.name}.{OmniCompiler._socket_name(sock)}"
                    )
                    OmniCompiler._add_register_bridge(
                        graph,
                        r,
                        node.name,
                        OmniCompiler._socket_name(sock),
                        source=f"tree_input:{uid}",
                        note="group input bridge",
                    )
                continue

            if node_idname == OmniCompiler.GROUP_OUTPUTS_IDNAME:
                for sock in node.inputs:
                    socket_links = sorted(
                        sock.links,
                        key=lambda l: (l.from_node.name, l.from_socket.identifier)
                    )
                    if not socket_links:
                        continue
                    link = socket_links[0]
                    key = (link.from_node.name, link.from_socket.identifier)
                    graph.output_regs[sock.identifier] = reg_map[key]
                    OmniCompiler._append_trace(
                        graph,
                        f"Bind tree output {sock.identifier} <- r{reg_map[key]} from {link.from_node.name}.{OmniCompiler._socket_name(link.from_socket)}"
                    )
                continue

            if node_idname == OmniCompiler.GROUP_NODE_IDNAME:
                child_tree = getattr(node, "target_tree", None)
                if child_tree is None:
                    node.is_bug = True
                    node.bug_text = "Group node has no target tree"
                    raise RuntimeError(f"Group node '{node.name}' has no target tree")

                try:
                    compiled_subtree = OmniCompiler._compile_tree(child_tree, compiling_stack, debug=debug)
                except Exception as e:
                    node.is_bug = True
                    node.bug_text = str(e)
                    raise

                input_regs = [compile_single_input(sock) for sock in node.inputs]

                output_regs = []
                for sock in node.outputs:
                    r = new_reg()
                    reg_map[(node.name, sock.identifier)] = r
                    output_regs.append(r)
                    OmniCompiler._add_register_bridge(
                        graph,
                        r,
                        node.name,
                        OmniCompiler._socket_name(sock),
                        source=f"subtree:{compiled_subtree.tree_name}",
                        note="subtree output bridge",
                    )

                instructions.append(SubtreeCall(compiled_subtree, input_regs, output_regs, node))
                OmniCompiler._append_trace(
                    graph,
                    f"Emit SUBTREE {node.name} -> {compiled_subtree.tree_name} inputs={input_regs} outputs={output_regs}"
                )
                continue

            func = getattr(node, "_func", None)
            input_regs = compile_node_inputs(node)

            output_regs = []
            for sock in node.outputs:
                r = new_reg()
                reg_map[(node.name, sock.identifier)] = r
                output_regs.append(r)
                OmniCompiler._add_register_bridge(
                    graph,
                    r,
                    node.name,
                    OmniCompiler._socket_name(sock),
                    source=OmniCompiler._func_name(func),
                    note="node output",
                )

            instructions.append(OpCall(func, input_regs, output_regs, node))
            graph.function_catalog.append({
                "func": OmniCompiler._func_name(func),
                "node": node.name,
            })
            OmniCompiler._append_trace(
                graph,
                f"Emit CALL {OmniCompiler._func_name(func)} @ {node.name} inputs={input_regs} outputs={output_regs}"
            )

        graph.instructions = instructions
        graph.reg_count = reg_id
        graph.node_order = [node.name for node in topo]
        OmniCompiler._append_trace(graph, f"Compile finished with {len(instructions)} instructions")
        return graph
