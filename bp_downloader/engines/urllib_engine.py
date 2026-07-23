"""
urllib 引擎 — Python 标准库下载器。

零依赖，始终可用。适合简单 HTTP 下载。
"""

import os
import time
import urllib.request
import urllib.error
from typing import List, Optional
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability
from ..registry import EngineRegistry
from ..utils import infer_filename, sanitize_filename


@EngineRegistry.register
class UrllibEngine(DownloadEngine):

    @property
    def name(self) -> str:
        return "urllib"

    @property
    def display_name(self) -> str:
        return "Python urllib"

    @property
    def capabilities(self) -> List[EngineCapability]:
        return [
            EngineCapability.HTTP,
            EngineCapability.FTP,
            EngineCapability.PROXY,
            EngineCapability.HEADER_CUSTOM,
        ]

    def is_available(self) -> bool:
        return True  # 标准库，始终可用

    def validate_request(self, request: DownloadRequest) -> Optional[str]:
        return None  # 始终有效

    def download(self, request: DownloadRequest) -> DownloadResult:
        import time as time_mod

        os.makedirs(request.output_dir, exist_ok=True)

        # 构建请求
        req = urllib.request.Request(request.url)

        # 设置 headers
        for k, v in request.headers.items():
            req.add_header(k, v)
        if request.referer:
            req.add_header("Referer", request.referer)
        ua = request.user_agent or request.headers.get("User-Agent")
        if ua:
            req.add_header("User-Agent", ua)
        if request.cookies:
            req.add_header("Cookie", request.cookies)

        # 代理
        if request.proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": request.proxy,
                "https": request.proxy,
            })
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener()

        # 确定输出文件名
        output_path = None
        if request.filename:
            output_path = os.path.join(request.output_dir, request.filename)

        start = time_mod.monotonic()
        try:
            resp = opener.open(req, timeout=request.timeout)

            # 从响应推断文件名
            if not output_path:
                cd = resp.headers.get("Content-Disposition")
                fname = infer_filename(request.url, cd)
                if fname:
                    output_path = os.path.join(request.output_dir, fname)
                else:
                    output_path = os.path.join(request.output_dir, "download")

            # 写入文件
            file_size = 0
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)  # 1MB buffer
                    if not chunk:
                        break
                    f.write(chunk)
                    file_size += len(chunk)

            elapsed = time_mod.monotonic() - start
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

        except urllib.error.HTTPError as e:
            elapsed = time_mod.monotonic() - start
            return DownloadResult(
                success=False,
                engine_name=self.name,
                url=request.url,
                elapsed=elapsed,
                error=f"HTTP {e.code}: {e.reason}",
                return_code=e.code,
                stderr=str(e),
            )
        except urllib.error.URLError as e:
            elapsed = time_mod.monotonic() - start
            return DownloadResult(
                success=False,
                engine_name=self.name,
                url=request.url,
                elapsed=elapsed,
                error=f"URL Error: {e.reason}",
                stderr=str(e),
            )
        except Exception as e:
            elapsed = time_mod.monotonic() - start
            return DownloadResult(
                success=False,
                engine_name=self.name,
                url=request.url,
                elapsed=elapsed,
                error=str(e),
                stderr=str(e),
            )
