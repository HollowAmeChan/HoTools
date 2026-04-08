import bpy
from bpy.types import Node, NodeSocket
from ...operator import NodeBaseOps


def setOutputNode(node, context):
    node.updateColor()


def setBugNode(node, context):
    node.updateColor()


def ProcessBoolToggleUpdate(node, context):
    node.inputs["_BOOL"].hide = 1-node.process_bool_toggle  # 先触发回调再更新
    return


class OmniNode(Node):
    '''节点基类'''
    bug_color: bpy.props.FloatVectorProperty(
        name="link连接bug", size=3, subtype="COLOR", default=(1, 0, 0))  # type: ignore
    bug_text: bpy.props.StringProperty(
        name="Bug详情", default="No bug")  # type: ignore
    is_bug: bpy.props.BoolProperty(
        name="是否bug", default=False, update=setBugNode)  # type: ignore
    debug: bpy.props.BoolProperty(name="调试", default=False)  # type: ignore

    default_width: bpy.props.FloatProperty(default=250)  # type: ignore
    default_heigh: bpy.props.FloatProperty(default=100)  # type: ignore

    is_output_node: bpy.props.BoolProperty(
        name="是否是输出节点", default=False, update=setOutputNode)  # type: ignore
    output_color: bpy.props.FloatVectorProperty(
        name="作为输出节点的高亮颜色", size=3, subtype="COLOR", default=(0, 0.6, 0))  # type: ignore
    base_color: bpy.props.FloatVectorProperty(
        name="默认类型", size=3, subtype="COLOR", default=(0.191, 0.061, 0.012))  # type: ignore
    omni_description: bpy.props.StringProperty(
        name="OMNI节点描述", default="没有使用描述")  # type: ignore
    process_bool_toggle: bpy.props.BoolProperty(
        name="是否公开bool逻辑接口", default=False, update=ProcessBoolToggleUpdate)  # type: ignore

    # 新增属性用于rebuild
    SocketInMetaDict: bpy.props.StringProperty(default="{}") # type: ignore
    SocketOutMetaDict: bpy.props.StringProperty(default="{}") # type: ignore
    SocketDefaultDict: bpy.props.StringProperty(default="{}") # type: ignore
    SocketIsMultiDict: bpy.props.StringProperty(default="{}") # type: ignore


# --------------------------------自身基本特性相关------------------------------

    def size2default(self):
        self.width = self.default_width
        self.height = self.default_heigh

    def updateColor(self):
        if self.is_bug:
            self.color = self.bug_color
            return
        if self.is_output_node:
            self.color = self.output_color
            return
        else:
            self.color = self.base_color
# --------------------------------自身功能相关------------------------------

    def processUsingPool(self, func):
        """程序化节点独有调用,手动创建节点要模仿这个写
        使用pool中的数据,处理也返回到pool中
        """
        pool = self["fatherTree"].pool
        kargs = pool[self.name].inputs
        outputs = pool[self.name].outputs
        if not kargs["_BOOL"]:
            return  # 逻辑关闭立刻退出
        try:
            del kargs["_BOOL"]  # 不传入BOOL变量
            result = func(**kargs)
        except Exception as error:
            return error  # 有错误返回错误

        if not isinstance(result, tuple):  # TODO:这样判定多返回会导致返回元组的函数无法正常生成,不好解决
            outputs["_OUTPUT0"] = result
            return  # 单返回
        else:
            index = 0
            for i in result:
                outputs["_OUTPUT"+str(index)] = i
                index += 1
            return  # 多返回

    def process(self):
        print("PROCESS RUN:", self.name)
        print("BOOL:", self["fatherTree"].pool[self.name].inputs.get("_BOOL"))
        self.is_bug = False
        self.property_unset("bug_text")  # 首先清空bug
        return
# --------------------------------rebuild相关------------------------------

    def rebuild(self):
        import json
        tree = self["fatherTree"]
        # 收集链接信息，避免 later invalid link objects
        input_links = []
        for sock in self.inputs:
            if sock.identifier == "_BOOL":
                continue
            for link in sock.links:
                input_links.append({
                    "from_node": link.from_node.name,
                    "from_socket": link.from_socket.identifier,
                    "to_socket": sock.identifier,
                })
        output_links = []
        for sock in self.outputs:
            for link in sock.links:
                output_links.append({
                    "from_socket": sock.identifier,
                    "to_node": link.to_node.name,
                    "to_socket": link.to_socket.identifier,
                })
        # 移除旧socket 和 关联链接
        for sock in list(self.inputs):
            if sock.identifier != "_BOOL":
                for link in list(sock.links):
                    tree.links.remove(link)
                self.inputs.remove(sock)
        for sock in list(self.outputs):
            for link in list(sock.links):
                tree.links.remove(link)
            self.outputs.remove(sock)
        # 重新创建 socket
        cls = type(self)
        in_meta = getattr(cls, "_SocketInMetaDict", None)
        out_meta = getattr(cls, "_SocketOutMetaDict", None)
        default_meta = getattr(cls, "_SocketDefaultDict", None)
        is_multi_meta = getattr(cls, "_SocketIsMultiDict", None)
        if in_meta is None or out_meta is None or default_meta is None:
            in_meta = json.loads(self.SocketInMetaDict)
            out_meta = json.loads(self.SocketOutMetaDict)
            default_meta = json.loads(self.SocketDefaultDict)
            is_multi_meta = json.loads(self.SocketIsMultiDict)
        for identifier, meta in in_meta.items():
            sock = self.inputs.new(**meta)
            default_value = default_meta.get(identifier, None)
            if default_value is not None:
                try:
                    sock.default_value = default_value
                except Exception:
                    pass
            if is_multi_meta.get(identifier, False):
                sock.display_shape = "SQUARE"

        for identifier, meta in out_meta.items():
            sock = self.outputs.new(**meta)
            if is_multi_meta.get(identifier, False):
                sock.display_shape = "SQUARE"
        # 重新连接，按 identifier 匹配
        for link_info in input_links:
            to_id = link_info["to_socket"]
            if to_id not in in_meta:
                continue
            from_node = tree.nodes.get(link_info["from_node"])
            if from_node is None:
                continue
            from_socket = from_node.outputs.get(link_info["from_socket"])
            to_socket = self.inputs.get(to_id)
            if from_socket is None or to_socket is None:
                continue
            tree.links.new(from_socket, to_socket)
        for link_info in output_links:
            from_id = link_info["from_socket"]
            if from_id not in out_meta:
                continue
            to_node = tree.nodes.get(link_info["to_node"])
            if to_node is None:
                continue
            from_socket = self.outputs.get(from_id)
            to_socket = to_node.inputs.get(link_info["to_socket"])
            if from_socket is None or to_socket is None:
                continue
            tree.links.new(from_socket, to_socket)
