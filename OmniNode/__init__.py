_REGISTERED = False


def register():
    global _REGISTERED
    if _REGISTERED:
        return
    from .. import PropertyCurve  # NOQA: E402
    from .NodeTree import OmniNodeRegister, OmniNodeTree  # NOQA: E402
    from .NodeTree import OmniNodeSocket  # NOQA: E402
    from .NodeTree import OmniNodeOperator  # NOQA: E402
    from .NodeTree import OmniNodeDraw  # NOQA: E402
    from . import OmniNodePanel  # NOQA: E402
    from .NodeTree.OmniTracy import report_startup as _tracy_report  # NOQA: E402

    OmniNodeDraw.register()
    OmniNodeOperator.register()
    OmniNodeTree.register()
    PropertyCurve.register()
    OmniNodeSocket.register()
    OmniNodeRegister.register()
    OmniNodePanel.register()
    _tracy_report()
    _REGISTERED = True


def unregister():
    global _REGISTERED
    if not _REGISTERED:
        return
    from .. import PropertyCurve  # NOQA: E402
    from .NodeTree import OmniNodeRegister, OmniNodeTree  # NOQA: E402
    from .NodeTree import OmniNodeSocket  # NOQA: E402
    from .NodeTree import OmniNodeOperator  # NOQA: E402
    from .NodeTree import OmniNodeDraw  # NOQA: E402
    from . import OmniNodePanel  # NOQA: E402

    # 清理物理世界调试绘制 handler（若已注册）
    try:
        from .NodeTree.Function.physicsWorld.debug_draw import _remove_draw_handler, _DRAW_STORE
        _DRAW_STORE.clear()
        _remove_draw_handler()
    except Exception:
        pass

    OmniNodePanel.unregister()
    OmniNodeDraw.unregister()
    OmniNodeOperator.unregister()
    OmniNodeTree.unregister()
    OmniNodeSocket.unregister()
    PropertyCurve.unregister()
    OmniNodeRegister.unregister()
    _REGISTERED = False
