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
import inspect


class _MutedPassthroughLink:
    def __init__(self, from_socket, to_socket, muted_path):
        self.from_socket = from_socket
        self.from_node = from_socket.node
        self.to_socket = to_socket
        self.to_node = to_socket.node
        self.muted_path = tuple(muted_path)


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
    def _is_muted_node(node):
        # Blender 里对节点按 M 会设置 node.mute。OmniNode 不复刻 Blender 内部旁路线，
        # 编译时把 muted 节点视为反向搜索屏障，节点本身和它的上游都不进入 IR。
        try:
            return bool(getattr(node, "mute", False))
        except Exception:
            return False

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
        self.reachable_nodes = set()
        self.muted_nodes = set()
        self.muted_passthrough_links = {}

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
        self.reachable_nodes = visited
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

    @staticmethod
    def _socket_key(sock):
        try:
            return int(sock.as_pointer())
        except Exception:
            return id(sock)

    @staticmethod
    def _socket_by_identifier(sockets, identifier):
        for sock in sockets:
            if getattr(sock, "identifier", None) == identifier:
                return sock
        try:
            return sockets.get(identifier)
        except Exception:
            return None

    def _muted_passthrough_input_socket(self, node, output_socket):
        mapping = getattr(node, "_omni_mute_passthrough", None) or {}
        output_id = getattr(output_socket, "identifier", None)
        input_id = mapping.get(output_id)
        if input_id is None:
            return None
        return self._socket_by_identifier(getattr(node, "inputs", ()), input_id)

    def _add_muted_passthrough_link(self, link):
        key = self._socket_key(link.to_socket)
        links = self.muted_passthrough_links.setdefault(key, [])
        signature = (
            link.from_node.name,
            getattr(link.from_socket, "identifier", ""),
            link.to_node.name,
            getattr(link.to_socket, "identifier", ""),
            tuple(node.name for node in link.muted_path),
        )
        for existing in links:
            existing_signature = (
                existing.from_node.name,
                getattr(existing.from_socket, "identifier", ""),
                existing.to_node.name,
                getattr(existing.to_socket, "identifier", ""),
                tuple(node.name for node in existing.muted_path),
            )
            if existing_signature == signature:
                return
        links.append(link)

    def _resolve_muted_passthrough_links(self, muted_node, output_socket, target_socket, seen=None):
        seen = tuple(seen or ())
        if muted_node in seen:
            OmniDebug.append_compile_trace(
                self.graph,
                f"Stop MUTED passthrough cycle at {OmniDebug.node_name(muted_node)}",
            )
            return []

        path = seen + (muted_node,)
        self.muted_nodes.add(muted_node)
        input_socket = self._muted_passthrough_input_socket(muted_node, output_socket)
        if input_socket is None:
            OmniDebug.append_compile_trace(
                self.graph,
                f"Block MUTED {OmniDebug.node_name(muted_node)}."
                f"{OmniDebug.socket_name(output_socket)} without mute_passthrough",
            )
            return []

        resolved = []
        for input_link in input_socket.links:
            source_node = input_link.from_node
            if OmniCompiler._is_muted_node(source_node):
                resolved.extend(
                    self._resolve_muted_passthrough_links(
                        source_node,
                        input_link.from_socket,
                        target_socket,
                        seen=path,
                    )
                )
                continue

            resolved.append(
                _MutedPassthroughLink(
                    input_link.from_socket,
                    target_socket,
                    path,
                )
            )

        if not resolved:
            OmniDebug.append_compile_trace(
                self.graph,
                f"MUTED {OmniDebug.node_name(muted_node)}."
                f"{OmniDebug.socket_name(output_socket)} passthrough has no active upstream link",
            )
            return []

        for link in resolved:
            OmniDebug.append_compile_trace(
                self.graph,
                f"Pass MUTED {' -> '.join(OmniDebug.node_name(node) for node in link.muted_path)} "
                f"as {link.from_node.name}.{OmniDebug.socket_name(link.from_socket)} -> "
                f"{OmniDebug.node_name(target_socket.node)}.{OmniDebug.socket_name(target_socket)}",
            )
        return resolved

    def _collect_reachable_graph(self):
        output_nodes = [node for node in self.tree.nodes if getattr(node, "is_output_node", False)]
        visited = set()
        links = set()

        def dfs(node):
            if node in visited:
                return
            if OmniCompiler._is_muted_node(node):
                self.muted_nodes.add(node)
                # muted 节点不生成输出寄存器，也不继续向输入侧搜索；
                # 下游仍保留的可见连线会在编译输入时按 reachable_nodes 再过滤。
                OmniDebug.append_compile_trace(
                    self.graph,
                    f"Block MUTED node {OmniDebug.node_name(node)} and skip its upstream",
                )
                return

            visited.add(node)

            if OmniCompiler._is_frame_node(node):
                return

            for input_socket in node.inputs:
                for link in input_socket.links:
                    if OmniCompiler._is_muted_node(link.from_node):
                        passthrough_links = self._resolve_muted_passthrough_links(
                            link.from_node,
                            link.from_socket,
                            input_socket,
                        )
                        if passthrough_links:
                            for passthrough_link in passthrough_links:
                                self._add_muted_passthrough_link(passthrough_link)
                                links.add(passthrough_link)
                                dfs(passthrough_link.from_node)
                            continue
                        # 到 muted 节点的 link 只属于编辑器可视连接，不参与运行时数据流。
                        self.muted_nodes.add(link.from_node)
                        OmniDebug.append_compile_trace(
                            self.graph,
                            f"Ignore link from MUTED {OmniDebug.node_name(link.from_node)} -> "
                            f"{OmniDebug.node_name(node)}.{OmniDebug.socket_name(input_socket)}",
                        )
                        continue
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
        if self.muted_nodes:
            OmniDebug.append_compile_trace(
                self.graph,
                "Muted nodes seen: " + ", ".join(
                    sorted(OmniDebug.node_name(node) for node in self.muted_nodes)
                ),
            )

    def sorted_socket_links(self, sock):
        # 反向搜索遇到 muted 节点会把那条分支剪掉，但 Blender 的 socket.links
        # 仍然保留可见连线；这里按可执行子图过滤，避免读取未分配的上游寄存器。
        active_nodes = self.reachable_nodes
        links = [
            link
            for link in sock.links
            if link.from_node in active_nodes and link.to_node in active_nodes
        ]
        links.extend(self.muted_passthrough_links.get(self._socket_key(sock), ()))
        return sorted(
            links,
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
        for sock in getattr(node, "inputs", ()):
            if getattr(sock, "identifier", None) == identifier:
                return sock
        try:
            return node.inputs.get(identifier)
        except Exception:
            return None

    def compile_missing_input_default(self, node, identifier, default_value):
        reg = self.new_reg()
        self.instructions.append(("CONST", reg, default_value))
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit CONST r{reg} = {OmniDebug.format_value(default_value)} for "
            f"{OmniDebug.node_name(node)}.{identifier} (missing socket, function default)",
        )
        OmniDebug.add_register_bridge(
            self.graph,
            reg,
            OmniDebug.node_name(node),
            identifier,
            source=OmniDebug.format_value(default_value),
            note="missing socket default",
        )
        return reg

    def function_missing_input_default(self, node, param):
        identifier = param.name
        declared_defaults = getattr(node, "_omni_socket_defaults", None)
        if isinstance(declared_defaults, dict) and identifier in declared_defaults:
            return declared_defaults[identifier]
        if param.default is not inspect._empty:
            return param.default

        message = (
            f"Missing required input socket '{identifier}' on {OmniDebug.node_name(node)}; "
            "rebuild this node after changing the function signature"
        )
        OmniCompiler._set_node_bug_state(node, message)
        raise RuntimeError(message)

    def validate_function_param(self, node, param):
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            return

        message = (
            f"Unsupported function parameter '{param.name}' ({param.kind.description}) on "
            f"{OmniDebug.node_name(node)}; Omni function nodes must use positional parameters"
        )
        OmniCompiler._set_node_bug_state(node, message)
        raise RuntimeError(message)

    def validate_stale_inputs(self, node, stale_socks):
        linked_stale_ids = [
            getattr(sock, "identifier", getattr(sock, "name", ""))
            for sock in stale_socks
            if len(getattr(sock, "links", ())) > 0
        ]
        if not linked_stale_ids:
            return

        message = (
            f"Stale linked input socket(s) on {OmniDebug.node_name(node)}: "
            f"{', '.join(map(str, linked_stale_ids))}; rebuild this node after changing the function signature"
        )
        OmniCompiler._set_node_bug_state(node, message)
        raise RuntimeError(message)

    def compile_function_inputs(self, node, func):
        try:
            parameters = list(inspect.signature(func).parameters.values())
        except Exception:
            return self.compile_node_inputs(node)

        input_regs = []
        socket_is_multi = getattr(node, "_socket_is_multi", None) or {}
        signature_ids = set()

        for param in parameters:
            self.validate_function_param(node, param)
            identifier = param.name
            signature_ids.add(identifier)
            is_multi = socket_is_multi.get(identifier, False)
            sock = self.input_socket(node, identifier)
            if sock is None:
                default_value = self.function_missing_input_default(node, param)
                reg = self.compile_missing_input_default(node, identifier, default_value)
                input_regs.append([reg] if is_multi else reg)
                continue

            if is_multi:
                input_regs.append(self.compile_multi_input(sock, trace_kind="multi"))
            else:
                input_regs.append(self.compile_single_input(sock))

        stale_socks = [
            sock
            for sock in getattr(node, "inputs", ())
            if getattr(sock, "identifier", None) not in signature_ids
        ]
        self.validate_stale_inputs(node, stale_socks)

        stale_ids = [
            getattr(sock, "identifier", getattr(sock, "name", ""))
            for sock in stale_socks
        ]
        if stale_ids:
            OmniDebug.append_compile_trace(
                self.graph,
                f"Ignore stale inputs on {OmniDebug.node_name(node)}: {', '.join(map(str, stale_ids))}",
            )

        return input_regs

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

        call = SubtreeCall(compiled_subtree, input_regs, output_regs, node)
        call._init_lazy_fields()
        self.instructions.append(call)
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

        # 读取 always_run：优先 _meta，其次判断 is_output_node
        func_meta = getattr(func, "__meta", {}) or {}
        is_output = bool(getattr(node, "is_output_node", False))
        has_always_run = bool(func_meta.get("always_run", is_output))

        input_regs  = self.compile_function_inputs(node, func)
        output_regs = self.allocate_outputs(node, source=OmniDebug.func_name(func), note="node output")

        op = OpCall(func, input_regs, output_regs, node, has_always_run=has_always_run)
        op._init_lazy_fields()   # 初始化 flat_inputs / version_buffer / last_snapshot
        self.instructions.append(op)

        self.graph.function_catalog.append({
            "func": OmniDebug.func_name(func),
            "node": node.name,
        })
        OmniDebug.append_compile_trace(
            self.graph,
            f"Emit CALL {OmniDebug.func_name(func)} @ {node.name} "
            f"always_run={has_always_run} inputs={input_regs} outputs={output_regs}",
        )

    @staticmethod
    def _runtime_node_identity(node, func=None):
        uid = OmniRuntimeState.ensure_node_runtime_uid(node)
        node_idname = OmniCompiler._node_idname(node)
        if func is None:
            return (uid, node_idname)
        return (
            uid,
            node_idname,
            str(getattr(func, "__module__", "") or ""),
            str(getattr(func, "__qualname__", getattr(func, "__name__", "")) or ""),
        )

    @staticmethod
    def _runtime_cache_key_contract(op, constants):
        node_identity = CompilerContext._runtime_node_identity(op.node)
        key_reg = getattr(op, "cache_key_input", None)
        if key_reg is None:
            return ("implicit", node_identity[0])
        if key_reg not in constants:
            return None
        value = constants[key_reg]
        if value is not None and not isinstance(value, (str, bool, int, float)):
            return None
        key = str(value or "").strip()
        return ("explicit", key) if key else ("implicit", node_identity[0])

    @staticmethod
    def _build_runtime_cache_contract(graph):
        instructions = tuple(graph.instructions or ())
        constants = {
            int(op[1]): op[2]
            for op in instructions
            if isinstance(op, tuple) and len(op) == 3 and op[0] == "CONST"
        }
        producers = {}
        for op in instructions:
            for reg in getattr(op, "outputs", ()) or ():
                producers[int(reg)] = op
        input_uids = {int(reg): str(uid) for uid, reg in graph.input_regs.items()}
        memo = {}

        def input_signature(value):
            if isinstance(value, list):
                return ("multi", tuple(register_signature(reg) for reg in value))
            if value is None:
                return ("missing",)
            return register_signature(value)

        def register_signature(reg):
            reg = int(reg)
            if reg in memo:
                return memo[reg]
            if reg in constants:
                result = ("const",)
                memo[reg] = result
                return result
            if reg in input_uids:
                result = ("tree_input", input_uids[reg])
                memo[reg] = result
                return result
            op = producers.get(reg)
            if op is None:
                result = ("unbound",)
                memo[reg] = result
                return result
            memo[reg] = ("cycle",)
            if isinstance(op, OpCall):
                result = (
                    "call",
                    CompilerContext._runtime_node_identity(op.node, op.func),
                    list(op.outputs).index(reg),
                    tuple(input_signature(value) for value in op.inputs),
                )
            elif isinstance(op, CacheReadCall):
                result = (
                    "cache_read",
                    CompilerContext._runtime_node_identity(op.node),
                    list(op.outputs).index(reg),
                    CompilerContext._runtime_cache_key_contract(op, constants),
                )
            elif isinstance(op, CacheWriteCall):
                result = (
                    "cache_write",
                    CompilerContext._runtime_node_identity(op.node),
                    register_signature(op.value_input)
                    if op.value_input is not None else ("missing",),
                )
            elif isinstance(op, (SubtreeCall, BatchSubtreeCall)):
                child = op.compiled_graph
                output_index = list(op.outputs).index(reg)
                output_uids = list(child.output_regs.keys())
                child_output = (
                    child.runtime_output_contracts.get(output_uids[output_index])
                    if output_index < len(output_uids) else None
                )
                result = (
                    "batch" if isinstance(op, BatchSubtreeCall) else "group",
                    CompilerContext._runtime_node_identity(op.node),
                    str(OmniRuntimeState.runtime_tree_key(child.tree_ref)),
                    child_output,
                    tuple(input_signature(value) for value in op.inputs),
                )
            else:
                result = (
                    op.__class__.__name__,
                    CompilerContext._runtime_node_identity(op.node),
                )
            memo[reg] = result
            return result

        owner_entries = []
        preservable = True
        children = []
        for op in instructions:
            if isinstance(op, (SubtreeCall, BatchSubtreeCall)):
                child = op.compiled_graph
                node_uid = OmniRuntimeState.ensure_node_runtime_uid(op.node)
                child_key = OmniRuntimeState.runtime_tree_key(child.tree_ref)
                children.append((
                    "batch" if isinstance(op, BatchSubtreeCall) else "group",
                    str(node_uid),
                    str(child_key),
                    child,
                ))
            if not isinstance(op, (CacheReadCall, CacheWriteCall, CacheDeleteCall)):
                continue
            key_contract = CompilerContext._runtime_cache_key_contract(op, constants)
            if key_contract is None:
                preservable = False
            entry = [
                op.__class__.__name__,
                CompilerContext._runtime_node_identity(op.node),
                key_contract,
            ]
            if isinstance(op, CacheWriteCall):
                entry.append(
                    register_signature(op.value_input)
                    if op.value_input is not None else ("missing",)
                )
            owner_entries.append(tuple(entry))

        graph.runtime_cache_contract = {
            "schema": 1,
            "preservable": bool(preservable),
            "signature": (
                "omni_runtime_cache_contract_v1",
                tuple(sorted(owner_entries, key=repr)),
            ),
        }
        graph.runtime_namespace_children = tuple(children)
        graph.runtime_output_contracts = {
            str(uid): register_signature(reg)
            for uid, reg in graph.output_regs.items()
        }

    def finish(self):
        # 插入计时桩
        self.instructions.insert(0, RuntimeTimingBeginCall(self.graph.tree_name, self.tree))
        self.instructions.append(RuntimeTimingEndCall(self.graph.tree_name, self.tree))

        # instructions 固化为 tuple（不可变，迭代更快）
        self.graph.instructions = tuple(self.instructions)
        self.graph.reg_count    = self.reg_id
        self.graph.node_order   = [node.name for node in self.topo]

        self._build_runtime_cache_contract(self.graph)

        # ── 懒求值：计算 has_always_run_node ──────────────────────────────────
        self.graph.has_always_run_node = self._compute_has_always_run(self.graph)

        # ── 懒求值：计算各子树 ref_count 和 inner_lazy_eval ───────────────────
        self._compute_ref_counts(self.graph)

        OmniDebug.append_compile_trace(
            self.graph,
            f"Compile finished with {len(self.graph.instructions)} instructions, "
            f"has_always_run_node={self.graph.has_always_run_node}",
        )
        return self.graph

    @staticmethod
    def _compute_has_always_run(graph) -> bool:
        """递归判断图中是否包含 always_run 节点（含子树）。"""
        from .OmniIR import OpCall as _OpCall, SubtreeCall as _SubCall, BatchSubtreeCall as _BSubCall
        for op in graph.instructions:
            if isinstance(op, _OpCall) and getattr(op, "has_always_run", False):
                return True
            if isinstance(op, (_SubCall, _BSubCall)):
                child = getattr(op, "compiled_graph", None)
                if child and getattr(child, "has_always_run_node", False):
                    return True
        return False

    @staticmethod
    def _compute_ref_counts(root_graph) -> None:
        """
        递归统计每个 compiled_graph 被引用的次数。
        ref_count > 1 的子树不允许内部节点 skip（防跨路径污染）。
        """
        from .OmniIR import SubtreeCall as _SubCall, BatchSubtreeCall as _BSubCall
        counts = {}   # id(graph) -> count

        def walk(g):
            for op in g.instructions:
                if isinstance(op, (_SubCall, _BSubCall)):
                    child = getattr(op, "compiled_graph", None)
                    if child is None:
                        continue
                    gid = id(child)
                    counts[gid] = counts.get(gid, 0) + 1
                    walk(child)

        walk(root_graph)

        def apply(g):
            for op in g.instructions:
                if isinstance(op, (_SubCall, _BSubCall)):
                    child = getattr(op, "compiled_graph", None)
                    if child is None:
                        continue
                    child.ref_count       = counts.get(id(child), 1)
                    child.inner_lazy_eval = (child.ref_count == 1)
                    apply(child)

        apply(root_graph)
