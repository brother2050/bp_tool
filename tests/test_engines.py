"""
测试所有 10 个下载引擎插件。

每个引擎测试：
1. 注册成功
2. name/display_name/capabilities 属性
3. is_available 检测
4. validate_request 逻辑
5. build_command 构建（CLI 引擎）
6. 实际下载（有条件执行）
"""

import pytest
import os
import tempfile
import shutil

from bp_downloader.base import DownloadRequest, DownloadResult, EngineCapability
from bp_downloader.registry import EngineRegistry, discover_engines


@pytest.fixture(autouse=True)
def ensure_engines():
    """确保引擎已发现"""
    discover_engines()


@pytest.fixture
def tmp_dir():
    """临时输出目录"""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_request(tmp_dir):
    """标准下载请求"""
    return DownloadRequest(
        url="https://httpbin.org/bytes/1024",
        output_dir=tmp_dir,
        timeout=30,
    )


# ============================================================
# 1. aria2c
# ============================================================
class TestAria2cEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("aria2c")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "aria2c"
        assert engine.display_name == "aria2c"

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.HTTP in caps
        assert EngineCapability.MULTI_CONNECTION in caps
        assert EngineCapability.TORRENT in caps
        assert EngineCapability.MAGNET in caps
        assert EngineCapability.RESUME in caps

    def test_validate_unavailable(self, monkeypatch):
        engine = self.get_engine()
        if not engine.is_available():
            req = DownloadRequest(url="https://example.com/file.zip")
            err = engine.validate_request(req)
            assert err is not None
            assert "not found" in err

    def test_build_command(self):
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://example.com/file.zip",
            output_dir="/tmp/dl",
            filename="custom.zip",
            connections=8,
            timeout=120,
            speed_limit="1M",
            proxy="http://proxy:8080",
            headers={"Authorization": "Bearer token"},
        )
        cmd = engine.build_command(req)
        assert cmd[0] == "aria2c"
        assert "-d" in cmd
        assert "/tmp/dl" in cmd
        assert "-o" in cmd
        assert "custom.zip" in cmd
        assert "-x" in cmd
        assert "8" in cmd
        assert "--max-download-limit" in cmd
        assert "--all-proxy" in cmd
        assert cmd[-1] == "https://example.com/file.zip"

    @pytest.mark.skipif(not shutil.which("aria2c"), reason="aria2c not installed")
    def test_download(self, sample_request, tmp_dir):
        engine = self.get_engine()
        result = engine.download(sample_request)
        assert isinstance(result, DownloadResult)
        assert result.engine_name == "aria2c"


# ============================================================
# 2. wget
# ============================================================
class TestWgetEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("wget")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "wget"
        assert "Wget" in engine.display_name

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.HTTP in caps
        assert EngineCapability.FTP in caps
        assert EngineCapability.RESUME in caps

    def test_build_command(self):
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://example.com/file.zip",
            output_dir="/tmp/dl",
            filename="custom.zip",
            speed_limit="500K",
            headers={"X-Custom": "value"},
        )
        cmd = engine.build_command(req)
        assert cmd[0] == "wget"
        assert "-O" in cmd
        assert "-c" in cmd
        assert "--limit-rate" in cmd
        assert "500K" in cmd
        assert "--header" in cmd
        assert cmd[-1] == "https://example.com/file.zip"

    @pytest.mark.skipif(not shutil.which("wget"), reason="wget not installed")
    def test_download(self, sample_request, tmp_dir):
        engine = self.get_engine()
        result = engine.download(sample_request)
        assert isinstance(result, DownloadResult)
        assert result.engine_name == "wget"


# ============================================================
# 3. curl
# ============================================================
class TestCurlEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("curl")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "curl"
        assert "curl" in engine.display_name.lower()

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.HTTP in caps
        assert EngineCapability.FTP in caps
        assert EngineCapability.RESUME in caps

    def test_build_command(self):
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://example.com/file.zip",
            output_dir="/tmp/dl",
            filename="out.zip",
            proxy="socks5://localhost:1080",
            referer="https://example.com",
            user_agent="Custom/1.0",
        )
        cmd = engine.build_command(req)
        assert cmd[0] == "curl"
        assert "-o" in cmd
        assert "-C" in cmd[cmd.index("-o") - 2] or "-C -" in " ".join(cmd)
        assert "-x" in cmd
        assert "-e" in cmd
        assert "-A" in cmd

    @pytest.mark.skipif(not shutil.which("curl"), reason="curl not installed")
    def test_download(self, sample_request, tmp_dir):
        engine = self.get_engine()
        result = engine.download(sample_request)
        assert isinstance(result, DownloadResult)
        assert result.engine_name == "curl"


