# bp_downloader — 统一多引擎下载管理器

插件化架构，集成 10 个下载引擎，配置驱动，智能路由，一个命令调用所有下载工具。

## 特性

- **10 个引擎插件**：aria2c / wget / curl / yt-dlp / rclone / megatools / urllib / requests / httpx / transmission
- **插件化**：`@EngineRegistry.register` 装饰器自动注册，新增引擎只需一个文件
- **操作系统感知**：自动检测平台兼容性，不支持的引擎明确标记，附安装提示
- **智能路由**：URL 模式匹配自动选择引擎（YouTube → yt-dlp，magnet → aria2c）
- **回退链**：首选引擎失败自动尝试下一个，直到成功或全部尝试
- **配置驱动**：YAML/JSON 配置文件 + 环境变量 `BP_DL_*` 覆盖
- **并发批量**：多线程并发下载，可控制并发数
- **零依赖可用**：Python 标准库 urllib 引擎始终可用，无需安装任何第三方包

## 引擎矩阵

| 引擎 | 平台 | 能力 | 安装 |
|------|------|------|------|
| **aria2c** | 全平台 | HTTP / FTP / Metalink / Torrent / Magnet / 多连接 / 断点续传 / 限速 / 代理 | `apt install aria2` |
| **wget** | 全平台 | HTTP / FTP / 断点续传 / 限速 / 代理 | `apt install wget` |
| **curl** | 全平台 | HTTP / FTP / 断点续传 / 限速 / 代理 | `apt install curl` |
| **yt-dlp** | 全平台 | 视频平台 (YouTube/B站/Twitter 等 1000+) / 断点续传 / 限速 | `pip install yt-dlp` |
| **rclone** | 全平台 | 云存储 (Google Drive/OneDrive/S3/Dropbox 等 40+) / 并行 | `curl https://rclone.org/install.sh \| sudo bash` |
| **megatools** | Linux/macOS | Mega.nz 下载 / 断点续传 / 代理 | `apt install megatools` |
| **transmission** | Linux/macOS | BitTorrent / Magnet / 断点续传 / 限速 | `apt install transmission-cli` |
| **urllib** | 全平台 | HTTP / FTP / 代理 | 无需安装 (Python 标准库) |
| **requests** | 全平台 | HTTP / 断点续传 / 代理 | `pip install requests` |
| **httpx** | 全平台 | HTTP/2 / 断点续传 / 代理 | `pip install httpx[http2]` |

### 能力对照

| 能力 | aria2c | wget | curl | yt-dlp | rclone | megatools | transmission | urllib | requests | httpx |
|------|:------:|:----:|:----:|:------:|:------:|:---------:|:------------:|:------:|:--------:|:-----:|
| HTTP | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| FTP | ✓ | ✓ | ✓ | | | | | ✓ | | |
| Torrent | ✓ | | | | | | ✓ | | | |
| Magnet | ✓ | | | | | | ✓ | | | |
| 多连接 | ✓ | | | | | | | | | |
| 断点续传 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ |
| 限速 | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ | | | |
| 代理 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 视频提取 | | | | ✓ | | | | | | |
| 云存储 | | | | | ✓ | | | | | |
| Mega.nz | | | | | | ✓ | | | | |

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/brother2050/bp_tool.git
cd bp_tool

# 无需额外依赖，Python 3.8+ 即可运行
```

### 基本用法

```bash
# 查看引擎状态（自动检测可用性 + 平台兼容性 + 安装提示）
python3 -m bp_downloader engines

# 下载文件（自动选择引擎）
python3 -m bp_downloader download https://example.com/file.zip

# 指定引擎下载
python3 -m bp_downloader download https://example.com/file.zip -e aria2c

# 指定输出目录和文件名
python3 -m bp_downloader download https://example.com/file.zip -o ./downloads -O custom.zip

# 智能下载（自动识别 URL 类型选引擎）
python3 -m bp_downloader auto https://www.youtube.com/watch?v=abc
python3 -m bp_downloader auto "magnet:?xt=urn:btih:..."
python3 -m bp_downloader auto https://mega.nz/file/abc

