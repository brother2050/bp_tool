"""
基础抽象层：引擎接口、数据模型、能力枚举。

所有下载引擎必须继承 DownloadEngine 并实现其抽象方法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Dict, List, Any
import platform
import time


def current_os() -> str:
    """返回当前操作系统: 'linux', 'darwin', 'windows'"""
    return platform.system().lower()


class EngineCapability(Enum):
    """引擎能力标志"""
    HTTP = auto()           # HTTP/HTTPS 下载
    FTP = auto()            # FTP 下载
    METALINK = auto()       # Metalink 支持
    TORRENT = auto()        # BitTorrent 支持
    MAGNET = auto()         # Magnet 链接
    MULTI_CONNECTION = auto()  # 多连接/分块下载
    RESUME = auto()         # 断点续传
    PROXY = auto()          # 代理支持
    SPEED_LIMIT = auto()    # 限速
    HEADER_CUSTOM = auto()  # 自定义请求头
    PARALLEL = auto()       # 并行多文件下载
    VIDEO = auto()          # 视频平台提取
    CLOUD_STORAGE = auto()  # 云存储协议
    MEGA = auto()           # Mega.nz 协议


@dataclass
class DownloadRequest:
    """下载请求"""
    url: str                                    # 下载 URL
    output_dir: str = "."                       # 输出目录
    filename: Optional[str] = None              # 指定文件名(None=自动)
    headers: Dict[str, str] = field(default_factory=dict)  # 自定义请求头
    proxy: Optional[str] = None                 # 代理地址
    timeout: int = 60                           # 超时(秒)
    max_retries: int = 3                        # 最大重试次数
    speed_limit: Optional[str] = None           # 限速 (如 "1M", "500K")
    connections: int = 0                        # 连接数(0=引擎默认)
    extra: Dict[str, Any] = field(default_factory=dict)  # 引擎特定参数
    checksum: Optional[str] = None              # 校验值 (type:hash, 如 "sha256:abc...")
    referer: Optional[str] = None               # Referer 头
    user_agent: Optional[str] = None            # User-Agent
    cookies: Optional[str] = None               # Cookie 字符串或文件路径


@dataclass
class DownloadResult:
    """下载结果"""
    success: bool                               # 是否成功
    engine_name: str = ""                       # 使用的引擎
    url: str = ""                               # 原始 URL
    output_path: Optional[str] = None           # 输出文件路径
    file_size: Optional[int] = None             # 文件大小(字节)
    elapsed: float = 0.0                        # 耗时(秒)
    speed: float = 0.0                          # 平均速度(B/s)
    error: Optional[str] = None                 # 错误信息
    return_code: int = 0                        # 进程返回码
    stdout: str = ""                            # 标准输出
    stderr: str = ""                            # 标准错误
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据

    @property
    def speed_human(self) -> str:
        """人类可读的速度"""
        if self.speed <= 0:
            return "N/A"
        for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
            if self.speed < 1024:
                return f"{self.speed:.1f} {unit}"
            self.speed /= 1024
        return f"{self.speed:.1f} TB/s"

    @property
    def size_human(self) -> str:
        """人类可读的文件大小"""
        if not self.file_size or self.file_size <= 0:
            return "N/A"
        size = float(self.file_size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"


class DownloadEngine(ABC):
    """
    下载引擎抽象基类。

    每个引擎插件必须：
    1. 继承此类
    2. 实现所有 @abstractmethod
    3. 在模块加载时通过 @EngineRegistry.register() 装饰器注册
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎唯一标识名 (小写, 下划线分隔)"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """引擎显示名称"""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> List[EngineCapability]:
        """引擎支持的能力列表"""
        ...

    @property
    def platforms(self) -> List[str]:
        """引擎支持的操作系统列表。返回空列表表示全平台支持。
        值: 'linux', 'darwin', 'windows'"""
        return []  # 空 = 全平台

    @property
    def install_hint(self) -> str:
        """引擎未安装时的安装提示"""
        return ""

    def is_platform_compatible(self) -> bool:
        """检查当前操作系统是否兼容此引擎"""
        supported = self.platforms
        if not supported:
            return True  # 空列表 = 全平台
        return current_os() in supported

    @abstractmethod
    def is_available(self) -> bool:
        """检测引擎是否可用(已安装/可访问)"""
        ...

    def availability_info(self) -> dict:
        """返回引擎可用性详情，用于诊断和展示"""
        plat_ok = self.is_platform_compatible()
        installed = self.is_available() if plat_ok else False
        return {
            "name": self.name,
            "display_name": self.display_name,
            "platform_compatible": plat_ok,
            "installed": installed,
            "available": plat_ok and installed,
            "current_os": current_os(),
            "supported_platforms": self.platforms or ["all"],
            "install_hint": self.install_hint,
        }

    @abstractmethod
    def download(self, request: DownloadRequest) -> DownloadResult:
        """执行下载"""
        ...

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        """
        验证请求是否被此引擎支持。
        返回 None 表示支持，返回字符串表示不支持的原因。
        """
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        """
        构建命令行参数列表（用于 CLI 引擎）。
        非 CLI 引擎可忽略。
        """
        return []

    def __repr__(self) -> str:
        status = "✓" if self.is_available() else "✗"
        return f"<{self.__class__.__name__} [{status}] {self.display_name}>"
