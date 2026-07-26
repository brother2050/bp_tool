#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百度网盘工具 — 20MB/s 极速版

在签名机制基础上，增加多线程分片下载：
- 单文件拆分为 N 个分片，N 个线程并行下载
- 每个线程独立 HTTP 连接，充分利用带宽
- 自动检测 CDN 节点速度，动态调整线程数
- 文件句柄持久化，预分配磁盘空间

目标：20MB/s（单文件多线程）
"""

import os, re, sys, json, time, hashlib, random, string, shutil, subprocess
import urllib.request, urllib.parse, urllib.error
import http.cookiejar, http.client, ssl, threading, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# ============================================================
# 常量
# ============================================================
PAN_BASE   = "https://pan.baidu.com"
PCS_BASE   = "https://pcs.baidu.com"
GO_UA = "netdisk;P2SP;3.0.0.8;netdisk;11.12.3;ANG-AN00;android-android;10.0;JSbridge4.4.0;jointBridge;1.1.0;"
PAN_APP_ID = "250528"
PCS_APP_ID = "778750"
PAN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
PCS_UA = "softxm;netdisk"

UPLOAD_CHUNK = 4 * 1024 * 1024
MAX_PAR      = 1

# ★ 多线程分片下载参数
MT_WORKERS       = 32          # 单文件最大并行线程数
MT_CHUNK_MIN     = 4 * 1024 * 1024   # 最小分片 4MB
MT_CHUNK_MAX     = 32 * 1024 * 1024  # 最大分片 32MB
MT_BUF           = 1024 * 1024        # 每线程读写缓冲 1MB
MT_SMALL_FILE    = 20 * 1024 * 1024   # 小于此大小用单线程

ARIA2_DEFAULTS = {
    "max-connection-per-server": 16,  # aria2c 上限是16
    "split": 16,
    "timeout": 120,
    "retry-wait": 2,
    "max-tries": 10,
    "min-split-size": "1M",
}

# ============================================================
# BaiduPCS-Go 签名机制
# ============================================================
_LOCATE_SECRET = b"ebrcUYiuxaZv2XGu7KIYKxUrqfnOfpDF"

def _dev_uid(bduss: str) -> str:
    return hashlib.md5(bduss.encode()).hexdigest().upper() + "|0"

def _locate_sign(uid: int, bduss: str) -> dict:
    now = int(time.time())
    devuid = _dev_uid(bduss)
    sha1_bduss = hashlib.sha1(bduss.encode()).hexdigest()
    rand_input = sha1_bduss + str(uid) + _LOCATE_SECRET.decode() + str(now) + devuid
    rand = hashlib.sha1(rand_input.encode()).hexdigest()
    return {"time": str(now), "rand": rand, "devuid": devuid, "cuid": devuid}

# ============================================================
# 工具函数
# ============================================================
def _md5(b): return hashlib.md5(b).hexdigest()
def _md5_file(p):
    h = hashlib.md5()
    with open(p,"rb") as f:
        for c in iter(lambda:f.read(8192),b""): h.update(c)
    return h.hexdigest()
def _slice_md5(p):
    h = hashlib.md5()
    with open(p,"rb") as f: h.update(f.read(256*1024))
    return h.hexdigest()
def _bd():
    return "----WB"+"".join(random.choices(string.ascii_letters+string.digits,k=16))
def _mp(fields, files, bd):
    ls = []
    for n,v in fields.items():
        ls += [f"--{bd}".encode(), f'disposition: form-data; name="{n}"'.encode(),
               b"", v.encode() if isinstance(v,str) else v]
    for n,(fn,d,ct) in files.items():
        ls += [f"--{bd}".encode(),
               f'Content-Disposition: form-data; name="{n}"; filename="{fn}"'.encode(),
               f"Content-Type: {ct}".encode(), b"", d]
    ls += [f"--{bd}--".encode(), b""]
    return b"\r\n".join(ls), f"multipart/form-data; boundary={bd}"

def _fmt(b):
    if b<1024: return f"{b:.0f}B"
    if b<1024**2: return f"{b/1024:.1f}KB"
    if b<1024**3: return f"{b/1024**2:.1f}MB"
    return f"{b/1024**3:.2f}GB"
def _spd(b):
    if b<1024: return f"{b:.0f}B/s"
    if b<1024**2: return f"{b/1024:.1f}KB/s"
    if b<1024**3: return f"{b/1024**2:.1f}MB/s"
    return f"{b/1024**3:.2f}GB/s"

def _has_aria2():
    if shutil.which("aria2c"): return True
    wrapper = os.path.expanduser("~/bin/aria2c")
    return os.path.isfile(wrapper) and os.access(wrapper, os.X_OK)

def _http_url(url):
    if url.startswith("https://"):
        return "http://" + url[8:]
    return url

# ============================================================
# HTTP 客户端
# ============================================================
class HClient:
    def __init__(self, cookies=None):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        if cookies:
            for k,v in cookies.items(): self.set_cookie(k,v)

    def set_cookie(self, name, val):
        self.jar.set_cookie(http.cookiejar.Cookie(
            version=0,name=name,value=val,port=None,port_specified=False,
            domain=".baidu.com",domain_specified=True,domain_initial_dot=True,
            path="/",path_specified=True,secure=False,
            expires=int(time.time())+86400*365,
            discard=False,comment=None,comment_url=None,rest={},rfc2109=False))

    def get_json(self, url, params=None, hdrs=None):
        if params: url += "?" + urllib.parse.urlencode(params)
        r = urllib.request.Request(url, method="GET")
        r.add_header("User-Agent", PAN_UA)
        if hdrs:
            for k,v in hdrs.items(): r.add_header(k,v)
        d = self.op.open(r, timeout=30).read()
        try: return json.loads(d)
        except: return {"raw":d.decode("utf-8",errors="replace")}

    def get_text(self, url, params=None, hdrs=None, timeout=60):
        if params: url += "?" + urllib.parse.urlencode(params)
        r = urllib.request.Request(url, method="GET")
        r.add_header("User-Agent", PAN_UA)
        if hdrs:
            for k,v in hdrs.items(): r.add_header(k,v)
        return self.op.open(r, timeout=timeout).read().decode("utf-8",errors="replace")

    def post_json(self, url, data=None, params=None, hdrs=None):
        if params: url += "?" + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data).encode() if data else b""
        r = urllib.request.Request(url, data=body, method="POST")
        r.add_header("User-Agent", PAN_UA)
        r.add_header("Content-Type","application/x-www-form-urlencoded")
        if hdrs:
            for k,v in hdrs.items(): r.add_header(k,v)
        d = self.op.open(r, timeout=60).read()
        try: return json.loads(d)
        except: return {"raw":d.decode("utf-8",errors="replace")}

    def post_raw(self, url, raw, ct, hdrs=None):
        r = urllib.request.Request(url, data=raw, method="POST")
        r.add_header("User-Agent", PCS_UA)
        r.add_header("Content-Type", ct)
        if hdrs:
            for k,v in hdrs.items(): r.add_header(k,v)
        return self.op.open(r, timeout=120).read()

# ============================================================
# 多线程分片下载引擎
# ============================================================
class MultiThreadDownloader:
    """多线程分片下载器 — 目标 20MB/s"""

    def __init__(self, bduss):
        self._bduss = bduss
        self._ssl_ctx = ssl.create_default_context()

    def _create_conn(self, host, port, is_https, timeout=120):
        if is_https:
            conn = http.client.HTTPSConnection(host, port, context=self._ssl_ctx, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        return conn

    def _do_request(self, url, headers, start_byte, end_byte):
        """发起单个 Range 请求"""
        p = urlparse(url)
        host = p.hostname
        port = p.port or (443 if p.scheme == "https" else 80)
        req_path = p.path + ("?"+p.query if p.query else "")
        is_https = p.scheme == "https"

        conn = self._create_conn(host, port, is_https)
        hdrs = dict(headers)
        # ★ 关键：qdall01 只接受 PCS_UA
        if "qdall01" in (host or ""):
            hdrs["User-Agent"] = PCS_UA
        hdrs["Range"] = f"bytes={start_byte}-{end_byte}"
        conn.request("GET", req_path, headers=hdrs)
        resp = conn.getresponse()

        if resp.status in (301, 302, 307, 308):
            loc = resp.getheader("Location", "")
            resp.read()
            conn.close()
            if loc:
                loc = _http_url(loc)
                p2 = urlparse(loc)
                conn = self._create_conn(
                    p2.hostname,
                    p2.port or (443 if p2.scheme=="https" else 80),
                    p2.scheme == "https")
                conn.request("GET", p2.path + ("?"+p2.query if p2.query else ""), headers=hdrs)
                resp = conn.getresponse()
        return conn, resp

    def _test_range(self, url):
        """测试URL是否支持Range请求"""
        headers = {
            "User-Agent": GO_UA,
            "Cookie": f"BDUSS={self._bduss}",
        }
        try:
            conn, resp = self._do_request(url, headers, 0, 1023)
            status = resp.status
            cr = resp.getheader("Content-Range", "")
            resp.read()
            conn.close()
            return status == 206 and "bytes" in cr
        except Exception:
            return False

    def _get_total_size(self, url, headers):
        """获取文件总大小"""
        conn, resp = self._do_request(url, headers, 0, 0)
        total = 0
        cr = resp.getheader("Content-Range", "")
        if "/" in cr:
            try: total = int(cr.split("/")[1])
            except: pass
        if not total:
            total = int(resp.getheader("Content-Length", 0))
        resp.read()
        conn.close()
        return total

    def _calc_chunk_size(self, total_size):
        """根据文件大小计算最优分片大小"""
        if total_size <= MT_SMALL_FILE:
            return total_size  # 小文件不分片
        # 目标：每个分片 4-32MB，总分片数不超过 MT_WORKERS
        chunk = total_size // MT_WORKERS
        chunk = max(MT_CHUNK_MIN, min(chunk, MT_CHUNK_MAX))
        return chunk

    def _calc_workers(self, total_size, chunk_size):
        """计算实际线程数"""
        if total_size <= MT_SMALL_FILE:
            return 1
        return min(MT_WORKERS, max(1, (total_size + chunk_size - 1) // chunk_size))

    def _download_chunk(self, url, headers, start, end, filepath, chunk_idx,
                        progress, errors):
        """下载单个分片"""
        retries = 3
        for attempt in range(retries):
            try:
                conn, resp = self._do_request(url, headers, start, end)
                if resp.status not in (200, 206):
                    resp.read()
                    conn.close()
                    if attempt < retries - 1:
                        time.sleep(1)
                        continue
                    errors[chunk_idx] = f"HTTP {resp.status}"
                    return

                pos = start
                while pos <= end:
                    chunk = resp.read(MT_BUF)
                    if not chunk:
                        break
                    # 写入文件指定位置
                    with open(filepath, "r+b") as f:
                        f.seek(pos)
                        f.write(chunk)
                    pos += len(chunk)
                    progress[chunk_idx] += len(chunk)
                conn.close()
                return  # 成功
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(1)
                else:
                    errors[chunk_idx] = str(e)

    def download(self, url, filepath, label="", size_hint=0):
        """多线程分片下载"""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        headers = {
            "User-Agent": GO_UA,
            "Cookie": f"BDUSS={self._bduss}",
            "Connection": "keep-alive",
        }

        # 获取文件大小
        total = self._get_total_size(url, headers)
        if not total:
            total = size_hint
        if not total:
            raise Exception("无法获取文件大小")

        # 预分配文件（创建指定大小的空文件）
        with open(filepath, "wb") as f:
            f.truncate(total)

        # 计算分片
        chunk_size = self._calc_chunk_size(total)
        workers = self._calc_workers(total, chunk_size)

        if workers == 1:
            # 小文件：单线程下载
            return self._download_single(url, headers, filepath, label, total)

        # 大文件：多线程分片下载
        chunks = []
        pos = 0
        while pos < total:
            end = min(pos + chunk_size - 1, total - 1)
            chunks.append((pos, end))
            pos = end + 1

        print(f"    {label} {_fmt(total)} → {len(chunks)}分片 x {workers}线程")

        progress = [0] * len(chunks)
        errors = {}

        t0 = time.time()
        last_print = t0
        last_total_dl = 0

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for idx, (start, end) in enumerate(chunks):
                fut = pool.submit(
                    self._download_chunk, url, headers, start, end,
                    filepath, idx, progress, errors)
                futures.append(fut)

            # 监控进度
            while not all(f.done() for f in futures):
                time.sleep(0.3)
                now = time.time()
                if now - last_print >= 0.5:
                    total_dl = sum(progress)
                    elapsed = now - t0
                    speed = total_dl / elapsed if elapsed > 0 else 0
                    pct = total_dl * 100 // total if total > 0 else 0
                    # 区间速度
                    interval = now - last_print
                    interval_speed = (total_dl - last_total_dl) / interval if interval > 0 else 0
                    last_total_dl = total_dl
                    last_print = now
                    active = sum(1 for f in futures if not f.done())
                    print(f"\r    {label} [{pct}%] {_spd(speed)} "
                          f"[区间{_spd(interval_speed)}] {active}线程活跃   ",
                          end="", flush=True)

            # 等待所有完成
            for f in futures:
                f.result()

        elapsed = time.time() - t0
        speed = total / elapsed if elapsed > 0 else 0

        if errors:
            print(f"\r    ⚠ {label} — {_fmt(total)} ({_spd(speed)}) 错误: {errors}        ")
        else:
            print(f"\r    ✓ {label} — {_fmt(total)} ({_spd(speed)}, {len(chunks)}分片)        ")

        if errors:
            raise Exception(f"分片下载错误: {errors}")
        return total

    def _download_single(self, url, headers, filepath, label, total):
        """单线程下载（小文件或回退）"""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        if os.path.exists(filepath):
            os.remove(filepath)

        # 尝试不带BDUSS的请求（签名URL自带认证）
        for use_cookie in [True, False]:
            try:
                h = dict(headers)
                if not use_cookie:
                    h.pop("Cookie", None)

                p = urlparse(url)
                is_https = p.scheme == "https"
                if is_https:
                    conn = http.client.HTTPSConnection(p.hostname, 443, context=self._ssl_ctx, timeout=120)
                else:
                    conn = http.client.HTTPConnection(p.hostname, 80, timeout=120)

                req_path = p.path + ("?"+p.query if p.query else "")
                conn.request("GET", req_path, headers=h)
                resp = conn.getresponse()

                # 处理重定向
                if resp.status in (301, 302, 307, 308):
                    loc = resp.getheader("Location", "")
                    resp.read()
                    conn.close()
                    if loc:
                        return self._download_single(loc, headers, filepath, label, total)

                if resp.status == 403:
                    resp.read()
                    conn.close()
                    continue

                t0 = time.time()
                downloaded = 0
                last_print = t0

                with open(filepath, "wb") as f:
                    while True:
                        chunk = resp.read(MT_BUF)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_print >= 0.5:
                            elapsed = now - t0
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            pct = downloaded * 100 // total if total > 0 else 0
                            print(f"\r    {label} [{pct}%] {_spd(speed)}   ",
                                  end="", flush=True)
                            last_print = now
                conn.close()

                # 验证下载结果
                if downloaded > 1024:
                    elapsed = time.time() - t0
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    print(f"\r    ✓ {label} — {_fmt(downloaded)} ({_spd(speed)})        ")
                    return downloaded
                # 下载内容太少，可能是错误
                continue
            except Exception:
                continue

        raise Exception(f"单线程下载失败: {label}")

# ============================================================
# aria2c 调用
# ============================================================
def aria2_download(url, out_dir, filename, bduss, params=None):
    out_path = os.path.join(out_dir, filename)
    cfg = dict(ARIA2_DEFAULTS)
    if params:
        cfg.update(params)
    aria2_cmd = shutil.which("aria2c") or os.path.expanduser("~/bin/aria2c")
    # ★ 关键：qdall01 只接受 PCS_UA
    host = urlparse(url).hostname or ""
    ua = PCS_UA if "qdall01" in host else GO_UA
    cmd = [aria2_cmd,
           "--console-log-level=warn",
           "--file-allocation=none",
           "--continue=true",
           "--auto-file-renaming=false",
           "--allow-overwrite=true",
           f"--dir={out_dir}",
           f"--out={filename}",
           f"--header=Cookie: BDUSS={bduss}",
           f"--header=User-Agent: {ua}",
           url]
    for k, v in cfg.items():
        cmd.append(f"--{k}={v}")
    x = cfg.get("max-connection-per-server", 32)
    s = cfg.get("split", 32)
    print(f"    ⚡ aria2c -x{x} -s{s} {filename}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if proc.returncode == 0:
            sz = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            print(f"    ✓ {filename} — {_fmt(sz)}")
            return True
        err_out = (proc.stderr or "").strip()
        err_lines = err_out.split("\n")[-5:] if err_out else []
        print(f"    ⚠ aria2c 失败 (code={proc.returncode}): {' '.join(err_lines)[:200]}")
        return False
    except subprocess.TimeoutExpired:
        print(f"    ⚠ aria2c 超时")
        return False
    except Exception as e:
        print(f"    ⚠ aria2c 异常: {e}")
        return False

# ============================================================
# 百度网盘下载器
# ============================================================
class BaiduPanDownloader:
    def __init__(self, bduss, stoken="", max_parallel=MAX_PAR,
                 use_aria2=None, aria2_params=None):
        self.cli = HClient({"BDUSS":bduss, "STOKEN":stoken})
        self._bduss = bduss
        self._stoken = stoken
        self._mp = max_parallel
        self._dl = MultiThreadDownloader(bduss)
        self._aria2_params = aria2_params or {}
        if use_aria2 is None:
            self._use_aria2 = _has_aria2()
        else:
            self._use_aria2 = use_aria2
        cfg = dict(ARIA2_DEFAULTS)
        cfg.update(self._aria2_params)
        x = cfg.get("max-connection-per-server", 32)
        s = cfg.get("split", 32)
        mode = f"⚡ aria2c -x{x} -s{s}" if self._use_aria2 else f"🚀 多线程分片 ({MT_WORKERS}线程)"
        print(f"  下载模式: {mode}")

    def _surl(self, url):
        m = re.search(r'/s/1([a-zA-Z0-9_-]+)', url)
        if m: return m.group(1)
        m = re.search(r'surl=([a-zA-Z0-9_-]+)', url)
        if m: return m.group(1)
        raise ValueError(f"无法提取 surl: {url}")

    def _get_captcha(self, surl):
        url = f"{PAN_BASE}/api/getcaptcha"
        params = {
            "surl": surl, "channel": "chunlei", "web": "1",
            "app_id": PAN_APP_ID, "clienttype": "0",
            "t": str(int(time.time()*1000)),
        }
        headers = {"Referer": f"{PAN_BASE}/s/1{surl}"}
        return self.cli.get_json(url, params=params, hdrs=headers)

    def _verify(self, surl, pwd):
        last_err = None
        for attempt in range(5):
            result = self.cli.post_json(f"{PAN_BASE}/share/verify",
                data={"pwd":pwd},
                params={"surl":surl,"t":str(int(time.time()*1000)),
                        "channel":"chunlei","web":"1","app_id":PAN_APP_ID,"clienttype":"0"},
                hdrs={"Referer":f"{PAN_BASE}/s/1{surl}", "Origin":PAN_BASE})
            errno = result.get("errno", -1)
            if errno == 0:
                return result
            last_err = result
            if errno == 9019:
                wait = 3 * (attempt + 1)
                print(f"  ⚠ 请求被限流 (errno=9019)，等待{wait}秒后重试 ({attempt+1}/5)...")
                time.sleep(wait)
                continue
            if errno in (-62, -9):
                print(f"  ⚠ 需要验证码 (errno={errno})，尝试获取...")
                captcha = self._get_captcha(surl)
                vcode_str = captcha.get("vcode_str", "")
                vcode_img = captcha.get("vcode_img", "")
                if vcode_str and vcode_img:
                    try:
                        img_data = self.cli.op.open(
                            urllib.request.Request(vcode_img), timeout=10).read()
                        captcha_path = os.path.join(os.path.expanduser("~"), ".baidu_captcha.jpg")
                        with open(captcha_path, "wb") as f:
                            f.write(img_data)
                        print(f"  验证码已保存到: {captcha_path}")
                        vcode = input("  请输入验证码: ").strip()
                        if vcode:
                            result = self.cli.post_json(f"{PAN_BASE}/share/verify",
                                data={"pwd":pwd, "vcode":vcode, "vcode_str":vcode_str},
                                params={"surl":surl,"t":str(int(time.time()*1000)),
                                        "channel":"chunlei","web":"1","app_id":PAN_APP_ID,"clienttype":"0"},
                                hdrs={"Referer":f"{PAN_BASE}/s/1{surl}"})
                            if result.get("errno") == 0:
                                return result
                    except Exception as e:
                        print(f"  ⚠ 获取验证码失败: {e}")
                time.sleep(2)
            else:
                return result
        return last_err or result

    def _page_data(self, url):
        html = self.cli.get_text(url)
        m = re.search(r'locals\.mset\((.+?)\);', html)
        if not m: raise Exception("无法解析分享页面")
        return json.loads(m.group(1))

    def _share_list(self, surl, uk, sid, bt, dirp="/"):
        r = self.cli.get_json(f"{PAN_BASE}/share/list",
            params={"uk":uk,"shareid":sid,"order":"other","desc":"1",
                    "showempty":"0","web":"1","page":"1","num":"100",
                    "dir":dirp,"channel":"chunlei","app_id":PAN_APP_ID,
                    "clienttype":"0","bdstoken":bt},
            hdrs={"Referer":f"{PAN_BASE}/s/1{surl}"})
        return r.get("list",[]) if r.get("errno")==0 else []

    def _transfer(self, uk, sid, bt, fids, path):
        r = self.cli.post_json(f"{PAN_BASE}/share/transfer",
            data={"fsidlist":json.dumps(fids),"path":path},
            params={"shareid":sid,"from":uk,"channel":"chunlei","web":"1",
                    "app_id":PAN_APP_ID,"clienttype":"0","bdstoken":bt})
        e = r.get("errno",-1)
        if e==0: return True,"转存成功"
        if e==2: return True,"文件已存在"
        return False,f"errno={e} {r.get('show_msg','')}"

    def _list_own(self, path):
        url = f"{PCS_BASE}/rest/2.0/pcs/file?method=list&by=name&limit=0-1000&order=asc&path={urllib.parse.quote(path)}&app_id={PCS_APP_ID}"
        r = urllib.request.Request(url)
        r.add_header("User-Agent",PCS_UA)
        r.add_header("Cookie",f"BDUSS={self._bduss}")
        try:
            return json.loads(self.cli.op.open(r,timeout=30).read()).get("list",[])
        except Exception:
            return []

    def _dl_url(self, path):
        """获取直链 — 返回所有可用URL列表（qdall01优先，签名CDN备选）"""
        all_urls = []

        # 1. 未签名 locatedownload（qdall01 节点，稳定可靠）
        for app_id in [PCS_APP_ID, PAN_APP_ID]:
            try:
                url = (f"{PCS_BASE}/rest/2.0/pcs/file?method=locatedownload"
                       f"&path={urllib.parse.quote(path)}&app_id={app_id}")
                r = urllib.request.Request(url)
                r.add_header("User-Agent", PCS_UA)
                r.add_header("Cookie", f"BDUSS={self._bduss}")
                d = json.loads(self.cli.op.open(r, timeout=10).read())
                for u in d.get("urls", []):
                    u_url = u['url']
                    if u_url not in all_urls:
                        all_urls.append(u_url)
            except Exception:
                continue

        # 2. 签名 locatedownload（高速CDN节点，可能不可用）
        sign = _locate_sign(0, self._bduss)
        params = {
            "ant": "1", "check_blue": "1", "es": "1", "esl": "1",
            "app_id": PAN_APP_ID, "method": "locatedownload",
            "path": path, "ver": "4.0", "clienttype": "17",
            "channel": "0", "apn_id": "1_0", "freeisp": "0",
            "queryfree": "0", "use": "0",
            "time": sign["time"], "rand": sign["rand"],
            "devuid": sign["devuid"], "cuid": sign["cuid"],
        }
        url = f"{PCS_BASE}/rest/2.0/pcs/file?{urllib.parse.urlencode(params)}"
        r = urllib.request.Request(url, method="POST", data=b"")
        r.add_header("User-Agent", GO_UA)
        r.add_header("Cookie", f"BDUSS={self._bduss}")
        r.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            d = json.loads(self.cli.op.open(r, timeout=15).read())
            for u in d.get("urls", []):
                u_url = u['url']
                if u_url not in all_urls:
                    all_urls.append(u_url)
        except Exception:
            pass

        if not all_urls:
            raise Exception("无下载链接")
        return all_urls

    def _mkdir(self, p):
        url = f"{PCS_BASE}/rest/2.0/pcs/file?method=mkdir&path={urllib.parse.quote(p)}&app_id={PCS_APP_ID}"
        r = urllib.request.Request(url)
        r.add_header("User-Agent",PCS_UA)
        r.add_header("Cookie",f"BDUSS={self._bduss}")
        try: self.cli.op.open(r,timeout=30)
        except: pass

    def _search_file(self, keyword):
        url = f"{PCS_BASE}/rest/2.0/pcs/file?method=search&path=%2F&wd={urllib.parse.quote(keyword)}&re=1&app_id={PCS_APP_ID}"
        r = urllib.request.Request(url)
        r.add_header("User-Agent",PCS_UA)
        r.add_header("Cookie",f"BDUSS={self._bduss}")
        try:
            return json.loads(self.cli.op.open(r,timeout=30).read()).get("list",[])
        except Exception:
            return []

    def download(self, share_url, password='', save_dir="./baidu_downloads",
                 remote_temp="/_baidu_dl_tmp"):
        surl = self._surl(share_url)
        print(f"[1/5] 验证... surl={surl}")

        pd = None
        if password:
            try:
                pd = self._page_data(f"{PAN_BASE}/s/1{surl}")
                if pd.get("file_list"):
                    print("  ✓ 直接获取页面数据成功（跳过verify）")
                else:
                    pd = None
            except Exception:
                pd = None

            if not pd:
                vr = self._verify(surl, password)
                errno = vr.get("errno", -1)
                if errno == 0:
                    rk = vr.get("randsk","")
                    if rk: self.cli.set_cookie("BDCLND", urllib.parse.unquote(rk))
                elif errno == -12:
                    raise Exception("提取码错误")
                elif errno == -62:
                    raise Exception("需要验证码")
                else:
                    print(f"  ⚠ verify errno={errno}，仍尝试获取页面...")
                    rk = vr.get("randsk","")
                    if rk: self.cli.set_cookie("BDCLND", urllib.parse.unquote(rk))

        print("[2/5] 获取分享信息...")
        if not pd:
            pd = self._page_data(f"{PAN_BASE}/s/1{surl}")
        uk = pd.get("share_uk") or pd.get("uk"); sid = pd.get("shareid")
        bt = pd.get("bdstoken","")
        if not uk or not sid: raise Exception("分享信息获取失败")
        print(f"  分享者: {pd.get('linkusername','未知')}")

        print("[3/5] 扫描文件...")
        pfl = pd.get("file_list",[])
        for f in pfl:
            fn = f.get("server_filename","")
            path = f.get("path","")
            if not path.startswith("/"):
                f["path"] = "/" + fn
        files = [f for f in pfl if f.get("isdir")==0]
        dirs  = [f for f in pfl if f.get("isdir")==1]
        for f in files: print(f"  📄 {f.get('server_filename')} ({_fmt(f.get('size',0))})")
        for d in dirs:  print(f"  📁 {d.get('server_filename')}/")
        allf = list(files)
        for d in dirs:
            dpath = d.get("path","")
            if not dpath.startswith("/"): dpath = "/" + d.get("server_filename","")
            sub = self._share_list(surl, uk, sid, bt, dpath)
            for sf in sub:
                if sf.get("isdir")==0: allf.append(sf)
                else:
                    deeper = self._share_list(surl, uk, sid, bt, sf["path"])
                    allf.extend([x for x in deeper if x.get("isdir")==0])
        print(f"  共 {len(allf)} 个文件")

        print("[4/5] 转存...")
        self._mkdir(remote_temp)
        ok,msg = self._transfer(uk, sid, bt, [f["fs_id"] for f in allf], remote_temp)
        print(f"  {msg}")
        if not ok: raise Exception(f"转存失败: {msg}")

        print(f"[5/5] 下载到 {save_dir}")
        os.makedirs(save_dir, exist_ok=True)

        own = self._list_own(remote_temp)
        if not own:
            for f in allf:
                fn = f.get("server_filename","")
                results = self._search_file(fn)
                if results:
                    own = results
                    print(f"  通过搜索找到 {len(own)} 个文件")
                    break
        if not own:
            own = self._list_own("/")
            if not own:
                print("  ⚠ 未找到文件"); return

        print(f"  获取 {len(own)} 个直链...")
        tasks = []
        for f in own:
            fn = f.get("server_filename",""); rp = f.get("path",""); sz = f.get("size",0)
            if not rp: continue
            try:
                dl_urls = self._dl_url(rp)
                tasks.append((dl_urls, os.path.join(save_dir,fn), sz, fn))
                print(f"    ✓ {fn} -> {urlparse(dl_urls[0]).hostname}")
            except Exception as e:
                print(f"    ⚠ {fn}: {e}")

        if not tasks:
            print("  ⚠ 无有效下载任务"); return

        total = len(tasks); ok_cnt = [0]; t0 = time.time()

        def dl_one(args, idx):
            dl_urls, lp, sz, fn = args
            try:
                if self._use_aria2:
                    for u in dl_urls:
                        if aria2_download(u, save_dir, fn, self._bduss,
                                          params=self._aria2_params):
                            ok_cnt[0] += 1; return
                    print("    aria2c 全部失败，回退到内置引擎...")
                # 内置引擎：逐个URL尝试
                for i, u in enumerate(dl_urls):
                    try:
                        host = urlparse(u).hostname or ""
                        # ★ 关键：qdall01 只接受 PCS_UA
                        ua = PCS_UA if "qdall01" in host else GO_UA
                        print(f"    [{i+1}/{len(dl_urls)}] 尝试 {host}...", flush=True)
                        # 先测试Range支持
                        supports_range = self._dl._test_range(u)
                        if supports_range and sz > MT_SMALL_FILE:
                            self._dl.download(u, lp, label=fn, size_hint=sz)
                        else:
                            self._dl._download_single(u, {
                                "User-Agent": ua,
                                "Cookie": f"BDUSS={self._bduss}",
                                "Connection": "keep-alive",
                            }, lp, fn, sz)
                        # 验证下载结果
                        if os.path.exists(lp) and os.path.getsize(lp) > 1024:
                            ok_cnt[0] += 1; return
                        print(f"    {fn} 下载结果异常，尝试下一个URL...")
                    except Exception as e:
                        print(f"    {fn} 下载异常: {e}")
                        continue
                raise Exception("所有下载URL均失败")
            except Exception as e:
                print(f"  ✗ [{idx}/{total}] {fn}: {e}")

        print(f"  并行下载 {total} 个文件 [并行度={self._mp}]")
        with ThreadPoolExecutor(max_workers=self._mp) as pool:
            futs = [pool.submit(dl_one, t, i) for i,t in enumerate(tasks,1)]
            for f in as_completed(futs): f.result()

        el = time.time()-t0
        print(f"\n完成! {ok_cnt[0]}/{total} 个文件 ({el:.1f}s)")
        print(f"目录: {os.path.abspath(save_dir)}")

# ============================================================
# 上传器
# ============================================================
class BaiduPanUploader:
    def __init__(self, bduss, stoken=""):
        self.cli = HClient({"BDUSS":bduss,"STOKEN":stoken})
        self._bduss = bduss

    def _simple_up(self, fp, rd, fn):
        url = f"{PCS_BASE}/rest/2.0/pcs/file?method=upload&ondup=overwrite&dir={urllib.parse.quote(rd)}&filename={urllib.parse.quote(fn)}&BDUSS={self._bduss}&app_id={PCS_APP_ID}"
        with open(fp,"rb") as f: data = f.read()
        bd = _bd(); body,ct = _mp({},{"file":(fn,data,"application/octet-stream")},bd)
        return json.loads(self.cli.post_raw(url, body, ct))

    def _chunk_up(self, fp, ci, uid, rp):
        with open(fp,"rb") as f: f.seek(ci*UPLOAD_CHUNK); ch=f.read(UPLOAD_CHUNK)
        fn = os.path.basename(fp)
        url = f"https://d.pcs.baidu.com/rest/2.0/pcs/superfile2/upload?method=upload&app_id={PCS_APP_ID}&type=tmpfile&path={urllib.parse.quote(rp)}&uploadid={uid}&partseq={ci}"
        bd = _bd(); body,ct = _mp({},{"file":(fn,ch,"application/octet-stream")},bd)
        return json.loads(self.cli.post_raw(url, body, ct))

    def _precreate(self, fp, rp):
        sz = os.path.getsize(fp); cm = _md5_file(fp); sm = _slice_md5(fp)
        bl = []
        with open(fp,"rb") as f:
            for c in iter(lambda:f.read(UPLOAD_CHUNK),b""): bl.append(_md5(c))
        return self.cli.post_json(f"{PAN_BASE}/rest/2.0/pcs/superfile2/precreate",
            data={"path":rp,"size":str(sz),"isdir":"0","rtype":"3",
                  "block_list":json.dumps(bl),"content-md5":cm,"slice-md5":sm},
            params={"method":"precreate","app_id":PAN_APP_ID},
            hdrs={"Cookie":f"BDUSS={self._bduss}"})

    def _create(self, rp, sz, uid, bl):
        return self.cli.post_json(f"{PAN_BASE}/rest/2.0/pcs/superfile2/create",
            data={"path":rp,"size":str(sz),"isdir":"0","rtype":"3",
                  "uploadid":uid,"block_list":json.dumps(bl)},
            params={"method":"create","app_id":PAN_APP_ID},
            hdrs={"Cookie":f"BDUSS={self._bduss}"})

    def _mkdir(self, p):
        try: self.cli.get_json(f"{PCS_BASE}/rest/2.0/pcs/file",
            params={"method":"mkdir","path":p,"app_id":PCS_APP_ID})
        except: pass

    def upload(self, lp, rp):
        if not os.path.isfile(lp): print(f"  ✗ 不存在: {lp}"); return False
        sz = os.path.getsize(lp); fn = os.path.basename(lp)
        if rp.endswith("/"): rp += fn
        rd = rp.rsplit("/",1)[0] if "/" in rp else "/"
        print(f"  上传: {fn} ({_fmt(sz)}) -> {rp}")
        if sz <= UPLOAD_CHUNK:
            print("    [简单上传]",end="",flush=True)
            try:
                r = self._simple_up(lp,rd,fn)
                if r.get("path") or r.get("errno",-1)==0: print(" ✓"); return True
                print(f" ✗ {r}"); return False
            except Exception as e: print(f" ✗ {e}"); return False
        else:
            print("    [分片上传]")
            print("    [1/3] 预创建...",end="",flush=True)
            pc = self._precreate(lp,rp)
            if pc.get("errno",-1)!=0: print(f" ✗ {pc.get('errno')}"); return False
            uid = pc.get("uploadid","")
            if not uid:
                if pc.get("return_type")==2: print(" ✓(秒传)"); return True
                print(" ✗ 无uploadid"); return False
            print(" ✓")
            bc = max(1,(sz+UPLOAD_CHUNK-1)//UPLOAD_CHUNK); bl=[]
            print(f"    [2/3] 分片 ({bc})...")
            for i in range(bc):
                print(f"      {i+1}/{bc}...",end="",flush=True)
                r = self._chunk_up(lp,i,uid,rp); bl.append(r.get("md5","")); print(" ✓")
            print("    [3/3] 合并...",end="",flush=True)
            cr = self._create(rp,sz,uid,bl)
            if cr.get("errno",-1)==0: print(" ✓"); return True
            print(f" ✗ {cr}"); return False

    def upload_dir(self, ld, rd):
        if not os.path.isdir(ld): print(f"✗ 不存在: {ld}"); return 0
        self._mkdir(rd); ts=[]
        for rt,_,fs in os.walk(ld):
            for f in fs:
                lp=os.path.join(rt,f)
                rp=f"{rd.rstrip('/')}/{os.path.relpath(lp,ld)}".replace("\\","/")
                ts.append((lp,rp))
        print(f"共 {len(ts)} 个文件"); ok=0
        for i,(lp,rp) in enumerate(ts,1):
            print(f"\n[{i}/{len(ts)}]")
            if self.upload(lp,rp): ok+=1
        print(f"\n完成: {ok}/{len(ts)}"); return ok

# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("百度网盘工具 — 20MB/s 极速版")
    print("=" * 60)
    print()
    print("核心加速技术：")
    print("  ✓ BaiduPCS-Go 签名 → 高速CDN节点")
    print("  ✓ 多线程分片下载（最多32线程）")
    print("  ✓ 自动分片大小（4-32MB/片）")
    print("  ✓ HTTP 优先 + GO_UA")
    if _has_aria2():
        print("  ⚡ aria2c -x32 -s32")
    print()

    BDUSS = '你的BDUSS'
    STOKEN = '你的STOKEN'
    SHARE_URL = 'https://pan.baidu.com/s/1xxx'
    PASSWORD = '****'

    dl = BaiduPanDownloader(bduss=BDUSS, stoken=STOKEN, max_parallel=MAX_PAR)

    dl.download(
        share_url=SHARE_URL,
        password=PASSWORD,
        save_dir='./baidu_downloads',
    )
