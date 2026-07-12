"""
领域枚举定义

纯业务语义的枚举类型，不依赖任何框架或基础设施。
"""

from enum import Enum, auto


class ResultType(str, Enum):
    """签到结果类型（替换 Emoji 前缀匹配，修复 M-B8）"""
    SUCCESS = "success"
    PARTIAL = "partial"
    ALL_ALREADY = "all_already"
    FAILED_FATAL = "failed_fatal"

    @property
    def is_ok(self) -> bool:
        return self in (ResultType.SUCCESS, ResultType.ALL_ALREADY)

    @property
    def is_terminal(self) -> bool:
        return self in (ResultType.SUCCESS, ResultType.ALL_ALREADY, ResultType.FAILED_FATAL)


class ScheduleState(str, Enum):
    """签到调度状态机状态"""
    IDLE = "idle"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED_FATAL = "failed_fatal"
    TIMEOUT = "timeout"
    BACKOFF = "backoff"


class ErrorType(str, Enum):
    """错误类型分类"""
    NETWORK = "network"
    AUTH = "auth"
    BUSINESS = "business"
    TIMEOUT = "timeout"
    INTERNAL = "internal"
    RATE_LIMIT = "rate_limit"


class DidSource(str, Enum):
    """设备指纹来源"""
    API = "api"
    CACHE = "cache"
    FALLBACK = "fallback"
