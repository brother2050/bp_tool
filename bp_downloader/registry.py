"""
引擎注册表：自动发现、注册、查询引擎插件。

使用装饰器 @EngineRegistry.register() 注册引擎，模块导入时自动完成。
"""

import importlib
import sys
import pkgutil
from typing import Dict, List, Optional, Type
from .base import DownloadEngine, EngineCapability


class EngineRegistry:
    """
    全局引擎注册表。

    用法：
        @EngineRegistry.register
        class MyEngine(DownloadEngine):
            ...
    """

    _engines: Dict[str, Type[DownloadEngine]] = {}
    _instances: Dict[str, DownloadEngine] = {}

    @classmethod
    def register(cls, engine_class: Type[DownloadEngine]) -> Type[DownloadEngine]:
        """注册引擎类（装饰器）"""
        # 从 property getter 推断 name
        name = None
        for base in engine_class.__mro__:
            if "name" in base.__dict__:
                descriptor = base.__dict__["name"]
                if isinstance(descriptor, property) and descriptor.fget:
                    try:
                        # 调用 property getter 用一个临时占位实例
                        class _Tmp(engine_class):
                            pass
                        name = descriptor.fget(_Tmp.__new__(_Tmp))
                    except Exception:
                        pass
                break

        if name is None:
            name = engine_class.__name__.lower().replace("engine", "")

        cls._engines[name] = engine_class
        return engine_class

    @classmethod
    def get_engine_class(cls, name: str) -> Optional[Type[DownloadEngine]]:
        """获取引擎类"""
        return cls._engines.get(name)

    @classmethod
    def get_engine(cls, name: str) -> Optional[DownloadEngine]:
        """获取引擎实例（单例）"""
        if name not in cls._instances:
            engine_cls = cls._engines.get(name)
            if engine_cls:
                cls._instances[name] = engine_cls()
        return cls._instances.get(name)

    @classmethod
    def get_all_engines(cls) -> Dict[str, Type[DownloadEngine]]:
        """获取所有注册的引擎类"""
        return dict(cls._engines)

    @classmethod
    def get_available_engines(cls) -> Dict[str, DownloadEngine]:
        """获取所有可用的引擎实例"""
        result = {}
        for name in cls._engines:
            engine = cls.get_engine(name)
            if engine and engine.is_available():
                result[name] = engine
        return result

    @classmethod
    def find_by_capability(cls, capability: EngineCapability) -> List[DownloadEngine]:
        """按能力查找引擎"""
        result = []
        for name in cls._engines:
            engine = cls.get_engine(name)
            if engine and engine.is_available() and capability in engine.capabilities:
                result.append(engine)
        return result

    @classmethod
    def clear(cls):
        """清空注册表（测试用）"""
        cls._engines.clear()
        cls._instances.clear()

    @classmethod
    def reset_instances(cls):
        """重置实例缓存"""
        cls._instances.clear()

    @classmethod
    def reload(cls):
        """清空注册表并重新发现所有引擎"""
        cls.clear()
        discover_engines(force=True)

    @classmethod
    def summary(cls) -> str:
        """返回注册表摘要"""
        lines = ["Registered engines:"]
        for name, engine_cls in sorted(cls._engines.items()):
            try:
                inst = cls.get_engine(name)
                status = "✓ available" if inst and inst.is_available() else "✗ unavailable"
                caps = ", ".join(c.name for c in inst.capabilities) if inst else "?"
            except Exception:
                status = "? error"
                caps = "?"
            lines.append(f"  {name:20s} [{status}] caps: {caps}")
        return "\n".join(lines)


def discover_engines(package_name: str = "bp_downloader.engines", force: bool = False):
    """
    自动发现并导入 engines 包下的所有模块，触发 @register 装饰器。

    Args:
        package_name: 引擎包名
        force: 强制重新导入（清缓存后使用）
    """
    try:
        package = importlib.import_module(package_name)
    except ImportError:
        return

    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        full_name = f"{package_name}.{modname}"
        if force and full_name in sys.modules:
            del sys.modules[full_name]
        importlib.import_module(full_name)


def get_registry() -> EngineRegistry:
    """获取注册表并确保引擎已发现"""
    if not EngineRegistry._engines:
        discover_engines()
    return EngineRegistry
