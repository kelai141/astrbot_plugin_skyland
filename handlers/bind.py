"""
绑定相关命令处理器

处理: /skland bind, /skland login, /skland unbind
"""
from datetime import date, datetime

import aiohttp

from astrbot.api.event import AstrMessageEvent

from ..lib.skyland_api import (
    SkylandApiClient,
    SkylandAuthError,
    parse_user_token,
)
from ..lib.skyland_engine import UserSignState, UserCredential
from ..lib.notification import NotificationTemplates


async def handle_bind(plugin, event: AstrMessageEvent, token: str):
    """处理 /skland bind <token>"""
    if event.get_group_id():
        yield event.plain_result(
            "🔒 请在私聊中使用此命令（token 不应暴露在群聊中）\n"
            "发送 /skland bind <token> 到机器人私聊即可。"
        )
        return

    sid = plugin._get_sender_id(event)

    if plugin.store.has_user(sid):
        yield event.plain_result(
            "⚠️ 你已经绑定过账号了！\n"
            "如需重新绑定，请先发送 /skland unbind 解绑。"
        )
        return

    if not token:
        yield event.plain_result(
            "⚠️ 请提供鹰角网络通行证 token\n"
            "获取方法：在森空岛官网按 F12 → Console → 输入：\n"
            "copy(JSON.parse(localStorage.getItem('userInfo')).token)\n"
            "然后发送 /skland bind <粘贴的token>"
        )
        return

    yield event.plain_result("⏳ 正在验证 token，请稍候…")

    try:
        state, info = await plugin.engine.bind_user(sid, token)
    except SkylandAuthError as e:
        yield event.plain_result(f"❌ Token 验证失败: {e}\n请检查 token 是否正确，是否已过期。")
        return
    except Exception as e:
        yield event.plain_result(f"❌ 绑定失败: {e}")
        return

    # 保存（notify_target 使用 AstrBot v4.24 unified_msg_origin 格式）
    state.notify_target = event.unified_msg_origin
    plugin._save_user_state(sid, state)
    plugin._start_auto_sign_loop()

    yield event.plain_result(
        NotificationTemplates.bind_success(info, plugin.config.get("sign_time", "09:05"))
    )


async def handle_login(plugin, event: AstrMessageEvent):
    """处理 /skland login（手机验证码登录）

    使用单层 session_waiter + 阶段状态机，避免嵌套 waiter 导致的超时 bug。
    阶段: 'phone' → 'code'
    """
    if event.get_group_id():
        yield event.plain_result(
            "🔒 请在私聊中使用此命令（验证码不应暴露在群聊中）\n"
            "发送 /skland login 到机器人私聊即可。"
        )
        return

    sid = plugin._get_sender_id(event)

    if plugin.store.has_user(sid):
        yield event.plain_result(
            "⚠️ 你已经绑定过账号了！\n"
            "如需重新绑定，请先发送 /skland unbind 解绑。"
        )
        return

    from astrbot.core.utils.session_waiter import session_waiter, SessionController

    yield event.plain_result(
        '📱 请输入你的手机号（发送"取消"取消）：'
    )

    # 状态机：用可变容器跨阶段传递状态
    stage = {"value": "phone", "phone": ""}

    @session_waiter(timeout=180)
    async def wait_input(controller: SessionController, ev: AstrMessageEvent):
        text = ev.message_str.strip()
        if not text:
            return

        # 通用取消
        if text == "取消":
            await ev.send(ev.plain_result("❌ 已取消"))
            controller.stop()
            return

        # ──── 阶段1: 等待手机号 ────
        if stage["value"] == "phone":
            phone = text.replace(" ", "").replace("-", "").replace("+86", "")
            if not phone.isdigit() or len(phone) != 11:
                await ev.send(ev.plain_result("⚠️ 手机号格式不正确，请输入11位手机号："))
                return  # 继续等待

            stage["phone"] = phone

            # 发送验证码
            try:
                resp = await plugin.engine.api.send_login_code(phone)
                if resp.get("status") != 0:
                    await ev.send(ev.plain_result(f"❌ {resp.get('msg', '发送验证码失败')}"))
                    controller.stop()
                    return
            except Exception as e:
                await ev.send(ev.plain_result(f"❌ 发送验证码出错: {e}"))
                controller.stop()
                return

            # 切换到验证码阶段
            stage["value"] = "code"
            await ev.send(ev.plain_result("📱 验证码已发送，请输入6位验证码："))
            return  # 继续等待

        # ──── 阶段2: 等待验证码 ────
        if stage["value"] == "code":
            code = text
            if not code.isdigit() or len(code) != 6:
                await ev.send(ev.plain_result("⚠️ 验证码格式不正确，请输入6位数字："))
                return

            try:
                resp = await plugin.engine.api.login_by_phone_code(stage["phone"], code)
                if resp.get("status") != 0:
                    await ev.send(ev.plain_result(f"❌ {resp.get('msg', '登录失败')}"))
                    controller.stop()
                    return

                token = resp["data"]["token"]
                state, info = await plugin.engine.bind_user(sid, token)
                state.notify_target = ev.unified_msg_origin
                plugin._save_user_state(sid, state)
                plugin._start_auto_sign_loop()

                await ev.send(ev.plain_result(
                    NotificationTemplates.bind_success(
                        info, plugin.config.get("sign_time", "09:05")
                    )
                ))
                controller.stop()

            except Exception as e:
                await ev.send(ev.plain_result(f"❌ 登录失败: {e}"))
                controller.stop()

    try:
        await wait_input(event)
    except TimeoutError:
        yield event.plain_result("⏰ 操作超时，已取消。\n请重新发送 /skland login 再次尝试。")
    except Exception as e:
        yield event.plain_result(f"❌ 出错: {e}")


async def handle_unbind(plugin, event: AstrMessageEvent):
    """处理 /skland unbind（直接解绑，无需二次确认）"""
    if event.get_group_id():
        yield event.plain_result(
            "🔒 请在私聊中使用此命令\n发送 /skland unbind 到机器人私聊即可。"
        )
        return

    sid = plugin._get_sender_id(event)
    state = plugin._load_user_state(sid)

    if state is None:
        yield event.plain_result("❌ 你还没有绑定账号！")
        return

    plugin.store.remove_user(sid)
    yield event.plain_result(
        f"✅ 已解绑！\n"
        f"角色: {state.game_info}\n"
        f"绑定于: {state.bound_at[:10] if state.bound_at else '未知'}\n"
        f"将停止自动签到，数据已清除。"
    )
