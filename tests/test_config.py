"""
测试配置系统。
"""

import pytest
import json
import os
import tempfile

from bp_downloader.config import DownloaderConfig, EngineConfig


class TestEngineConfig:
    """EngineConfig 测试"""

    def test_defaults(self):
        ec = EngineConfig()
        assert ec.enabled is True
        assert ec.priority == 50
        assert ec.max_connections == 0
        assert ec.timeout == 60
        assert ec.max_retries == 3
        assert ec.extra_args == []
        assert ec.env == {}
        assert ec.custom == {}


class TestDownloaderConfig:
    """DownloaderConfig 测试"""

    def test_defaults(self):
        config = DownloaderConfig()
        assert config.default_engine is None
        assert config.fallback_engines == []
        assert config.output_dir == "./downloads"
        assert config.max_concurrent == 3
        assert config.timeout == 60
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.speed_limit is None
        assert config.proxy is None
        assert config.user_agent is None
        assert config.engines == {}
        assert config.route_rules == []

    def test_from_dict(self):
        data = {
            "default_engine": "aria2c",
            "output_dir": "/tmp/test",
            "max_concurrent": 5,
            "timeout": 120,
            "speed_limit": "1M",
            "proxy": "http://proxy:8080",
            "engines": {
                "aria2c": {"enabled": True, "priority": 10},
                "wget": {"enabled": False},
            },
            "route_rules": [
                {"pattern": "*.youtube.com", "engine": "yt_dlp"},
            ],
        }
        config = DownloaderConfig.from_dict(data)
        assert config.default_engine == "aria2c"
        assert config.output_dir == "/tmp/test"
        assert config.max_concurrent == 5
        assert config.timeout == 120
        assert config.speed_limit == "1M"
        assert config.proxy == "http://proxy:8080"
        assert "aria2c" in config.engines
        assert config.engines["aria2c"].priority == 10
        assert config.engines["wget"].enabled is False
        assert len(config.route_rules) == 1

    def test_from_dict_engine_bool(self):
        """引擎配置可以是布尔值"""
        data = {"engines": {"aria2c": True, "wget": False}}
        config = DownloaderConfig.from_dict(data)
        assert config.engines["aria2c"].enabled is True
        assert config.engines["wget"].enabled is False

    def test_from_file_json(self):
        data = {"default_engine": "curl", "output_dir": "/tmp/json"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            config = DownloaderConfig.from_file(path)
            assert config.default_engine == "curl"
            assert config.output_dir == "/tmp/json"
        finally:
            os.unlink(path)

    def test_from_file_yaml(self):
        data = {"default_engine": "wget", "output_dir": "/tmp/yaml"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            try:
                import yaml
                yaml.dump(data, f)
            except ImportError:
                # fallback to JSON if no yaml
                json.dump(data, f)
            path = f.name
        try:
            config = DownloaderConfig.from_file(path)
            assert config.default_engine == "wget"
        finally:
            os.unlink(path)

    def test_from_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            DownloaderConfig.from_file("/nonexistent/config.json")

    def test_from_file_invalid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                DownloaderConfig.from_file(path)
        finally:
            os.unlink(path)

    def test_get_engine_config_default(self):
        config = DownloaderConfig()
        ec = config.get_engine_config("nonexistent")
        assert ec.enabled is True
        assert ec.priority == 50

    def test_get_engine_config_existing(self):
        config = DownloaderConfig()
        config.engines["aria2c"] = EngineConfig(enabled=True, priority=5)
        ec = config.get_engine_config("aria2c")
        assert ec.priority == 5

    def test_to_dict(self):
        config = DownloaderConfig()
        config.default_engine = "aria2c"
        config.engines["wget"] = EngineConfig(priority=20)
        d = config.to_dict()
        assert d["default_engine"] == "aria2c"
        assert d["engines"]["wget"]["priority"] == 20

    def test_save_and_load_json(self):
        config = DownloaderConfig()
        config.default_engine = "curl"
        config.engines["curl"] = EngineConfig(priority=15)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            config.save(path)
            loaded = DownloaderConfig.from_file(path)
            assert loaded.default_engine == "curl"
            assert loaded.engines["curl"].priority == 15
        finally:
            os.unlink(path)

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("BP_DL_OUTPUT_DIR", "/env/dir")
        monkeypatch.setenv("BP_DL_MAX_CONCURRENT", "10")
        monkeypatch.setenv("BP_DL_TIMEOUT", "300")
        config = DownloaderConfig.from_dict({})
        assert config.output_dir == "/env/dir"
        assert config.max_concurrent == 10
        assert config.timeout == 300
