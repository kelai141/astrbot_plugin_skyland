"""
应用层签到服务测试
"""
from datetime import datetime, timezone

import pytest

from domain.enums import SignStatus, GamePlatform, CredentialType, BindingStatus, NotificationPolicy
from domain.models import UserBinding, UserCredential, SignRecord
from domain.ports import UserBindingRepository, SignRecordRepository, SkylandApiClient, NotificationPort
from domain.errors import UserNotBoundError
from application.dto import SignInDTO
from application.sign_service import SignService


class FakeBindingRepo(UserBindingRepository):
    def __init__(self):
        self._store: dict[str, UserBinding] = {}

    async def find_by_user_id(self, user_id: str, platform: str) -> UserBinding | None:
        return self._store.get(f"{platform}:{user_id}")

    async def save(self, binding: UserBinding) -> UserBinding:
        self._store[f"{binding.platform}:{binding.user_id}"] = binding
        return binding

    async def delete(self, user_id: str, platform: str) -> bool:
        key = f"{platform}:{user_id}"
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def list_all(self) -> list[UserBinding]:
        return list(self._store.values())

    async def list_active(self) -> list[UserBinding]:
        return [b for b in self._store.values() if b.is_active]


class FakeSignRecordRepo(SignRecordRepository):
    async def save(self, record: SignRecord) -> SignRecord:
        return record

    async def find_by_user_id(self, user_id: str, limit: int = 10) -> list[SignRecord]:
        return []

    async def find_recent_by_user(self, user_id: str, days: int = 7) -> list[SignRecord]:
        return []


class FakeApiClient(SkylandApiClient):
    async def login_by_phone(self, phone: str) -> dict:
        return {"code": 0, "message": "验证码已发送"}

    async def verify_code(self, phone: str, code: str) -> dict:
        return {"code": 0, "data": {"token": "session_token_test"}}

    async def get_token_by_session(self, session_token: str) -> str:
        return "hypergryph_token_test"

    async def sign(self, token: str, did: str, game_id: str) -> dict:
        return {"code": 0, "data": {"reward": "合成玉×100"}}

    async def get_sign_status(self, token: str, did: str, game_id: str) -> dict:
        return {"code": 0}

    async def get_player_info(self, token: str, game_id: str) -> dict:
        return {"data": {"nickname": "测试"}}

    async def get_games(self, token: str) -> list[dict]:
        return [{"game_id": "1", "name": "明日方舟"}]


class FakeNotificationPort(NotificationPort):
    async def send(self, notification) -> bool:
        return True

    async def send_to_admin(self, message: str) -> bool:
        return True


@pytest.fixture
def sign_service():
    return SignService(
        binding_repo=FakeBindingRepo(),
        sign_record_repo=FakeSignRecordRepo(),
        api_client=FakeApiClient(),
        notification_port=FakeNotificationPort(),
        default_game=GamePlatform.ARKNIENTS,
    )


@pytest.mark.asyncio
class TestSignService:
    async def test_execute_sign_user_not_found(self, sign_service):
        dto = SignInDTO(user_id="nonexistent", platform="aiocqhttp")
        result = await sign_service.execute_sign(dto)
        assert result.status == SignStatus.SKIPPED
        assert "未绑定" in (result.error_message or "")

    async def test_execute_sign_success(self, sign_service):
        # 先绑定用户
        cred = UserCredential(type=CredentialType.TOKEN, value="test_token")
        binding = UserBinding(user_id="user1", platform="aiocqhttp", credential=cred)
        await sign_service._binding_repo.save(binding)

        dto = SignInDTO(user_id="user1", platform="aiocqhttp")
        result = await sign_service.execute_sign(dto)
        assert result.status == SignStatus.SUCCESS

    async def test_batch_sign_no_users(self, sign_service):
        result = await sign_service.execute_batch_sign()
        assert result.total == 0
        assert result.success == 0
        assert result.failed == 0
