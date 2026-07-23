"""
aria2c 引擎 — 高性能多连接下载器。

支持 HTTP/HTTPS/FTP/Metalink/BitTorrent/Magnet，最多 16 连接/服务器。
"""

import os
import json
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from ..registry import EngineRegistry
from ..utils import run_command, check_command, infer_filename, parse_speed_limit


@EngineRegistry.register
class Aria2cEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "aria2c"

    @property
    def display_name(self) -> str:
        return "aria2c"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.FTP,
            EngineCapability.METALINK,
            EngineCapability.TORRENT,
            EngineCapability.MAGNET,
            EngineCapability.MULTI_CONNECTION,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
            EngineCapability.SPEED_LIMIT,
            EngineCapability.HEADER_CUSTOM,
            EngineCapability.PARALLEL,
        ]

    def is_available(self) -> bool:
        return check_command("aria2c")

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "aria2c not found in PATH"
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        cmd = ["aria2c"]

        # 输出目录和文件名
        cmd.extend(["-d", request.output_dir])
        if request.filename:
            cmd.extend(["-o", request.filename])

        # 连接数
        connections = request.connections if request.connections > 0 else 16
        cmd.extend(["-x", str(connections), "-s", str(connections)])

        # 断点续传
        cmd.append("--continue=true")

        # 超时
        cmd.extend(["--timeout", str(request.timeout)])
        cmd.extend(["--max-tries", str(request.max_retries)])
        cmd.extend(["--retry-wait", "3"])

        # 限速
        if request.speed_limit:
            cmd.extend(["--max-download-limit", request.speed_limit])

        # 代理
        if request.proxy:
            cmd.extend(["--all-proxy", request.proxy])

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

        # 校验
        if request.checksum:
            parts = request.checksum.split(":", 1)
            if len(parts) == 2:
                cmd.extend([f"--check-integrity=true", f"--checksum={parts[0]}={parts[1]}"])

        # 额外参数
        for arg in request.extra.get("extra_args", []):
            cmd.append(arg)

        # 静默模式 + JSON 结果
        cmd.append("--console-log-level=warn")
        cmd.append("--download-result=hide")

        # URL 必须放在最后
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
            # 尝试找到下载的文件
            if request.filename:
                output_path = os.path.join(request.output_dir, request.filename)
            else:
                # 从 stdout/stderr 解析文件名
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
