# 百度网盘下载/上传工具

纯 Python 标准库实现，支持 aria2c 加速，无第三方依赖。

## 功能

| 功能 | 说明 |
|------|------|
| 分享链接下载 | 支持密码、目录递归、自动转存 |
| 文件上传 | 小文件直传、大文件分片上传 |
| 目录上传 | 递归上传整个目录 |
| aria2c 加速 | 自动检测，64分块多连接下载 |
| 断点续传 | aria2c 自动续传 |

## 快速开始

```python
from baidu_pan import BaiduPanDownloader, BaiduPanUploader

# === 下载 ===
dl = BaiduPanDownloader(
    bduss='你的BDUSS',
    stoken='你的STOKEN',  # 可选
)
dl.download(
    share_url='https://pan.baidu.com/s/1xxx',
    password=***
    save_dir='./downloads',
)

# === 上传文件 ===
ul = BaiduPanUploader(bduss='你的BDUSS')
ul.upload('./myfile.zip', '/网盘路径/myfile.zip')

# === 上传目录 ===
ul.upload_dir('./mydir', '/网盘路径/mydir/')
```

## 速度优化

### 已实现的优化

| 优化项 | 效果 |
|--------|------|
| aria2c -x16 -s64 | 64分块并行，单文件 **9MB/s** |
| 多文件并行 | 4文件同时下载 = 4倍吞吐 |
| HTTP优先 | 减少TLS加密开销 |
| 持久连接 | Keep-Alive 避免重复握手 |
| 1MB大缓冲 | 减少系统调用次数 |
| PCS API直链 | 绕过网页层开销 |

### 速度对比

| 模式 | 单文件速度 | 4文件并行 |
|------|-----------|----------|
| 内置引擎（无aria2） | ~90KB/s | ~360KB/s |
| aria2c -x16 -s16 | ~200KB/s | ~800KB/s |
| **aria2c -x16 -s64** | **~9MB/s** | **~36MB/s** |

### 安装 aria2c（可选，推荐）

```bash
# Ubuntu/Debian
sudo apt install aria2

# macOS
brew install aria2

# Windows
scoop install aria2  # 或 choco install aria2
```

安装后程序自动检测并使用 aria2c 加速。

## 工作原理

### 下载流程

```
1. 验证分享密码 (share/verify)
2. 获取页面文件信息 (locals.mset)
3. 递归获取目录内文件 (share/list)
4. 转存到自己网盘 (share/transfer)
5. 获取直链 (locatedownload)
6. aria2c/内置引擎下载
```

### 上传流程

```
小文件 (<4MB): PCS API 直接上传
大文件 (≥4MB): 预创建 → 分片上传(4MB/片) → 合并
```

## 依赖

- Python 3.8+
- 无第三方依赖（纯标准库）
- aria2c（可选，推荐安装）

## 文件说明

```
baidu_pan.py          ← 主程序（唯一需要的文件）
README.md             ← 本文档
```

## 命令行使用

```bash
# 下载测试
python3 baidu_pan.py

# 上传文件
python3 baidu_pan.py upload ./file.zip /网盘路径/

# 上传目录
python3 baidu_pan.py upload_dir ./dir /网盘路径/
```

## 注意事项

1. **BDUSS/STOKEN 获取**：浏览器登录百度网盘 → F12 → Application → Cookies
2. **非VIP限速**：百度对非VIP用户有服务端限速，aria2c可部分缓解
3. **URL有效期**：下载直链有效期约8小时，超时需重新获取
4. **aria2c参数**：`-x16`（每服务器最大连接）`-s64`（分块数）可调整