# --------------------------------原生方法重载------------------------------

    def init(self, context):
        fatherTree = self["fatherTree"] = bpy.context.space_data.node_tree
        fatherTree.doing_initNode = True  # 更新树状态-正在新建节点,子类定义init后要切回来
        self.use_custom_color = True
        self.updateColor()
        self.size2default()

        # 生成布尔总开关
        bool = self.inputs.new(type="NodeSocketBool",
                               name="执行", identifier="_BOOL")
        bool.hide = True
        bool.default_value = True

    def draw_label(self):
        '''动态标签'''
        return f"{self.name}"

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        '''绘制节点按钮'''
        # bug描述
        if self.is_bug:
            layout.label(text=f"{self.bug_text}")

        main_row = layout.row(align=False)

        row_L = main_row.row(align=True)  # 左侧按钮
        row_L.alignment = 'LEFT'
        if self.is_bug:
            row_L.label(icon="ERROR",)
        
        row_L.prop(self, "debug", text="", toggle=True, icon="FILE_SCRIPT")
        row_L.operator(
            NodeBaseOps.NodeRebuildSockets.bl_idname, text="", icon="NODETREE")
        SetDefaultSize = row_L.operator(
            NodeBaseOps.NodeSetDefaultSize.bl_idname, text="", icon="REMOVE")
        SetDefaultSize.node_name = self.name
        SetBiggerSize = row_L.operator(
            NodeBaseOps.NodeSetBiggerSize.bl_idname, text="", icon="ADD")
        SetBiggerSize.node_name = self.name


        row_R = main_row.row(align=True)  # 右侧按钮
        row_R.alignment = 'RIGHT'
        row_R.prop(self, "is_output_node", text="", icon="ANIM_DATA")
        row_R.operator(
            NodeBaseOps.LayerRunning.bl_idname, text="", icon="FILE_REFRESH")
        
        # debug显示
        if self.debug:
            # 内部prop详情
            pool = self["fatherTree"].pool
            if pool[self.name]:
                inputsInfo: dict = pool[self.name].inputs
                outputInfo: dict = pool[self.name].outputs
                # 输入表
                col = layout.column(align=True)
                grid = col.grid_flow(columns=3, align=True)

                grid.label(text="[标识符]")
                for key in inputsInfo.keys():
                    grid.label(text=str(key))
                grid.label(text="[值]")
                for value in inputsInfo.values():
                    grid.label(text=str(value))
                grid.label(text="[类型]")
                for value in inputsInfo.values():
                    grid.label(text=type(value).__name__)
                # 输出表
                layout.label(text="")
                col = layout.column(align=True)
                grid = col.grid_flow(columns=3, align=True)

                grid.label(text="[标识符]")
                for key in outputInfo.keys():
                    grid.label(text=str(key))
                grid.label(text="[值]")
                for value in outputInfo.values():
                    grid.label(text=str(value))
                grid.label(text="[类型]")
                for value in outputInfo.values():
                    grid.label(text=type(value).__name__)

            # layout.label(text="Socket构建")
            # layout.label(text="SocketInMetaDict: ")
            # layout.label(text=self.SocketInMetaDict)
            # layout.label(text="SocketOutMetaDict: ")
            # layout.label(text=self.SocketOutMetaDict)
            # layout.label(text="SocketDefaultDict: ")
            # layout.label(text=self.SocketDefaultDict)
            # layout.label(text="SocketIsMultiDict: ")
            # layout.label(text=self.SocketIsMultiDict)
        pass


    def draw_buttons_ext(self, context, layout: bpy.types.UILayout):
        '''侧边栏中节点属性绘制'''
        row = layout.row(align=True)
        # 是否是自动更新的
        if context.space_data.node_tree.is_auto_update:
            row.alert = True
            row.prop(context.space_data.node_tree,
                    "is_auto_update", text="树自动更新", icon="DECORATE_LINKED")
            row.alert = False
        else:
            row.prop(context.space_data.node_tree,
                    "is_auto_update", text="树自动更新", icon="UNLINKED")
        row.prop(self, "process_bool_toggle",
                    text="逻辑socket", icon="DECORATE_ANIMATE")
            
        # OMNI节点描述
        lines = self.omni_description.splitlines()
        for line in lines:
            layout.label(text=line)

        pass