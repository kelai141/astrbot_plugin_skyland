"""
管理员命令处理器

处理: /skland list, /skland remove, /skland broadcast
"""
import asyncio
from datetime import date

from astrbot.api.event import AstrMessageEvent


async def handle_list_users(plugin, event: AstrMessageEvent):
    """处理 /skland list（管理员查看所有用户）"""
    if not plugin._is_admin(event):
        yield event.plain_result("❌ 仅管理员可使用此命令")
        return

    users = plugin.store.get_users()
    if not users:
        yield event.plain_result("📋 暂无已绑定的用户")
        return

    today = date.today().isoformat()
    lines = [f"📋 已绑定用户列表 (共 {len(users)} 人)"]
    for i, (sid, info) in enumerate(users.items(), 1):
        is_signed = info.get("last_sign_date") == today
        sign_icon = "✅" if is_signed else "⏳"
        game = info.get("game_info", "未知角色")
        push = "📢" if info.get("push_enabled", True) else "🔇"
        sign_time = info.get("sign_time", "09:05")
        lines.append(f"{i}. {sign_icon} {push} [{sign_time}] {game} (ID: {sid})")

    yield event.plain_result("\n".join(lines))


async def handle_remove_user(plugin, event: AstrMessageEvent, user_id: str = None):
    """处理 /skland remove <id>"""
    if not plugin._is_admin(event):
        yield event.plain_result("❌ 仅管理员可使用此命令")
        return

    if not user_id:
        yield event.plain_result(
            "⚠️ 请指定要移除的用户 ID\n"
            "使用 /skland list 查看用户 ID"
        )
        return

    removed = plugin.store.remove_user(user_id)
    if removed:
        yield event.plain_result(
            f"✅ 已移除用户 {user_id} 的绑定（角色: {removed.get('game_info', '未知')}）"
        )
    else:
        yield event.plain_result(f"❌ 未找到用户: {user_id}")


async def handle_broadcast(plugin, event: AstrMessageEvent):
    """处理 /skland broadcast <msg>（管理员群发）"""
    if not plugin._is_admin(event):
        yield event.plain_result("❌ 仅管理员可使用此命令")
        return

    # 提取消息内容
    raw = event.message_str.strip()
    msg = ""
    for prefix in ("/skland broadcast ", "/skland broadcast", "/skland bc "):
        if raw.startswith(prefix):
            msg = raw[len(prefix):].strip()
            break

    if not msg:
        yield event.plain_result("⚠️ 请提供要群发的消息内容\n使用方法：/skland broadcast <消息内容>")
        return

    from ..lib.notification import NotificationTemplates

    notification = NotificationTemplates.admin_broadcast(msg)
    users = plugin.store.get_users()

    success_count = 0
    fail_count = 0
    for sid, info in users.items():
        try:
            await plugin._notify_user(info, notification)
            success_count += 1
        except Exception:
            fail_count += 1
        await asyncio.sleep(0.5)

    yield event.plain_result(f"📢 群发完成！成功: {success_count}，失败: {fail_count}")
