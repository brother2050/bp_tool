"""
transmission-cli 引擎 — BitTorrent 下载工具。

支持 torrent 文件和 magnet 链接。
"""

import os
import time
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability, current_os
from ..registry import EngineRegistry
from ..utils import run_command, check_command


@EngineRegistry.register
class TransmissionEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "transmission"

    @property
    def display_name(self) -> str:
        return "Transmission CLI"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.TORRENT,
            EngineCapability.MAGNET,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
            EngineCapability.SPEED_LIMIT,
        ]

    @property
    def platforms(self) -> list:
        return ["linux", "darwin"]  # Windows 需要额外配置

    @property
    def install_hint(self) -> str:
        os_name = current_os()
        if os_name == "linux":
            return "apt install transmission-cli / yum install transmission-cli"
        elif os_name == "darwin":
            return "brew install transmission"
        return "https://transmissionbt.com/ (Windows 需安装完整 Transmission)"

    def is_available(self) -> bool:
        if not self.is_platform_compatible():
            return False
        return check_command("transmission-cli") or check_command("transmission-remote")

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "transmission-cli not found in PATH"
        url = request.url
        if not (url.endswith(".torrent") or url.startswith("magnet:")):
            return "Not a torrent/magnet URL"
        return None

    def build_command(self, request: DownloadRequest) -> List[str]:
        os.makedirs(request.output_dir, exist_ok=True)

        if check_command("transmission-cli"):
            cmd = ["transmission-cli"]
            cmd.extend(["-w", request.output_dir])

            # 限速
            if request.speed_limit:
                from ..utils import parse_speed_limit
                kbps = parse_speed_limit(request.speed_limit) // 1024
                cmd.extend(["-d", str(kbps)])

            # URL (torrent file or magnet)
            cmd.append(request.url)

        else:
            # transmission-remote
            cmd = ["transmission-remote"]
            cmd.extend(["-w", request.output_dir])

            # 限速
            if request.speed_limit:
                from ..utils import parse_speed_limit
                kbps = parse_speed_limit(request.speed_limit) // 1024
                cmd.extend(["-d", str(kbps)])

            cmd.extend(["-a", request.url])

        # 额外参数
        for arg in request.extra.get("extra_args", []):
            cmd.append(arg)

        return cmd

    def download(self, request: DownloadRequest) -> DownloadResult:
        err = self.validate_request(request)
        if err:
            return DownloadResult(success=False, engine_name=self.name, url=request.url, error=err)

        cmd = self.build_command(request)
        start = time.monotonic()

        # transmission 可能需要较长时间
        timeout = max(request.timeout, 300)
        rc, stdout, stderr = run_command(cmd, timeout=timeout)
        elapsed = time.monotonic() - start

        success = rc == 0
        output_path = None
        file_size = None

        if success:
            # 检查输出目录中的文件
            try:
                total_size = 0
                latest_file = None
                latest_mtime = 0
                for root, dirs, files in os.walk(request.output_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        mt = os.path.getmtime(fp)
                        sz = os.path.getsize(fp)
                        total_size += sz
                        if mt > latest_mtime:
                            latest_mtime = mt
                            latest_file = fp
                if latest_file:
                    output_path = latest_file
                    file_size = total_size
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
