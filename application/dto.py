"""
应用层数据传输对象
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from domain.enums import SignStatus, GamePlatform, NotificationPolicy


@dataclass
class SignInDTO:
    """签到输入"""
    user_id: str
    platform: str = "aiocqhttp"
    force: bool = False             # 强制签到（忽略是否已签）


@dataclass
class SignResultDTO:
    """签到结果"""
    user_id: str
    game: GamePlatform
    status: SignStatus
    reward: Optional[str] = None
    error_message: Optional[str] = None
    signed_at: datetime = field(default_factory=lambda: datetime.now().astimezone())


@dataclass
class BindDTO:
    """绑定输入"""
    user_id: str
    platform: str
    credential_value: str
    credential_type: str = "token"      # token 或 phone_session
    game: GamePlatform = GamePlatform.ARKNIENTS


@dataclass
class UserInfoDTO:
    """用户信息输出"""
    user_id: str
    platform: str
    game: str
    sign_time: str
    notification_policy: NotificationPolicy
    bound_at: Optional[str] = None
    last_sign_at: Optional[str] = None
    consecutive_days: int = 0
    total_signs: int = 0
    is_active: bool = True
    credential_masked: str = ""


@dataclass
class BatchSignResultDTO:
    """批量签到结果"""
    total: int
    success: int
    failed: int
    skipped: int
    details: list[SignResultDTO] = field(default_factory=list)
