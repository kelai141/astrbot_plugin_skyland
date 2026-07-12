"""
领域模型定义

纯数据容器（dataclass），零业务方法，零框架依赖。
Account / Credential / TaskResult / SignSchedule / DeviceFinger / BindingInfo
"""

from dataclasses import dataclass, field
from typing import Optional

from .enums import ResultType, ScheduleState, ErrorType, DidSource


@dataclass(frozen=True)
class DeviceFinger:
    """设备指纹（值对象，不可变）"""
    did: str
    cached_at: Optional[str] = None  # ISO 格式
    source: DidSource = DidSource.FALLBACK

    def __bool__(self) -> bool:
        return bool(self.did) and self.did.startswith("B")


@dataclass(frozen=True)
class Credential:
    """用户凭证（不可变值对象）"""
    token: str = ""
    grant_code: Optional[str] = None
    cred: str = ""
    sign_token: str = ""
    refreshed_at: str = ""
    expires_at: str = ""
    grant_at: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not self.token

    @property
    def can_sign(self) -> bool:
        return bool(self.sign_token) and bool(self.cred)


@dataclass(frozen=True)
class TaskResult:
    """签到结果（不可变值对象）"""
    success: bool = True
    result_type: ResultType = ResultType.SUCCESS
    messages: list[str] = field(default_factory=list)
    signed_games: list[str] = field(default_factory=list)
    already_signed_games: list[str] = field(default_factory=list)
    failed_games: list[str] = field(default_factory=list)
    error: Optional[str] = None
    trace_id: str = ""
    timestamp: str = ""

    @property
    def is_all_already_signed(self) -> bool:
        return self.result_type == ResultType.ALL_ALREADY

    @property
    def is_partial(self) -> bool:
        return self.result_type == ResultType.PARTIAL


@dataclass(frozen=False)
class Account:
    """用户账户（领域实体，可变更）"""
    sender_id: str = ""
    game_info: str = ""
    push_enabled: bool = True
    sign_time: str = "09:05"
    bound_at: str = ""
    token_expired: bool = False
    credential: Credential = field(default_factory=Credential)


@dataclass(frozen=False)
class SignSchedule:
    """签到调度记录（领域实体）"""
    account_id: str = ""
    sign_time: str = "09:05"
    last_signed_at: Optional[str] = None
    last_trace_id: Optional[str] = None
    status: ScheduleState = ScheduleState.IDLE
    retry_count: int = 0
    max_retries: int = 2
    error_type: Optional[ErrorType] = None
    error_message: Optional[str] = None

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def mark_running(self):
        self.status = ScheduleState.RUNNING

    def mark_completed(self):
        self.status = ScheduleState.COMPLETED
        self.retry_count = 0

    def mark_timeout(self):
        self.status = ScheduleState.TIMEOUT
        self.error_type = ErrorType.TIMEOUT

    def mark_failed_fatal(self, error_type=ErrorType.AUTH, message=""):
        self.status = ScheduleState.FAILED_FATAL
        self.error_type = error_type
        self.error_message = message

    def increment_retry(self):
        self.retry_count += 1
        self.status = ScheduleState.BACKOFF


@dataclass(frozen=True)
class BindingInfo:
    """游戏绑定信息（值对象）"""
    app_code: str = ""
    game_name: str = ""
    game_id: Optional[str] = None
    uid: Optional[str] = None
    nick_name: str = ""
    channel_name: str = ""
    roles: list[dict] = field(default_factory=list)
