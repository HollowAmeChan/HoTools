"""HoTools 通用属性曲线模块。"""

from . import definitions as _definitions
from . import icons as _icons

from .definitions import *  # noqa: F401,F403
from .presets import *  # noqa: F401,F403
from .sampling import *  # noqa: F401,F403
from .drawing import *  # noqa: F401,F403
from .icons import *  # noqa: F401,F403


def register():
    _definitions.register()
    _icons.register_icon_previews()
    try_use_native_curve_sampler_backend()


def unregister():
    use_python_curve_sampler_backend()
    _icons.unregister_icon_previews()
    _definitions.unregister()
