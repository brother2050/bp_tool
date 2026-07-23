"""
bp_downloader — 统一多引擎下载管理器

支持 10+ 下载引擎，插件化架构，配置驱动，智能路由。
"""

__version__ = "1.0.0"

from .base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from .registry import EngineRegistry, get_registry
from .config import DownloaderConfig
from .downloader import UnifiedDownloader

__all__ = [
    "DownloadEngine",
    "DownloadRequest",
    "DownloadResult",
    "EngineCapability",
    "EngineRegistry",
    "get_registry",
    "DownloaderConfig",
    "UnifiedDownloader",
]
