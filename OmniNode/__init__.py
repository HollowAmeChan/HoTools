from .NodeTree.Base import Nodes, OmniNodeTree


def register():
    print("==========   OMNI NodeTree    ==========")
    from .NodeTree.Base import NodeSocket  # NOQA: E402
    from .operator import NodeBaseOps  # NOQA: E402
    import os  # NOQA: E402
    import sys  # NOQA: E402
    import bpy  # NOQA: E402
    # 将本地的第三方库导入
    plugin_dir = os.path.dirname(__file__)
    lib_dir = os.path.abspath(os.path.join(
        plugin_dir, ".", "lib"))
    sys.path.append(lib_dir)
    
    NodeBaseOps.register()
    OmniNodeTree.register()
    NodeSocket.register()
    Nodes.register()
    print("==========         END         ==========")


def unregister():
    from .NodeTree.Base import NodeSocket  # NOQA: E402
    from .operator import NodeBaseOps  # NOQA: E402
    NodeBaseOps.unregister()
    OmniNodeTree.unregister()
    NodeSocket.unregister()
    Nodes.unregister()
