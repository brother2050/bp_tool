"""
工具函数：命令执行、文件名推断、URL 匹配等。
"""

import os
import re
import subprocess
import shutil
import hashlib
from typing import Optional, List, Tuple
from urllib.parse import urlparse, unquote


def run_command(
    cmd: List[str],
    timeout: int = 60,
    env: Optional[dict] = None,
    cwd: Optional[str] = None,
    input_data: Optional[str] = None,
) -> Tuple[int, str, str]:
    """
    执行外部命令，返回 (returncode, stdout, stderr)。
    """
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)

    try:
        proc = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=True,
            text=True,
            env=merged_env,
            cwd=cwd,
            input=input_data,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -3, "", str(e)


def check_command(name: str) -> bool:
    """检测命令是否可用"""
    return shutil.which(name) is not None


def get_command_path(name: str) -> Optional[str]:
    """获取命令完整路径"""
    return shutil.which(name)


def infer_filename(url: str, content_disposition: Optional[str] = None) -> Optional[str]:
    """
    从 URL 或 Content-Disposition 推断文件名。
    """
    # 优先从 Content-Disposition 解析
    if content_disposition:
        match = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\r\n]+)', content_disposition, re.I)
        if match:
            name = unquote(match.group(1).strip())
            if name:
                return sanitize_filename(name)

    # 从 URL 路径解析
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if path and path != "/":
        name = os.path.basename(path)
        if name and "." in name:
            return sanitize_filename(name)

    return None


def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    # 替换非法字符
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    # 去除首尾空格和点
    name = name.strip(" .")
    # 限制长度
    if len(name) > 255:
        base, ext = os.path.splitext(name)
        name = base[:255 - len(ext)] + ext
    return name or "download"


def match_pattern(url: str, pattern: str) -> bool:
    """
    URL 模式匹配。
    支持：
      - "*.example.com"  域名通配
      - "magnet:*"       协议前缀
      - "*.ext"          扩展名
      - 完整 URL 子串匹配
    """
    if pattern.startswith("*."):
        # 域名通配: *.youtube.com
        domain = pattern[2:]
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host == domain or host.endswith("." + domain)

    if pattern.endswith("*"):
        # 前缀匹配: magnet:*
        prefix = pattern[:-1]
        return url.startswith(prefix)

    if pattern.startswith("*.") and "." in pattern[2:]:
        # 扩展名: *.mp4
        ext = pattern[1:]  # .mp4
        parsed = urlparse(url)
        return parsed.path.endswith(ext)

    # 子串匹配
    return pattern in url


def parse_speed_limit(limit: str) -> int:
    """
    解析限速字符串为 bytes/sec。
    "1M" -> 1048576, "500K" -> 512000, "1024" -> 1024
    """
    limit = limit.strip().upper()
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3}
    if limit and limit[-1] in multipliers:
        return int(float(limit[:-1]) * multipliers[limit[-1]])
    return int(limit)


def compute_checksum(filepath: str, algo: str = "sha256") -> str:
    """计算文件校验和"""
    h = hashlib.new(algo)
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def format_speed(bps: float) -> str:
    """格式化速度"""
    if bps <= 0:
        return "0 B/s"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"
