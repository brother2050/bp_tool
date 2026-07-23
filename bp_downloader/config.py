"""
配置系统：支持 YAML/JSON 文件 + 字典覆盖 + 环境变量。

层级优先级：环境变量 > 代码覆盖 > 配置文件 > 默认值
"""

import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class EngineConfig:
    """单个引擎的配置"""
    enabled: bool = True                        # 是否启用
    priority: int = 50                          # 优先级 (越小越优先)
    max_connections: int = 0                    # 最大连接数 (0=默认)
    timeout: int = 60                           # 超时秒数
    max_retries: int = 3                        # 最大重试
    extra_args: List[str] = field(default_factory=list)  # 额外命令行参数
    env: Dict[str, str] = field(default_factory=dict)    # 环境变量
    custom: Dict[str, Any] = field(default_factory=dict) # 引擎特定配置


@dataclass
class DownloaderConfig:
    """全局下载器配置"""

    # 默认下载设置
    default_engine: Optional[str] = None        # 默认引擎 (None=自动选择)
    fallback_engines: List[str] = field(default_factory=list)  # 回退引擎链
    output_dir: str = "./downloads"             # 默认输出目录
    max_concurrent: int = 3                     # 最大并发下载数
    timeout: int = 60                           # 全局超时
    max_retries: int = 3                        # 全局最大重试
    retry_delay: float = 1.0                    # 重试延迟(秒)
    speed_limit: Optional[str] = None           # 全局限速
    proxy: Optional[str] = None                 # 全局代理
    user_agent: Optional[str] = None            # 全局 User-Agent

    # 引擎配置
    engines: Dict[str, EngineConfig] = field(default_factory=dict)

    # 路由规则
    route_rules: List[Dict[str, Any]] = field(default_factory=list)
    # 示例:
    # [{"pattern": "*.youtube.com|*.bilibili.com", "engine": "yt_dlp"},
    #  {"pattern": "magnet:*", "engine": "aria2c"},
    #  {"pattern": "*.mega.nz", "engine": "megatools"}]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DownloaderConfig":
        """从字典创建配置"""
        config = cls()
        # 顶层字段
        for key in ("default_engine", "output_dir", "max_concurrent",
                     "timeout", "max_retries", "retry_delay", "speed_limit",
                     "proxy", "user_agent"):
            if key in data:
                setattr(config, key, data[key])
        if "fallback_engines" in data:
            config.fallback_engines = list(data["fallback_engines"])
        # 引擎配置
        for eng_name, eng_data in data.get("engines", {}).items():
            if isinstance(eng_data, dict):
                ec = EngineConfig()
                for k, v in eng_data.items():
                    if hasattr(ec, k):
                        setattr(ec, k, v)
                config.engines[eng_name] = ec
            elif isinstance(eng_data, bool):
                config.engines[eng_name] = EngineConfig(enabled=eng_data)
        # 路由规则
        config.route_rules = data.get("route_rules", [])
        # 环境变量覆盖
        env_prefix = "BP_DL_"
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                attr = key[len(env_prefix):].lower()
                if hasattr(config, attr):
                    current = getattr(config, attr)
                    if isinstance(current, int):
                        setattr(config, attr, int(value))
                    elif isinstance(current, float):
                        setattr(config, attr, float(value))
                    elif isinstance(current, bool):
                        setattr(config, attr, value.lower() in ("1", "true", "yes"))
                    else:
                        setattr(config, attr, value)
        return config

    @classmethod
    def from_file(cls, path: str) -> "DownloaderConfig":
        """从文件加载配置 (JSON 或 YAML)"""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if path.endswith((".yml", ".yaml")):
            try:
                import yaml
                data = yaml.safe_load(content)
            except ImportError:
                raise ImportError("PyYAML not installed. Use JSON or: pip install pyyaml")
        else:
            data = json.loads(content)

        if not isinstance(data, dict):
            raise ValueError(f"Config file must be a dict, got {type(data).__name__}")
        return cls.from_dict(data)

    def get_engine_config(self, engine_name: str) -> EngineConfig:
        """获取引擎配置，不存在则返回默认"""
        return self.engines.get(engine_name, EngineConfig())

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        result = {}
        for key in ("default_engine", "output_dir", "max_concurrent",
                     "timeout", "max_retries", "retry_delay", "speed_limit",
                     "proxy", "user_agent", "fallback_engines"):
            val = getattr(self, key)
            if val is not None:
                result[key] = val
        if self.engines:
            result["engines"] = {}
            for name, ec in self.engines.items():
                result["engines"][name] = {
                    "enabled": ec.enabled,
                    "priority": ec.priority,
                    "max_connections": ec.max_connections,
                    "timeout": ec.timeout,
                    "max_retries": ec.max_retries,
                }
                if ec.extra_args:
                    result["engines"][name]["extra_args"] = ec.extra_args
                if ec.custom:
                    result["engines"][name]["custom"] = ec.custom
        if self.route_rules:
            result["route_rules"] = self.route_rules
        return result

    def save(self, path: str):
        """保存配置到文件"""
        data = self.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            if path.endswith((".yml", ".yaml")):
                try:
                    import yaml
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
                except ImportError:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)
