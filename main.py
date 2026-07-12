"""
森空岛自动签到 AstrBot 插件 — v3.0（DDD 架构）

分层依赖：Interface → Application → Domain ← Infrastructure
"""
import asyncio, random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

_DATA_BASE_PLUGIN = "astrbot_plugin_skyland"
try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    _DATA_BASE = Path(get_astrbot_data_path()) / "plugin_data" / _DATA_BASE_PLUGIN
except Exception:
    _DATA_BASE = Path("data") / "plugin_data" / _DATA_BASE_PLUGIN
_DATA_BASE.mkdir(parents=True, exist_ok=True)


@register(_DATA_BASE_PLUGIN, "森空岛签到",
          "森空岛自动签到，多用户管理、手机号登录、定时推送", "v3.0.0")
class SklandSignPlugin(Star):

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context, config)
        self.config = config or {}
        self._sign_task: Optional[asyncio.Task] = None
        self._task_started = False

    async def initialize(self):
        # === 使用新版 Domain/Infrastructure 架构 ===
        try:
            from .domain.enums import ResultType
            from .domain.models import Account, Credential
            from .infrastructure.persistence.file_repository import FileAccountRepository
            from .infrastructure.skyland.api_client_impl import SkylandApiClient
            from .infrastructure.compat import AstrBotPathAdapter
            from .infrastructure.notification import NotificationTemplates, PushPolicy
            from .infrastructure.notification_port import AstrBotNotificationPort
            from .infrastructure.persistence.credential_cache import MemoryCredentialCache
            from .infrastructure.skyland.security import set_cache_dir, fetch_did
            from .interface.handlers.bind import handle_bind, handle_login, handle_unbind
            from .interface.handlers.sign import handle_sign, handle_push_toggle, handle_time_config, handle_status, handle_did
            from .interface.handlers.admin import handle_list_users, handle_remove_user, handle_broadcast

            self._account_repo = FileAccountRepository(str(_DATA_BASE))
            self._api_client = SkylandApiClient()
            self._cred_cache = MemoryCredentialCache()
            self._notif_port = AstrBotNotificationPort(self.context)

            try:
                from .application.sign_service import SignService
                from .application.account_service import AccountService as AcctSvc
                from .application.schedule_service import ScheduleService
                self._sign_svc = SignService(api=self._api_client, account_repo=self._account_repo,
                    schedule_repo=self._account_repo, cred_cache=self._cred_cache)
                self._acct_svc = AcctSvc(api=self._api_client, account_repo=self._account_repo,
                    schedule_repo=self._account_repo, notification=self._notif_port)
                self._sched_svc = ScheduleService()
                logger.info("[v3] Application 层已加载")
            except Exception as e:
                logger.warning(f"[v3] Application 层未就绪 ({e})，使用兼容模式")
                self._sign_svc = None
                self._acct_svc = None

            set_cache_dir(str(_DATA_BASE))
            try:
                await fetch_did()
            except Exception:
                pass
            self._start_v3_loop()
            logger.info("✅ 森空岛签到 v3.0 初始化完成")
        except Exception as e:
            logger.warning(f"[v3] DDD 架构导入失败 ({e})，回退 v2 引擎")
            await self._legacy_init()

    async def _legacy_init(self):
        from .lib.skyland_engine import SkylandSignEngine, EngineConfig
        from .lib.storage import FileStore, migrate_from_old
        from .lib.security import set_cache_dir, fetch_did
        from .lib.timeutil import beijing_now
        self.store = FileStore(str(_DATA_BASE))
        migrate_from_old(self.store)
        self.store.load()
        self.engine = SkylandSignEngine(EngineConfig(
            default_sign_time=self.config.get("sign_time", "09:05"),
            sign_interval_seconds=self.config.get("sign_interval_seconds", 2),
            sign_retry_count=self.config.get("sign_retry_count", 2),
            cred_refresh_window_hours=self.config.get("cred_refresh_window_hours", 24),
            push_enabled_default=self.config.get("push_enabled_default", True),
        ))
        await self.engine.initialize()
        set_cache_dir(str(_DATA_BASE))
        try:
            await fetch_did()
        except Exception:
            pass
        if self.store.get_users():
            self._start_auto_sign_loop()
        logger.info(f"✅ 森空岛签到 v3.0（兼容模式）初始化完成，{len(self.store.get_users())} 用户")

    def _start_v3_loop(self):
        if self._task_started:
            return
        self._task_started = True
        self._sign_task = asyncio.create_task(self._v3_loop())
        logger.info("v3 自动签到循环已启动")

    async def _v3_loop(self):
        try:
            await asyncio.sleep(5)
            last_slot = None
            while True:
                try:
                    now = self._now_beijing()
                    slot = now.hour * 60 + now.minute
                    if last_slot is None:
                        slots = [slot]
                    else:
                        slots = list(range(last_slot + 1, slot + 1)) if last_slot <= slot else [slot]
                    for s in slots:
                        h, m = divmod(s, 60)
                        for acct in (await self._account_repo.find_all()):
                            if acct.token_expired or acct.sign_time != f"{h:02d}:{m:02d}":
                                continue
                            result = await self._sign_svc.execute_sign(acct)
                            await self._account_repo.save(acct)
                    last_slot = slot
                    await asyncio.sleep(60 - self._now_beijing().second + 0.5)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"v3 循环异常: {e}", exc_info=True)
                    await asyncio.sleep(3)
        except asyncio.CancelledError:
            logger.info("v3 循环已取消")

    def _now_beijing(self):
        return datetime.now(timezone.utc) + timedelta(hours=8)

    def _get_sender_id(self, event):
        gid = event.get_group_id()
        return f"{gid}:{event.get_sender_id()}" if gid else event.get_sender_id()

    def _is_admin(self, event):
        sid = event.get_sender_id()
        if sid in self.config.get("admin_users", []):
            return True
        try:
            return self.context.is_admin(sid)
        except Exception:
            return False

    async def terminate(self):
        if hasattr(self, 'store'):
            self.store.flush()
        if self._sign_task and not self._sign_task.done():
            self._sign_task.cancel()
            try:
                await self._sign_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, 'engine'):
            await self.engine.shutdown()
        logger.info("插件已关闭")

    # ======= 指令系统 =======

    @filter.command_group("skland")
    def skland():
        pass

    @skland.command("help")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "🌠 森空岛自动签到 v3.0\n\n"
            "📋 可用指令：\n"
            "  /skland bind <token>    绑定鹰角通行证 token\n"
            "  /skland login           手机号+验证码登录\n"
            "  /skland sign            立即手动签到\n"
            "  /skland status          查看签到状态\n"
            "  /skland push on|off     开关自动推送\n"
            "  /skland time [set HH:MM] 设置签到时间\n"
            "  /skland did             查看设备指纹\n"
            "  /skland unbind          解绑账号\n\n"
            "🔧 管理员指令：\n"
            "  /skland list            查看所有用户\n"
            "  /skland remove <id>     移除用户\n"
            "  /skland broadcast <msg> 群发消息\n\n"
            "💡 推荐 /skland login 手机号登录（无需浏览器）"
        )

    @skland.command("bind")
    async def bind(self, event: AstrMessageEvent, token: str = None):
        if hasattr(self, '_acct_svc') and self._acct_svc:
            from .interface.handlers.bind import handle_bind as h
        else:
            from .handlers.bind import handle_bind as h
        async for msg in h(self, event, token):
            yield msg

    @skland.command("login")
    async def login(self, event: AstrMessageEvent):
        if hasattr(self, '_acct_svc') and self._acct_svc:
            from .interface.handlers.bind import handle_login as h
        else:
            from .handlers.bind import handle_login as h
        async for msg in h(self, event):
            yield msg

    @skland.command("sign")
    async def sign(self, event: AstrMessageEvent):
        if hasattr(self, '_sign_svc') and self._sign_svc:
            from .interface.handlers.sign import handle_sign as h
        else:
            from .handlers.sign import handle_sign as h
        async for msg in h(self, event):
            yield msg

    @skland.command("push")
    async def push_toggle(self, event: AstrMessageEvent, action: str = None):
        from .handlers.sign import handle_push_toggle as h
        async for msg in h(self, event, action):
            yield msg

    @skland.command("time")
    async def time_config(self, event: AstrMessageEvent, action: str = None, arg: str = None):
        from .handlers.sign import handle_time_config as h
        async for msg in h(self, event, action, arg):
            yield msg

    @skland.command("status")
    async def status(self, event: AstrMessageEvent):
        from .handlers.sign import handle_status as h
        async for msg in h(self, event):
            yield msg

    @skland.command("did")
    async def did(self, event: AstrMessageEvent):
        from .handlers.sign import handle_did as h
        async for msg in h(self, event):
            yield msg

    @skland.command("unbind")
    async def unbind(self, event: AstrMessageEvent):
        if hasattr(self, '_acct_svc') and self._acct_svc:
            from .interface.handlers.bind import handle_unbind as h
        else:
            from .handlers.bind import handle_unbind as h
        async for msg in h(self, event):
            yield msg

    @skland.command("list")
    async def list_users(self, event: AstrMessageEvent):
        from .handlers.admin import handle_list_users as h
        async for msg in h(self, event):
            yield msg

    @skland.command("remove")
    async def remove_user(self, event: AstrMessageEvent, user_id: str = None):
        from .handlers.admin import handle_remove_user as h
        async for msg in h(self, event, user_id):
            yield msg

    @skland.command("broadcast")
    async def broadcast(self, event: AstrMessageEvent):
        from .handlers.admin import handle_broadcast as h
        async for msg in h(self, event):
            yield msg
