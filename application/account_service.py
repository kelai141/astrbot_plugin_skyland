"""
应用层 — 账号绑定/解绑/登录用例
"""
from typing import Optional

from astrbot.api import logger

from domain.enums import (
    CredentialType, BindingStatus, GamePlatform, NotificationPolicy,
)
from domain.models import UserBinding, UserCredential
from domain.ports import (
    UserBindingRepository, SkylandApiClient, NotificationPort,
)
from domain.errors import UserAlreadyBoundError, UserNotBoundError, InvalidCredentialError
from application.dto import BindDTO


class AccountService:
    """账号管理应用服务"""

    def __init__(
        self,
        binding_repo: UserBindingRepository,
        api_client: SkylandApiClient,
        notification_port: NotificationPort,
    ):
        self._binding_repo = binding_repo
        self._api_client = api_client
        self._notification_port = notification_port

    async def bind_by_token(self, dto: BindDTO) -> UserBinding:
        """通过 Token 绑定账号"""
        existing = await self._binding_repo.find_by_user_id(dto.user_id, dto.platform)
        if existing and existing.is_active:
            raise UserAlreadyBoundError(dto.user_id)

        # 验证 token 有效性
        try:
            games = await self._api_client.get_games(dto.credential_value)
        except Exception as e:
            raise InvalidCredentialError(f"Token 验证失败: {e}")

        credential = UserCredential(
            type=CredentialType.TOKEN,
            value=dto.credential_value,
        )

        binding = UserBinding(
            user_id=dto.user_id,
            platform=dto.platform,
            credential=credential,
            game=dto.game,
            status=BindingStatus.ACTIVE,
        )

        saved = await self._binding_repo.save(binding)

        logger.info(f"[账号] {dto.user_id} 通过 Token 绑定成功")
        await self._notification_port.send_to_admin(
            f"🔗 用户 {dto.user_id} 通过 Token 绑定了森空岛账号"
        )

        return saved

    async def bind_by_phone(self, user_id: str, platform: str, phone: str) -> dict:
        """手机号登录第一步：发送验证码"""
        existing = await self._binding_repo.find_by_user_id(user_id, platform)
        if existing and existing.is_active:
            raise UserAlreadyBoundError(user_id)

        try:
            result = await self._api_client.login_by_phone(phone)
            logger.info(f"[账号] {user_id} 手机号 {phone[:3]}****{phone[-3:]} 验证码已发送")
            return result
        except Exception as e:
            raise InvalidCredentialError(f"发送验证码失败: {e}")

    async def verify_and_bind(
        self,
        user_id: str,
        platform: str,
        phone: str,
        code: str,
        game: GamePlatform = GamePlatform.ARKNIENTS,
    ) -> UserBinding:
        """手机号登录第二步：验证验证码并绑定"""
        try:
            verify_result = await self._api_client.verify_code(phone, code)
            session_token = verify_result.get("data", {}).get("token", "")
            if not session_token:
                raise InvalidCredentialError("验证码验证成功但未获取到 session token")

            hypergryph_token = await self._api_client.get_token_by_session(session_token)

            credential = UserCredential(
                type=CredentialType.PHONE_SESSION,
                value=hypergryph_token,
                hypergryph_token=hypergryph_token,
            )

            # 验证 token
            await self._api_client.get_games(hypergryph_token)

            binding = UserBinding(
                user_id=user_id,
                platform=platform,
                credential=credential,
                game=game,
                status=BindingStatus.ACTIVE,
            )

            saved = await self._binding_repo.save(binding)

            logger.info(f"[账号] {user_id} 通过手机号绑定成功")
            await self._notification_port.send_to_admin(
                f"🔗 用户 {user_id} 通过手机号绑定了森空岛账号"
            )

            return saved

        except InvalidCredentialError:
            raise
        except Exception as e:
            raise InvalidCredentialError(f"手机号绑定失败: {e}")

    async def unbind(self, user_id: str, platform: str) -> bool:
        """解绑账号"""
        binding = await self._binding_repo.find_by_user_id(user_id, platform)
        if not binding:
            raise UserNotBoundError(user_id)

        result = await self._binding_repo.delete(user_id, platform)

        logger.info(f"[账号] {user_id} 解绑成功")
        await self._notification_port.send_to_admin(
            f"🔓 用户 {user_id} 已解绑森空岛账号"
        )

        return result

    async def list_all_bindings(self) -> list[UserBinding]:
        """获取所有绑定"""
        return await self._binding_repo.list_all()

    async def remove_binding(self, user_id: str, platform: str) -> bool:
        """管理员移除绑定"""
        return await self.unbind(user_id, platform)
