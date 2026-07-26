#!/usr/bin/env python3
"""
BaiduPCS-Py 测试脚本
测试基本功能: 用户信息、文件列表、上传、下载、限速
"""

import os
import sys
import time
import tempfile

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from baidupcs import BaiduPCS, parse_speed, format_size, format_speed, SpeedLimiter

# ============================================================
# 配置 (从环境变量读取)
# ============================================================
BDUSS = os.environ.get("BDUSS", "")
STOKEN = os.environ.get("STOKEN", "")

if not BDUSS:
    print("❌ 请设置环境变量 BDUSS 和 STOKEN")
    print("   export BDUSS='your_bduss'")
    print("   export STOKEN='your_stoken'")
    sys.exit(1)


def test_speed_limiter():
    """测试限速器"""
    print("\n" + "=" * 50)
    print("🧪 测试限速器")
    print("=" * 50)

    for speed_str in ["1M", "10M", "20M"]:
        speed = parse_speed(speed_str)
        limiter = SpeedLimiter(speed)
        data = b"x" * (1024 * 1024)  # 1MB

        start = time.monotonic()
        for _ in range(5):  # 5MB
            limiter.consume(len(data))
        elapsed = time.monotonic() - start

        actual_speed = 5 * 1024 * 1024 / elapsed
        print(f"  限速 {speed_str}/s → 实际 {format_speed(actual_speed)} (耗时 {elapsed:.2f}s)")

    print("✅ 限速器测试通过")


def test_user_info(pcs: BaiduPCS):
    """测试用户信息"""
    print("\n" + "=" * 50)
    print("🧪 测试用户信息")
    print("=" * 50)

    try:
        info = pcs.user_info()
        records = info.get("records", [{}])
        if records:
            u = records[0]
            print(f"  用户名: {u.get('username', '?')}")
            print(f"  VIP类型: {u.get('vip_type', 0)}")
            print(f"  UID: {u.get('uk', '?')}")

        q = pcs.quota()
        used = q.get("used", 0)
        total = q.get("total", 0)
        print(f"  容量: {format_size(used)} / {format_size(total)}")
        print("✅ 用户信息获取成功")
    except Exception as e:
        print(f"❌ 用户信息获取失败: {e}")


def test_list_files(pcs: BaiduPCS, path: str = "/"):
    """测试文件列表"""
    print("\n" + "=" * 50)
    print(f"🧪 测试文件列表: {path}")
    print("=" * 50)

    try:
        files = pcs.list_files(path)
        print(f"  共 {len(files)} 个文件/目录")
        for f in files[:10]:
            is_dir = f.get("isdir", 0)
            ftype = "📁" if is_dir else "📄"
            size = format_size(f.get("size", 0)) if not is_dir else "<DIR>"
            name = f.get("server_filename", "?")
            print(f"  {ftype} {name} ({size})")
        if len(files) > 10:
            print(f"  ... 还有 {len(files) - 10} 个")
        print("✅ 文件列表获取成功")
        return files
    except Exception as e:
        print(f"❌ 文件列表获取失败: {e}")
        return []


def test_upload(pcs: BaiduPCS, speed_str: str = "0"):
    """测试上传"""
    print("\n" + "=" * 50)
    print(f"🧪 测试上传 (限速: {speed_str or '不限'})")
    print("=" * 50)

    # 创建测试文件
    test_content = b"Hello BaiduPCS-Py! " * 1000  # ~19KB
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False, prefix="baidupcs_test_") as f:
        f.write(test_content)
        test_file = f.name

    try:
        speed = parse_speed(speed_str)
        start = time.monotonic()
        pcs.upload(test_file, "/apps/baidupcs_py_test/", speed_limit=speed)
        elapsed = time.monotonic() - start
        print(f"  耗时: {elapsed:.2f}s")
    except Exception as e:
        print(f"❌ 上传失败: {e}")
    finally:
        os.unlink(test_file)


def test_download(pcs: BaiduPCS, remote_path: str, speed_str: str = "0"):
    """测试下载"""
    print("\n" + "=" * 50)
    print(f"🧪 测试下载: {remote_path} (限速: {speed_str or '不限'})")
    print("=" * 50)

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            speed = parse_speed(speed_str)
            start = time.monotonic()
            pcs.download(remote_path, tmpdir, speed_limit=speed)
            elapsed = time.monotonic() - start
            print(f"  耗时: {elapsed:.2f}s")
        except Exception as e:
            print(f"❌ 下载失败: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="BaiduPCS-Py 测试")
    parser.add_argument("--bduss", default=BDUSS)
    parser.add_argument("--stoken", default=STOKEN)
    parser.add_argument("--test", default="all",
                        choices=["all", "speed", "info", "ls", "upload", "download"])
    parser.add_argument("--speed", default="0", help="速度限制 (1M, 10M, 20M)")
    parser.add_argument("--remote", default="", help="下载的远程文件路径")
    args = parser.parse_args()

    pcs = BaiduPCS(args.bduss, args.stoken, loglevel="info")

    if args.test in ("all", "speed"):
        test_speed_limiter()

    if args.test in ("all", "info"):
        test_user_info(pcs)

    if args.test in ("all", "ls"):
        test_list_files(pcs)

    if args.test in ("all", "upload"):
        for speed in ["1M", "10M", "20M"]:
            test_upload(pcs, speed)

    if args.test in ("all", "download"):
        remote = args.remote or "/apps/baidupcs_py_test/baidupcs_test_*.txt"
        for speed in ["1M", "10M", "20M"]:
            test_download(pcs, remote, speed)


if __name__ == "__main__":
    main()
