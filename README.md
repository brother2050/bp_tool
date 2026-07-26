# BaiduPCS-Py - 百度网盘 Python 客户端

基于 [BaiduPCS-Go](https://github.com/qjfoidnh/BaiduPCS-Go) 的 API 逻辑，纯 Python 实现。

## 功能

- ✅ 登录认证 (BDUSS + STOKEN)
- ✅ 文件列表 (ls)
- ✅ 文件上传 (upload) - 分片上传 + 秒传检测
- ✅ 文件下载 (download) - 断点续传
- ✅ 创建目录 / 删除 / 重命名
- ✅ 分享链接转存
- ✅ 用户信息 / 容量查询

## 依赖

```bash
pip install requests
```

## 使用

```bash
export BDUSS="你的BDUSS"
export STOKEN="***"

python baidupcs.py info
python baidupcs.py ls /
python baidupcs.py upload ./file.txt /
python baidupcs.py download /file.txt ./
python baidupcs.py share "https://pan.baidu.com/s/1xxx" -p z5x4
python baidupcs.py mkdir /newdir
python baidupcs.py delete /file.txt
python baidupcs.py rename /old.txt new.txt
```

### Python API

```python
from baidupcs import BaiduPCS

pcs = BaiduPCS("your_bduss", "your_stoken")
files = pcs.list_files("/")
pcs.upload("./file.txt", "/backup/")
pcs.download("/remote.txt", "./local/")
```
