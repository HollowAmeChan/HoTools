# 此文件专用于omninode-tree的编译，为执行做准备
# TODO:暂时不支持子图编译

# 子图需要检测自循环防止卡死
# 子图需要隔离参数域
# 子图的数据传输需要有桥（有可能写在graphnode的_func里吗）
# 需要分两段编译，首先编译tree+group（递归得到，中间做循环检查），然后再做数据的mapping以及缓存隔离
# 可能的话可以编译成直接可以执行的代码，寄存器也丢里面统一运行
# 编译bug了需要直接找到出问题的node去显示bug
# node.is_bug = True
# node.bug_text = str(e)

# 子图需要特判
# node.bl_idename == "HO_OmniNode_GroupNode"
# node.bl_idename == "HO_OmniNode_GroupNode_Inputs"
# node.bl_idename == "HO_OmniNode_GroupNode_Outputs"
# 子树subtree可以通过HO_OmniNode_GroupNode类型节点的target_tree来获取
# 这些节点语义上直接代表tree的IO
# 需要注意io的名字，现在graphnode的socket的identity直接使用treeIO内容的uid，在每个tree内部都是唯一的，作用域+uid就可以解决桥中参数的定位问题
# 严格注意io存在tree上不在node的socket上，这几个特殊节点的socket的defaultvalue我隐藏了不让用户改，出问题直接报错用户自己会排查
# 后面也许可以做检测判定是否有输入

class CompiledGraph:
    """树的编译结果"""
    def __init__(self):
        self.instructions = [] 
        self.reg_count = 0
        # debug用 TODO:没写完，不知道哪儿绘制
        self.node_order = []

class OpCall:
    def __init__(self, func, inputs, outputs, node):
        self.func = func
        self.inputs = inputs
        self.outputs = outputs
        self.node = node  # debug

class OmniCompiler:

    @staticmethod
    def topo_sort(nodes, links):
        """
        nodes: set[OmniNode]
        links: set[NodeLink]

        return: list[OmniNode]
        """
        # 1. 初始化
        in_degree = {node: 0 for node in nodes}
        adjacency = {node: [] for node in nodes}

        # 2. 构建图
        for link in links:
            src = link.from_node
            dst = link.to_node
            # 只处理在子图内的节点
            if src not in nodes or dst not in nodes:
                continue
            adjacency[src].append(dst)
            in_degree[dst] += 1

        # 3. 找入度为0的节点
        queue = [node for node in nodes if in_degree[node] == 0]
        queue.sort(key=lambda n: n.name)# 避免 Blender 内部随机顺序

        result = []
        # 4. Kahn 算法
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

            # 避免 Blender 内部随机顺序
            queue.sort(key=lambda n: n.name)

        # 5. 环检测
        if len(result) != len(nodes):
            cycle_nodes = [n for n in nodes if in_degree[n] > 0]
            for n in cycle_nodes:
                n.is_bug = True
                n.bug_text = "Cycle detected in node graph"

            raise RuntimeError("Cycle detected in OmniNodeTree")

        return result
    
    @staticmethod
    def compile(tree):
        graph = CompiledGraph()
        # -----------------------
        # 1. 找有效子图
        # -----------------------
        output_nodes = [n for n in tree.nodes if n.is_output_node]

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

        for n in output_nodes:
            dfs(n)

        # -----------------------
        # 2. 拓扑排序
        # -----------------------
        topo = OmniCompiler.topo_sort(visited, links)

        # -----------------------
        # 3. 分配寄存器
        # -----------------------
        reg_map = {}
        reg_id = 0

        def new_reg():
            nonlocal reg_id
            r = reg_id
            reg_id += 1
            return r

        instructions = []

        # -----------------------
        # 4. 编译每个节点
        # -----------------------
        for node in topo:

            func = node._func   # 👈 关键：后面说怎么加

            input_regs = []

            for sock in node.inputs:
                if not node._socket_is_multi: continue
                is_multi = node._socket_is_multi.get(sock.identifier, False)
                links = sorted(
                    sock.links,
                    key=lambda l: (l.from_node.name, l.from_socket.identifier)
                )
                # multi-input
                if is_multi:
                    # 需要注意编译阶段是完全无法做flatten的，因为根本没有结果给你合
                    regs = []
                    if links:
                        for link in links:
                            key = (link.from_node.name, link.from_socket.identifier)
                            regs.append(reg_map[key])
                    else:pass # 空 multi → []
                    input_regs.append(regs)

                # single input
                else:
                    if links:
                        link = links[0]
                        key = (link.from_node.name, link.from_socket.identifier)
                        r = reg_map[key]
                    else:
                        r = new_reg()
                        instructions.append(("CONST", r, sock.default_value))
                    input_regs.append(r)

            output_regs = []
            for sock in node.outputs:
                r = new_reg()
                reg_map[(node.name, sock.identifier)] = r
                output_regs.append(r)

            instructions.append(
                OpCall(func, input_regs, output_regs, node)
            )

        graph.instructions = instructions
        graph.reg_count = reg_id
        #debug用
        graph.node_order = [node.name for node in topo]

        return graph