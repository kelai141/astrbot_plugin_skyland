"""
基础设施 — AstrBot 原生通知适配
"""
from astrbot.api import logger
from astrbot.api.message_components import Plain, Image, Record

from domain.models import PushNotification
from domain.ports import NotificationPort


class AstrBotNotificationAdapter(NotificationPort):
    """使用 AstrBot 原生消息链发送通知"""

    def __init__(self, context):
        self._context = context

    async def send(self, notification: PushNotification) -> bool:
        """发送通知给指定用户"""
        try:
            message_chain = [Plain(text=f"{notification.title}\n{notification.message}")]
            await self._context.send_message(
                message_chain,
                user_id=notification.user_id,
            )
            return True
        except Exception as e:
            logger.error(f"[通知] 发送给 {notification.user_id} 失败: {e}")
            return False

    async def send_to_admin(self, message: str) -> bool:
        """发送通知给管理员（通过日志记录）"""
        try:
            logger.info(f"[管理员通知] {message}")
            return True
        except Exception as e:
            logger.error(f"[通知] 管理员通知失败: {e}")
            return False
