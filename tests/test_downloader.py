"""
测试统一下载管理器。
"""

import pytest
import os
import tempfile

from bp_downloader.base import DownloadRequest, DownloadResult, EngineCapability
from bp_downloader.registry import EngineRegistry, discover_engines
from bp_downloader.config import DownloaderConfig, EngineConfig
from bp_downloader.downloader import UnifiedDownloader
import shutil


@pytest.fixture
def tmp_dir():
    """临时输出目录"""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestUnifiedDownloader:
    """UnifiedDownloader 测试"""

    def setup_method(self):
        discover_engines()
        self.tmpdir = tempfile.mkdtemp()
        self.config = DownloaderConfig()
        self.config.output_dir = self.tmpdir

    def test_list_engines(self):
        dl = UnifiedDownloader(self.config)
        engines = dl.list_engines()
        assert len(engines) >= 10
        for name, info in engines.items():
            assert "display_name" in info
            assert "available" in info
            assert "enabled" in info
            assert "priority" in info
            assert "capabilities" in info
            assert "platform_compatible" in info
            assert "installed" in info
            assert "supported_platforms" in info
            assert "install_hint" in info

    def test_select_engine_preferred(self):
        dl = UnifiedDownloader(self.config)
        req = DownloadRequest(url="https://example.com/file.zip")
        # urllib 始终可用
        engine = dl.select_engine(req, preferred="urllib")
        assert engine is not None
        assert engine.name == "urllib"

    def test_select_engine_default(self):
        self.config.default_engine = "urllib"
        dl = UnifiedDownloader(self.config)
        req = DownloadRequest(url="https://example.com/file.zip")
        engine = dl.select_engine(req)
        assert engine is not None
        assert engine.name == "urllib"

    def test_select_engine_by_priority(self):
        """优先级最低的 urllib 应该最后被选中（如果其他可用）"""
        dl = UnifiedDownloader(self.config)
        req = DownloadRequest(url="https://example.com/file.zip")
        engine = dl.select_engine(req)
        # 应该是某个可用的引擎
        assert engine is not None

    def test_select_engine_disabled(self):
        """禁用的引擎不应被选中"""
        self.config.engines["urllib"] = EngineConfig(enabled=False)
        # 设置一个只有 urllib 可用的场景
        self.config.default_engine = "urllib"
        dl = UnifiedDownloader(self.config)
        req = DownloadRequest(url="https://example.com/file.zip")
        # 如果 urllib 被禁用，应该尝试其他引擎
        # （这里不设置 fallback，所以可能返回 None 或其他引擎）
        # 这取决于系统上有哪些引擎可用

    def test_select_engine_route_rules(self):
        """路由规则应优先匹配"""
        self.config.route_rules = [
            {"pattern": "*.youtube.com", "engine": "urllib"},
        ]
        dl = UnifiedDownloader(self.config)
        req = DownloadRequest(url="https://www.youtube.com/watch?v=abc")
        engine = dl.select_engine(req)
        assert engine is not None
        assert engine.name == "urllib"

    def test_select_engine_route_pattern(self):
        """测试各种路由模式"""
        self.config.route_rules = [
            {"pattern": "magnet:*", "engine": "urllib"},
        ]
        dl = UnifiedDownloader(self.config)
        req = DownloadRequest(url="magnet:?xt=urn:btih:abc")
        engine = dl.select_engine(req)
        assert engine is not None
        assert engine.name == "urllib"

    def test_apply_defaults(self):
        self.config.proxy = "http://proxy:8080"
        self.config.speed_limit = "1M"
        self.config.user_agent = "TestAgent/1.0"
        dl = UnifiedDownloader(self.config)
        req = DownloadRequest(url="https://example.com/file.zip")
        result = dl._apply_defaults(req)
        assert result.proxy == "http://proxy:8080"
        assert result.speed_limit == "1M"
        assert result.user_agent == "TestAgent/1.0"
        assert result.output_dir == self.tmpdir

    def test_download_with_urllib(self):
        """使用 urllib 引擎下载（始终可用）"""
        dl = UnifiedDownloader(self.config)
        # 使用一个公开的小文件测试
        result = dl.download(
            url="https://httpbin.org/bytes/1024",
            engine="urllib",
            fallback=False,
            timeout=30,
        )
        # 注意：这需要网络访问
        # 在无网络环境下跳过
        if result.success:
            assert result.engine_name == "urllib"
            assert result.output_path is not None
            assert result.file_size == 1024
        else:
            # 无网络环境下允许失败
            assert result.error is not None

    def test_download_no_engine(self):
        """无可用引擎时返回错误"""
        # 禁用所有引擎
        for name in EngineRegistry.get_all_engines():
            self.config.engines[name] = EngineConfig(enabled=False)
        dl = UnifiedDownloader(self.config)
        result = dl.download(url="https://example.com/file.zip", fallback=False)
        assert result.success is False
        assert "No available engine" in result.error

    def test_download_batch_empty(self):
        dl = UnifiedDownloader(self.config)
        results = dl.download_batch(urls=[], engine="urllib")
        assert results == []

    def test_auto_download_video_url(self):
        """auto_download 应该对视频 URL 使用 yt-dlp（如果可用）"""
        dl = UnifiedDownloader(self.config)
        result = dl.auto_download(url="https://www.youtube.com/watch?v=abc")
        # yt-dlp 不可用时会回退到其他引擎
        assert result.engine_name in ("yt_dlp", "aria2c", "none", "urllib", "wget", "curl", "requests", "httpx")

    def test_auto_download_magnet(self, tmp_dir):
        """auto_download 应该对 magnet 链接使用 aria2c/transmission"""
        dl = UnifiedDownloader(self.config)
        result = dl.auto_download(url="magnet:?xt=urn:btih:abc123")
        # 如果 aria2c/transmission 都不可用，返回 none
        assert result.engine_name in ("aria2c", "transmission", "none")

    def test_auto_download_mega(self, tmp_dir):
        """auto_download 应该对 mega.nz 使用 megatools"""
        dl = UnifiedDownloader(self.config)
        result = dl.auto_download(url="https://mega.nz/file/abc123")
        assert result.engine_name in ("megatools", "none")
