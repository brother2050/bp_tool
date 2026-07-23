"""
测试基础数据模型和抽象类。
"""

import pytest
import os
import time

from bp_downloader.base import (
    DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
)


class TestDownloadRequest:
    """DownloadRequest 测试"""

    def test_default_values(self):
        req = DownloadRequest(url="https://example.com/file.zip")
        assert req.url == "https://example.com/file.zip"
        assert req.output_dir == "."
        assert req.filename is None
        assert req.headers == {}
        assert req.proxy is None
        assert req.timeout == 60
        assert req.max_retries == 3
        assert req.speed_limit is None
        assert req.connections == 0
        assert req.extra == {}
        assert req.checksum is None
        assert req.referer is None
        assert req.user_agent is None
        assert req.cookies is None

    def test_custom_values(self):
        req = DownloadRequest(
            url="https://example.com/file.zip",
            output_dir="/tmp/dl",
            filename="custom.zip",
            headers={"Authorization": "Bearer token"},
            proxy="http://proxy:8080",
            timeout=120,
            max_retries=5,
            speed_limit="1M",
            connections=8,
            extra={"format": "best"},
            referer="https://example.com",
            user_agent="Custom/1.0",
            cookies="session=abc123",
        )
        assert req.output_dir == "/tmp/dl"
        assert req.filename == "custom.zip"
        assert req.headers["Authorization"] == "Bearer token"
        assert req.proxy == "http://proxy:8080"
        assert req.timeout == 120
        assert req.max_retries == 5
        assert req.speed_limit == "1M"
        assert req.connections == 8
        assert req.extra["format"] == "best"
        assert req.referer == "https://example.com"
        assert req.user_agent == "Custom/1.0"
        assert req.cookies == "session=abc123"

    def test_mutable_defaults_isolated(self):
        """确保默认值的可变对象是隔离的"""
        req1 = DownloadRequest(url="a")
        req2 = DownloadRequest(url="b")
        req1.headers["key"] = "value"
        assert "key" not in req2.headers


class TestDownloadResult:
    """DownloadResult 测试"""

    def test_success_result(self):
        r = DownloadResult(
            success=True,
            engine_name="test",
            url="https://example.com/file.zip",
            output_path="/tmp/file.zip",
            file_size=1024 * 1024,
            elapsed=2.0,
            speed=512 * 1024,
        )
        assert r.success is True
        assert r.size_human == "1.0 MB"
        assert "KB/s" in r.speed_human or "MB/s" in r.speed_human

    def test_failed_result(self):
        r = DownloadResult(
            success=False,
            engine_name="test",
            url="https://example.com/file.zip",
            error="Connection refused",
        )
        assert r.success is False
        assert r.error == "Connection refused"
        assert r.size_human == "N/A"
        assert r.speed_human == "N/A"

    def test_speed_human_zero(self):
        r = DownloadResult(success=True, speed=0)
        assert r.speed_human == "N/A"

    def test_size_human_zero(self):
        r = DownloadResult(success=True, file_size=0)
        assert r.size_human == "N/A"

    def test_size_human_large(self):
        r = DownloadResult(success=True, file_size=1024**4)
        assert "TB" in r.size_human


class TestEngineCapability:
    """EngineCapability 测试"""

    def test_values_unique(self):
        values = [cap.value for cap in EngineCapability]
        assert len(values) == len(set(values))

    def test_has_essential_capabilities(self):
        caps = [cap.name for cap in EngineCapability]
        assert "HTTP" in caps
        assert "FTP" in caps
        assert "TORRENT" in caps
        assert "MAGNET" in caps
        assert "RESUME" in caps
        assert "PROXY" in caps
        assert "VIDEO" in caps
        assert "CLOUD_STORAGE" in caps
        assert "MEGA" in caps


class TestDownloadEngineAbstract:
    """DownloadEngine 抽象类测试"""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            DownloadEngine()

    def test_concrete_subclass(self):
        class DummyEngine(DownloadEngine):
            @property
            def name(self):
                return "dummy"

            @property
            def display_name(self):
                return "Dummy"

            @property
            def capabilities(self):
                return [EngineCapability.HTTP]

            def is_available(self):
                return True

            def download(self, request):
                return DownloadResult(success=True, engine_name="dummy", url=request.url)

        engine = DummyEngine()
        assert engine.name == "dummy"
        assert engine.display_name == "Dummy"
        assert engine.is_available() is True
        assert EngineCapability.HTTP in engine.capabilities
        assert "✓" in repr(engine)

    def test_unavailable_repr(self):
        class UnavailEngine(DownloadEngine):
            @property
            def name(self):
                return "unavail"

            @property
            def display_name(self):
                return "Unavailable"

            @property
            def capabilities(self):
                return []

            def is_available(self):
                return False

            def download(self, request):
                pass

        engine = UnavailEngine()
        assert "✗" in repr(engine)

    def test_validate_request_default(self):
        class SimpleEngine(DownloadEngine):
            @property
            def name(self):
                return "simple"

            @property
            def display_name(self):
                return "Simple"

            @property
            def capabilities(self):
                return []

            def is_available(self):
                return True

            def download(self, request):
                pass

        engine = SimpleEngine()
        assert engine.validate_request(DownloadRequest(url="x")) is None

    def test_build_command_default(self):
        class SimpleEngine(DownloadEngine):
            @property
            def name(self):
                return "simple"

            @property
            def display_name(self):
                return "Simple"

            @property
            def capabilities(self):
                return []

            def is_available(self):
                return True

            def download(self, request):
                pass

        engine = SimpleEngine()
        assert engine.build_command(DownloadRequest(url="x")) == []
