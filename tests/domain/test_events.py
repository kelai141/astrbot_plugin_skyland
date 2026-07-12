"""
领域层事件测试
"""
from datetime import datetime

from domain.events import (
    UserBoundEvent, UserUnboundEvent,
    SignCompletedEvent, CredentialExpiredEvent, NotificationSentEvent,
)
from domain.enums import GamePlatform, SignStatus


class TestUserBoundEvent:
    def test_create(self):
        event = UserBoundEvent(
            event_id="evt_001",
            user_id="123",
            platform="aiocqhttp",
        )
        assert event.event_id == "evt_001"
        assert event.user_id == "123"
        assert event.platform == "aiocqhttp"
        assert isinstance(event.occurred_at, datetime)


class TestUserUnboundEvent:
    def test_create(self):
        event = UserUnboundEvent(
            event_id="evt_002",
            user_id="123",
            platform="aiocqhttp",
            reason="用户主动解绑",
        )
        assert event.reason == "用户主动解绑"


class TestSignCompletedEvent:
    def test_create_success(self):
        event = SignCompletedEvent(
            event_id="evt_003",
            user_id="123",
            game=GamePlatform.ARKNIENTS,
            status=SignStatus.SUCCESS,
            reward="合成玉×100",
        )
        assert event.status == SignStatus.SUCCESS
        assert event.reward == "合成玉×100"

    def test_create_failure(self):
        event = SignCompletedEvent(
            event_id="evt_004",
            user_id="123",
            game=GamePlatform.ARKNIENTS,
            status=SignStatus.FAILED,
            error_message="网络超时",
        )
        assert event.status == SignStatus.FAILED
        assert event.error_message == "网络超时"


class TestCredentialExpiredEvent:
    def test_create(self):
        event = CredentialExpiredEvent(
            event_id="evt_005",
            user_id="123",
            platform="aiocqhttp",
        )
        assert event.user_id == "123"


class TestNotificationSentEvent:
    def test_create(self):
        event = NotificationSentEvent(
            event_id="evt_006",
            user_id="123",
            notification_type="sign_result",
            success=True,
        )
        assert event.success is True
