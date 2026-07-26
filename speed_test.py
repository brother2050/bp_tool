#!/usr/bin/env python3
"""
速度测试脚本 - 测试 1M/s, 10M/s, 20M/s 限速效果
"""

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baidupcs import BaiduPCS, SpeedLimiter, parse_speed, format_size, format_speed


def test_speed_limiter_accuracy():
    """精确测试限速器"""
    print("=" * 60)
    print("🎯 限速器精度测试")
    print("=" * 60)

    test_cases = [
        ("1M", 1 * 1024 * 1024),
        ("10M", 10 * 1024 * 1024),
        ("20M", 20 * 1024 * 1024),
    ]

    for speed_str, expected_bytes in test_cases:
        speed = parse_speed(speed_str)
        limiter = SpeedLimiter(speed)
        data = b"x" * 65536  # 64KB chunks

        total = 0
        start = time.monotonic()
        while total < expected_bytes * 3:  # 测试 3 秒
            limiter.consume(len(data))
            total += len(data)
        elapsed = time.monotonic() - start

        actual_speed = total / elapsed
        error = abs(actual_speed - speed) / speed * 100

        print(f"  {speed_str}/s:")
        print(f"    期望: {format_speed(speed)}")
        print(f"    实际: {format_speed(actual_speed)}")
        print(f"    误差: {error:.1f}%")
        print(f"    数据: {format_size(total)} / {elapsed:.2f}s")
        print()

    print("✅ 限速器测试完成\n")


def test_upload_download_speed(bduss: str, stoken: str):
    """测试实际上传下载速度"""
    print("=" * 60)
    print("📡 实际上传下载速度测试")
    print("=" * 60)

    pcs = BaiduPCS(bduss, stoken, loglevel="info")

    # 先检查用户信息
    try:
        info = pcs.user_info()
        print(f"用户: {info.get('records', [{}])[0].get('username', '?')}")
    except Exception as e:
        print(f"❌ 认证失败: {e}")
        return

    # 创建测试文件 (1MB)
    test_size = 1024 * 1024
    test_data = os.urandom(test_size)

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False, prefix="speed_test_") as f:
        f.write(test_data)
        test_file = f.name

    speed_tests = [
        ("不限速", "0"),
        ("1M/s", "1M"),
        ("10M/s", "10M"),
        ("20M/s", "20M"),
    ]

    try:
        for label, speed_str in speed_tests:
            print(f"\n--- 上传测试: {label} ---")
            speed = parse_speed(speed_str)
            start = time.monotonic()
            try:
                pcs.upload(test_file, "/apps/baidupcs_py_test/", speed_limit=speed)
                elapsed = time.monotonic() - start
                actual = test_size / elapsed if elapsed > 0 else 0
                print(f"  结果: {format_speed(actual)} (耗时 {elapsed:.2f}s)")
            except Exception as e:
                print(f"  上传失败: {e}")

        # 下载测试
        remote_path = "/apps/baidupcs_py_test/speed_test_.bin"
        for label, speed_str in speed_tests:
            print(f"\n--- 下载测试: {label} ---")
            speed = parse_speed(speed_str)
            with tempfile.TemporaryDirectory() as tmpdir:
                start = time.monotonic()
                try:
                    pcs.download(remote_path, tmpdir, speed_limit=speed)
                    elapsed = time.monotonic() - start
                    actual = test_size / elapsed if elapsed > 0 else 0
                    print(f"  结果: {format_speed(actual)} (耗时 {elapsed:.2f}s)")
                except Exception as e:
                    print(f"  下载失败: {e}")

    finally:
        os.unlink(test_file)

    print("\n✅ 速度测试完成")


def main():
    bduss = os.environ.get("BDUSS", "")
    stoken = os.environ.get("STOKEN", "")

    # 测试限速器精度 (不需要网络)
    test_speed_limiter_accuracy()

    # 如果有认证信息，测试实际速度
    if bduss:
        test_upload_download_speed(bduss, stoken)
    else:
        print("💡 设置 BDUSS 和 STOKEN 环境变量可测试实际上传下载速度")
        print("   export BDUSS='...'")
        print("   export STOKEN='...'")


if __name__ == "__main__":
    main()