# 批量下载（4 并发）
python3 -m bp_downloader batch https://a.com/1.zip https://b.com/2.zip -j 4

# 带配置文件
python3 -m bp_downloader -c config.yaml download https://example.com/file.zip
```

### CLI 别名

| 完整命令 | 别名 |
|----------|------|
| `download` | `dl` |
| `batch` | `b` |
| `auto` | `a` |
| `engines` | `e` |

### 下载参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `-o` / `--output-dir` | 输出目录 | `-o ./downloads` |
| `-O` / `--filename` | 指定文件名 | `-O file.zip` |
| `-e` / `--engine` | 指定引擎 | `-e aria2c` |
| `--no-fallback` | 禁用回退链 | |
| `--proxy` | 代理地址 | `--proxy http://127.0.0.1:7890` |
| `--speed-limit` | 限速 | `--speed-limit 1M` |
| `--connections` | 连接数 | `--connections 16` |
| `--timeout` | 超时秒数 | `--timeout 120` |
| `-H` / `--header` | 自定义请求头 | `-H "Authorization: Bearer xxx"` |
| `--user-agent` | User-Agent | `--user-agent "Custom/1.0"` |
| `--referer` | Referer | `--referer https://example.com` |
| `--cookies` | Cookie 字符串或文件 | `--cookies cookies.txt` |

## Python API

```python
from bp_downloader import UnifiedDownloader, DownloaderConfig

# 默认配置
dl = UnifiedDownloader()

# 单文件下载
result = dl.download(
    url="https://example.com/file.zip",
    output_dir="./downloads",
    engine="aria2c",         # 可选，不指定则自动选择
    connections=16,
    speed_limit="1M",
)
print(result.success, result.output_path, result.speed_human)

# 智能下载（自动识别 URL 类型）
result = dl.auto_download("https://www.youtube.com/watch?v=abc")

# 批量下载
results = dl.download_batch(
    urls=["https://a.com/1.zip", "https://b.com/2.zip"],
    max_workers=4,
)

# 查看引擎状态
for name, info in dl.list_engines().items():
    print(f"{name}: {'✓' if info['available'] else '✗'} {info['install_hint']}")
```

## 配置

### 配置文件

```bash
# 复制示例
cp bp_downloader/config.example.yaml config.yaml
# 编辑后使用
python3 -m bp_downloader -c config.yaml engines
```

### 配置结构

```yaml
# 默认引擎 (null = 自动选择)
default_engine: null

# 失败回退链
fallback_engines:
  - aria2c
  - curl
  - wget
  - urllib

# 默认输出目录
output_dir: ./downloads

# 最大并发下载数
max_concurrent: 3

# 全局超时(秒)
timeout: 60

# 全局限速 (如 "1M", "500K")
speed_limit: null

# 全局代理
proxy: null

# 全局 User-Agent
user_agent: null

# 引擎配置
engines:
  aria2c:
    enabled: true
    priority: 10          # 越小越优先
    max_connections: 16
    timeout: 120
  yt_dlp:
    enabled: true
    priority: 5
    custom:
      format: "best"
  megatools:
    enabled: false        # 禁用某引擎

# 路由规则 (按顺序匹配)
route_rules:
  - pattern: "*.youtube.com"
    engine: yt_dlp
  - pattern: "magnet:*"
    engine: aria2c
  - pattern: "*.mega.nz"
    engine: megatools
```

### 环境变量覆盖

所有配置项可通过 `BP_DL_` 前缀环境变量覆盖：

```bash
export BP_DL_OUTPUT_DIR=/tmp/downloads
export BP_DL_MAX_CONCURRENT=8
export BP_DL_TIMEOUT=300
export BP_DL_PROXY=http://127.0.0.1:7890
```

### 智能路由规则

`auto_download` 自动识别 URL 类型：

