"""
签到、推送开关、时间设置、状态查询处理器
"""
from datetime import datetime
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain

from domain.enums import NotificationPolicy, GamePlatform
from domain.errors import UserNotBoundError, SignInProgressError
from application.dto import SignInDTO


async def handle_sign(plugin, event: AstrMessageEvent):
    """处理 /skland sign — 手动签到"""
    user_id = event.get_sender_id()

    # 检查是否绑定
    binding = await plugin._binding_repo.find_by_user_id(user_id, plugin._platform)
    if not binding or not binding.is_active:
        yield event.chain_result([Plain("❌ 你还没有绑定森空岛账号\n\n使用 /skland login <手机号> 或 /skland bind <token> 绑定")])
        return

    yield event.chain_result([Plain("🔄 正在执行签到...")])

    try:
        dto = SignInDTO(user_id=user_id, platform=plugin._platform)
        result = await plugin._sign_service.execute_sign(dto)

        if result.status.value == "success":
            msg = (
                f"✅ 签到成功！\n"
                f"🎁 奖励: {result.reward or '无'}\n"
                f"⏰ {result.signed_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        elif result.status.value == "already_signed":
            msg = "ℹ️ 今天已经签到过了，明天再来吧~"
        else:
            msg = f"❌ 签到失败: {result.error_message or '未知错误'}"

        yield event.chain_result([Plain(msg)])

    except UserNotBoundError:
        yield event.chain_result([Plain("❌ 你还没有绑定森空岛账号")])
    except SignInProgressError:
        yield event.chain_result([Plain("⏳ 签到正在进行中，请稍后...")])
    except Exception as e:
        logger.error(f"[签到] 手动签到失败: {e}", exc_info=True)
        yield event.chain_result([Plain(f"❌ 签到失败: {e}")])


async def handle_push_toggle(plugin, event: AstrMessageEvent, action: str = None):
    """处理 /skland push on|off — 推送开关"""
    if not action:
        # 查询当前状态
        binding = await plugin._binding_repo.find_by_user_id(
            event.get_sender_id(), plugin._platform
        )
        if not binding:
            yield event.chain_result([Plain("❌ 你还没有绑定森空岛账号")])
            return
        status = "开启" if binding.notification_policy != NotificationPolicy.NONE else "关闭"
        yield event.chain_result([Plain(f"📢 当前推送状态: {status}\n使用 /skland push on 开启\n使用 /skland push off 关闭")])
        return

    action = action.strip().lower()
    if action not in ("on", "off"):
        yield event.chain_result([Plain("❌ 请使用 /skland push on 或 /skland push off")])
        return

    try:
        new_policy = NotificationPolicy.ALL if action == "on" else NotificationPolicy.NONE
        binding = await plugin._binding_repo.find_by_user_id(
            event.get_sender_id(), plugin._platform
        )
        if not binding:
            yield event.chain_result([Plain("❌ 你还没有绑定森空岛账号")])
            return

        binding.notification_policy = new_policy
        await plugin._binding_repo.save(binding)

        status_text = "已开启 ✅" if action == "on" else "已关闭 ❌"
        yield event.chain_result([Plain(f"📢 推送通知{status_text}")])
    except Exception as e:
        logger.error(f"[推送] 设置失败: {e}")
        yield event.chain_result([Plain(f"❌ 设置失败: {e}")])


async def handle_time_config(plugin, event: AstrMessageEvent, action: str = None, arg: str = None):
    """处理 /skland time [set HH:MM] — 查看/设置签到时间"""
    if not action:
        # 查询当前时间
        binding = await plugin._binding_repo.find_by_user_id(
            event.get_sender_id(), plugin._platform
        )
        if not binding:
            yield event.chain_result([Plain("❌ 你还没有绑定森空岛账号")])
            return
        yield event.chain_result([Plain(f"⏰ 当前签到时间: {binding.sign_time}\n使用 /skland time set 07:30 修改")])
        return

    if action.lower() != "set" or not arg:
        yield event.chain_result([Plain("❌ 请使用 /skland time set HH:MM 设置签到时间\n例如: /skland time set 07:30")])
        return

    # 验证时间格式
    time_pattern = r'^([01]\d|2[0-3]):([0-5]\d)$'
    import re
    if not re.match(time_pattern, arg):
        yield event.chain_result([Plain("❌ 时间格式错误，请使用 HH:MM 格式（如 07:30, 22:00）")])
        return

    try:
        binding = await plugin._binding_repo.find_by_user_id(
            event.get_sender_id(), plugin._platform
        )
        if not binding:
            yield event.chain_result([Plain("❌ 你还没有绑定森空岛账号")])
            return

        binding.sign_time = arg
        await plugin._binding_repo.save(binding)

        yield event.chain_result([Plain(f"✅ 签到时间已更新为 {arg}\n下次定时签到将在此时执行")])
    except Exception as e:
        logger.error(f"[时间] 设置失败: {e}")
        yield event.chain_result([Plain(f"❌ 设置失败: {e}")])


async def handle_status(plugin, event: AstrMessageEvent):
    """处理 /skland status — 查看签到状态"""
    user_id = event.get_sender_id()

    binding = await plugin._binding_repo.find_by_user_id(user_id, plugin._platform)
    if not binding:
        yield event.chain_result([Plain(
            "❌ 你还没有绑定森空岛账号\n\n"
            "📱 绑定方式：\n"
            "  /skland bind <token>    通过 Token 绑定\n"
            "  /skland login <手机号>  通过手机号登录"
        )])
        return

    masked = binding.credential.safe_masked if binding.credential else "N/A"
    push_status = "开启" if binding.notification_policy != NotificationPolicy.NONE else "关闭"

    msg = (
        f"📊 签到状态\n"
        f"{'='*20}\n"
        f"🎮 游戏: {binding.game.value}\n"
        f"⏰ 签到时间: {binding.sign_time}\n"
        f"📢 推送通知: {push_status}\n"
        f"🔑 凭证: {masked}\n"
        f"📅 连续签到: {binding.consecutive_days} 天\n"
        f"🏆 总签到: {binding.total_signs} 次\n"
        f"✅ 状态: {'正常' if binding.is_active else '已失效'}\n"
    )

    if binding.last_sign_at:
        last_sign = binding.last_sign_at.strftime("%Y-%m-%d %H:%M")
        msg += f"📌 上次签到: {last_sign}\n"

    msg += (
        f"\n💡 使用 /skland sign 立即签到"
    )

    yield event.chain_result([Plain(msg)])


async def handle_did(plugin, event: AstrMessageEvent):
    """处理 /skland did — 查看设备指纹状态"""
    try:
        did = await plugin._did_manager.get_or_create()
        yield event.chain_result([Plain(
            f"📱 设备指纹 (dId)\n"
            f"{'='*20}\n"
            f"dId: {did[:16]}...{did[-8:]}\n"
            f"长度: {len(did)} 字符\n"
            f"状态: {'✅ 有效' if did else '❌ 未生成'}\n\n"
            "设备指纹用于签到 API 验证\n"
            "通常无需手动刷新"
        )])
    except Exception as e:
        logger.error(f"[dId] 查询失败: {e}")
        yield event.chain_result([Plain(f"❌ 查询设备指纹失败: {e}")])
