"""
领域事件定义（frozen dataclass）
覆盖签到、凭证、授权、账户生命周期全流程。
"""

from dataclasses import dataclass, field
from typing import Optional
from .enums import ErrorType
from .models import TaskResult


@dataclass(frozen=True)
class SignCompleted:
    account_id: str
    result: TaskResult
    timestamp: str = ""

@dataclass(frozen=True)
class SignFailed:
    account_id: str
    error: str
    error_type: ErrorType = ErrorType.INTERNAL
    retry_count: int = 0
    timestamp: str = ""

@dataclass(frozen=True)
class CredentialExpired:
    account_id: str
    reason: str
    expired_at: str = ""

@dataclass(frozen=True)
class CredentialRefreshed:
    account_id: str
    old_token_hash: str = ""
    refreshed_at: str = ""

@dataclass(frozen=True)
class CredentialRefreshFailed:
    account_id: str
    reason: str
    retry_count: int = 0

@dataclass(frozen=True)
class GrantCodeAcquired:
    account_id: str
    acquired_at: str = ""

@dataclass(frozen=True)
class GrantCodeFailed:
    account_id: str
    reason: str
    error_type: ErrorType = ErrorType.AUTH

@dataclass(frozen=True)
class AccountBound:
    account_id: str
    game_info: str = ""
    timestamp: str = ""

@dataclass(frozen=True)
class AccountUnbound:
    account_id: str
    timestamp: str = ""

@dataclass(frozen=True)
class NotificationSent:
    account_id: str
    target: str = ""
    success: bool = True
    error: Optional[str] = None
