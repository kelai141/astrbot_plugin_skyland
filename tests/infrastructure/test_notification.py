"""
通知端口测试
"""
import pytest

from domain.models import PushNotification
from infrastructure.notification_port import ConsoleNotificationPort, CompositeNotificationPort


class TestConsoleNotificationPort:
    @pytest.mark.asyncio
    async def test_send(self):
        port = ConsoleNotificationPort()
        notif = PushNotification(
            user_id="test_user",
            title="测试通知",
            message="这是一条测试消息",
        )
        result = await port.send(notif)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_to_admin(self):
        port = ConsoleNotificationPort()
        result = await port.send_to_admin("管理员测试消息")
        assert result is True


class TestCompositeNotificationPort:
    @pytest.mark.asyncio
    async def test_primary_success(self):
        primary = ConsoleNotificationPort()
        composite = CompositeNotificationPort(primary)
        notif = PushNotification(user_id="u1", title="t", message="m")
        result = await composite.send(notif)
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_notification(self):
        primary = ConsoleNotificationPort()
        composite = CompositeNotificationPort(primary)
        result = await composite.send_to_admin("测试")
        assert result is True
