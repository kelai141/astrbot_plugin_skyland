"""
领域层枚举测试
"""
import pytest

from domain.enums import (
    GamePlatform, SignStatus, NotificationPolicy,
    CredentialType, BindingStatus,
)


class TestGamePlatform:
    def test_values(self):
        assert GamePlatform.ARKNIENTS.value == "arknights"
        assert GamePlatform.ENDFIELD.value == "endfield"
        assert GamePlatform.UNKNOWN.value == "unknown"

    def test_from_string(self):
        assert GamePlatform("arknights") == GamePlatform.ARKNIENTS
        assert GamePlatform("endfield") == GamePlatform.ENDFIELD
        assert GamePlatform("unknown") == GamePlatform.UNKNOWN

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            GamePlatform("invalid_game")


class TestSignStatus:
    def test_values(self):
        assert SignStatus.SUCCESS.value == "success"
        assert SignStatus.ALREADY_SIGNED.value == "already_signed"
        assert SignStatus.FAILED.value == "failed"
        assert SignStatus.SKIPPED.value == "skipped"


class TestNotificationPolicy:
    def test_values(self):
        assert NotificationPolicy.ALL.value == "all"
        assert NotificationPolicy.FAILURE_ONLY.value == "failure_only"
        assert NotificationPolicy.NONE.value == "none"


class TestCredentialType:
    def test_values(self):
        assert CredentialType.TOKEN.value == "token"
        assert CredentialType.PHONE_SESSION.value == "phone_session"


class TestBindingStatus:
    def test_values(self):
        assert BindingStatus.ACTIVE.value == "active"
        assert BindingStatus.EXPIRED.value == "expired"
        assert BindingStatus.REVOKED.value == "revoked"
