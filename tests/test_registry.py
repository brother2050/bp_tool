"""
测试引擎注册表。
"""

import pytest
from bp_downloader.base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from bp_downloader.registry import EngineRegistry, discover_engines


class TestEngineRegistry:
    """EngineRegistry 测试"""

    def setup_method(self):
        """每个测试前清空注册表"""
        EngineRegistry.clear()

    def teardown_method(self):
        """每个测试后重新发现"""
        EngineRegistry.reload()

    def test_register_decorator(self):
        @EngineRegistry.register
        class TestEngine(DownloadEngine):
            @property
            def name(self):
                return "test_reg"

            @property
            def display_name(self):
                return "Test"

            @property
            def capabilities(self):
                return [EngineCapability.HTTP]

            def is_available(self):
                return True

            def download(self, request):
                return DownloadResult(success=True, engine_name="test_reg", url=request.url)

        assert "test_reg" in EngineRegistry._engines
        assert EngineRegistry.get_engine_class("test_reg") is TestEngine

    def test_get_engine_singleton(self):
        @EngineRegistry.register
        class SingletonEngine(DownloadEngine):
            @property
            def name(self):
                return "singleton"

            @property
            def display_name(self):
                return "Singleton"

            @property
            def capabilities(self):
                return []

            def is_available(self):
                return True

            def download(self, request):
                pass

        inst1 = EngineRegistry.get_engine("singleton")
        inst2 = EngineRegistry.get_engine("singleton")
        assert inst1 is inst2

    def test_get_nonexistent_engine(self):
        assert EngineRegistry.get_engine("nonexistent") is None
        assert EngineRegistry.get_engine_class("nonexistent") is None

    def test_get_available_engines(self):
        @EngineRegistry.register
        class AvailEngine(DownloadEngine):
            @property
            def name(self):
                return "avail"

            @property
            def display_name(self):
                return "Avail"

            @property
            def capabilities(self):
                return [EngineCapability.HTTP]

            def is_available(self):
                return True

            def download(self, request):
                pass

        @EngineRegistry.register
        class UnavailEngine(DownloadEngine):
            @property
            def name(self):
                return "unavail"

            @property
            def display_name(self):
                return "Unavail"

            @property
            def capabilities(self):
                return []

            def is_available(self):
                return False

            def download(self, request):
                pass

        available = EngineRegistry.get_available_engines()
        assert "avail" in available
        assert "unavail" not in available

    def test_find_by_capability(self):
        @EngineRegistry.register
        class TorrentEngine(DownloadEngine):
            @property
            def name(self):
                return "tor_cap"

            @property
            def display_name(self):
                return "Torrent"

            @property
            def capabilities(self):
                return [EngineCapability.TORRENT, EngineCapability.MAGNET]

            def is_available(self):
                return True

            def download(self, request):
                pass

        engines = EngineRegistry.find_by_capability(EngineCapability.TORRENT)
        names = [e.name for e in engines]
        assert "tor_cap" in names

    def test_reset_instances(self):
        @EngineRegistry.register
        class ResetEngine(DownloadEngine):
            @property
            def name(self):
                return "reset"

            @property
            def display_name(self):
                return "Reset"

            @property
            def capabilities(self):
                return []

            def is_available(self):
                return True

            def download(self, request):
                pass

        inst1 = EngineRegistry.get_engine("reset")
        EngineRegistry.reset_instances()
        inst2 = EngineRegistry.get_engine("reset")
        assert inst1 is not inst2

    def test_summary(self):
        discover_engines()
        summary = EngineRegistry.summary()
        assert "Registered engines:" in summary

    def test_discover_engines_loads_all(self):
        """验证自动发现能加载所有引擎"""
        EngineRegistry.clear()
        discover_engines(force=True)
        all_engines = EngineRegistry.get_all_engines()
        # 至少 10 个引擎
        assert len(all_engines) >= 10, f"Expected >=10 engines, got {len(all_engines)}"
        # 验证关键引擎
        expected = ["aria2c", "wget", "curl", "yt_dlp", "rclone",
                     "megatools", "urllib", "requests", "httpx", "transmission"]
        for name in expected:
            assert name in all_engines, f"Missing engine: {name}"
