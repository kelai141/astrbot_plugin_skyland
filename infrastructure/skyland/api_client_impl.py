"""
森空岛 API 客户端实现
"""
import asyncio
import hashlib
import time
from typing import Optional

import aiohttp
from astrbot.api import logger

from infrastructure.skyland.signer import SkylandSigner
from infrastructure.skyland.api_client import ISkylandApiClient


class SkylandApiClientImpl(ISkylandApiClient):
    """森空岛 API 客户端 — HTTP 实现"""

    BASE_URL = "https://as.hypergryph.com"
    SKLAND_URL = "https://api.skland.com"
    USER_AGENT = "Skland/1.0.0 (Android; com.hypergryph.skland)"

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        timeout_seconds: int = 30,
    ):
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._signer = SkylandSigner()
        self._owned_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owned_session = True
        return self._session

    async def close(self):
        if self._owned_session and self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        url: str,
        headers: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        session = await self._get_session()
        default_headers = {
            "User-Agent": self.USER_AGENT,
            "Content-Type": "application/json",
        }
        if headers:
            default_headers.update(headers)

        try:
            async with session.request(
                method, url, headers=default_headers, **kwargs,
            ) as resp:
                data = await resp.json()
                return data
        except asyncio.TimeoutError:
            return {"code": -1, "message": "请求超时"}
        except Exception as e:
            logger.error(f"[API] 请求失败 {url}: {e}")
            return {"code": -1, "message": str(e)}

    async def _skland_request(
        self,
        method: str,
        path: str,
        token: str,
        did: str,
        body: Optional[dict] = None,
    ) -> dict:
        headers = {
            "cred": token,
            "did": did,
            "platform": "1",
            "v": "1.1.0",
        }
        # 生成签名
        sign_headers = self._signer.to_header(path, body)
        headers.update(sign_headers)

        return await self._request(
            method,
            f"{self.SKLAND_URL}{path}",
            headers=headers,
            json=body,
        )

    # ---- 鹰角通行证 API ----

    async def get_token_by_code(self, code: str) -> str:
        """通过授权码获取 token（OAuth 流程）"""
        data = await self._request(
            "POST",
            f"{self.BASE_URL}/user/auth/v2/token_by_code",
            json={
                "kind": 1,
                "code": code,
            },
        )
        return data.get("data", {}).get("token", "")

    async def get_token_by_session(self, session_token: str) -> str:
        """通过 session token 获取鹰角通行证 token"""
        data = await self._request(
            "POST",
            f"{self.BASE_URL}/user/auth/v2/token_by_session",
            json={
                "kind": 1,
                "session_token": session_token,
            },
        )
        return data.get("data", {}).get("token", "")

    async def login_by_phone(self, phone: str) -> dict:
        """手机号登录 — 发送验证码"""
        return await self._request(
            "POST",
            f"{self.BASE_URL}/user/auth/v2/send_phone_code",
            json={
                "kind": 1,
                "phone": phone,
            },
        )

    async def verify_code(self, phone: str, code: str) -> dict:
        """验证手机验证码"""
        return await self._request(
            "POST",
            f"{self.BASE_URL}/user/auth/v2/verify_code",
            json={
                "kind": 1,
                "phone": phone,
                "code": code,
            },
        )

    # ---- 森空岛 API ----

    async def get_player_info(self, token: str, game_id: str) -> dict:
        """获取玩家信息"""
        return await self._skland_request(
            "GET",
            f"/api/v1/game/player_info?game_id={game_id}",
            token=token,
            did="",
        )

    async def get_games(self, token: str) -> list[dict]:
        """获取账号下的游戏列表"""
        data = await self._skland_request(
            "GET",
            "/api/v1/game/list",
            token=token,
            did="",
        )
        return data.get("data", {}).get("list", [])

    async def sign(self, token: str, did: str, game_id: str) -> dict:
        """执行签到"""
        return await self._skland_request(
            "POST",
            "/api/v1/sign",
            token=token,
            did=did,
            body={"game_id": game_id},
        )

    async def get_sign_status(self, token: str, did: str, game_id: str) -> dict:
        """获取签到状态"""
        return await self._skland_request(
            "GET",
            f"/api/v1/sign?game_id={game_id}",
            token=token,
            did=did,
        )
