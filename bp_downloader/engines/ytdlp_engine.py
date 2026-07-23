"""
yt-dlp 引擎 — 视频平台下载利器。

支持 YouTube, Bilibili, Twitter 等 1000+ 视频平台。
"""

import os
import json
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from ..registry import EngineRegistry
from ..utils import run_command, check_command


@EngineRegistry.register
class YtDlpEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "yt_dlp"

    @property
    def display_name(self) -> str:
        return "yt-dlp"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.VIDEO,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
            EngineCapability.SPEED_LIMIT,
            EngineCapability.HEADER_CUSTOM,
            EngineCapability.PARALLEL,
        ]

    def is_available(self) -> bool:
        return check_command("yt-dlp")

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "yt-dlp not found in PATH"
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        cmd = ["yt-dlp"]

        # 输出模板
        if request.filename:
            out = os.path.join(request.output_dir, request.filename)
            cmd.extend(["-o", out])
        else:
            out = os.path.join(request.output_dir, "%(title)s.%(ext)s")
            cmd.extend(["-o", out])

        # 不覆盖已有文件（配合续传）
        cmd.append("--no-overwrites")

        # 限速
        if request.speed_limit:
            from ..utils import parse_speed_limit
            bps = parse_speed_limit(request.speed_limit)
            cmd.extend(["--limit-rate", str(bps)])

        # 代理
        if request.proxy:
            cmd.extend(["--proxy", request.proxy])

        # 请求头
        for k, v in request.headers.items():
            cmd.extend(["--add-header", f"{k}:{v}"])

        # Referer
        if request.referer:
            cmd.extend(["--referer", request.referer])

        # User-Agent
        ua = request.user_agent or request.headers.get("User-Agent")
        if ua:
            cmd.extend(["--user-agent", ua])

        # Cookies
        if request.cookies:
            if os.path.isfile(request.cookies):
                cmd.extend(["--cookies", request.cookies])
            else:
                cmd.extend(["--add-header", f"Cookie: {request.cookies}"])

        # 重试
        cmd.extend(["--retries", str(request.max_retries)])
        cmd.extend(["--fragment-retries", str(request.max_retries)])

        # 超时
        cmd.extend(["--socket-timeout", str(request.timeout)])

        # 从 extra 获取额外 yt-dlp 参数
        # extra_args: 额外 CLI 参数
        for arg in request.extra.get("extra_args", []):
            cmd.append(arg)

        # format 选择
        fmt = request.extra.get("format", "best")
        cmd.extend(["-f", fmt])

        # 合并格式
        merge = request.extra.get("merge_output_format")
        if merge:
            cmd.extend(["--merge-output-format", merge])

        # 输出 JSON 信息 (用于解析结果)
        cmd.append("--print-json")
        cmd.append("--no-warnings")

        # URL
        cmd.append(request.url)
        return cmd

    def download(self, request: DownloadRequest) -> DownloadResult:
        err = self.validate_request(request)
        if err:
            return DownloadResult(success=False, engine_name=self.name, url=request.url, error=err)

        import time
        cmd = self.build_command(request)
        start = time.monotonic()
        rc, stdout, stderr = run_command(cmd, timeout=request.timeout + 120)
        elapsed = time.monotonic() - start

        success = rc == 0
        output_path = None
        file_size = None
        metadata = {}

        if success and stdout.strip():
            # 解析 yt-dlp JSON 输出
            try:
                for line in stdout.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        info = json.loads(line)
                        metadata["title"] = info.get("title")
                        metadata["ext"] = info.get("ext")
                        metadata["duration"] = info.get("duration")
                        metadata["filesize"] = info.get("filesize")
                        # yt-dlp 下载后的文件路径
                        if info.get("requested_downloads"):
                            dl = info["requested_downloads"][0]
                            output_path = dl.get("filepath")
                        if not output_path and info.get("_filename"):
                            output_path = info["_filename"]
                        if info.get("filesize"):
                            file_size = info["filesize"]
                        break
            except (json.JSONDecodeError, KeyError):
                pass

        # 回退：检查输出目录中最新的文件
        if success and not output_path:
            try:
                files = []
                for f in os.listdir(request.output_dir):
                    fp = os.path.join(request.output_dir, f)
                    if os.path.isfile(fp):
                        files.append((fp, os.path.getmtime(fp)))
                if files:
                    files.sort(key=lambda x: x[1], reverse=True)
                    output_path = files[0][0]
                    file_size = os.path.getsize(output_path)
            except OSError:
                pass

        if output_path and file_size is None and os.path.isfile(output_path):
            file_size = os.path.getsize(output_path)

        speed = file_size / elapsed if success and file_size and elapsed > 0 else 0

        return DownloadResult(
            success=success,
            engine_name=self.name,
            url=request.url,
            output_path=output_path,
            file_size=file_size,
            elapsed=elapsed,
            speed=speed,
            error=stderr.strip() if not success else None,
            return_code=rc,
            stdout=stdout,
            stderr=stderr,
            metadata=metadata,
        )
