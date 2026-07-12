"""
领域层模型测试
"""
from datetime import datetime, timedelta, timezone

import pytest

from domain.enums import (
    CredentialType, BindingStatus, GamePlatform, NotificationPolicy, SignStatus,
)
from domain.models import (
    UserCredential, UserBinding, SignRecord, DidRecord, PushNotification,
)


class TestUserCredential:
    def test_create_token_credential(self):
        cred = UserCredential(
            type=CredentialType.TOKEN,
            value="test_token_12345",
        )
        assert cred.type == CredentialType.TOKEN
        assert cred.value == "test_token_12345"
        assert cred.hypergryph_token is None
        assert cred.did is None

    def test_safe_masked_short(self):
        cred = UserCredential(type=CredentialType.TOKEN, value="abcdefgh")
        assert cred.safe_masked == "abcd****"

    def test_safe_masked_long(self):
        cred = UserCredential(type=CredentialType.TOKEN, value="abcdefghijklmnop")
        assert cred.safe_masked == "abcd****mnop"

    def test_is_expired_no_expiry(self):
        cred = UserCredential(type=CredentialType.TOKEN, value="test")
        assert cred.is_expired() is False

    def test_is_expired_future(self):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        cred = UserCredential(
            type=CredentialType.TOKEN, value="test", expires_at=future,
        )
        assert cred.is_expired() is False

    def test_is_expired_past(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        cred = UserCredential(
            type=CredentialType.TOKEN, value="test", expires_at=past,
        )
        assert cred.is_expired() is True


class TestUserBinding:
    def test_create_binding(self):
        cred = UserCredential(type=CredentialType.TOKEN, value="token123")
        binding = UserBinding(
            user_id="123456",
            platform="aiocqhttp",
            credential=cred,
        )
        assert binding.user_id == "123456"
        assert binding.platform == "aiocqhttp"
        assert binding.credential == cred
        assert binding.game == GamePlatform.ARKNIENTS
        assert binding.sign_time == "09:05"
        assert binding.notification_policy == NotificationPolicy.ALL
        assert binding.status == BindingStatus.ACTIVE
        assert binding.consecutive_days == 0
        assert binding.total_signs == 0

    def test_is_active(self):
        cred = UserCredential(type=CredentialType.TOKEN, value="test")
        active = UserBinding(user_id="1", platform="p", credential=cred, status=BindingStatus.ACTIVE)
        expired = UserBinding(user_id="2", platform="p", credential=cred, status=BindingStatus.EXPIRED)
        assert active.is_active is True
        assert expired.is_active is False


class TestSignRecord:
    def test_create_record(self):
        now = datetime.now(timezone.utc)
        record = SignRecord(
            user_id="123",
            game=GamePlatform.ARKNIENTS,
            status=SignStatus.SUCCESS,
            signed_at=now,
            reward="合成玉×100",
        )
        assert record.user_id == "123"
        assert record.game == GamePlatform.ARKNIENTS
        assert record.status == SignStatus.SUCCESS
        assert record.reward == "合成玉×100"
        assert record.signed_at == now


class TestDidRecord:
    def test_valid_did(self):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        record = DidRecord(
            did="dId_abc123",
            created_at=datetime.now(timezone.utc),
            expires_at=future,
        )
        assert record.is_valid() is True

    def test_expired_did(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        record = DidRecord(
            did="dId_abc123",
            created_at=past,
            expires_at=past,
        )
        assert record.is_valid() is False

    def test_no_expiry_did(self):
        record = DidRecord(
            did="dId_abc123",
            created_at=datetime.now(timezone.utc),
        )
        assert record.is_valid() is True


class TestPushNotification:
    def test_create_notification(self):
        notif = PushNotification(
            user_id="123",
            title="签到成功",
            message="明日方舟 签到成功！获得合成玉×100",
        )
        assert notif.user_id == "123"
        assert notif.title == "签到成功"
        assert notif.notification_type == "sign_result"
        assert notif.created_at is not None
