"""
通知端口实现 — 兼容新旧 AstrBot API
"""
from typing import Optional

from astrbot.api import logger

from domain.models import PushNotification
from domain.ports import NotificationPort


class ConsoleNotificationPort(NotificationPort):
    """控制台通知（开发/调试用）"""

    async def send(self, notification: PushNotification) -> bool:
        logger.info(f"[通知->{notification.user_id}] {notification.title}: {notification.message}")
        return True

    async def send_to_admin(self, message: str) -> bool:
        logger.info(f"[管理员通知] {message}")
        return True


class CompositeNotificationPort(NotificationPort):
    """复合通知端口 — 按策略选择发送方式"""

    def __init__(self, primary: NotificationPort, fallback: Optional[NotificationPort] = None):
        self._primary = primary
        self._fallback = fallback

    async def send(self, notification: PushNotification) -> bool:
        try:
            return await self._primary.send(notification)
        except Exception as e:
            logger.warning(f"[通知] 主端口发送失败，使用备用: {e}")
            if self._fallback:
                return await self._fallback.send(notification)
            return False

    async def send_to_admin(self, message: str) -> bool:
        try:
            return await self._primary.send_to_admin(message)
        except Exception as e:
            logger.warning(f"[通知] 主端口管理员通知失败: {e}")
            if self._fallback:
                return await self._fallback.send_to_admin(message)
            return False
