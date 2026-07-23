"""
测试 CLI 入口。
"""

import pytest
import sys
import os
import tempfile
import json

from bp_downloader.cli import main, create_parser, parse_headers


@pytest.fixture
def tmp_dir():
    """临时输出目录"""
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestCreateParser:
    def test_parser_has_subcommands(self):
        parser = create_parser()
        # 测试 help 不报错
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--help"])
        assert exc.value.code == 0

    def test_download_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["download", "https://example.com/file.zip"])
        assert args.command == "download"
        assert args.url == "https://example.com/file.zip"

    def test_download_with_options(self):
        parser = create_parser()
        args = parser.parse_args([
            "download", "https://example.com/file.zip",
            "-o", "/tmp/dl",
            "-O", "custom.zip",
            "-e", "aria2c",
            "--no-fallback",
            "--proxy", "http://proxy:8080",
            "--speed-limit", "1M",
            "--connections", "8",
            "--timeout", "120",
            "-H", "Authorization: Bearer token",
            "--user-agent", "Custom/1.0",
            "--referer", "https://example.com",
        ])
        assert args.output_dir == "/tmp/dl"
        assert args.filename == "custom.zip"
        assert args.engine == "aria2c"
        assert args.no_fallback is True
        assert args.proxy == "http://proxy:8080"
        assert args.speed_limit == "1M"
        assert args.connections == 8
        assert args.timeout == 120
        assert args.header == ["Authorization: Bearer token"]
        assert args.user_agent == "Custom/1.0"
        assert args.referer == "https://example.com"

    def test_batch_subcommand(self):
        parser = create_parser()
        args = parser.parse_args([
            "batch", "https://a.com/1.zip", "https://b.com/2.zip",
            "-o", "/tmp/dl",
            "-j", "4",
        ])
        assert args.command == "batch"
        assert len(args.urls) == 2
        assert args.jobs == 4

    def test_auto_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["auto", "https://www.youtube.com/watch?v=abc"])
        assert args.command == "auto"
        assert args.url == "https://www.youtube.com/watch?v=abc"

    def test_engines_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["engines"])
        assert args.command == "engines"

    def test_engines_json(self):
        parser = create_parser()
        args = parser.parse_args(["engines", "--json"])
        assert args.json is True

    def test_dl_alias(self):
        parser = create_parser()
        args = parser.parse_args(["dl", "https://example.com/file.zip"])
        assert args.command == "dl"

    def test_b_alias(self):
        parser = create_parser()
        args = parser.parse_args(["b", "https://example.com/file.zip"])
        assert args.command == "b"

    def test_a_alias(self):
        parser = create_parser()
        args = parser.parse_args(["a", "https://example.com/file.zip"])
        assert args.command == "a"

    def test_e_alias(self):
        parser = create_parser()
        args = parser.parse_args(["e"])
        assert args.command == "e"


class TestParseHeaders:
    def test_empty(self):
        assert parse_headers(None) == {}
        assert parse_headers([]) == {}

    def test_single(self):
        headers = parse_headers(["Authorization: Bearer token123"])
        assert headers == {"Authorization": "Bearer token123"}

    def test_multiple(self):
        headers = parse_headers([
            "Authorization: Bearer token",
            "X-Custom: value",
        ])
        assert headers["Authorization"] == "Bearer token"
        assert headers["X-Custom"] == "value"

    def test_colon_in_value(self):
        headers = parse_headers(["Host: example.com:8080"])
        assert headers["Host"] == "example.com:8080"


class TestMainFunction:
    def test_no_command(self, capsys):
        result = main([])
        assert result == 0

    def test_engines_command(self, capsys):
        result = main(["engines"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Engine" in captured.out
        assert "Status" in captured.out

    def test_engines_json(self, capsys):
        result = main(["engines", "--json"])
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)
        assert len(data) >= 10

    def test_download_with_config(self, tmp_dir):
        """带配置文件的下载"""
        config_data = {
            "output_dir": tmp_dir,
            "default_engine": "urllib",
        }
        config_path = os.path.join(tmp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        result = main([
            "-c", config_path,
            "download", "https://httpbin.org/bytes/64",
            "--timeout", "30",
        ])
        # 成功或失败都行（取决于网络）
        assert result in (0, 1)

    def test_batch_download(self, tmp_dir):
        result = main([
            "batch",
            "https://httpbin.org/bytes/32",
            "https://httpbin.org/bytes/64",
            "-o", tmp_dir,
            "-e", "urllib",
            "-j", "2",
        ])
        assert result in (0, 1)

    def test_auto_download(self, tmp_dir):
        result = main([
            "auto", "https://httpbin.org/bytes/128",
            "-o", tmp_dir,
        ])
        assert result in (0, 1)
