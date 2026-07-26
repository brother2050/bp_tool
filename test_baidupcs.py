#!/usr/bin/env python3
"""BaiduPCS-Py 测试脚本"""

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baidupcs import BaiduPCS, format_size

BDUSS = os.environ.get("BDUSS", "")
STOKEN = os.environ.get("STOKEN", "")

if not BDUSS:
    print("❌ 请设置环境变量 BDUSS 和 STOKEN")
    sys.exit(1)


def main():
    pcs = BaiduPCS(BDUSS, STOKEN, loglevel="info")

    # 用户信息
    info = pcs.user_info()
    u = info["records"][0]
    print(f"✅ 用户: {u['uname']} (VIP: {u['vip_level']})")
    q = pcs.quota()
    print(f"✅ 配额: {format_size(q.get('used', 0))} / {format_size(q.get('total', 0))}")

    # 文件列表
    files = pcs.list_files("/")
    print(f"✅ 根目录: {len(files)} 个")
    for f in files[:5]:
        t = "📁" if f.get("isdir") else "📄"
        print(f"   {t} {f.get('server_filename', '?')}")

    # 上传测试
    test_data = os.urandom(100 * 1024)
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False, prefix="test_") as f:
        f.write(test_data)
        test_file = f.name

    try:
        print("\n--- 上传测试 ---")
        start = time.monotonic()
        pcs.upload(test_file, "/apps/baidupcs_py_test/")
        print(f"耗时: {time.monotonic() - start:.2f}s")

        print("\n--- 下载测试 ---")
        with tempfile.TemporaryDirectory() as tmpdir:
            start = time.monotonic()
            pcs.download("/apps/baidupcs_py_test/" + os.path.basename(test_file), tmpdir)
            print(f"耗时: {time.monotonic() - start:.2f}s")
    finally:
        os.unlink(test_file)

    print("\n✅ 测试完成!")


if __name__ == "__main__":
    main()
