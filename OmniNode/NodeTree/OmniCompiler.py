# 该文件将 OmniNode 树编译成简单的运行时指令列表。
# 组节点被视为子树桥而不是普通的功能节点。

from .OmniDebug import OmniDebug
from . import OmniRuntimeState
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
        return CompilerContext(tree, compiling_stack, debug=debug).compile()


class CompilerContext:
    SPECIAL_EMITTERS = {
        OmniCompiler.FRAME_NODE_IDNAME: "emit_frame",
        OmniCompiler.REROUTE_NODE_IDNAME: "emit_reroute",
        OmniCompiler.GROUP_INPUTS_IDNAME: "emit_group_inputs",
        OmniCompiler.GROUP_OUTPUTS_IDNAME: "emit_group_outputs",
        OmniCompiler.GROUP_NODE_IDNAME: "emit_group",
        OmniCompiler.BATCH_GROUP_NODE_IDNAME: "emit_batch_group",
        OmniCompiler.CACHE_READ_NODE_IDNAME: "emit_cache_read",
        OmniCompiler.CACHE_WRITE_NODE_IDNAME: "emit_cache_write",
        OmniCompiler.CACHE_DELETE_NODE_IDNAME: "emit_cache_delete",
        OmniCompiler.CACHE_DUMP_NODE_IDNAME: "emit_cache_dump",
    }

    def __init__(self, tree, compiling_stack, debug=False):
        self.tree = tree
        self.compiling_stack = list(compiling_stack)
        self.debug = debug
        self.reg_map = {}
        self.reg_id = 0
        self.instructions = []
        self.topo = []

        OmniRuntimeState.ensure_tree_runtime_uids(tree)

        self.graph = CompiledGraph()
        self.graph.tree_name = getattr(tree, "name", "")
        self.graph.tree_ref = tree
        self.graph.debug_enabled = debug
        try:
            self.graph.runtime_timing_tree_key = f"tree:{int(tree.as_pointer())}"
        except Exception:
            self.graph.runtime_timing_tree_key = f"name:{self.graph.tree_name}"

        OmniDebug.append_compile_trace(self.graph, f"Start compile tree '{self.graph.tree_name}'")

    def compile(self):
        self._check_subtree_cycle()
        self.compiling_stack = self.compiling_stack + [self.tree]

        output_nodes, visited, links = self._collect_reachable_graph()
        self.topo = OmniCompiler.topo_sort(visited, links)
        self._trace_topology(output_nodes)

        for node in self.topo:
            self.emit_node(node)

        return self.finish()

    def _check_subtree_cycle(self):
        if self.tree not in self.compiling_stack:
            return

        cycle_path = [getattr(t, "name", "<tree>") for t in self.compiling_stack + [self.tree]]
        raise RuntimeError("Cycle detected in OmniNode subtree: " + " -> ".join(cycle_path))

    def _collect_reachable_graph(self):
        output_nodes = [node for node in self.tree.nodes if getattr(node, "is_output_node", False)]
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

        return output_nodes, visited, links

    def _trace_topology(self, output_nodes):
        OmniDebug.append_compile_trace(
            self.graph,
            "Reachable output nodes: " + ", ".join(sorted(OmniDebug.node_name(node) for node in output_nodes))
            if output_nodes else "Reachable output nodes: <none>",
        )
        OmniDebug.append_compile_trace(
            self.graph,
            "Topo order: " + ", ".join(OmniDebug.node_name(node) for node in self.topo)
            if self.topo else "Topo order: <empty>",
        )

    def sorted_socket_links(self, sock):
        return sorted(
            sock.links,
            key=lambda link: (link.from_node.name, link.from_socket.identifier),
        )

    def new_reg(self):
        reg = self.reg_id
        self.reg_id += 1
        return reg

    def compile_single_input(self, sock):
        socket_links = self.sorted_socket_links(sock)
        if socket_links:
            link = socket_links[0]
            key = (link.from_node.name, link.from_socket.identifier)
            reg = self.reg_map[key]
            OmniDebug.append_compile_trace(
                self.graph,
                f"Use r{reg} bridge {link.from_node.name}.{OmniDebug.socket_name(link.from_socket)} -> "
                f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
            )
            return reg

        reg = self.new_reg()
        default_value = OmniCompiler._socket_default_value(sock)
        self.instructions.append(("CONST", reg, default_value))
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit CONST r{reg} = {OmniDebug.format_value(default_value)} for "
            f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
        )
        OmniDebug.add_register_bridge(
            self.graph,
            reg,
            OmniDebug.node_name(sock.node),
            OmniDebug.socket_name(sock),
            source=OmniDebug.format_value(default_value),
            note="CONST default",
        )
        return reg

    def compile_multi_input(self, sock, trace_kind="multi"):
        socket_links = self.sorted_socket_links(sock)
        if not socket_links:
            reg = self.compile_single_input(sock)
            OmniDebug.append_compile_trace(
                self.graph,
                f"Use {trace_kind} default r{reg} for "
                f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
            )
            return [reg]

        regs = []
        for link in socket_links:
            key = (link.from_node.name, link.from_socket.identifier)
            reg = self.reg_map[key]
            regs.append(reg)
            OmniDebug.append_compile_trace(
                self.graph,
                f"Use {trace_kind} bridge r{reg} {link.from_node.name}.{OmniDebug.socket_name(link.from_socket)} -> "
                f"{OmniDebug.node_name(sock.node)}.{OmniDebug.socket_name(sock)}",
            )
        return regs

    def compile_node_inputs(self, node):
        input_regs = []
        socket_is_multi = getattr(node, "_socket_is_multi", None) or {}

        for sock in node.inputs:
            is_multi = socket_is_multi.get(sock.identifier, False)
            if is_multi:
                input_regs.append(self.compile_multi_input(sock, trace_kind="multi"))
            else:
                input_regs.append(self.compile_single_input(sock))

        return input_regs

    def input_socket(self, node, identifier):
        try:
            return node.inputs.get(identifier)
        except Exception:
            return None

    def compile_optional_input(self, node, identifier):
        sock = self.input_socket(node, identifier)
        return self.compile_single_input(sock) if sock is not None else None

    def allocate_outputs(self, node, source, note):
        output_regs = []
        for sock in node.outputs:
            reg = self.new_reg()
            self.reg_map[(node.name, sock.identifier)] = reg
            output_regs.append(reg)
            OmniDebug.add_register_bridge(
                self.graph,
                reg,
                node.name,
                OmniDebug.socket_name(sock),
                source=source,
                note=note,
            )
        return output_regs

    def emit_node(self, node):
        node_idname = OmniCompiler._node_idname(node)
        emitter_name = self.SPECIAL_EMITTERS.get(node_idname)
        if emitter_name is not None:
            getattr(self, emitter_name)(node)
            return

        self.emit_function_call(node, node_idname)

    def emit_frame(self, node):
        OmniDebug.append_compile_trace(self.graph, f"Skip FRAME {node.name}")

    def emit_reroute(self, node):
        input_sock = node.inputs[0] if len(node.inputs) > 0 else None
        if input_sock is not None:
            input_reg = self.compile_single_input(input_sock)
        else:
            input_reg = self.new_reg()
            self.instructions.append(("CONST", input_reg, None))
            OmniDebug.add_register_bridge(
                self.graph,
                input_reg,
                node.name,
                "<missing input>",
                source="None",
                note="reroute fallback",
            )

        for sock in node.outputs:
            self.reg_map[(node.name, sock.identifier)] = input_reg
            OmniDebug.add_register_bridge(
                self.graph,
                input_reg,
                node.name,
                OmniDebug.socket_name(sock),
                source="reroute passthrough",
                note="reroute output bridge",
            )

        OmniDebug.append_compile_trace(
            self.graph,
            f"Pass REROUTE {node.name} -> r{input_reg}",
        )

    def emit_group_inputs(self, node):
        for sock in node.outputs:
            uid = sock.identifier
            reg = self.graph.input_regs.get(uid)
            if reg is None:
                reg = self.new_reg()
                self.graph.input_regs[uid] = reg
            self.reg_map[(node.name, sock.identifier)] = reg
            OmniDebug.append_compile_trace(
                self.graph,
                f"Map tree input {uid} -> r{reg} via {node.name}.{OmniDebug.socket_name(sock)}",
            )
            OmniDebug.add_register_bridge(
                self.graph,
                reg,
                node.name,
                OmniDebug.socket_name(sock),
                source=f"tree_input:{uid}",
                note="group input bridge",
            )

    def emit_group_outputs(self, node):
        for sock in node.inputs:
            socket_links = self.sorted_socket_links(sock)
            if not socket_links:
                continue
            link = socket_links[0]
            key = (link.from_node.name, link.from_socket.identifier)
            self.graph.output_regs[sock.identifier] = self.reg_map[key]
            OmniDebug.append_compile_trace(
                self.graph,
                f"Map tree output {sock.identifier} <- r{self.reg_map[key]} from "
                f"{link.from_node.name}.{OmniDebug.socket_name(link.from_socket)}",
            )

    def emit_group(self, node):
        child_tree = getattr(node, "target_tree", None)
        if child_tree is None:
            node.set_bug_state("Group node has no target tree")
            raise RuntimeError(f"Group node '{node.name}' has no target tree")

        try:
            compiled_subtree = OmniCompiler._compile_tree(child_tree, self.compiling_stack, debug=self.debug)
        except Exception as exc:
            node.set_bug_state(exc)
            raise

        input_regs = [self.compile_single_input(sock) for sock in node.inputs]
        output_regs = self.allocate_outputs(
            node,
            source=f"subtree:{compiled_subtree.tree_name}",
            note="subtree output bridge",
        )

        self.instructions.append(SubtreeCall(compiled_subtree, input_regs, output_regs, node))
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit SUBTREE {node.name} -> {compiled_subtree.tree_name} inputs={input_regs} outputs={output_regs}",
        )

    def emit_batch_group(self, node):
        child_tree = getattr(node, "target_tree", None)
        if child_tree is None:
            node.set_bug_state("Batch group node has no target tree")
            raise RuntimeError(f"Batch group node '{node.name}' has no target tree")

        try:
            compiled_subtree = OmniCompiler._compile_tree(child_tree, self.compiling_stack, debug=self.debug)
        except Exception as exc:
            node.set_bug_state(exc)
            raise

        batch_input_index = int(getattr(node, "batch_input_index", -1))
        if batch_input_index < 0 or batch_input_index >= len(node.inputs):
            batch_input_index = -1

        input_regs = []
        for index, sock in enumerate(node.inputs):
            if index == batch_input_index:
                input_regs.append(self.compile_multi_input(sock, trace_kind="batch"))
            else:
                input_regs.append(self.compile_single_input(sock))

        if batch_input_index < 0:
            node.set_bug_state("Batch group node has no batch input selected")
            raise RuntimeError(f"Batch group node '{node.name}' has no batch input selected")

        output_regs = self.allocate_outputs(
            node,
            source=f"batch_subtree:{compiled_subtree.tree_name}",
            note="batch subtree output bridge",
        )

        self.instructions.append(
            BatchSubtreeCall(
                compiled_subtree,
                input_regs,
                output_regs,
                node,
                batch_input_index=batch_input_index,
            )
        )
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit BATCH SUBTREE {node.name} -> {compiled_subtree.tree_name} "
            f"batch_input_index={batch_input_index} inputs={input_regs} outputs={output_regs}",
        )

    def emit_cache_read(self, node):
        cache_key_reg = self.compile_optional_input(node, "cache_key")
        output_regs = self.allocate_outputs(node, source="runtime_cache_read", note="cache read output")

        self.instructions.append(CacheReadCall(cache_key_reg, output_regs, node))
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit CACHE READ {node.name} key={cache_key_reg} outputs={output_regs}",
        )

    def emit_cache_write(self, node):
        cache_key_reg = self.compile_optional_input(node, "cache_key")
        value_reg = self.compile_optional_input(node, "value")
        enabled_reg = self.compile_optional_input(node, "enable")
        output_regs = self.allocate_outputs(node, source="runtime_cache_write", note="cache write passthrough")

        self.instructions.append(
            CacheWriteCall(
                cache_key_reg,
                value_reg,
                enabled_reg,
                output_regs,
                node,
            )
        )
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit CACHE WRITE {node.name} key={cache_key_reg} value={value_reg} enabled={enabled_reg} outputs={output_regs}",
        )

    def emit_cache_delete(self, node):
        trigger_reg = self.compile_optional_input(node, "trigger")
        cache_key_reg = self.compile_optional_input(node, "cache_key")
        delete_all_reg = self.compile_optional_input(node, "delete_all")
        enabled_reg = self.compile_optional_input(node, "enable")
        output_regs = self.allocate_outputs(node, source="runtime_cache_delete", note="cache delete output")

        self.instructions.append(
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
            self.graph,
            f"Emit CACHE DELETE {node.name} trigger={trigger_reg} key={cache_key_reg} delete_all={delete_all_reg} enabled={enabled_reg} outputs={output_regs}",
        )

    def emit_cache_dump(self, node):
        trigger_reg = self.compile_single_input(node.inputs[0]) if len(node.inputs) > 0 else None
        label_reg = self.compile_single_input(node.inputs[1]) if len(node.inputs) > 1 else None
        output_regs = self.allocate_outputs(node, source="runtime_cache_dump", note="cache dump output")

        self.instructions.append(
            CacheDumpCall(
                trigger_reg,
                label_reg,
                output_regs,
                node,
                bool(getattr(node, "print_to_console", True)),
            )
        )
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit CACHE DUMP {node.name} trigger={trigger_reg} label={label_reg} outputs={output_regs}",
        )

    def emit_function_call(self, node, node_idname):
        func = getattr(node, "_func", None)
        if func is None:
            message = f"Unsupported OmniNode node type: {node_idname}"
            OmniCompiler._set_node_bug_state(node, message)
            raise RuntimeError(f"{message} ({node.name})")

        input_regs = self.compile_node_inputs(node)
        output_regs = self.allocate_outputs(node, source=OmniDebug.func_name(func), note="node output")

        self.instructions.append(OpCall(func, input_regs, output_regs, node))
        self.graph.function_catalog.append({
            "func": OmniDebug.func_name(func),
            "node": node.name,
        })
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit CALL {OmniDebug.func_name(func)} @ {node.name} inputs={input_regs} outputs={output_regs}",
        )

    def finish(self):
        self.graph.instructions = self.instructions
        self.graph.instructions.insert(0, RuntimeTimingBeginCall(self.graph.tree_name, self.tree))
        self.graph.instructions.append(RuntimeTimingEndCall(self.graph.tree_name, self.tree))
        self.graph.reg_count = self.reg_id
        self.graph.node_order = [node.name for node in self.topo]
        OmniDebug.append_compile_trace(
            self.graph,
            f"Compile finished with {len(self.instructions)} instructions",
        )
        return self.graph
