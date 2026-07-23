"""
httpx 引擎 — 现代异步 HTTP 客户端。

支持 HTTP/2，异步下载，现代化 API。
"""

import os
import time
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from ..registry import EngineRegistry
from ..utils import infer_filename


@EngineRegistry.register
class HttpxEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "httpx"

    @property
    def display_name(self) -> str:
        return "httpx"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.RESUME,
            EngineCapability.PROXY,
            EngineCapability.HEADER_CUSTOM,
        ]

    def is_available(self) -> bool:
        try:
            import httpx  # noqa: F401
            return True
        except ImportError:
            return False

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        if not self.is_available():
            return "httpx not installed (pip install httpx)"
        return None

    def download(self, request: DownloadRequest) -> DownloadResult:
        err = self.validate_request(request)
        if err:
            return DownloadResult(success=False, engine_name=self.name, url=request.url, error=err)

        import httpx

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
        proxies = request.proxy

        # 确定输出路径
        output_path = None
        if request.filename:
            output_path = os.path.join(request.output_dir, request.filename)

        start = time.monotonic()
        try:
            with httpx.Client(
                proxy=proxies,
                timeout=request.timeout,
                follow_redirects=True,
                http2=True,
            ) as client:
                with client.stream("GET", request.url, headers=headers) as resp:
                    resp.raise_for_status()

                    # 推断文件名
                    if not output_path:
                        cd = resp.headers.get("content-disposition")
                        fname = infer_filename(request.url, cd)
                        if fname:
                            output_path = os.path.join(request.output_dir, fname)
                        else:
                            output_path = os.path.join(request.output_dir, "download")

                    # 流式写入
                    file_size = 0
                    with open(output_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
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

        except httpx.HTTPStatusError as e:
            elapsed = time.monotonic() - start
            return DownloadResult(
                success=False,
                engine_name=self.name,
                url=request.url,
                elapsed=elapsed,
                error=f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
                return_code=e.response.status_code,
                stderr=str(e),
            )
        except httpx.RequestError as e:
            elapsed = time.monotonic() - start
            return DownloadResult(
                success=False,
                engine_name=self.name,
                url=request.url,
                elapsed=elapsed,
                error=str(e),
                stderr=str(e),
            )
