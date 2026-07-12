"""
接口层 — 定时调度器注册
"""
import asyncio
from typing import Optional

from astrbot.api import logger

from application.schedule_service import ScheduleService


class PluginScheduler:
    """插件定时调度器封装"""

    def __init__(self, schedule_service: ScheduleService):
        self._schedule_service = schedule_service
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """启动定时签到"""
        if self._task and not self._task.done():
            logger.warning("[调度器] 已在运行")
            return

        self._task = asyncio.create_task(self._schedule_service._run_loop())
        logger.info("[调度器] 定时签到已启动")

    async def stop(self):
        """停止定时签到"""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            logger.info("[调度器] 定时签到已停止")

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()
