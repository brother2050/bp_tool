#!/usr/bin/env python3
"""
BaiduPCS-Py: 百度网盘 Python 客户端
基于 BaiduPCS-Go 的 API 逻辑，纯 Python 实现上传、下载等功能。

用法:
    python baidupcs.py info
    python baidupcs.py ls /
    python baidupcs.py upload ./file.txt /
    python baidupcs.py download /file.txt ./
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

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
# 工具函数
# ============================================================
def format_size(size: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.2f}{u}"
        size /= 1024
    return f"{size:.2f}PB"


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
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
        table.append(crc)
    crc = 0xFFFFFFFF
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(131072), b""):
            for b in chunk:
                crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return format((crc ^ 0xFFFFFFFF) & 0xFFFFFFFF, "08x")


# ============================================================
# Sign 生成 (与 BaiduPCS-Go netdisksign 一致)
# ============================================================
def generate_locate_download_sign(uid: int, bduss: str) -> dict:
    """生成 locatedownload 签名参数"""
    devuid = hashlib.md5(bduss.encode()).hexdigest()[:40]
    t = int(time.time())
    bduss_sha1 = hashlib.sha1(bduss.encode()).hexdigest()
    salt = b"ebrcUYiuxaZv2XGu7KIYKxUrqfnOpDF"
    rand_input = bduss_sha1.encode() + str(uid).encode() + salt + str(t).encode() + devuid.encode()
    rand = hashlib.sha1(rand_input).hexdigest()
    return {"time": t, "rand": rand, "devuid": devuid, "cuid": devuid}


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
        url = f"https://{PAN_BAIDU_COM}/api/quota"
        r = self.session.get(url, params={"checkfree": 1, "checkexpire": 1}, timeout=30)
        return r.json()

    # ----------------------------------------------------------
    # 文件列表
    # ----------------------------------------------------------
    def list_files(self, remote_dir: str = "/", order: str = "time", desc: bool = True) -> list:
        url = f"https://{PAN_BAIDU_COM}/api/list"
        params = {
            "dir": remote_dir, "order": order,
            "desc": 1 if desc else 0, "showempty": 0,
            "web": 1, "page": 1, "num": 1000,
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
        url = f"https://{PAN_BAIDU_COM}/api/create"
        data = {"path": remote_dir, "isdir": 1, "block_list": "[]", "rtype": 0}
        r = self.session.post(url, data=data, timeout=10)
        return r.json()

    # ----------------------------------------------------------
    # 下载
    # ----------------------------------------------------------
    def download(self, remote_path: str, local_path: str):
        file_info = self._get_file_info(remote_path)
        if not file_info:
            raise FileNotFoundError(f"远程文件不存在: {remote_path}")

        file_size = file_info.get("size", 0)

        if os.path.isdir(local_path):
            local_path = os.path.join(local_path, os.path.basename(remote_path))

        self._log("info", f"下载: {remote_path} → {local_path} ({format_size(file_size)})")

        dlink = self._get_download_link(remote_path, file_info.get("fs_id"))
        if not dlink:
            raise RuntimeError("无法获取下载链接")

        self._do_download(dlink, local_path, file_size)
        self._log("info", f"✅ 下载完成: {local_path}")

    def _get_file_info(self, remote_path: str) -> dict:
        parent = os.path.dirname(remote_path) or "/"
        filename = os.path.basename(remote_path)
        try:
            for f in self.list_files(parent):
                if f.get("server_filename") == filename or f.get("path") == remote_path:
                    return f
        except Exception:
            pass
        return None

    def _get_download_link(self, remote_path: str, fs_id: int) -> str:
        dlink = self._locate_download(remote_path)
        if dlink:
            return dlink
        return self._pan_api_download(fs_id)

    def _locate_download(self, remote_path: str) -> str:
        if self.uid == 0:
            self.user_info()
        sign_params = generate_locate_download_sign(self.uid, self.bduss)
        url = f"https://{PCS_BAIDU_COM}/rest/2.0/pcs/file"
        params = {
            "ant": "1", "check_blue": "1", "es": "1", "esl": "1",
            "app_id": PAN_APP_ID, "method": "locatedownload",
            "path": remote_path, "ver": "4.0", "clienttype": "17",
            "channel": "0", "apn_id": "1_0", "freeisp": "0",
            "queryfree": "0", "use": "0",
            **{k: str(v) for k, v in sign_params.items()},
        }
        try:
            r = self.session.post(url, params=params, headers={"User-Agent": NETDISK_UA}, timeout=15)
            data = r.json()
            if "urls" in data:
                for u in data["urls"]:
                    dl_url = u.get("url", "")
                    if dl_url:
                        return dl_url.replace("http://", "https://") if dl_url.startswith("http://") else dl_url
        except Exception as e:
            self._log("debug", f"locatedownload 异常: {e}")
        return None

    def _pan_api_download(self, fs_id: int) -> str:
        url = f"https://{PAN_BAIDU_COM}/api/download"
        data = {"fidlist": f"[{fs_id}]", "type": "dlink"}
        try:
            r = self.session.post(url, data=data, timeout=15)
            dlinks = r.json().get("dlink", [])
            if dlinks:
                return dlinks[0].get("dlink", "")
        except Exception:
            pass
        return None

    def _do_download(self, url: str, local_path: str, total_size: int):
        tmp_path = local_path + ".baidupcs_py_tmp"
        downloaded = 0

        if os.path.exists(tmp_path):
            downloaded = os.path.getsize(tmp_path)
            self._log("info", f"断点续传: 已下载 {format_size(downloaded)}")

        headers = {"User-Agent": NETDISK_UA}
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"

        r = self.session.get(url, headers=headers, stream=True, timeout=120, allow_redirects=True)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"下载失败, HTTP {r.status_code}")
        if r.status_code == 200 and downloaded > 0:
            downloaded = 0

        mode = "ab" if downloaded > 0 else "wb"
        start_time = time.monotonic()
        last_report = start_time
        last_downloaded = downloaded

        with open(tmp_path, mode) as f:
            for chunk in r.iter_content(chunk_size=65536):
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_report >= 1.0:
                    speed = (downloaded - last_downloaded) / (now - last_report)
                    pct = (downloaded / total_size * 100) if total_size > 0 else 0
                    self._log("info", f"下载: {pct:.1f}% | {format_size(downloaded)}/{format_size(total_size)} | {format_size(int(speed))}/s")
                    last_report = now
                    last_downloaded = downloaded

        if os.path.exists(local_path):
            os.remove(local_path)
        os.rename(tmp_path, local_path)

    # ----------------------------------------------------------
    # 上传
    # ----------------------------------------------------------
    def upload(self, local_path: str, remote_dir: str = "/"):
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"本地文件不存在: {local_path}")

        filename = os.path.basename(local_path)
        file_size = os.path.getsize(local_path)
        remote_path = f"{remote_dir.rstrip('/')}/{filename}"

        self._log("info", f"上传: {local_path} → {remote_path} ({format_size(file_size)})")

        md5 = file_md5(local_path)
        slice_md5 = file_slice_md5(local_path)
        crc32 = file_content_crc32(local_path)

        # 确定分片大小
        if file_size > MAX_UPLOAD_THRESHOLD:
            block_size = MAX_BLOCK_SIZE
        elif file_size > MIDDLE_UPLOAD_THRESHOLD:
            block_size = MIDDLE_BLOCK_SIZE
        else:
            block_size = MIN_BLOCK_SIZE

        block_list = []
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(block_size)
                if not chunk:
                    break
                block_list.append(hashlib.md5(chunk).hexdigest())

        # Precreate
        precreate_result = self._precreate(remote_path, file_size, md5, slice_md5, crc32, block_list)
        return_type = precreate_result.get("return_type", 0)
        upload_id = precreate_result.get("uploadid", "")

        if return_type == 2:
            self._log("info", f"✅ 秒传成功: {remote_path}")
            return
        if return_type == 1 and not upload_id:
            raise RuntimeError(f"预创建失败: {precreate_result}")

        # 分片上传
        self._log("info", f"分片上传 (uploadid={upload_id})")
        block_list_result = []
        with open(local_path, "rb") as f:
            for seq in range(len(block_list)):
                chunk = f.read(block_size)
                if not chunk:
                    break
                self._log("info", f"上传分片 {seq + 1}/{len(block_list)} ({format_size(len(chunk))})")
                self._upload_superfile2(upload_id, remote_path, seq, chunk)
                block_list_result.append(hashlib.md5(chunk).hexdigest())

        # 合并
        result = self._create_file(remote_path, file_size, upload_id, block_list_result)
        if result.get("errno", -1) != 0:
            raise RuntimeError(f"合并文件失败: {result}")
        self._log("info", f"✅ 上传完成: {remote_path}")

    def _precreate(self, remote_path, file_size, md5, slice_md5, crc32, block_list):
        url = f"https://{PAN_BAIDU_COM}/api/precreate"
        data = {
            "path": remote_path, "size": str(file_size), "isdir": "0",
            "block_list": json.dumps(block_list), "autoinit": "1",
            "content-md5": md5, "slice-md5": slice_md5,
            "contentCrc32": crc32, "rtype": "2",
        }
        r = self.session.post(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded", "User-Agent": NETDISK_UA,
        }, timeout=30)
        return r.json()

    def _upload_superfile2(self, upload_id, remote_path, part_seq, data):
        url = f"https://{PCS_BAIDU_COM}/rest/2.0/pcs/superfile2"
        params = {
            "method": "upload", "type": "tmpfile", "path": remote_path,
            "partseq": str(part_seq), "partoffset": "0",
            "uploadid": upload_id, "vip": "1", "app_id": PAN_APP_ID,
        }
        files = {"file": ("blob", data, "application/octet-stream")}
        r = self.session.post(url, params=params, files=files, timeout=120)
        return r.json()

    def _create_file(self, remote_path, file_size, upload_id, block_list):
        url = f"https://{PAN_BAIDU_COM}/api/create"
        data = {
            "path": remote_path, "size": str(file_size), "isdir": "0",
            "rtype": "2", "uploadid": upload_id,
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
        self._log("info", f"转存: {share_url}")
        m = re.search(r"s/([a-zA-Z0-9_-]+)", share_url)
        if not m:
            m = re.search(r"surl=([a-zA-Z0-9_-]+)", share_url)
        if not m:
            raise ValueError(f"无法提取 surl: {share_url}")
        surl = m.group(1)

        tokens = self._access_share_page(f"1{surl}")
        if tokens.get("ErrMsg") != "0":
            raise RuntimeError(f"访问分享页失败: {tokens.get('ErrMsg')}")

        if password:
            vr = self._verify_share_password(surl, password)
            if vr.get("ErrMsg") != "0":
                raise RuntimeError(f"提取码验证失败: {vr.get('ErrMsg')}")

        file_list = self._get_share_file_list(tokens["shareid"], tokens["uk"], surl)
        if not file_list:
            raise RuntimeError("分享链接中没有文件")

        self._log("info", f"找到 {len(file_list)} 个文件")
        fs_ids = [str(f["fs_id"]) for f in file_list]
        return self._transfer_share(tokens["shareid"], tokens["uk"], fs_ids, remote_dir, surl)

    def _access_share_page(self, featurestr):
        r = self.session.get(f"https://{PAN_BAIDU_COM}/s/{featurestr}", timeout=10)
        body = r.text
        if "platform-non-found" in body:
            return {"ErrMsg": "分享链接已失效"}
        m = re.search(r'(\{.+?loginstate.+?\})\);', body)
        if not m:
            return {"ErrMsg": "请确认已包含 STOKEN"}
        info = json.loads(m.group(1))
        return {"ErrMsg": "0", "bdstoken": info.get("bdstoken", ""),
                "uk": str(info.get("uk", "")), "shareid": str(info.get("shareid", ""))}

    def _verify_share_password(self, surl, password):
        r = self.session.post(f"https://{PAN_BAIDU_COM}/share/verify",
                              data={"surl": surl, "pwd": password, "t": str(int(time.time() * 1000))}, timeout=10)
        body = r.json()
        if body.get("errno") == 0:
            return {"ErrMsg": "0"}
        return {"ErrMsg": "提取码错误" if body.get("errno") == -9 else f"errno={body.get('errno')}"}

    def _get_share_file_list(self, shareid, uk, surl):
        r = self.session.get(f"https://{PAN_BAIDU_COM}/share/list",
                             params={"uk": uk, "shareid": shareid, "order": "other", "desc": "1", "page": "1", "num": "100", "dir": "/"}, timeout=10)
        return r.json().get("list", [])

    def _transfer_share(self, shareid, uk, fs_ids, remote_dir, surl):
        r = self.session.post(f"https://{PAN_BAIDU_COM}/share/transfer",
                              params={"app_id": PAN_APP_ID, "channel": "chunlei", "clienttype": "0", "web": "1"},
                              data={"from": uk, "shareid": shareid, "path": remote_dir, "fsidlist": json.dumps(fs_ids)},
                              headers={"Referer": f"https://{PAN_BAIDU_COM}/s/1{surl}"}, timeout=30)
        return r.json()

    # ----------------------------------------------------------
    # 删除 / 重命名
    # ----------------------------------------------------------
    def delete(self, remote_paths: list) -> dict:
        r = self.session.post(f"https://{PAN_BAIDU_COM}/api/filemanager",
                              data={"opera": "delete", "filelist": json.dumps(remote_paths)}, timeout=10)
        return r.json()

    def rename(self, remote_path: str, new_name: str) -> dict:
        dest = os.path.dirname(remote_path) or "/"
        r = self.session.post(f"https://{PAN_BAIDU_COM}/api/filemanager",
                              data={"opera": "rename", "filelist": json.dumps([{"path": remote_path, "dest": dest, "newname": new_name}])}, timeout=10)
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
    parser = argparse.ArgumentParser(description="BaiduPCS-Py: 百度网盘 Python 客户端")
    parser.add_argument("--bduss", default=os.environ.get("BDUSS", ""), help="BDUSS")
    parser.add_argument("--stoken", default=os.environ.get("STOKEN", ""), help="STOKEN")
    parser.add_argument("--loglevel", default="info", choices=["debug", "info", "warn", "error"])

    sub = parser.add_subparsers(dest="command")

    p_ls = sub.add_parser("ls", help="列出文件")
    p_ls.add_argument("path", nargs="?", default="/")

    p_up = sub.add_parser("upload", aliases=["u"], help="上传")
    p_up.add_argument("local", help="本地文件")
    p_up.add_argument("remote", nargs="?", default="/")

    p_dl = sub.add_parser("download", aliases=["d"], help="下载")
    p_dl.add_argument("remote", help="远程文件")
    p_dl.add_argument("local", nargs="?", default="./")

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

    if not args.bduss:
        print("❌ 请提供 BDUSS (--bduss 或环境变量 BDUSS)", file=sys.stderr)
        sys.exit(1)

    pcs = BaiduPCS(args.bduss, args.stoken, loglevel=args.loglevel)

    try:
        if args.command == "info":
            info = pcs.user_info()
            records = info.get("records", [{}])
            if records:
                u = records[0]
                print(f"用户: {u.get('uname', '?')} (VIP: {u.get('vip_level', 0)})")
            q = pcs.quota()
            used, total = q.get("used", 0), q.get("total", 0)
            if total:
                print(f"容量: {format_size(used)} / {format_size(total)}")

        elif args.command == "ls":
            print_file_table(pcs.list_files(args.path))

        elif args.command in ("upload", "u"):
            pcs.upload(args.local, args.remote)

        elif args.command in ("download", "d"):
            pcs.download(args.remote, args.local)

        elif args.command == "mkdir":
            r = pcs.mkdir(args.path)
            print("✅ 创建成功" if r.get("errno", -1) == 0 else f"❌ 失败: {r}")

        elif args.command in ("delete", "rm"):
            r = pcs.delete(args.paths)
            print("✅ 删除成功" if r.get("errno", -1) == 0 else f"❌ 失败: {r}")

        elif args.command in ("rename", "mv"):
            r = pcs.rename(args.path, args.newname)
            print("✅ 重命名成功" if r.get("errno", -1) == 0 else f"❌ 失败: {r}")

        elif args.command == "share":
            r = pcs.save_share(args.url, args.password, args.dir)
            print("✅ 转存成功" if r.get("errno", -1) == 0 else f"❌ 转存失败: {r}")

    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
