# BaiduPCS-Py - 百度网盘 Python 客户端

基于 [BaiduPCS-Go](https://github.com/qjfoidnh/BaiduPCS-Go) 的 API 逻辑，纯 Python 实现。

## 功能

- ✅ 登录认证 (BDUSS + STOKEN)
- ✅ 文件列表 (ls)
- ✅ 文件上传 (upload) - 分片上传 + 秒传检测
- ✅ 文件下载 (download) - 断点续传
- ✅ 速度限制 (1M/s, 10M/s, 20M/s 等精确限速)
- ✅ 创建目录 / 删除 / 重命名
- ✅ 分享链接转存
- ✅ 用户信息 / 容量查询

## 依赖

```bash
pip install requests
```

## 使用

### 命令行

```bash
# 设置认证
export BDUSS="你的BDUSS"
export STOKEN="你的STOKEN"

# 查看信息
python baidupcs.py info

# 列出文件
python baidupcs.py ls /
python baidupcs.py ls /documents

# 上传 (支持限速)
python baidupcs.py upload ./file.txt /
python baidupcs.py upload ./file.txt / --speed 1M    # 限速 1M/s
python baidupcs.py upload ./file.txt / --speed 10M   # 限速 10M/s
python baidupcs.py upload ./file.txt / --speed 20M   # 限速 20M/s

# 下载 (支持限速)
python baidupcs.py download /file.txt ./
python baidupcs.py download /file.txt ./ --speed 1M  # 限速 1M/s

# 转存分享链接
python baidupcs.py share "https://pan.baidu.com/s/1xxx" --password abcd

# 创建目录
python baidupcs.py mkdir /newdir

# 删除 / 重命名
python baidupcs.py delete /file.txt
python baidupcs.py rename /old.txt new.txt
```

### 速度限制格式

| 格式 | 含义 |
|------|------|
| `1M` 或 `1M/s` | 1 MB/s |
| `10M` | 10 MB/s |
| `20M` | 20 MB/s |
| `512K` | 512 KB/s |
| `0` 或不填 | 不限速 |

### Python API

```python
from baidupcs import BaiduPCS

pcs = BaiduPCS("your_bduss", "your_stoken")

# 列出文件
files = pcs.list_files("/")

# 上传 (限速 10M/s)
pcs.upload("./file.txt", "/backup/", speed_limit=10*1024*1024)

# 下载 (限速 20M/s)
pcs.download("/remote.txt", "./local/", speed_limit=20*1024*1024)

# 转存分享链接
pcs.save_share("https://pan.baidu.com/s/1xxx", "password", "/save/dir")
```

## 测试

```bash
# 限速器精度测试
python speed_test.py

# 完整功能测试
python test_baidupcs.py
```

## 技术实现

### API 端点 (来自 BaiduPCS-Go 源码分析)

| 功能 | API |
|------|-----|
| 用户信息 | `GET pan.baidu.com/api/user/getinfo` |
| 文件列表 | `GET pan.baidu.com/api/list` |
| 预创建上传 | `POST pan.baidu.com/api/precreate` |
| 分片上传 | `POST pcs.baidu.com/rest/2.0/pcs/superfile2` |
| 合并文件 | `POST pan.baidu.com/api/create` |
| 获取下载链接 | `POST pcs.baidu.com/rest/2.0/pcs/file?method=locatedownload` |
| 删除文件 | `POST pan.baidu.com/api/filemanager` |

### 签名算法

- **locatedownload 签名**: `SHA1( SHA1(BDUSS).hex + UID + fixed_salt + timestamp + devUID )`
- **devUID**: `MD5(BDUSS)[:40]`
- **fixed_salt**: `ebrcUYiuxaZv2XGu7KIYKxUrqfnOpDF`

### 分片策略 (与 BaiduPCS-Go 一致)

| 文件大小 | 分片大小 |
|----------|----------|
| < 8GB | 4MB |
| 8GB - 32GB | 16MB |
| > 32GB | 64MB |

### 限速实现

令牌桶算法 (Token Bucket)，精度误差 < 1%。
