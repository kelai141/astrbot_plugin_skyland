"""
森空岛 API 客户端 — 端口定义
"""
from abc import ABC, abstractmethod
from typing import Optional


class ISkylandApiClient(ABC):
    """森空岛 API 客户端接口"""

    @abstractmethod
    async def get_token_by_code(self, code: str) -> str:
        """通过授权码获取 token"""
        ...

    @abstractmethod
    async def get_token_by_session(self, session_token: str) -> str:
        """通过 session token 获取鹰角通行证 token"""
        ...

    @abstractmethod
    async def login_by_phone(self, phone: str) -> dict:
        """手机号登录第一步：发送验证码"""
        ...

    @abstractmethod
    async def verify_code(self, phone: str, code: str) -> dict:
        """手机号登录第二步：验证验证码"""
        ...

    @abstractmethod
    async def get_player_info(self, token: str, game_id: str) -> dict:
        """获取玩家信息"""
        ...

    @abstractmethod
    async def get_games(self, token: str) -> list[dict]:
        """获取账号下的游戏列表"""
        ...

    @abstractmethod
    async def sign(self, token: str, did: str, game_id: str) -> dict:
        """执行签到"""
        ...

    @abstractmethod
    async def get_sign_status(self, token: str, did: str, game_id: str) -> dict:
        """获取签到状态"""
        ...