| URL 模式 | 选择引擎 |
|----------|----------|
| YouTube / B站 / Twitter / TikTok 等视频平台 | yt-dlp |
| `magnet:*` / `*.torrent` | aria2c → transmission |
| `*.mega.nz` | megatools |
| `remote:path` (rclone 格式) | rclone |
| 其他 HTTP/FTP | 按优先级自动选择 |

## 项目结构

```
bp_downloader/
├── __init__.py              # 包入口，导出核心类
├── __main__.py              # python -m bp_downloader 入口
├── base.py                  # 引擎抽象基类 + 数据模型
│                            #   DownloadRequest / DownloadResult
│                            #   EngineCapability 枚举
│                            #   current_os() / platforms / install_hint
├── registry.py              # 引擎注册表 + 自动发现
│                            #   @EngineRegistry.register 装饰器
│                            #   discover_engines() 自动导入
├── config.py                # 配置系统
│                            #   YAML/JSON/字典/环境变量 四层配置
├── downloader.py            # 统一下载管理器
│                            #   路由 / 重试 / 回退 / 并发 / auto_download
├── utils.py                 # 工具函数
│                            #   run_command / check_command / infer_filename
│                            #   match_pattern / parse_speed_limit
├── cli.py                   # CLI 入口 (download/batch/auto/engines)
├── config.example.yaml      # 配置模板
└── engines/                 # 引擎插件目录
    ├── __init__.py          # 自动导入所有引擎模块
    ├── aria2c_engine.py     # aria2c — 多连接/Torrent/Magnet
    ├── wget_engine.py       # GNU Wget — 经典 HTTP/FTP
    ├── curl_engine.py       # cURL — 万能协议
    ├── ytdlp_engine.py      # yt-dlp — 视频平台
    ├── rclone_engine.py     # rclone — 云存储
    ├── megatools_engine.py  # megatools — Mega.nz
    ├── transmission_engine.py # Transmission — BitTorrent
    ├── urllib_engine.py     # Python urllib — 零依赖
    ├── requests_engine.py   # Python requests
    └── httpx_engine.py      # httpx — HTTP/2
```

## 开发

### 测试

```bash
# 运行全部测试
python3 -m pytest tests/ -v

# 测试覆盖模块
python3 -m pytest tests/test_base.py       # 数据模型
python3 -m pytest tests/test_registry.py   # 注册表
python3 -m pytest tests/test_config.py     # 配置系统
python3 -m pytest tests/test_downloader.py # 管理器
python3 -m pytest tests/test_engines.py    # 10 个引擎
python3 -m pytest tests/test_cli.py        # CLI
```

### 新增引擎

只需 3 步：

```python
# 1. 创建 engines/my_engine.py
from ..base import DownloadEngine, DownloadRequest, DownloadResult, EngineCapability, current_os
from ..registry import EngineRegistry

@EngineRegistry.register
class MyEngine(DownloadEngine):
    @property
    def name(self) -> str:
        return "my_engine"

    @property
    def display_name(self) -> str:
        return "My Engine"

    @property
    def capabilities(self):
        return [EngineCapability.HTTP, EngineCapability.RESUME]

    @property
    def platforms(self):
        return ["linux", "darwin"]  # 空列表 = 全平台

    @property
    def install_hint(self):
        return "apt install my-engine"

    def is_available(self):
        if not self.is_platform_compatible():
            return False
        return check_command("my-engine")

    def download(self, request: DownloadRequest) -> DownloadResult:
        # 实现下载逻辑
        ...

# 2. 自动注册 — engines/__init__.py 会自动导入
# 3. 运行测试验证
```

## 依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.8+ | ✓ | 运行环境 |
| aria2c | 可选 | 高性能多连接下载 |
| wget | 可选 | 经典下载器 |
| curl | 可选 | 万能协议支持 |
| yt-dlp | 可选 | 视频平台下载 |
| rclone | 可选 | 云存储同步 |
| megatools | 可选 | Mega.nz 下载 |
| transmission-cli | 可选 | BitTorrent 下载 |
| requests | 可选 | Python HTTP 库 |
| httpx | 可选 | 现代 HTTP/2 库 |
