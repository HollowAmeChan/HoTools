from .NodeTree import NodeFactory

from .NodeTree import OmniNodeTree


def register():
    print("==========   OMNI NodeTree    ==========")
    from .NodeTree import OmniNodeSocket  # NOQA: E402
    from .NodeTree import OmniNodeOperators  # NOQA: E402
    import os  # NOQA: E402
    import sys  # NOQA: E402
    import bpy  # NOQA: E402
    # 将本地的第三方库导入
    plugin_dir = os.path.dirname(__file__)
    lib_dir = os.path.abspath(os.path.join(
        plugin_dir, ".", "lib"))
    sys.path.append(lib_dir)
    
    OmniNodeOperators.register()
    OmniNodeTree.register()
    OmniNodeSocket.register()
    NodeFactory.register()
    print("==========         END         ==========")


def unregister():
    from .NodeTree import OmniNodeSocket  # NOQA: E402
    from .NodeTree import OmniNodeOperators  # NOQA: E402
    OmniNodeOperators.unregister()
    OmniNodeTree.unregister()
    OmniNodeSocket.unregister()
    NodeFactory.unregister()
