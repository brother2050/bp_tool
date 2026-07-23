"""
统一下载管理器 — 路由、重试、并发、回退。

核心调度层，根据 URL 模式、配置规则、引擎优先级自动选择最佳引擎。
"""

import os
import time
import fnmatch
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse

from .base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from .registry import EngineRegistry, discover_engines, get_registry
from .config import DownloaderConfig, EngineConfig
from .utils import match_pattern


class UnifiedDownloader:
    """
    统一下载管理器。

    功能：
    - 自动引擎选择（按能力、优先级、可用性）
    - 路由规则（URL 模式 → 指定引擎）
    - 失败回退（自动尝试下一个引擎）
    - 并发下载
    - 配置驱动
    """

    def __init__(self, config: Optional[DownloaderConfig] = None):
        self.config = config or DownloaderConfig()
        # 确保引擎已发现
        discover_engines()
        self._registry = EngineRegistry

    def list_engines(self) -> Dict[str, Dict[str, Any]]:
        """列出所有引擎及其状态"""
        result = {}
        for name, engine_cls in self._registry.get_all_engines().items():
            engine = self._registry.get_engine(name)
            ec = self.config.get_engine_config(name)
            result[name] = {
                "display_name": engine.display_name if engine else name,
                "available": engine.is_available() if engine else False,
                "enabled": ec.enabled,
                "priority": ec.priority,
                "capabilities": [c.name for c in engine.capabilities] if engine else [],
            }
        return result

    def select_engine(
        self,
        request: DownloadRequest,
        preferred: Optional[str] = None,
    ) -> Optional[DownloadEngine]:
        """
        为请求选择最佳引擎。

        选择逻辑：
        1. 路由规则匹配 → 指定引擎
        2. preferred 引擎（如果可用且启用）
        3. default_engine 配置
        4. 按优先级排序的可用引擎
        """
        # 1. 路由规则
        for rule in self.config.route_rules:
            pattern = rule.get("pattern", "")
            engine_name = rule.get("engine", "")
            if match_pattern(request.url, pattern):
                engine = self._registry.get_engine(engine_name)
                if engine and engine.is_available():
                    ec = self.config.get_engine_config(engine_name)
                    if ec.enabled:
                        return engine

        # 2. 指定引擎
        if preferred:
            engine = self._registry.get_engine(preferred)
            if engine and engine.is_available():
                ec = self.config.get_engine_config(preferred)
                if ec.enabled:
                    return engine

        # 3. 默认引擎
        if self.config.default_engine:
            engine = self._registry.get_engine(self.config.default_engine)
            if engine and engine.is_available():
                ec = self.config.get_engine_config(self.config.default_engine)
                if ec.enabled:
                    return engine

        # 4. 按优先级选择
        candidates = []
        for name in self._registry.get_all_engines():
            engine = self._registry.get_engine(name)
            if not engine or not engine.is_available():
                continue
            ec = self.config.get_engine_config(name)
            if not ec.enabled:
                continue
            # 验证请求
            err = engine.validate_request(request)
            if err:
                continue
            candidates.append((ec.priority, name, engine))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][2]

        return None

    def _apply_defaults(self, request: DownloadRequest) -> DownloadRequest:
        """应用全局配置默认值"""
        if not request.output_dir or request.output_dir == ".":
            request.output_dir = self.config.output_dir
        if request.timeout <= 0:
            request.timeout = self.config.timeout
        if request.max_retries <= 0:
            request.max_retries = self.config.max_retries
        if not request.speed_limit and self.config.speed_limit:
            request.speed_limit = self.config.speed_limit
        if not request.proxy and self.config.proxy:
            request.proxy = self.config.proxy
        if not request.user_agent and self.config.user_agent:
            request.user_agent = self.config.user_agent
        os.makedirs(request.output_dir, exist_ok=True)
        return request

    def download(
        self,
        url: str,
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        engine: Optional[str] = None,
        fallback: bool = True,
        **kwargs,
    ) -> DownloadResult:
        """
        单文件下载。

        Args:
            url: 下载 URL
            output_dir: 输出目录
            filename: 指定文件名
            engine: 指定引擎
            fallback: 失败时是否尝试回退引擎
            **kwargs: 传递给 DownloadRequest 的额外参数
        """
        request = DownloadRequest(
            url=url,
            output_dir=output_dir or self.config.output_dir,
            filename=filename,
            **kwargs,
        )
        request = self._apply_defaults(request)

        # 选择引擎
        selected = self.select_engine(request, preferred=engine)
        if not selected:
            return DownloadResult(
                success=False,
                engine_name="none",
                url=url,
                error="No available engine for this URL",
            )

        # 尝试下载
        result = selected.download(request)

        # 回退逻辑
        if not result.success and fallback:
            fallback_list = self.config.fallback_engines
            for fb_name in fallback_list:
                fb_engine = self._registry.get_engine(fb_name)
                if fb_engine and fb_engine.is_available() and fb_engine.name != selected.name:
                    err = fb_engine.validate_request(request)
                    if err:
                        continue
                    result = fb_engine.download(request)
                    if result.success:
                        break

        return result

    def download_batch(
        self,
        urls: List[str],
        output_dir: Optional[str] = None,
        engine: Optional[str] = None,
        max_workers: Optional[int] = None,
        **kwargs,
    ) -> List[DownloadResult]:
        """
        批量并发下载。

        Args:
            urls: URL 列表
            output_dir: 输出目录
            engine: 指定引擎
            max_workers: 最大并发数
        """
        workers = max_workers or self.config.max_concurrent
        results = []

        def _download_one(url):
            return self.download(url, output_dir=output_dir, engine=engine, **kwargs)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_download_one, url): url for url in urls}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as e:
                    url = futures[future]
                    result = DownloadResult(
                        success=False, engine_name="error", url=url, error=str(e)
                    )
                results.append(result)

        return results

    def auto_download(
        self,
        url: str,
        output_dir: Optional[str] = None,
        **kwargs,
    ) -> DownloadResult:
        """
        智能下载：自动检测 URL 类型并选择最合适的方式。

        - 视频平台 → yt-dlp
        - magnet/torrent → aria2c / transmission
        - mega.nz → megatools
        - 云存储 → rclone
        - 普通 HTTP → 按优先级选择
        """
        url_lower = url.lower()

        # 视频平台
        video_domains = [
            "youtube.com", "youtu.be", "bilibili.com", "b23.tv",
            "twitter.com", "x.com", "tiktok.com", "instagram.com",
            "vimeo.com", "dailymotion.com", "twitch.tv",
        ]
        parsed = urlparse(url)
        host = (parsed.hostname or "").lstrip("www.")
        if any(host.endswith(d) for d in video_domains):
            return self.download(url, output_dir=output_dir, engine="yt_dlp", **kwargs)

        # Magnet / Torrent
        if url.startswith("magnet:") or url.endswith(".torrent"):
            # 优先 aria2c，回退 transmission
            engine = self._registry.get_engine("aria2c")
            if engine and engine.is_available():
                return self.download(url, output_dir=output_dir, engine="aria2c", fallback=False, **kwargs)
            engine = self._registry.get_engine("transmission")
            if engine and engine.is_available():
                return self.download(url, output_dir=output_dir, engine="transmission", fallback=False, **kwargs)
            return DownloadResult(
                success=False, engine_name="none", url=url,
                error="No torrent engine available (install aria2c or transmission-cli)",
            )

        # Mega.nz
        if "mega.nz" in url or "mega.co.nz" in url:
            engine = self._registry.get_engine("megatools")
            if engine and engine.is_available():
                return self.download(url, output_dir=output_dir, engine="megatools", fallback=False, **kwargs)
            return DownloadResult(
                success=False, engine_name="none", url=url,
                error="megatools not available (install megatools)",
            )

        # 云存储 rclone 格式 (remote:path)
        if ":" in url and "/" in url and not url.startswith(("http://", "https://", "ftp://", "magnet:")):
            engine = self._registry.get_engine("rclone")
            if engine and engine.is_available():
                return self.download(url, output_dir=output_dir, engine="rclone", fallback=False, **kwargs)
            return DownloadResult(
                success=False, engine_name="none", url=url,
                error="rclone not available",
            )

        # 普通 HTTP/FTP — 使用默认/优先级选择
        return self.download(url, output_dir=output_dir, **kwargs)