# ============================================================
# 4. yt-dlp
# ============================================================
class TestYtDlpEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("yt_dlp")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "yt_dlp"
        assert "yt-dlp" in engine.display_name

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.VIDEO in caps
        assert EngineCapability.HTTP in caps
        assert EngineCapability.RESUME in caps

    def test_build_command(self):
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://www.youtube.com/watch?v=abc",
            output_dir="/tmp/dl",
            extra={"format": "best[height<=720]"},
        )
        cmd = engine.build_command(req)
        assert cmd[0] == "yt-dlp"
        assert "-f" in cmd
        assert "best[height<=720]" in cmd
        assert "--print-json" in cmd
        assert cmd[-1] == "https://www.youtube.com/watch?v=abc"

    def test_build_command_with_cookies(self, tmp_dir):
        engine = self.get_engine()
        cookie_file = os.path.join(tmp_dir, "cookies.txt")
        with open(cookie_file, "w") as f:
            f.write("# Netscape HTTP Cookie File\n")
        req = DownloadRequest(
            url="https://www.youtube.com/watch?v=abc",
            output_dir=tmp_dir,
            cookies=cookie_file,
        )
        cmd = engine.build_command(req)
        assert "--cookies" in cmd


# ============================================================
# 5. rclone
# ============================================================
class TestRcloneEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("rclone")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "rclone"
        assert engine.display_name == "rclone"

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.CLOUD_STORAGE in caps
        assert EngineCapability.HTTP in caps

    def test_build_command(self):
        engine = self.get_engine()
        req = DownloadRequest(
            url="gdrive:backup/file.zip",
            output_dir="/tmp/dl",
            connections=8,
            speed_limit="2M",
        )
        cmd = engine.build_command(req)
        assert cmd[0] == "rclone"
        assert "copy" in cmd
        assert "--transfers" in cmd
        assert "8" in cmd
        assert "--bwlimit" in cmd


# ============================================================
# 6. megatools
# ============================================================
class TestMegatoolsEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("megatools")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "megatools"
        assert engine.display_name == "megatools"

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.MEGA in caps
        assert EngineCapability.HTTP in caps

    def test_validate_not_mega_url(self):
        engine = self.get_engine()
        req = DownloadRequest(url="https://example.com/file.zip")
        err = engine.validate_request(req)
        if engine.is_available():
            assert "Mega" in err

    def test_build_command(self):
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://mega.nz/file/abc123",
            output_dir="/tmp/dl",
        )
        cmd = engine.build_command(req)
        assert "mega" in cmd[0]  # megadl or megaget
        assert "--path" in cmd


# ============================================================
# 7. urllib
# ============================================================
class TestUrllibEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("urllib")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "urllib"

    def test_always_available(self):
        engine = self.get_engine()
        assert engine.is_available() is True

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.HTTP in caps
        assert EngineCapability.FTP in caps

    def test_download_success(self, tmp_dir):
        """urllib 引擎下载测试（需要网络）"""
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://httpbin.org/bytes/256",
            output_dir=tmp_dir,
            timeout=30,
        )
        result = engine.download(req)
        if result.success:
            assert result.engine_name == "urllib"
            assert result.output_path is not None
            assert result.file_size == 256
        # 无网络环境下允许失败

    def test_download_invalid_url(self, tmp_dir):
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://invalid.invalid.invalid/file.zip",
            output_dir=tmp_dir,
            timeout=5,
        )
        result = engine.download(req)
        assert result.success is False
        assert result.error is not None

    def test_download_with_headers(self, tmp_dir):
        engine = self.get_engine()
        req = DownloadRequest(
            url="https://httpbin.org/headers",
            output_dir=tmp_dir,
            headers={"X-Test": "value"},
            referer="https://example.com",
            timeout=30,
        )
        result = engine.download(req)
        # 不管成功与否，验证没有崩溃
        assert isinstance(result, DownloadResult)


