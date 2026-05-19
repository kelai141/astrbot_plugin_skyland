"""
北京时间工具模块

森空岛签到插件的所有用户在中国，鹰角服务器在中国（UTC+8）。
无论 AstrBot 部署在哪个时区，所有时间计算必须以北京时间为准。
"""
from datetime import datetime, date, timezone, timedelta

# 北京时间 = UTC + 8
_BEIJING_OFFSET = timedelta(hours=8)
BEIJING_TZ = timezone(_BEIJING_OFFSET)


def beijing_now() -> datetime:
    """返回带时区信息的北京时间 now

    用法: 替换所有 datetime.now()
    """
    return datetime.now(BEIJING_TZ)


def beijing_today() -> date:
    """返回北京时间今天的日期

    用法: 替换所有 date.today()
    """
    return beijing_now().date()


def beijing_iso() -> str:
    """返回北京时间 ISO 格式时间戳"""
    return beijing_now().isoformat()
