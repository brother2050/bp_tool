"""
curl 引擎 — 万能数据传输工具。

支持 HTTP/HTTPS/FTP/SCP/SFTP 等众多协议。
"""

import os
import re
import json
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from ..registry import EngineRegistry
from ..utils import run_command, check_command, infer_filename


@EngineRegistry.register
class CurlEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "curl"

    @property
    def display_name(self) -> str:
        return "cURL"

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
        return check_command("curl")

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "curl not found in PATH"
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        cmd = ["curl", "-fSL"]  # fail silently on HTTP errors, show errors, follow redirects

        # 输出文件
        if request.filename:
            out = os.path.join(request.output_dir, request.filename)
        else:
            # 让 curl 自动推断文件名 (需要 -J 配合)
            out = os.path.join(request.output_dir, "-")
            # 用 -J 从 Content-Disposition 推断，但不指定 -O 时需手动处理
            # 这里用 -o 自动命名，依赖 URL
            inferred = infer_filename(request.url)
            if inferred:
                out = os.path.join(request.output_dir, inferred)
            else:
                out = os.path.join(request.output_dir, "download")
        cmd.extend(["-o", out])

        # 创建输出目录
        os.makedirs(request.output_dir, exist_ok=True)

        # 断点续传
        cmd.extend(["-C", "-"])

        # 超时
        cmd.extend(["--connect-timeout", str(min(request.timeout, 30))])
        cmd.extend(["--max-time", str(request.timeout)])

        # 重试
        cmd.extend(["--retry", str(request.max_retries)])
        cmd.extend(["--retry-delay", "2"])

        # 限速
        if request.speed_limit:
            cmd.extend(["--limit-rate", request.speed_limit])

        # 代理
        if request.proxy:
            cmd.extend(["-x", request.proxy])

        # 请求头
        for k, v in request.headers.items():
            cmd.extend(["-H", f"{k}: {v}"])

        # Referer
        if request.referer:
            cmd.extend(["-e", request.referer])

        # User-Agent
        ua = request.user_agent or request.headers.get("User-Agent")
        if ua:
            cmd.extend(["-A", ua])

        # Cookies
        if request.cookies:
            if os.path.isfile(request.cookies):
                cmd.extend(["-b", request.cookies])
            else:
                cmd.extend(["-b", request.cookies])

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

        # 确定输出路径
        if request.filename:
            output_path = os.path.join(request.output_dir, request.filename)
        else:
            inferred = infer_filename(request.url)
            if inferred:
                output_path = os.path.join(request.output_dir, inferred)
            else:
                output_path = os.path.join(request.output_dir, "download")

        start = time.monotonic()
        rc, stdout, stderr = run_command(cmd, timeout=request.timeout + 30)
        elapsed = time.monotonic() - start

        success = rc == 0
        file_size = None

        if success and os.path.isfile(output_path):
            file_size = os.path.getsize(output_path)

        speed = file_size / elapsed if success and file_size and elapsed > 0 else 0

        return DownloadResult(
            success=success,
            engine_name=self.name,
            url=request.url,
            output_path=output_path if success else None,
            file_size=file_size,
            elapsed=elapsed,
            speed=speed,
            error=stderr.strip() if not success else None,
            return_code=rc,
            stdout=stdout,
            stderr=stderr,
        )