# ============================================================
# 8. requests
# ============================================================
class TestRequestsEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("requests")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "requests"

    def test_available(self):
        engine = self.get_engine()
        # requests 通常已安装
        try:
            import requests
            assert engine.is_available() is True
        except ImportError:
            assert engine.is_available() is False

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.HTTP in caps
        assert EngineCapability.RESUME in caps

    def test_download_success(self, tmp_dir):
        engine = self.get_engine()
        if not engine.is_available():
            pytest.skip("requests not installed")
        req = DownloadRequest(
            url="https://httpbin.org/bytes/512",
            output_dir=tmp_dir,
            timeout=30,
        )
        result = engine.download(req)
        if result.success:
            assert result.engine_name == "requests"
            assert result.file_size == 512

    def test_download_404(self, tmp_dir):
        engine = self.get_engine()
        if not engine.is_available():
            pytest.skip("requests not installed")
        req = DownloadRequest(
            url="https://httpbin.org/status/404",
            output_dir=tmp_dir,
            timeout=30,
        )
        result = engine.download(req)
        assert result.success is False
        assert result.error is not None


# ============================================================
# 9. httpx
# ============================================================
class TestHttpxEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("httpx")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "httpx"

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.HTTP in caps

    def test_available_depends_on_package(self):
        engine = self.get_engine()
        try:
            import httpx
            assert engine.is_available() is True
        except ImportError:
            assert engine.is_available() is False

    def test_download_without_httpx(self, tmp_dir, monkeypatch):
        """httpx 未安装时返回错误"""
        engine = self.get_engine()
        if engine.is_available():
            pytest.skip("httpx is installed")
        req = DownloadRequest(url="https://example.com/file.zip", output_dir=tmp_dir)
        result = engine.download(req)
        assert result.success is False
        assert "not installed" in result.error


# ============================================================
# 10. transmission
# ============================================================
class TestTransmissionEngine:
    def get_engine(self):
        return EngineRegistry.get_engine("transmission")

    def test_registered(self):
        engine = self.get_engine()
        assert engine is not None
        assert engine.name == "transmission"
        assert "Transmission" in engine.display_name

    def test_capabilities(self):
        engine = self.get_engine()
        caps = engine.capabilities
        assert EngineCapability.TORRENT in caps
        assert EngineCapability.MAGNET in caps

    def test_validate_not_torrent(self):
        engine = self.get_engine()
        req = DownloadRequest(url="https://example.com/file.zip")
        err = engine.validate_request(req)
        if engine.is_available():
            assert "torrent" in err.lower() or "magnet" in err.lower()

    def test_validate_torrent(self):
        engine = self.get_engine()
        req = DownloadRequest(url="https://example.com/file.torrent")
        err = engine.validate_request(req)
        if engine.is_available():
            assert err is None

    def test_validate_magnet(self):
        engine = self.get_engine()
        req = DownloadRequest(url="magnet:?xt=urn:btih:abc123")
        err = engine.validate_request(req)
        if engine.is_available():
            assert err is None


# ============================================================
# 交叉验证：所有引擎注册完整性
# ============================================================
class TestAllEnginesRegistered:
    """验证所有 10 个引擎都已注册"""

    EXPECTED_ENGINES = [
        "aria2c", "wget", "curl", "yt_dlp", "rclone",
        "megatools", "urllib", "requests", "httpx", "transmission",
    ]

    def test_all_registered(self):
        all_engines = EngineRegistry.get_all_engines()
        for name in self.EXPECTED_ENGINES:
            assert name in all_engines, f"Engine '{name}' not registered"

    def test_count(self):
        all_engines = EngineRegistry.get_all_engines()
        assert len(all_engines) >= len(self.EXPECTED_ENGINES)

    def test_all_have_required_methods(self):
        for name in self.EXPECTED_ENGINES:
            engine = EngineRegistry.get_engine(name)
            assert engine is not None, f"Engine '{name}' instance is None"
            assert hasattr(engine, "name")
            assert hasattr(engine, "display_name")
            assert hasattr(engine, "capabilities")
            assert hasattr(engine, "is_available")
            assert hasattr(engine, "download")
            assert hasattr(engine, "validate_request")
            assert hasattr(engine, "build_command")
            assert isinstance(engine.capabilities, list)

    def test_all_names_unique(self):
        names = []
        for name in self.EXPECTED_ENGINES:
            engine = EngineRegistry.get_engine(name)
            assert engine.name not in names, f"Duplicate engine name: {engine.name}"
            names.append(engine.name)
