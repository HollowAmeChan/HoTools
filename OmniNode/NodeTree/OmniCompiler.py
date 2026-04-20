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
            for n in cycle_nodes:
                n.is_bug = True
                n.bug_text = "Cycle detected in node graph"
            raise RuntimeError("Cycle detected in OmniNodeTree")

        return result

    @staticmethod
    def compile(tree):
        return OmniCompiler._compile_tree(tree, compiling_stack=[])

    @staticmethod
    def _compile_tree(tree, compiling_stack):
        graph = CompiledGraph()
        graph.tree_name = getattr(tree, "name", "")

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
                return reg_map[key]

            r = new_reg()
            instructions.append(("CONST", r, sock.default_value))
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
                        regs.append(reg_map[key])
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
                continue

            if node_idname == OmniCompiler.GROUP_NODE_IDNAME:
                child_tree = getattr(node, "target_tree", None)
                if child_tree is None:
                    node.is_bug = True
                    node.bug_text = "Group node has no target tree"
                    raise RuntimeError(f"Group node '{node.name}' has no target tree")

                try:
                    compiled_subtree = OmniCompiler._compile_tree(child_tree, compiling_stack)
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

                instructions.append(SubtreeCall(compiled_subtree, input_regs, output_regs, node))
                continue

            func = getattr(node, "_func", None)
            input_regs = compile_node_inputs(node)

            output_regs = []
            for sock in node.outputs:
                r = new_reg()
                reg_map[(node.name, sock.identifier)] = r
                output_regs.append(r)

            instructions.append(OpCall(func, input_regs, output_regs, node))

        graph.instructions = instructions
        graph.reg_count = reg_id
        graph.node_order = [node.name for node in topo]
        return graph
