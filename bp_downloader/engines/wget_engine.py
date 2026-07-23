"""
wget 引擎 — 经典 GNU 下载器。

支持 HTTP/HTTPS/FTP，断点续传，递归下载。
"""

import os
import re
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from ..registry import EngineRegistry
from ..utils import run_command, check_command, infer_filename


@EngineRegistry.register
class WgetEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "wget"

    @property
    def display_name(self) -> str:
        return "GNU Wget"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.FTP,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
            EngineCapability.SPEED_LIMIT,
            EngineCapability.HEADER_CUSTOM,
        ]

    def is_available(self) -> bool:
        return check_command("wget")

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "wget not found in PATH"
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        cmd = ["wget"]

        # 输出目录和文件名
        if request.filename:
            cmd.extend(["-O", os.path.join(request.output_dir, request.filename)])
        else:
            cmd.extend(["-P", request.output_dir])

        # 断点续传
        cmd.append("-c")

        # 超时
        cmd.extend(["--timeout", str(request.timeout)])
        cmd.extend(["--tries", str(request.max_retries)])

        # 限速
        if request.speed_limit:
            cmd.extend(["--limit-rate", request.speed_limit])

        # 代理
        if request.proxy:
            cmd.extend(["-e", f"use_proxy=yes", "-e", f"http_proxy={request.proxy}",
                         "-e", f"https_proxy={request.proxy}"])

        # 请求头
        for k, v in request.headers.items():
            cmd.extend(["--header", f"{k}: {v}"])

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
                cmd.extend(["--load-cookies", request.cookies])
            else:
                cmd.extend(["--header", f"Cookie: {request.cookies}"])

        # 静默但显示进度
        cmd.append("-q")

        # 额外参数
        for arg in request.extra.get("extra_args", []):
            cmd.append(arg)

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
        rc, stdout, stderr = run_command(cmd, timeout=request.timeout + 30)
        elapsed = time.monotonic() - start

        success = rc == 0
        output_path = None
        file_size = None

        if success:
            if request.filename:
                output_path = os.path.join(request.output_dir, request.filename)
            else:
                # wget 默认用 URL 文件名
                inferred = infer_filename(request.url)
                if inferred:
                    output_path = os.path.join(request.output_dir, inferred)
            if output_path and os.path.isfile(output_path):
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
        )
