#!/usr/bin/env python3
"""
bp_downloader CLI — 统一下载管理器命令行入口。

用法：
    python -m bp_downloader download <url> [options]
    python -m bp_downloader batch <url1> <url2> ... [options]
    python -m bp_downloader engines
    python -m bp_downloader auto <url>
"""

import argparse
import sys
import os
import json

from .config import DownloaderConfig
from .downloader import UnifiedDownloader
from .base import DownloadRequest


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bp_downloader",
        description="统一多引擎下载管理器",
    )
    parser.add_argument(
        "-c", "--config",
        help="配置文件路径 (JSON/YAML)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细输出",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # download 子命令
    dl_parser = subparsers.add_parser("download", aliases=["dl"], help="下载文件")
    dl_parser.add_argument("url", help="下载 URL")
    dl_parser.add_argument("-o", "--output-dir", help="输出目录")
    dl_parser.add_argument("-O", "--filename", help="指定文件名")
    dl_parser.add_argument("-e", "--engine", help="指定引擎")
    dl_parser.add_argument("--no-fallback", action="store_true", help="禁用回退")
    dl_parser.add_argument("--proxy", help="代理地址")
    dl_parser.add_argument("--speed-limit", help="限速 (如 1M, 500K)")
    dl_parser.add_argument("--connections", type=int, help="连接数")
    dl_parser.add_argument("--timeout", type=int, help="超时秒数")
    dl_parser.add_argument("--header", "-H", action="append", help="自定义请求头 (Key: Value)")
    dl_parser.add_argument("--user-agent", help="User-Agent")
    dl_parser.add_argument("--referer", help="Referer")
    dl_parser.add_argument("--cookies", help="Cookie 字符串或文件路径")

    # batch 子命令
    batch_parser = subparsers.add_parser("batch", aliases=["b"], help="批量下载")
    batch_parser.add_argument("urls", nargs="+", help="URL 列表")
    batch_parser.add_argument("-o", "--output-dir", help="输出目录")
    batch_parser.add_argument("-e", "--engine", help="指定引擎")
    batch_parser.add_argument("-j", "--jobs", type=int, help="并发数")
    batch_parser.add_argument("--proxy", help="代理地址")
    batch_parser.add_argument("--speed-limit", help="限速")

    # auto 子命令
    auto_parser = subparsers.add_parser("auto", aliases=["a"], help="智能下载（自动选择引擎）")
    auto_parser.add_argument("url", help="下载 URL")
    auto_parser.add_argument("-o", "--output-dir", help="输出目录")

    # engines 子命令
    eng_parser = subparsers.add_parser("engines", aliases=["e"], help="列出引擎状态")
    eng_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    return parser


def parse_headers(header_list) -> dict:
    """解析 -H 参数列表为 dict"""
    headers = {}
    if not header_list:
        return headers
    for h in header_list:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()
    return headers


def cmd_download(args, config):
    """执行单文件下载"""
    downloader = UnifiedDownloader(config)

    result = downloader.download(
        url=args.url,
        output_dir=args.output_dir,
        filename=args.filename,
        engine=args.engine,
        fallback=not args.no_fallback,
        headers=parse_headers(args.header),
        proxy=args.proxy,
        speed_limit=args.speed_limit,
        connections=args.connections or 0,
        timeout=args.timeout or 0,
        user_agent=args.user_agent,
        referer=args.referer,
        cookies=args.cookies,
    )

    _print_result(result, args.verbose)
    return 0 if result.success else 1


def cmd_batch(args, config):
    """执行批量下载"""
    downloader = UnifiedDownloader(config)

    results = downloader.download_batch(
        urls=args.urls,
        output_dir=args.output_dir,
        engine=args.engine,
        max_workers=args.jobs,
    )

    success = 0
    for r in results:
        _print_result(r, args.verbose)
        if r.success:
            success += 1

    print(f"\n{'='*50}")
    print(f"Total: {len(results)} | Success: {success} | Failed: {len(results) - success}")
    return 0 if success == len(results) else 1


def cmd_auto(args, config):
    """智能下载"""
    downloader = UnifiedDownloader(config)

    result = downloader.auto_download(
        url=args.url,
        output_dir=args.output_dir,
    )

    _print_result(result, args.verbose)
    return 0 if result.success else 1


def cmd_engines(args, config):
    """列出引擎"""
    downloader = UnifiedDownloader(config)
    engines = downloader.list_engines()

    if args.json:
        print(json.dumps(engines, indent=2, ensure_ascii=False))
        return 0

    print(f"{'Engine':<20} {'Status':<12} {'Enabled':<10} {'Priority':<10} {'Capabilities'}")
    print("-" * 90)
    for name, info in sorted(engines.items()):
        status = "✓ available" if info["available"] else "✗ missing"
        enabled = "yes" if info["enabled"] else "no"
        caps = ", ".join(info["capabilities"][:4])
        if len(info["capabilities"]) > 4:
            caps += f" +{len(info['capabilities']) - 4}"
        print(f"{name:<20} {status:<12} {enabled:<10} {info['priority']:<10} {caps}")

    available = sum(1 for e in engines.values() if e["available"])
    print(f"\nTotal: {len(engines)} engines, {available} available")
    return 0


def _print_result(result, verbose=False):
    """打印下载结果"""
    status = "✓ SUCCESS" if result.success else "✗ FAILED"
    print(f"[{status}] {result.engine_name} → {result.url}")
    if result.success:
        print(f"  File: {result.output_path}")
        print(f"  Size: {result.size_human} | Speed: {result.speed_human} | Time: {result.elapsed:.1f}s")
    else:
        print(f"  Error: {result.error}")
    if verbose:
        if result.stdout:
            print(f"  stdout: {result.stdout[:500]}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    # 加载配置
    config = DownloaderConfig()
    if args.config:
        config = DownloaderConfig.from_file(args.config)

    commands = {
        "download": cmd_download,
        "dl": cmd_download,
        "batch": cmd_batch,
        "b": cmd_batch,
        "auto": cmd_auto,
        "a": cmd_auto,
        "engines": cmd_engines,
        "e": cmd_engines,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args, config)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
