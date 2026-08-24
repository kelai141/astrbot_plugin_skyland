"""
签到与状态相关命令处理器

处理: /skland sign, /skland status, /skland push, /skland time
"""
from datetime import datetime

from astrbot.api.event import AstrMessageEvent

from ..lib.notification import NotificationTemplates, PushPolicy
from ..lib.skyland_engine import SignResult
from ..lib.timeutil import beijing_now, beijing_today, BEIJING_TZ


async def handle_sign(plugin, event: AstrMessageEvent):
    """处理 /skland sign（手动签到）"""
    sid = plugin._get_sender_id(event)
    state = plugin._load_user_state(sid)

    if state is None:
        yield event.plain_result(
            "❌ 你还没有绑定账号！\n"
            "请使用 /skland bind <token> 或 /skland login 绑定。"
        )
        return

    yield event.plain_result("⏳ 正在签到，请稍候…")

    try:
        result = await plugin.engine.sign(state)
    except Exception as e:
        yield event.plain_result(f"❌ 签到失败: {e}")
        return

    # 保存状态
    plugin._save_user_state(sid, state)

    # 格式化结果
    decision = PushPolicy.decide(state, result, is_manual=True)
    yield event.plain_result(decision.message)


async def handle_push_toggle(plugin, event: AstrMessageEvent, action: str = None):
    """处理 /skland push [on|off]"""
    sid = plugin._get_sender_id(event)
    state = plugin._load_user_state(sid)

    if state is None:
        yield event.plain_result("❌ 你还没有绑定账号！")
        return

    if not action or action not in ("on", "off"):
        enabled = state.push_enabled
        yield event.plain_result(
            f"📢 自动推送: {'🟢 已开启' if enabled else '🔴 已关闭'}\n"
            f"修改: /skland push on 或 /skland push off"
        )
        return

    state.push_enabled = (action == "on")
    plugin._save_user_state(sid, state)

    msg = (
        f"📢 自动推送已{'开启' if action == 'on' else '关闭'}"
        + ("\n签到完成后会私聊通知你。" if action == "on" else "\n不会再主动推送签到结果。")
    )
    yield event.plain_result(msg)


async def handle_time_config(plugin, event: AstrMessageEvent, action: str = None, arg: str = None):
    """处理 /skland time [set HH:MM]"""
    sid = plugin._get_sender_id(event)
    state = plugin._load_user_state(sid)

    if state is None:
        yield event.plain_result("❌ 你还没有绑定账号！")
        return

    if action == "set" and arg:
        try:
            parts = arg.split(":")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except (ValueError, IndexError):
            yield event.plain_result(
                "❌ 时间格式错误，请使用 HH:MM\n例如: /skland time set 08:30"
            )
            return

        state.sign_time = f"{h:02d}:{m:02d}"
        plugin._save_user_state(sid, state)

        # 如果当前时间 ≥ 设置的时间 且 今天还没签过 → 立即触发签到
        today = beijing_today().isoformat()
        now = beijing_now()
        if (h < now.hour or (h == now.hour and m <= now.minute)) \
                and state.last_sign_date != today:
            yield event.plain_result(
                f"⏰ 签到时间已设置为 每天 {state.sign_time}\n"
                f"⏳ 今日 {state.sign_time} 已过，现在为你执行签到…"
            )
            async for msg in handle_sign(plugin, event):
                yield msg
        else:
            yield event.plain_result(f"⏰ 签到时间已设置为 每天 {state.sign_time}")
    else:
        yield event.plain_result(
            f"⏰ 当前签到时间: 每天 {state.sign_time}\n"
            f"修改: /skland time set HH:MM\n"
            f"例如: /skland time set 08:30"
        )


async def handle_status(plugin, event: AstrMessageEvent):
    """处理 /skland status"""
    sid = plugin._get_sender_id(event)
    state = plugin._load_user_state(sid)

    if state is None:
        yield event.plain_result("❌ 你还没有绑定账号！")
        return

    report = NotificationTemplates.status_report(state)
    yield event.plain_result(report)


async def handle_did(plugin, event: AstrMessageEvent):
    """处理 /skland did"""
    from ..lib.security import get_did_meta, _DID_CACHE_FILE
    import os

    did, source = get_did_meta()
    lines = ["📟 设备指纹 (dId) 状态"]

    if source == "shumei" and did:
        lines.append(f"✅ 有效: {did[:16]}...{did[-8:]}")
        lines.append(f"📁 来源: 数美 API")
        lines.append(f"📁 缓存文件: {_DID_CACHE_FILE or '未设置'}")

        if _DID_CACHE_FILE and os.path.exists(_DID_CACHE_FILE):
            mtime = datetime.fromtimestamp(os.path.getmtime(_DID_CACHE_FILE), tz=BEIJING_TZ)
            lines.append(f"🕐 缓存时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    elif source == "legacy" and did:
        lines.append("⚠️ 发现旧版 dId 缓存（可能为 fallback 假 dId）")
        lines.append("   插件初始化时会自动清理并重新获取，重载插件即可")
    else:
        lines.append("❌ 未生成有效 dId")
        lines.append("   插件初始化时会尝试从数美 API 获取")
        lines.append("   若持续失败，请检查服务器能否访问 fp-it.portal101.cn")

    lines.append("")
    lines.append("💡 dId 是设备指纹，用于森空岛 API 鉴权")
    lines.append("   如果遇到登录问题，可删除缓存文件后重载插件")

    yield event.plain_result("\n".join(lines))
