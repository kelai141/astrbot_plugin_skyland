"""
基础设施兼容层 — 适配 AstrBot 不同版本 API
"""
from typing import Optional
from pathlib import Path


def get_plugin_data_dir() -> Path:
    """获取插件数据目录，兼容 AstrBot 4.x 不同版本"""
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        data_path = Path(get_astrbot_data_path())
    except (ImportError, Exception):
        data_path = Path("data")

    plugin_dir = data_path / "plugin_data" / "astrbot_plugin_skyland"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    return plugin_dir


def get_astrbot_version() -> str:
    """获取 AstrBot 版本号"""
    try:
        from astrbot import __version__
        return __version__
    except (ImportError, AttributeError):
        return "unknown"
