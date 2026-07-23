"""
megatools 引擎 — Mega.nz 下载工具。

支持 Mega.nz 链接直接下载。
"""

import os
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from ..registry import EngineRegistry
from ..utils import run_command, check_command, infer_filename


@EngineRegistry.register
class MegatoolsEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "megatools"

    @property
    def display_name(self) -> str:
        return "megatools"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.MEGA,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
        ]

    def is_available(self) -> bool:
        return check_command("megadl") or check_command("megaget")

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "megatools not found in PATH"
        if "mega.nz" not in request.url and "mega.co.nz" not in request.url:
            return "Not a Mega.nz URL"
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        # megadl 或 megaget
        if check_command("megadl"):
            cmd = ["megadl"]
        else:
            cmd = ["megaget"]

        # 输出目录
        os.makedirs(request.output_dir, exist_ok=True)
        cmd.extend(["--path", request.output_dir])

        # 文件名
        if request.filename:
            cmd.extend(["--choose-file", request.filename])

        # 代理
        if request.proxy:
            cmd.extend(["--proxy", request.proxy])

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

        if success:
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
