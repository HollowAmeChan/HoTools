import bpy
from bpy.types import Node, NodeSocket
from . import OmniNodeOperator
import json

def setOutputNode(node, context):
    node.updateColor()


def setBugNode(node, context):
    node.updateColor()


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
        name="默认类型颜色", size=3, subtype="COLOR", default=(0.191, 0.061, 0.012))  # type: ignore
    omni_description: bpy.props.StringProperty(
        name="OMNI节点描述", default="没有使用描述")  # type: ignore
    
    _SocketInMetaDict = None# 正常初始化时读取,在类生成时就被定义了，不会随着工程持久化储存
    _SocketOutMetaDict = None
    _SocketDefaultDict = None
    _SocketIsMultiDict = None


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

        try:
            result = func(**kargs)
        except Exception as error:
            return error  # 有错误返回错误

        if not isinstance(result, tuple):
            outputs["_OUTPUT0"] = result
            return  # 单返回
        else:
            index = 0
            for i in result:
                outputs["_OUTPUT"+str(index)] = i
                index += 1
            return  # 多返回

    def process(self):
        self.is_bug = False
        self.property_unset("bug_text")  # 首先清空bug
        return
# --------------------------------rebuild相关------------------------------

    def rebuild(self):
        # TODO:没有考虑非functionnode的rebuild，也就是没有存_SocketMetaDict等数据的node会报错，未来会添加一些专用的带UI的节点无法使用function来描述
        # TODO:没有对OmniNode某些自带的参数进行rebuild，比如base_color，is_output_node等（我不确定是不是所有的基类变量都应该被rebuild）
        tree = self["fatherTree"]
        # -----------------------------
        # 1. 缓存旧 socket 的值和链接信息
        # -----------------------------
        input_value_cache = {}
        output_value_cache = {}

        for sock in self.inputs:
            try:
                input_value_cache[sock.identifier] = getattr(sock, "default_value", None)
            except Exception:
                pass

        for sock in self.outputs:
            try:
                output_value_cache[sock.identifier] = getattr(sock, "default_value", None)
            except Exception:
                pass

        # -----------------------------
        # 2. 收集 link
        # -----------------------------
        input_links = []
        for sock in self.inputs:
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

        # -----------------------------
        # 3. 清理旧 socket
        # -----------------------------
        for sock in list(self.inputs):
            for link in list(sock.links):
                tree.links.remove(link)
            self.inputs.remove(sock)

        for sock in list(self.outputs):
            for link in list(sock.links):
                tree.links.remove(link)
            self.outputs.remove(sock)

        # -----------------------------
        # 4. 重新创建 socket
        # -----------------------------
        in_meta = self._SocketInMetaDict
        out_meta = self._SocketOutMetaDict
        default_meta = self._SocketDefaultDict
        is_multi_meta = self._SocketIsMultiDict

        # -----------------------------
        # 5. inputs rebuild + restore value
        # -----------------------------
        for identifier, meta in in_meta.items():
            sock = self.inputs.new(**meta)
            value = input_value_cache.get(identifier, None)
            if value is None:
                value = default_meta.get(identifier, None)

            if value is not None:
                try:
                    sock.default_value = value
                except Exception:
                    pass

            if is_multi_meta.get(identifier, False):
                sock.display_shape = "SQUARE"

        # -----------------------------
        # 6. outputs rebuild + restore value
        # -----------------------------
        for identifier, meta in out_meta.items():
            sock = self.outputs.new(**meta)

            value = output_value_cache.get(identifier, None)
            if value is not None:
                try:
                    sock.default_value = value
                except Exception:
                    pass

            if is_multi_meta.get(identifier, False):
                sock.display_shape = "SQUARE"

        # -----------------------------
        # 7. reconnect input links
        # -----------------------------
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

        # -----------------------------
        # 8. reconnect output links
        # -----------------------------
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
        Rebuild = row_L.operator(
            OmniNodeOperator.NodeRebuildSockets.bl_idname, text="", icon="NODETREE")
        Rebuild.node_name = self.name
        SetDefaultSize = row_L.operator(
            OmniNodeOperator.NodeSetDefaultSize.bl_idname, text="", icon="REMOVE")
        SetDefaultSize.node_name = self.name
        SetBiggerSize = row_L.operator(
            OmniNodeOperator.NodeSetBiggerSize.bl_idname, text="", icon="ADD")
        SetBiggerSize.node_name = self.name


        row_R = main_row.row(align=True)  # 右侧按钮
        row_R.alignment = 'RIGHT'
        row_R.prop(self, "is_output_node", text="", icon="ANIM_DATA")
        row_R.operator(
            OmniNodeOperator.LayerRunning.bl_idname, text="", icon="FILE_REFRESH")
        
        # debug显示
        # TODO:目前显示的比较丑，列表太长会看不清楚（节点最大宽度不够用，应该要换行，或者有个按钮能看），同时英文变量名会被强制汉化（需要插入0长字符防止汉化）
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

            # TODO:很丑很难看
            layout.label(text="Socket构建")
            layout.label(text="SocketInMetaDict: ")
            layout.label(text=self._SocketInMetaDict)
            layout.label(text="SocketOutMetaDict: ")
            layout.label(text=self._SocketOutMetaDict)
            layout.label(text="SocketDefaultDict: ")
            layout.label(text=self._SocketDefaultDict)
            layout.label(text="SocketIsMultiDict: ")
            layout.label(text=self._SocketIsMultiDict)
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
            
        # OMNI节点描述
        lines = self.omni_description.splitlines()
        for line in lines:
            layout.label(text=line)

        pass