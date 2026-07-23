"""
requests 引擎 — Python requests 库下载器。

流行且易用，支持会话、重定向、Cookie 等。
"""

import os
import time
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability, current_os
from ..registry import EngineRegistry
from ..utils import infer_filename


@EngineRegistry.register
class RequestsEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "requests"

    @property
    def display_name(self) -> str:
        return "Python requests"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
            EngineCapability.HEADER_CUSTOM,
        ]

    @property
    def platforms(self) -> list:
        return []  # Python 库，全平台

    @property
    def install_hint(self) -> str:
        return "pip install requests"

    def is_available(self) -> bool:
        if not self.is_platform_compatible():
            return False
        try:
            import requests  # noqa: F401
            return True
        except ImportError:
            return False

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "requests library not installed (pip install requests)"
        return None

    def download(self, request: DownloadRequest) -> DownloadResult:
        err = self.validate_request(request)
        if err:
            return DownloadResult(success=False, engine_name=self.name, url=request.url, error=err)

        import requests

        os.makedirs(request.output_dir, exist_ok=True)

        # 构建 headers
        headers = dict(request.headers)
        if request.referer:
            headers["Referer"] = request.referer
        ua = request.user_agent or request.headers.get("User-Agent")
        if ua:
            headers["User-Agent"] = ua
        if request.cookies:
            headers["Cookie"] = request.cookies

        # 代理
        proxies = None
        if request.proxy:
            proxies = {"http": request.proxy, "https": request.proxy}

        # 确定输出路径
        output_path = None
        if request.filename:
            output_path = os.path.join(request.output_dir, request.filename)

        start = time.monotonic()
        try:
            resp = requests.get(
                request.url,
                headers=headers,
                proxies=proxies,
                timeout=request.timeout,
                stream=True,
                allow_redirects=True,
            )
            resp.raise_for_status()

            # 推断文件名
            if not output_path:
                cd = resp.headers.get("Content-Disposition")
                fname = infer_filename(request.url, cd)
                if fname:
                    output_path = os.path.join(request.output_dir, fname)
                else:
                    output_path = os.path.join(request.output_dir, "download")

            # 流式写入
            file_size = 0
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        file_size += len(chunk)

            elapsed = time.monotonic() - start
            speed = file_size / elapsed if elapsed > 0 else 0

            return DownloadResult(
                success=True,
                engine_name=self.name,
                url=request.url,
                output_path=output_path,
                file_size=file_size,
                elapsed=elapsed,
                speed=speed,
            )

        except requests.exceptions.HTTPError as e:
            elapsed = time.monotonic() - start
            return DownloadResult(
                success=False,
                engine_name=self.name,
                url=request.url,
                elapsed=elapsed,
                error=f"HTTP {e.response.status_code}: {e.response.reason}",
                return_code=e.response.status_code,
                stderr=str(e),
            )
        except requests.exceptions.RequestException as e:
            elapsed = time.monotonic() - start
            return DownloadResult(
                success=False,
                engine_name=self.name,
                url=request.url,
                elapsed=elapsed,
                error=str(e),
                stderr=str(e),
            )
