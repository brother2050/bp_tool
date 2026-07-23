"""
rclone 引擎 — 云存储同步/下载工具。

支持 Google Drive, OneDrive, S3, Dropbox 等 40+ 云存储。
"""

import os
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability, current_os
from ..registry import EngineRegistry
from ..utils import run_command, check_command


@EngineRegistry.register
class RcloneEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "rclone"

    @property
    def display_name(self) -> str:
        return "rclone"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.CLOUD_STORAGE,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
            EngineCapability.SPEED_LIMIT,
            EngineCapability.PARALLEL,
        ]

    @property
    def platforms(self) -> list:
        return []  # 全平台

    @property
    def install_hint(self) -> str:
        os_name = current_os()
        if os_name == "linux":
            return "curl https://rclone.org/install.sh | sudo bash"
        elif os_name == "darwin":
            return "brew install rclone"
        elif os_name == "windows":
            return "scoop install rclone / choco install rclone"
        return "https://rclone.org/downloads/"

    def is_available(self) -> bool:
        if not self.is_platform_compatible():
            return False
        return check_command("rclone")

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "rclone not found in PATH"
        # rclone URL 通常是 remote:path 格式
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        # rclone copy <remote:path> <local_dir>
        cmd = ["rclone", "copy"]

        # URL 作为源 (remote:path)
        cmd.append(request.url)

        # 输出目录
        os.makedirs(request.output_dir, exist_ok=True)
        cmd.append(request.output_dir)

        # 指定文件名（如果给定）
        if request.filename:
            cmd.extend(["--include", request.filename])

        # 限速
        if request.speed_limit:
            cmd.extend(["--bwlimit", request.speed_limit])

        # 并发
        if request.connections > 0:
            cmd.extend(["--transfers", str(request.connections)])
        else:
            cmd.extend(["--transfers", "4"])

        # 超时
        cmd.extend(["--low-level-retries", str(request.max_retries)])
        cmd.extend(["--contimeout", f"{request.timeout}s"])

        # 代理
        if request.proxy:
            cmd.extend(["--http-proxy", request.proxy])

        # 进度
        cmd.append("--progress")

        # 额外参数
        for arg in request.extra.get("extra_args", []):
            cmd.append(arg)

        return cmd

    def download(self, request: DownloadRequest) -> DownloadResult:
        err = self.validate_request(request)
        if err:
            return DownloadResult(success=False, engine_name=self.name, url=request.url, error=err)

        import time
        cmd = self.build_command(request)
        start = time.monotonic()
        rc, stdout, stderr = run_command(cmd, timeout=request.timeout + 60)
        elapsed = time.monotonic() - start

        success = rc == 0
        output_path = None
        file_size = None

        if success:
            # 检查输出目录中的文件
            try:
                files = []
                for f in os.listdir(request.output_dir):
                    fp = os.path.join(request.output_dir, f)
                    if os.path.isfile(fp):
                        files.append(fp)
                if files:
                    output_path = max(files, key=os.path.getmtime)
                    file_size = os.path.getsize(output_path)
            except OSError:
                pass

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
