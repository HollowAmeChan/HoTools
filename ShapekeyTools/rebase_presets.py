"""保留旧模块名的查询入口；新代码请使用 :mod:`shapekey_catalog`。"""

try:
    from .shapekey_catalog import *
    from .shapekey_catalog import __all__
except ImportError:  # 兼容直接导入脚本
    from shapekey_catalog import *
    from shapekey_catalog import __all__
