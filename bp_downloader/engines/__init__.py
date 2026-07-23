"""engines 包初始化 — 自动导入所有引擎模块以触发注册。"""

import importlib
import pkgutil
import os

# 自动导入同目录下所有 .py 模块 (排除 __init__.py)
_package_dir = os.path.dirname(__file__)
for _finder, _name, _ispkg in pkgutil.iter_modules([_package_dir]):
    if _name != "__init__":
        importlib.import_module(f"{__name__}.{_name}")
