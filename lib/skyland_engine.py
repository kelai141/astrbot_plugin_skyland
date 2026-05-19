"""
森空岛签到引擎 — 纯净业务逻辑，与 AstrBot 框架完全解耦

职责：
- 用户凭证生命周期管理（绑定 → 验证 → 签到 → 刷新）
- 单用户/批量签到编排
- 结果聚合与格式化

不依赖 AstrBot 任何模块，可在任意 Python 环境中独立使用。
"""
import asyncio
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from .skyland_api import (
    SkylandApiClient,
    SkylandApiError,
    SkylandAuthError,
    parse_user_token,
)


# ==================== 数据模型 ====================

@dataclass
class UserCredential:
    """用户凭证"""
    token: str                     # 鹰角网络通行证
    cred: str = ''                 # 森空岛 cred
    sign_token: str = ''           # CRED_TOKEN（签名密钥）
    refreshed_at: str = ''         # 凭证刷新时间 (ISO format)
    expires_at: str = ''           # 凭证预估过期时间


@dataclass
class SignResult:
    """单次签到结果"""
    success: bool
    messages: list[str] = field(default_factory=list)
    signed_games: list[str] = field(default_factory=list)
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UserSignState:
    """用户签到状态"""
    sender_id: str
    credential: UserCredential
    game_info: str = ''            # 角色摘要
    last_sign_date: str = ''       # 上次签到日期
    last_sign_result: str = ''     # 上次签到结果文本
    push_enabled: bool = True      # 是否推送通知
    sign_time: str = '09:05'       # 用户签到时间 (HH:MM)
    bound_at: str = field(default_factory=lambda: datetime.now().isoformat())
    notify_target: str = ''        # 通知目标 (unified_msg_origin)


@dataclass
class EngineConfig:
    """引擎配置"""
    default_sign_time: str = '09:05'
    sign_interval_seconds: int = 2
    sign_retry_count: int = 2
    cred_refresh_window_hours: int = 24
    push_enabled_default: bool = True


# ==================== 签到引擎 ====================

class SkylandSignEngine:
    """森空岛签到引擎

    管理用户凭证、编排签到流程、处理结果。

    使用示例:
        engine = SkylandSignEngine(EngineConfig())
        await engine.initialize()

        # 绑定用户
        state = await engine.bind_user("user_001", token)

        # 签到
        result = await engine.sign("user_001", state)
    """

    def __init__(self, config: Optional[EngineConfig] = None):
        self.config = config or EngineConfig()
        self._api_client: Optional[SkylandApiClient] = None

    async def initialize(self):
        """初始化引擎（创建 API 客户端连接池）"""
        if self._api_client is None:
            self._api_client = SkylandApiClient(
                retry_count=self.config.sign_retry_count,
            )
            # 触发 session 创建
            await self._api_client._get_session()

    async def shutdown(self):
        """关闭引擎（释放连接池）"""
        if self._api_client:
            await self._api_client.close()
            self._api_client = None

    @property
    def api(self) -> SkylandApiClient:
        if self._api_client is None:
            raise RuntimeError("引擎未初始化，请先调用 initialize()")
        return self._api_client

    # ==================== 用户绑定 ====================

    async def bind_user(self, sender_id: str, token: str) -> tuple[UserSignState, str]:
        """绑定用户：验证 token → 获取角色 → 返回状态

        Args:
            sender_id: 用户唯一标识
            token: 鹰角网络通行证

        Returns:
            (UserSignState, 角色摘要字符串)

        Raises:
            SkylandApiError: token 无效或 API 错误
        """
        # 解析 token
        token = parse_user_token(token)

        # 验证凭证
        ok, info, cred_data = await self.api.verify_token(token)
        if not ok:
            raise SkylandAuthError(info)

        credential = UserCredential(
            token=token,
            cred=cred_data.get('cred', ''),
            sign_token=cred_data.get('token', token),
            refreshed_at=datetime.now().isoformat(),
        )

        state = UserSignState(
            sender_id=sender_id,
            credential=credential,
            game_info=info,
            push_enabled=self.config.push_enabled_default,
            sign_time=self.config.default_sign_time,
            notify_target=sender_id,
        )

        return state, info

    # ==================== 签到 ====================

    async def sign(self, state: UserSignState) -> SignResult:
        """为单个用户执行签到

        Args:
            state: 用户签到状态

        Returns:
            SignResult
        """
        try:
            # 检查凭证是否需要刷新
            await self._ensure_credential(state)

            # 执行签到
            logs = await self.api.do_sign(
                state.credential.sign_token,
                state.credential.cred,
            )

            # 更新状态
            today = date.today().isoformat()
            state.last_sign_date = today
            state.last_sign_result = '✅ ' + ' | '.join(logs) if logs else '✅ 签到完成'

            return SignResult(
                success=True,
                messages=logs,
                signed_games=self._extract_games(logs),
            )

        except SkylandAuthError as e:
            # 认证失败，尝试刷新凭证后重试一次
            try:
                await self._refresh_credential(state)
                logs = await self.api.do_sign(
                    state.credential.sign_token,
                    state.credential.cred,
                )
                today = date.today().isoformat()
                state.last_sign_date = today
                state.last_sign_result = '✅ ' + ' | '.join(logs) if logs else '✅ 签到完成'

                return SignResult(
                    success=True,
                    messages=logs,
                    signed_games=self._extract_games(logs),
                )
            except Exception as retry_err:
                err_msg = f'❌ 凭证刷新后签到仍失败: {retry_err}'
                state.last_sign_result = err_msg
                return SignResult(success=False, error=err_msg)

        except Exception as e:
            err_msg = f'❌ 签到失败: {e}'
            state.last_sign_result = err_msg
            return SignResult(success=False, error=err_msg)

    async def sign_batch(
        self,
        states: list[UserSignState],
    ) -> list[tuple[UserSignState, SignResult]]:
        """批量签到（带间隔防风控）

        Args:
            states: 用户状态列表

        Returns:
            [(state, result), ...]
        """
        results = []
        for state in states:
            # 随机间隔（基础间隔 ± 50%）
            result = await self.sign(state)
            results.append((state, result))
            interval = self.config.sign_interval_seconds * random.uniform(0.5, 1.5)
            await asyncio.sleep(interval)
        return results

    # ==================== 凭证管理 ====================

    async def _ensure_credential(self, state: UserSignState):
        """确保凭证有效（必要时刷新）"""
        if not state.credential.refreshed_at:
            return

        try:
            refreshed = datetime.fromisoformat(state.credential.refreshed_at)
            window = timedelta(hours=self.config.cred_refresh_window_hours)
            if datetime.now() - refreshed > window:
                await self._refresh_credential(state)
        except (ValueError, TypeError):
            pass

    async def _refresh_credential(self, state: UserSignState):
        """刷新凭证"""
        new_token = await self.api.refresh_token(
            state.credential.token,
            state.credential.cred,
        )
        state.credential.token = new_token
        # 重新走完整鉴权流程获取新 cred
        cred_data = await self.api.get_cred_by_token(new_token)
        state.credential.cred = cred_data.get('cred', '')
        state.credential.sign_token = cred_data.get('token', new_token)
        state.credential.refreshed_at = datetime.now().isoformat()

    # ==================== 工具 ====================

    @staticmethod
    def _extract_games(logs: list[str]) -> list[str]:
        """从日志中提取游戏名"""
        games = []
        for log in logs:
            if log.startswith('✅ [') or log.startswith('❌ ['):
                try:
                    game = log.split(']')[0].split('[')[1]
                    if game not in games:
                        games.append(game)
                except IndexError:
                    pass
        return games
