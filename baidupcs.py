#!/usr/bin/env python3
"""
BaiduPCS-Py: 百度网盘 Python 客户端
基于 BaiduPCS-Go 的 API 逻辑，纯 Python 实现上传、下载、限速等功能。

用法:
    python baidupcs.py info
    python baidupcs.py ls /
    python baidupcs.py upload ./file.txt /
    python baidupcs.py download /file.txt ./ --speed 10M
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

# ============================================================
# 常量 (与 BaiduPCS-Go 一致)
# ============================================================
PCS_BAIDU_COM = "pcs.baidu.com"
PAN_BAIDU_COM = "pan.baidu.com"
PAN_APP_ID = "250528"
NETDISK_UA = "netdisk;P2SP;3.0.0.8;netdisk;11.12.3;ANG-AN00;android-android;10.0;JSbridge4.4.0;jointBridge;1.1.0;"
WEB_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 分片大小
MIN_BLOCK_SIZE = 4 * 1024 * 1024       # 4MB
MIDDLE_BLOCK_SIZE = 16 * 1024 * 1024   # 16MB
MAX_BLOCK_SIZE = 64 * 1024 * 1024      # 64MB
SLICE_MD5_SIZE = 256 * 1024            # 256KB

# 分片阈值
MIDDLE_UPLOAD_THRESHOLD = 8 * 1024 * 1024 * 1024   # 8GB
MAX_UPLOAD_THRESHOLD = 32 * 1024 * 1024 * 1024     # 32GB


# ============================================================
# 限速器 (Token Bucket)
# ============================================================
class SpeedLimiter:
    """令牌桶限速器 (精确版)"""

    def __init__(self, max_speed: int = 0):
        self.max_speed = max_speed
        self.tokens = 0.0  # 初始令牌为 0，避免初始突发
        self.last_time = time.monotonic()

    def consume(self, size: int):
        if self.max_speed <= 0:
            return
        while True:
            now = time.monotonic()
            elapsed = now - self.last_time
            self.tokens = min(float(self.max_speed), self.tokens + elapsed * self.max_speed)
            self.last_time = now
            if self.tokens >= size:
                self.tokens -= size
                return
            # 计算需要等待的时间
            deficit = size - self.tokens
            wait = deficit / self.max_speed
            time.sleep(wait)


def parse_speed(s: str) -> int:
    """解析速度字符串 '1M', '10M', '20M', '512K' → bytes/s"""
    if not s or s.strip() in ("0", "unlimited", ""):
        return 0
    s = s.strip().upper()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([KMG])?B?/?S?$", s)
    if not m:
        return int(s)
    num = float(m.group(1))
    unit = m.group(2) or ""
    return int(num * {"K": 1024, "M": 1024**2, "G": 1024**3}.get(unit, 1))


def format_size(size: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.2f}{u}"
        size /= 1024
    return f"{size:.2f}PB"


def format_speed(speed: float) -> str:
    return format_size(int(speed)) + "/s"


# ============================================================
# CRC32 / MD5 计算
# ============================================================
def _crc32_table():
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
        table.append(crc)
    return table


CRC32_TABLE = _crc32_table()


def baidu_crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc = CRC32_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def file_md5(filepath: str) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(131072), b""):
            h.update(chunk)
    return h.hexdigest()


def file_slice_md5(filepath: str, length: int = SLICE_MD5_SIZE) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        remaining = length
        while remaining > 0:
            chunk = f.read(min(remaining, 8192))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


def file_content_crc32(filepath: str) -> str:
    """计算整个文件的 CRC32"""
    crc = 0xFFFFFFFF
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(131072), b""):
            for b in chunk:
                crc = CRC32_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return format((crc ^ 0xFFFFFFFF) & 0xFFFFFFFF, "08x")


def file_data_content(filepath: str, offset: int = 0, length: int = 256 * 1024) -> str:
    """读取文件指定区间的 hex 内容 (用于秒传 v2)"""
    with open(filepath, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    return data.hex()


# ============================================================
# Sign 生成 (与 BaiduPCS-Go netdisksign 一致)
# ============================================================
def generate_locate_download_sign(uid: int, bduss: str) -> dict:
    """生成 locatedownload 签名参数"""
    devuid = hashlib.md5(bduss.encode()).hexdigest()[:40]
    t = int(time.time())

    # sign = SHA1( SHA1(BDUSS).hex + uid + fixed_salt + time + devuid )
    bduss_sha1 = hashlib.sha1(bduss.encode()).hexdigest()
    salt = b"ebrcUYiuxaZv2XGu7KIYKxUrqfnOpDF"
    rand_input = bduss_sha1.encode() + str(uid).encode() + salt + str(t).encode() + devuid.encode()
    rand = hashlib.sha1(rand_input).hexdigest()

    return {"time": t, "rand": rand, "devuid": devuid, "cuid": devuid}


def sign2_rc4(key: list, data: list) -> bytes:
    """RC4 加密 (与 BaiduPCS-Go Sign2 一致)"""
    a = [0] * 256
    p = list(range(256))
    v = len(key)
    if v == 0:
        return bytes(len(data))

    for q in range(256):
        a[q] = key[q % v]

    u = 0
    for q in range(256):
        u = (u + p[q] + a[q]) % 256
        p[q], p[u] = p[u], p[q]

    o = []
    u = 0
    i = 0
    for q in range(len(data)):
        i = (i + 1) % 256
        u = (u + p[i]) % 256
        p[i], p[u] = p[u], p[i]
        k = p[(p[i] + p[u]) % 256]
        o.append(data[q] ^ k)

    return bytes(o)


# ============================================================
# BaiduPCS 核心客户端
# ============================================================
class BaiduPCS:
    """百度网盘 Python 客户端"""

    def __init__(self, bduss: str, stoken: str, loglevel: str = "info"):
        self.bduss = bduss
        self.stoken = stoken
        self.loglevel = loglevel
        self.uid = 0
        self._user_info = None
        self._sign_cache = None

        # 创建 session
        self.session = requests.Session()
        self.session.cookies.set("BDUSS", bduss, domain=".baidu.com")
        self.session.cookies.set("STOKEN", stoken, domain=".baidu.com")
        self.session.headers.update({
            "User-Agent": WEB_UA,
            "Referer": "https://pan.baidu.com/disk/home",
        })

    def _log(self, level: str, msg: str):
        levels = {"debug": 0, "info": 1, "warn": 2, "error": 3}
        icons = {"debug": "🔍", "info": "ℹ️ ", "warn": "⚠️ ", "error": "❌"}
        if levels.get(level, 1) >= levels.get(self.loglevel, 1):
            print(f"{icons.get(level, '')} {msg}", file=sys.stderr)

    # ----------------------------------------------------------
    # 用户信息
    # ----------------------------------------------------------
    def user_info(self) -> dict:
        if self._user_info:
            return self._user_info
        url = f"https://{PAN_BAIDU_COM}/api/user/getinfo"
        r = self.session.get(url, params={"need_selfinfo": "1"}, timeout=30)
        data = r.json()
        if data.get("errno", -1) != 0:
            raise RuntimeError(f"获取用户信息失败: {data}")
        records = data.get("records", [])
        if records:
            self.uid = records[0].get("uk", 0)
        self._user_info = data
        return data

    def quota(self) -> dict:
        """获取配额信息"""
        url = f"https://{PAN_BAIDU_COM}/api/quota"
        r = self.session.get(url, params={"checkfree": 1, "checkexpire": 1}, timeout=30)
        return r.json()

    # ----------------------------------------------------------
    # 获取 sign (用于 pan API download)
    # ----------------------------------------------------------
    def _get_pan_sign(self) -> dict:
        """获取首页签名 (用于 /api/download)"""
        if self._sign_cache:
            return self._sign_cache

        # 访问首页获取 sign1, sign3, timestamp
        url = f"https://{PAN_BAIDU_COM}/disk/home"
        r = self.session.get(url, headers={"User-Agent": WEB_UA}, timeout=10, allow_redirects=False)

        # 如果被重定向到登录页，cookie 可能无效
        loc = r.headers.get("Location", "")
        if loc == "/" or "passport.baidu.com" in loc:
            self._log("warn", "Cookie 可能已过期，尝试继续...")

        body = r.text
        m = re.search(r'"sign1":"(.*?)"[\s\S]*"sign3":"(.*?)","timestamp":(\d*?),', body)
        if m:
            sign1 = m.group(2)
            sign3 = m.group(1)
            timestamp = m.group(3)

            # RC4 加密
            sign_bytes = sign2_rc4(list(sign3.encode()), list(sign1.encode()))
            import base64
            sign_b64 = base64.b64encode(sign_bytes).decode()

            self._sign_cache = {"sign": sign_b64, "timestamp": timestamp}
            return self._sign_cache

        self._log("debug", "无法从首页提取签名，将使用备用下载方式")
        return None

    # ----------------------------------------------------------
    # 获取 UID
    # ----------------------------------------------------------
    def _ensure_uid(self):
        if self.uid == 0:
            self.user_info()

    # ----------------------------------------------------------
    # 文件列表
    # ----------------------------------------------------------
    def list_files(self, remote_dir: str = "/", order: str = "time", desc: bool = True) -> list:
        """列出目录下的文件 (使用 pan API)"""
        url = f"https://{PAN_BAIDU_COM}/api/list"
        params = {
            "dir": remote_dir,
            "order": order,
            "desc": 1 if desc else 0,
            "showempty": 0,
            "web": 1,
            "page": 1,
            "num": 1000,
        }
        r = self.session.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("errno", -1) != 0:
            raise RuntimeError(f"列出文件失败: {data}")
        return data.get("list", [])

    # ----------------------------------------------------------
    # 创建目录
    # ----------------------------------------------------------
    def mkdir(self, remote_dir: str) -> dict:
        """创建目录 (使用 pan API)"""
        url = f"https://{PAN_BAIDU_COM}/api/create"
        data = {"path": remote_dir, "isdir": 1, "block_list": "[]", "rtype": 0}
        r = self.session.post(url, data=data, timeout=10)
        return r.json()

    # ----------------------------------------------------------
    # 下载
    # ----------------------------------------------------------
    def download(self, remote_path: str, local_path: str, speed_limit: int = 0):
        """下载文件"""
        # 获取文件信息
        file_info = self._get_file_info(remote_path)
        if not file_info:
            raise FileNotFoundError(f"远程文件不存在: {remote_path}")

        file_size = file_info.get("size", 0)
        fs_id = file_info.get("fs_id")

        if os.path.isdir(local_path):
            local_path = os.path.join(local_path, os.path.basename(remote_path))

        self._log("info", f"下载: {remote_path} → {local_path}")
        self._log("info", f"文件大小: {format_size(file_size)}")

        # 获取下载链接 (优先使用 locatedownload)
        dlink = self._get_download_link(remote_path, fs_id)
        if not dlink:
            raise RuntimeError("无法获取下载链接")

        limiter = SpeedLimiter(speed_limit)
        if speed_limit > 0:
            self._log("info", f"限速: {format_speed(speed_limit)}")

        self._do_download(dlink, local_path, file_size, limiter)
        self._log("info", f"✅ 下载完成: {local_path}")

    def _get_file_info(self, remote_path: str) -> dict:
        parent = os.path.dirname(remote_path) or "/"
        filename = os.path.basename(remote_path)
        try:
            files = self.list_files(parent)
            for f in files:
                if f.get("server_filename") == filename or f.get("path") == remote_path:
                    return f
        except Exception:
            pass
        return None

    def _get_download_link(self, remote_path: str, fs_id: int) -> str:
        """获取下载链接，按 BaiduPCS-Go 逻辑: locatedownload → pan API download"""

        # 方式1: locatedownload (PCS API, 需要签名)
        dlink = self._locate_download(remote_path)
        if dlink:
            return dlink

        # 方式2: pan API download
        dlink = self._pan_api_download(fs_id)
        if dlink:
            return dlink

        return None

    def _locate_download(self, remote_path: str) -> str:
        """通过 locatedownload API 获取下载链接"""
        self._ensure_uid()

        sign_params = generate_locate_download_sign(self.uid, self.bduss)
        url = f"https://{PCS_BAIDU_COM}/rest/2.0/pcs/file"
        params = {
            "ant": "1",
            "check_blue": "1",
            "es": "1",
            "esl": "1",
            "app_id": PAN_APP_ID,
            "method": "locatedownload",
            "path": remote_path,
            "ver": "4.0",
            "clienttype": "17",
            "channel": "0",
            "apn_id": "1_0",
            "freeisp": "0",
            "queryfree": "0",
            "use": "0",
            **{k: str(v) for k, v in sign_params.items()},
        }

        try:
            r = self.session.post(url, params=params, headers={"User-Agent": NETDISK_UA}, timeout=15)
            data = r.json()
            if "urls" in data:
                for u in data["urls"]:
                    dl_url = u.get("url", "")
                    if dl_url:
                        # 将 http 改为 https
                        if dl_url.startswith("http://"):
                            dl_url = "https://" + dl_url[7:]
                        return dl_url
            self._log("debug", f"locatedownload 失败: {data}")
        except Exception as e:
            self._log("debug", f"locatedownload 异常: {e}")

        return None

    def _pan_api_download(self, fs_id: int) -> str:
        """通过 pan API 获取下载链接"""
        sign_info = self._get_pan_sign()

        url = f"https://{PAN_BAIDU_COM}/api/download"
        data = {
            "fidlist": f"[{fs_id}]",
            "type": "dlink",
        }
        if sign_info:
            data["sign"] = sign_info["sign"]
            data["timestamp"] = sign_info["timestamp"]

        try:
            r = self.session.post(url, data=data, timeout=15)
            result = r.json()
            dlinks = result.get("dlink", [])
            if dlinks:
                return dlinks[0].get("dlink", "")
            self._log("debug", f"pan API download 失败: {result}")
        except Exception as e:
            self._log("debug", f"pan API download 异常: {e}")

        return None

    def _do_download(self, url: str, local_path: str, total_size: int, limiter: SpeedLimiter):
        """执行下载，支持断点续传"""
        tmp_path = local_path + ".baidupcs_py_tmp"
        downloaded = 0

        if os.path.exists(tmp_path):
            downloaded = os.path.getsize(tmp_path)
            self._log("info", f"断点续传: 已下载 {format_size(downloaded)}")

        headers = {
            "User-Agent": NETDISK_UA,
        }
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"

        # 使用 stream=True, 禁用自动解压缩
        r = self.session.get(url, headers=headers, stream=True, timeout=120,
                            allow_redirects=True)

        if r.status_code not in (200, 206):
            raise RuntimeError(f"下载失败, HTTP {r.status_code}")

        if r.status_code == 200 and downloaded > 0:
            downloaded = 0  # 服务器不支持断点续传

        mode = "ab" if downloaded > 0 else "wb"
        start_time = time.monotonic()
        last_report = start_time
        last_downloaded = downloaded

        with open(tmp_path, mode) as f:
            for chunk in r.iter_content(chunk_size=65536):
                if not chunk:
                    break
                limiter.consume(len(chunk))
                f.write(chunk)
                downloaded += len(chunk)

                now = time.monotonic()
                if now - last_report >= 1.0:
                    speed = (downloaded - last_downloaded) / (now - last_report)
                    pct = (downloaded / total_size * 100) if total_size > 0 else 0
                    self._log("info", f"下载: {pct:.1f}% | {format_size(downloaded)}/{format_size(total_size)} | {format_speed(speed)}")
                    last_report = now
                    last_downloaded = downloaded

        if os.path.exists(local_path):
            os.remove(local_path)
        os.rename(tmp_path, local_path)

    # ----------------------------------------------------------
    # 上传
    # ----------------------------------------------------------
    def upload(self, local_path: str, remote_dir: str = "/", speed_limit: int = 0):
        """上传文件"""
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"本地文件不存在: {local_path}")

        filename = os.path.basename(local_path)
        file_size = os.path.getsize(local_path)
        remote_path = f"{remote_dir.rstrip('/')}/{filename}"

        self._log("info", f"上传: {local_path} → {remote_path}")
        self._log("info", f"文件大小: {format_size(file_size)}")

        limiter = SpeedLimiter(speed_limit)
        if speed_limit > 0:
            self._log("info", f"限速: {format_speed(speed_limit)}")

        # 计算文件哈希
        md5 = file_md5(local_path)
        slice_md5 = file_slice_md5(local_path)
        crc32 = file_content_crc32(local_path)

        self._log("debug", f"MD5: {md5}")
        self._log("debug", f"SliceMD5: {slice_md5}")
        self._log("debug", f"CRC32: {crc32}")

        # 确定分片大小
        if file_size > MAX_UPLOAD_THRESHOLD:
            block_size = MAX_BLOCK_SIZE
        elif file_size > MIDDLE_UPLOAD_THRESHOLD:
            block_size = MIDDLE_BLOCK_SIZE
        else:
            block_size = MIN_BLOCK_SIZE

        # 计算分片 MD5 列表
        block_list = self._calc_block_md5_list(local_path, block_size)

        # 步骤1: Precreate (预创建)
        precreate_result = self._precreate(remote_path, file_size, md5, slice_md5, crc32, block_list)

        return_type = precreate_result.get("return_type", 0)
        upload_id = precreate_result.get("uploadid", "")

        if return_type == 2:
            # 秒传成功
            self._log("info", f"✅ 秒传成功: {remote_path}")
            return

        if return_type == 1 and not upload_id:
            raise RuntimeError(f"预创建失败: {precreate_result}")

        # 步骤2: 分片上传
        self._log("info", f"开始分片上传 (uploadid={upload_id})")
        block_list_result = []

        with open(local_path, "rb") as f:
            for seq in range(len(block_list)):
                chunk = f.read(block_size)
                if not chunk:
                    break

                chunk_md5 = hashlib.md5(chunk).hexdigest()
                self._log("info", f"上传分片 {seq + 1}/{len(block_list)} ({format_size(len(chunk))})")

                limiter.consume(len(chunk))
                result = self._upload_superfile2(upload_id, remote_path, seq, chunk)
                block_list_result.append(chunk_md5)

                pct = (seq + 1) / len(block_list) * 100
                self._log("info", f"上传进度: {pct:.1f}%")

        # 步骤3: Create (合并)
        create_result = self._create_file(remote_path, file_size, upload_id, block_list_result)
        if create_result.get("errno", -1) != 0:
            raise RuntimeError(f"合并文件失败: {create_result}")

        self._log("info", f"✅ 上传完成: {remote_path}")

    def _calc_block_md5_list(self, filepath: str, block_size: int) -> list:
        """计算每个分片的 MD5"""
        blocks = []
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(block_size)
                if not chunk:
                    break
                blocks.append(hashlib.md5(chunk).hexdigest())
        return blocks

    def _precreate(self, remote_path: str, file_size: int, md5: str, slice_md5: str,
                   crc32: str, block_list: list) -> dict:
        """预创建上传任务"""
        url = f"https://{PAN_BAIDU_COM}/api/precreate"
        data = {
            "path": remote_path,
            "size": str(file_size),
            "isdir": "0",
            "block_list": json.dumps(block_list),
            "autoinit": "1",
            "content-md5": md5,
            "slice-md5": slice_md5,
            "contentCrc32": crc32,
            "rtype": "2",  # 2=重命名
        }

        r = self.session.post(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": NETDISK_UA,
        }, timeout=30)
        return r.json()

    def _upload_superfile2(self, upload_id: str, remote_path: str, part_seq: int, data: bytes) -> dict:
        """上传单个分片"""
        url = f"https://{PCS_BAIDU_COM}/rest/2.0/pcs/superfile2"
        params = {
            "method": "upload",
            "type": "tmpfile",
            "path": remote_path,
            "partseq": str(part_seq),
            "partoffset": "0",
            "uploadid": upload_id,
            "vip": "1",
            "app_id": PAN_APP_ID,
        }

        files = {"file": ("blob", data, "application/octet-stream")}
        r = self.session.post(url, params=params, files=files, timeout=120)
        return r.json()

    def _create_file(self, remote_path: str, file_size: int, upload_id: str, block_list: list) -> dict:
        """合并分片"""
        url = f"https://{PAN_BAIDU_COM}/api/create"
        data = {
            "path": remote_path,
            "size": str(file_size),
            "isdir": "0",
            "rtype": "2",
            "uploadid": upload_id,
            "block_list": json.dumps(block_list),
            "target_path": os.path.dirname(remote_path) + "/",
        }

        r = self.session.post(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        }, timeout=30)
        return r.json()

    # ----------------------------------------------------------
    # 分享链接转存
    # ----------------------------------------------------------
    def save_share(self, share_url: str, password: str = "", remote_dir: str = "/") -> dict:
        """转存分享链接中的文件到自己的网盘"""
        self._log("info", f"转存分享链接: {share_url}")

        # 提取 surl
        m = re.search(r"s/([a-zA-Z0-9_-]+)", share_url)
        if not m:
            m = re.search(r"surl=([a-zA-Z0-9_-]+)", share_url)
        if not m:
            raise ValueError(f"无法提取 surl: {share_url}")

        surl = m.group(1)
        featurestr = f"1{surl}"

        # 1. 访问分享页
        tokens = self._access_share_page(featurestr)
        if tokens.get("ErrMsg") != "0":
            raise RuntimeError(f"访问分享页失败: {tokens.get('ErrMsg')}")

        shareid = tokens.get("shareid", "")
        uk = tokens.get("uk", "")
        bdstoken = tokens.get("bdstoken", "")

        self._log("debug", f"shareid={shareid}, uk={uk}")

        # 2. 验证提取码
        if password:
            verify_result = self._verify_share_password(surl, password)
            if verify_result.get("ErrMsg") != "0":
                raise RuntimeError(f"提取码验证失败: {verify_result.get('ErrMsg')}")

        # 3. 获取文件列表
        file_list = self._get_share_file_list(shareid, uk, surl)
        if not file_list:
            raise RuntimeError("分享链接中没有文件")

        self._log("info", f"找到 {len(file_list)} 个文件")
        for f in file_list:
            self._log("info", f"  - {f.get('server_filename', '?')} ({format_size(f.get('size', 0))})")

        # 4. 转存
        fs_ids = [str(f["fs_id"]) for f in file_list]
        return self._transfer_share(shareid, uk, bdstoken, fs_ids, remote_dir, surl)

    def _access_share_page(self, featurestr: str) -> dict:
        """访问分享页获取 token"""
        url = f"https://{PAN_BAIDU_COM}/s/{featurestr}"
        r = self.session.get(url, headers={
            "User-Agent": WEB_UA,
            "Referer": f"https://{PAN_BAIDU_COM}/disk/home",
        }, timeout=10)

        body = r.text
        if "platform-non-found" in body:
            return {"ErrMsg": "分享链接已失效"}
        if "error-404" in body:
            return {"ErrMsg": "页面不存在"}

        m = re.search(r'(\{.+?loginstate.+?\})\);', body)
        if not m:
            return {"ErrMsg": "请确认已包含 STOKEN"}

        info = json.loads(m.group(1))
        return {
            "ErrMsg": "0",
            "bdstoken": info.get("bdstoken", ""),
            "uk": str(info.get("uk", "")),
            "share_uk": str(info.get("share_uk", "")),
            "shareid": str(info.get("shareid", "")),
        }

    def _verify_share_password(self, surl: str, password: str) -> dict:
        """验证分享提取码"""
        url = f"https://{PAN_BAIDU_COM}/share/verify"
        data = {"surl": surl, "pwd": password, "t": str(int(time.time() * 1000))}
        r = self.session.post(url, data=data, headers={
            "User-Agent": WEB_UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"https://{PAN_BAIDU_COM}/share/init?surl={surl}",
        }, timeout=10)

        body = r.json()
        if body.get("errno", -1) == 0:
            return {"ErrMsg": "0", "randsk": body.get("randsk", "")}
        elif body.get("errno") == -9:
            return {"ErrMsg": "提取码错误"}
        return {"ErrMsg": f"未知错误, errno={body.get('errno')}"}

    def _get_share_file_list(self, shareid: str, uk: str, surl: str) -> list:
        """获取分享文件列表"""
        url = f"https://{PAN_BAIDU_COM}/share/list"
        params = {
            "uk": uk,
            "shareid": shareid,
            "order": "other",
            "desc": "1",
            "showempty": "0",
            "page": "1",
            "num": "100",
            "dir": "/",
        }
        r = self.session.get(url, params=params, headers={
            "User-Agent": WEB_UA,
        }, timeout=10)
        data = r.json()
        if data.get("errno", -1) != 0:
            self._log("debug", f"获取分享文件列表失败: {data}")
            return []
        return data.get("list", [])

    def _transfer_share(self, shareid: str, uk: str, bdstoken: str, fs_ids: list,
                        remote_dir: str, surl: str) -> dict:
        """执行转存"""
        url = f"https://{PAN_BAIDU_COM}/share/transfer"
        params = {
            "app_id": PAN_APP_ID,
            "channel": "chunlei",
            "clienttype": "0",
            "web": "1",
        }
        data = {
            "from": uk,
            "shareid": shareid,
            "path": remote_dir,
            "fsidlist": json.dumps(fs_ids),
        }
        r = self.session.post(url, params=params, data=data, headers={
            "User-Agent": WEB_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"https://{PAN_BAIDU_COM}/s/1{surl}",
        }, timeout=30)
        return r.json()

    # ----------------------------------------------------------
    # 删除 / 重命名
    # ----------------------------------------------------------
    def delete(self, remote_paths: list) -> dict:
        """删除文件 (使用 pan API)"""
        url = f"https://{PAN_BAIDU_COM}/api/filemanager"
        data = {
            "opera": "delete",
            "filelist": json.dumps(remote_paths),
        }
        r = self.session.post(url, data=data, timeout=10)
        return r.json()

    def rename(self, remote_path: str, new_name: str) -> dict:
        """重命名文件 (使用 pan API)"""
        url = f"https://{PAN_BAIDU_COM}/api/filemanager"
        dest = os.path.dirname(remote_path) or "/"
        data = {
            "opera": "rename",
            "filelist": json.dumps([{"path": remote_path, "dest": dest, "newname": new_name}]),
        }
        r = self.session.post(url, data=data, timeout=10)
        return r.json()


# ============================================================
# CLI
# ============================================================
def print_file_table(files: list):
    if not files:
        print("(空目录)")
        return
    print(f"{'类型':<4} {'大小':>12} {'修改时间':<20} {'文件名'}")
    print("-" * 70)
    for f in files:
        is_dir = f.get("isdir", 0)
        ftype = "📁" if is_dir else "📄"
        size = format_size(f.get("size", 0)) if not is_dir else "<DIR>"
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.get("mtime", 0)))
        name = f.get("server_filename", f.get("path", "?"))
        print(f"{ftype:<4} {size:>12} {mtime:<20} {name}")


def main():
    parser = argparse.ArgumentParser(
        description="BaiduPCS-Py: 百度网盘 Python 客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s info
  %(prog)s ls /
  %(prog)s upload ./file.txt / --speed 1M
  %(prog)s download /file.txt ./ --speed 10M
""",
    )
    parser.add_argument("--bduss", default=os.environ.get("BDUSS", ""), help="BDUSS")
    parser.add_argument("--stoken", default=os.environ.get("STOKEN", ""), help="STOKEN")
    parser.add_argument("--loglevel", default="info", choices=["debug", "info", "warn", "error"])

    sub = parser.add_subparsers(dest="command")

    p_ls = sub.add_parser("ls", help="列出文件")
    p_ls.add_argument("path", nargs="?", default="/")

    p_up = sub.add_parser("upload", aliases=["u"], help="上传")
    p_up.add_argument("local", help="本地文件")
    p_up.add_argument("remote", nargs="?", default="/")
    p_up.add_argument("--speed", default="0")

    p_dl = sub.add_parser("download", aliases=["d"], help="下载")
    p_dl.add_argument("remote", help="远程文件")
    p_dl.add_argument("local", nargs="?", default="./")
    p_dl.add_argument("--speed", default="0")

    p_mkdir = sub.add_parser("mkdir", help="创建目录")
    p_mkdir.add_argument("path")

    p_rm = sub.add_parser("delete", aliases=["rm"], help="删除")
    p_rm.add_argument("paths", nargs="+")

    p_mv = sub.add_parser("rename", aliases=["mv"], help="重命名")
    p_mv.add_argument("path")
    p_mv.add_argument("newname")

    sub.add_parser("info", help="用户信息")

    p_share = sub.add_parser("share", help="转存分享链接")
    p_share.add_argument("url", help="分享链接")
    p_share.add_argument("--password", "-p", default="")
    p_share.add_argument("--dir", default="/")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    bduss = args.bduss
    stoken = args.stoken
    if not bduss:
        print("❌ 请提供 BDUSS (--bduss 或环境变量 BDUSS)", file=sys.stderr)
        sys.exit(1)

    pcs = BaiduPCS(bduss, stoken, loglevel=args.loglevel)

    try:
        if args.command == "info":
            info = pcs.user_info()
            records = info.get("records", [{}])
            if records:
                u = records[0]
                print(f"用户: {u.get('uname', u.get('priority_name', '?'))} (VIP等级: {u.get('vip_level', 0)})")
            q = pcs.quota()
            used = q.get("used", 0)
            total = q.get("total", 0)
            if total:
                print(f"容量: {format_size(used)} / {format_size(total)}")

        elif args.command == "ls":
            files = pcs.list_files(args.path)
            print_file_table(files)

        elif args.command in ("upload", "u"):
            pcs.upload(args.local, args.remote, speed_limit=parse_speed(args.speed))

        elif args.command in ("download", "d"):
            pcs.download(args.remote, args.local, speed_limit=parse_speed(args.speed))

        elif args.command == "mkdir":
            r = pcs.mkdir(args.path)
            print(f"✅ 创建成功" if r.get("errno", -1) == 0 else f"❌ 失败: {r}")

        elif args.command in ("delete", "rm"):
            r = pcs.delete(args.paths)
            print(f"✅ 删除成功" if r.get("errno", -1) == 0 else f"❌ 失败: {r}")

        elif args.command in ("rename", "mv"):
            r = pcs.rename(args.path, args.newname)
            print(f"✅ 重命名成功" if r.get("errno", -1) == 0 else f"❌ 失败: {r}")

        elif args.command == "share":
            r = pcs.save_share(args.url, args.password, args.dir)
            if r.get("errno", -1) == 0:
                print(f"✅ 转存成功")
            else:
                print(f"❌ 转存失败: {r}")

    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
