"""
应用层 — 定时调度用例
"""
import asyncio
from datetime import datetime
from typing import Optional, Callable

from astrbot.api import logger

from domain.enums import GamePlatform
from domain.services import SignScheduleService
from application.dto import BatchSignResultDTO
from application.sign_service import SignService


class ScheduleService:
    """定时调度服务"""

    def __init__(
        self,
        sign_service: SignService,
        default_sign_time: str = "09:05",
    ):
        self._sign_service = sign_service
        self._default_sign_time = default_sign_time
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._current_sign_time: str = default_sign_time

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_sign_time(self) -> str:
        return self._current_sign_time

    def update_sign_time(self, sign_time: str):
        """更新签到时间"""
        self._current_sign_time = sign_time
        logger.info(f"[调度] 签到时间更新为 {sign_time}")

    async def start(self):
        """启动定时签到循环"""
        if self._running:
            logger.warning("[调度] 定时签到已在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"[调度] 定时签到已启动，签到时间: {self._current_sign_time}")

    async def stop(self):
        """停止定时签到循环"""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[调度] 定时签到已停止")

    async def run_once(self, game: GamePlatform = None) -> BatchSignResultDTO:
        """立即执行一次批量签到"""
        logger.info("[调度] 手动触发批量签到")
        return await self._sign_service.execute_batch_sign(game)

    async def _run_loop(self):
        """定时签到主循环"""
        while self._running:
            try:
                now = datetime.now().astimezone()
                next_run = SignScheduleService.get_next_run_time(self._current_sign_time)
                wait_seconds = (next_run - now).total_seconds()

                logger.info(f"[调度] 下次签到时间: {next_run.isoformat()} (等待 {wait_seconds:.0f} 秒)")
                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                logger.info("[调度] ⏰ 定时签到触发")
                await self._sign_service.execute_batch_sign()

                # 等待 60 秒防止短时间重复触发
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[调度] 定时签到循环异常: {e}", exc_info=True)
                await asyncio.sleep(30)
