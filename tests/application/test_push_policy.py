"""
推送策略逻辑测试
"""
import pytest

from domain.enums import NotificationPolicy, SignStatus


def should_push(policy: NotificationPolicy, status: SignStatus) -> bool:
    """推送决策逻辑（内联以方便测试）"""
    if policy == NotificationPolicy.ALL:
        return True
    if policy == NotificationPolicy.FAILURE_ONLY:
        return status in (SignStatus.FAILED,)
    if policy == NotificationPolicy.NONE:
        return False
    return True


class TestPushPolicy:
    def test_all_policy(self):
        assert should_push(NotificationPolicy.ALL, SignStatus.SUCCESS) is True
        assert should_push(NotificationPolicy.ALL, SignStatus.FAILED) is True
        assert should_push(NotificationPolicy.ALL, SignStatus.ALREADY_SIGNED) is True

    def test_failure_only_policy(self):
        assert should_push(NotificationPolicy.FAILURE_ONLY, SignStatus.SUCCESS) is False
        assert should_push(NotificationPolicy.FAILURE_ONLY, SignStatus.FAILED) is True
        assert should_push(NotificationPolicy.FAILURE_ONLY, SignStatus.ALREADY_SIGNED) is False

    def test_none_policy(self):
        assert should_push(NotificationPolicy.NONE, SignStatus.SUCCESS) is False
        assert should_push(NotificationPolicy.NONE, SignStatus.FAILED) is False
