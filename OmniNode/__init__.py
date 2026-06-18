from .NodeTree import GraphNode, OmniNodeRegister

from .NodeTree import OmniNodeTree


def register():
    from .NodeTree import OmniCurve  # NOQA: E402
    from .NodeTree import OmniNodeSocket  # NOQA: E402
    from .NodeTree import OmniNodeOperator  # NOQA: E402
    from .NodeTree import OmniNodeDraw  # NOQA: E402
    from . import OmniNodePanel  # NOQA: E402
    
    OmniNodeDraw.register()
    OmniNodeOperator.register()
    OmniNodeTree.register()
    OmniCurve.register()
    OmniNodeSocket.register()
    OmniNodeRegister.register()
    OmniNodePanel.register()


def unregister():
    from .NodeTree import OmniCurve  # NOQA: E402
    from .NodeTree import OmniNodeSocket  # NOQA: E402
    from .NodeTree import OmniNodeOperator  # NOQA: E402
    from .NodeTree import OmniNodeDraw  # NOQA: E402
    from . import OmniNodePanel  # NOQA: E402
    OmniNodePanel.unregister()
    OmniNodeDraw.unregister()
    OmniNodeOperator.unregister()
    OmniNodeTree.unregister()
    OmniNodeSocket.unregister()
    OmniCurve.unregister()
    OmniNodeRegister.unregister()
